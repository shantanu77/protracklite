from __future__ import annotations

import argparse
import html
import smtplib
from dataclasses import dataclass
from datetime import date
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import Organization, Role, User
from app.reports import compute_work_rate, previous_week_bounds
from app.time_utils import local_today


settings = get_settings()


@dataclass
class DigestResult:
    manager_email: str
    recipient: str
    status: str
    member_count: int
    subject: str | None = None
    text_body: str | None = None
    html_body: str | None = None
    reason: str | None = None


def reporting_line(db: Session, org_id: int, manager_id: int) -> list[tuple[User, int]]:
    """Return every active direct and indirect report, without looping on bad data."""
    people = db.scalars(
        select(User)
        .where(User.org_id == org_id, User.is_active.is_(True), User.id != manager_id)
        .order_by(User.full_name.asc(), User.id.asc())
    ).all()
    reports_by_manager: dict[int, list[User]] = {}
    for person in people:
        if person.manager_id is not None:
            reports_by_manager.setdefault(person.manager_id, []).append(person)

    result: list[tuple[User, int]] = []
    seen = {manager_id}
    pending = [(person, 1) for person in reports_by_manager.get(manager_id, [])]
    while pending:
        person, depth = pending.pop(0)
        if person.id in seen:
            continue
        seen.add(person.id)
        result.append((person, depth))
        pending.extend((report, depth + 1) for report in reports_by_manager.get(person.id, []))
    return result


def effort_rows(
    db: Session,
    org: Organization,
    manager: User,
    report_date: date,
) -> tuple[list[dict], date, date, date]:
    last_week_start, last_week_end = previous_week_bounds(report_date)
    month_start = report_date.replace(day=1)
    rows: list[dict] = []
    for member, depth in reporting_line(db, org.id, manager.id):
        last_week = compute_work_rate(db, org.id, member.id, last_week_start, last_week_end)
        month_to_date = compute_work_rate(db, org.id, member.id, month_start, report_date)
        rows.append(
            {
                "name": member.full_name,
                "email": member.email,
                "depth": depth,
                "relationship": "Direct" if depth == 1 else f"Level {depth}",
                "last_week_available": float(last_week["available_hours"]),
                "last_week_logged": float(last_week["total_logged_hours"]),
                "last_week_rate": float(last_week["total_rate"]),
                "month_available": float(month_to_date["available_hours"]),
                "month_logged": float(month_to_date["total_logged_hours"]),
                "month_rate": float(month_to_date["total_rate"]),
            }
        )
    return rows, last_week_start, last_week_end, month_start


def build_message(
    db: Session,
    org: Organization,
    manager: User,
    report_date: date,
) -> tuple[str, str, str, int]:
    rows, last_week_start, last_week_end, month_start = effort_rows(db, org, manager, report_date)
    subject = f"Team effort summary: {last_week_start:%d %b}–{last_week_end:%d %b %Y}"

    text_lines = [
        f"Hi {manager.full_name},",
        "",
        "Here is the Monday effort summary for your full reporting line.",
        f"Last week: {last_week_start:%d %b %Y} to {last_week_end:%d %b %Y}",
        f"Month to date: {month_start:%d %b %Y} to {report_date:%d %b %Y}",
        "",
        "Team member | Level | Last week available | Last week booked | Last week % | MTD booked | MTD available | MTD %",
    ]
    html_rows: list[str] = []
    for row in rows:
        text_lines.append(
            f"{row['name']} | {row['relationship']} | {row['last_week_available']:.2f}h | "
            f"{row['last_week_logged']:.2f}h | {row['last_week_rate']:.1f}% | "
            f"{row['month_logged']:.2f}h | {row['month_available']:.2f}h | {row['month_rate']:.1f}%"
        )
        html_rows.append(
            "<tr>"
            f"<td style='padding:10px;border-bottom:1px solid #e1e7ea'><strong>{html.escape(row['name'])}</strong><br>"
            f"<span style='color:#687780;font-size:12px'>{html.escape(row['email'])}</span></td>"
            f"<td style='padding:10px;border-bottom:1px solid #e1e7ea'>{row['relationship']}</td>"
            f"<td style='padding:10px;border-bottom:1px solid #e1e7ea;text-align:right'>{row['last_week_available']:.2f}h</td>"
            f"<td style='padding:10px;border-bottom:1px solid #e1e7ea;text-align:right'>{row['last_week_logged']:.2f}h<br>"
            f"<span style='color:#687780;font-size:12px'>{row['last_week_rate']:.1f}%</span></td>"
            f"<td style='padding:10px;border-bottom:1px solid #e1e7ea;text-align:right'>{row['month_logged']:.2f}h<br>"
            f"<span style='color:#687780;font-size:12px'>{row['month_rate']:.1f}% of {row['month_available']:.2f}h</span></td>"
            "</tr>"
        )

    totals = {
        "last_available": sum(row["last_week_available"] for row in rows),
        "last_logged": sum(row["last_week_logged"] for row in rows),
        "month_available": sum(row["month_available"] for row in rows),
        "month_logged": sum(row["month_logged"] for row in rows),
    }
    text_lines.extend(
        [
            "",
            f"Team totals | Last week: {totals['last_logged']:.2f}h booked / {totals['last_available']:.2f}h available | "
            f"Month to date: {totals['month_logged']:.2f}h booked / {totals['month_available']:.2f}h available",
            "",
            f"Organization: {org.name}",
        ]
    )
    empty_row = "<tr><td colspan='5' style='padding:18px;color:#687780'>No active reports are assigned.</td></tr>"
    html_body = f"""<!doctype html>
<html><body style="margin:0;background:#f3f6f5;font-family:Arial,sans-serif;color:#1d3442">
<div style="max-width:900px;margin:0 auto;padding:28px 18px">
  <div style="background:#123d39;border-radius:16px 16px 0 0;padding:24px;color:#fff">
    <div style="font-size:12px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;color:#9ed8c8">Monday manager digest</div>
    <h1 style="font-size:25px;margin:8px 0">Team effort summary</h1>
    <div style="color:#d9eee8">Last week: {last_week_start:%d %b}–{last_week_end:%d %b %Y} &middot; Month to date: {month_start:%d %b}–{report_date:%d %b %Y}</div>
  </div>
  <div style="background:#fff;border:1px solid #d9e0e4;border-top:0;border-radius:0 0 16px 16px;padding:24px;overflow-x:auto">
    <p>Hi {html.escape(manager.full_name)},</p>
    <p style="color:#52636d">Here is the effort position for every active person in your direct and lower reporting line.</p>
    <table style="width:100%;border-collapse:collapse;font-size:14px">
      <thead><tr style="background:#eef4f2;text-align:left"><th style="padding:10px">Team member</th><th style="padding:10px">Level</th><th style="padding:10px;text-align:right">Available last week</th><th style="padding:10px;text-align:right">Booked last week</th><th style="padding:10px;text-align:right">Booked MTD</th></tr></thead>
      <tbody>{''.join(html_rows) if html_rows else empty_row}</tbody>
      <tfoot><tr style="font-weight:700;background:#f7f9f8"><td colspan="2" style="padding:10px">Team totals</td><td style="padding:10px;text-align:right">{totals['last_available']:.2f}h</td><td style="padding:10px;text-align:right">{totals['last_logged']:.2f}h</td><td style="padding:10px;text-align:right">{totals['month_logged']:.2f}h of {totals['month_available']:.2f}h</td></tr></tfoot>
    </table>
    <p style="margin:20px 0 0;color:#71808a;font-size:12px">ProtrackLite &middot; {html.escape(org.name)}</p>
  </div>
</div></body></html>"""
    return subject, "\n".join(text_lines), html_body, len(rows)


def send_email(recipient: str, subject: str, text_body: str, html_body: str) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_username:
            server.starttls()
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)


def run_digests(
    report_date: date,
    org_slug: str | None = None,
    manager_email: str | None = None,
    recipient: str | None = None,
    dry_run: bool = False,
) -> list[DigestResult]:
    with SessionLocal() as db:
        stmt = (
            select(User, Organization)
            .join(Organization, User.org_id == Organization.id)
            .where(
                User.is_active.is_(True),
                User.role.in_([Role.MANAGER, Role.ADMIN]),
                Organization.is_active.is_(True),
            )
            .order_by(User.email.asc())
        )
        if org_slug:
            stmt = stmt.where(Organization.slug == org_slug.strip().lower())
        if manager_email:
            stmt = stmt.where(User.email == manager_email.strip().lower())
        manager_rows = db.execute(stmt).all()

        results: list[DigestResult] = []
        for manager, org in manager_rows:
            subject, text_body, html_body, member_count = build_message(db, org, manager, report_date)
            destination = recipient.strip().lower() if recipient else manager.email
            if member_count == 0:
                results.append(DigestResult(manager.email, destination, "skipped", 0, reason="no-active-reports"))
            elif dry_run:
                results.append(DigestResult(manager.email, destination, "dry-run", member_count, subject, text_body, html_body))
            else:
                send_email(destination, subject, text_body, html_body)
                results.append(DigestResult(manager.email, destination, "sent", member_count, subject, text_body, html_body))
        return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send Monday full-reporting-line effort summaries to managers.")
    parser.add_argument("--date", help="Report date in YYYY-MM-DD format. Defaults to today.")
    parser.add_argument("--org-slug", help="Restrict summaries to one organization.")
    parser.add_argument("--manager-email", help="Restrict the run to one manager's reporting line.")
    parser.add_argument("--recipient", help="Override delivery address for testing; report ownership is unchanged.")
    parser.add_argument("--dry-run", action="store_true", help="Build and print summaries without sending email.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report_date = date.fromisoformat(args.date) if args.date else local_today()
    results = run_digests(report_date, args.org_slug, args.manager_email, args.recipient, args.dry_run)
    if args.manager_email and not results:
        print("No active manager matched the requested email.")
        return 1
    for result in results:
        print(f"[{result.status}] manager={result.manager_email} recipient={result.recipient} members={result.member_count}")
        if result.reason:
            print(f"Reason: {result.reason}")
        if args.dry_run and result.subject and result.text_body:
            print(f"Subject: {result.subject}")
            print(result.text_body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
