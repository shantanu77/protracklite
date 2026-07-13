from __future__ import annotations

import argparse
import html
import smtplib
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import SessionLocal
from app.models import Organization, User, WorkList
from app.time_utils import local_today


settings = get_settings()


@dataclass
class TargetReminderResult:
    email: str
    status: str
    list_count: int
    subject: str | None = None
    body: str | None = None


def target_timing(days_remaining: int) -> str:
    if days_remaining < 0:
        days = abs(days_remaining)
        return f"Overdue by {days} day{'s' if days != 1 else ''}"
    if days_remaining == 0:
        return "Due today"
    return f"{days_remaining} day{'s' if days_remaining != 1 else ''} remaining"


def list_url(org: Organization, work_list: WorkList) -> str:
    return f"https://{settings.base_domain}/{org.slug}/lists?list_id={work_list.id}"


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


def build_message(user: User, org: Organization, entries: list[dict]) -> tuple[str, str, str]:
    urgent_count = sum(1 for entry in entries if entry["days_remaining"] <= 7)
    subject = (
        f"Your ProtrackLite list targets: {urgent_count} need attention"
        if urgent_count
        else f"Your ProtrackLite list targets: {len(entries)} progress update{'s' if len(entries) != 1 else ''}"
    )
    text_lines = [
        f"Hi {user.full_name},",
        "",
        "Here is your target-focused list progress update.",
        "",
    ]
    cards = []
    for entry in entries:
        timing = target_timing(entry["days_remaining"])
        text_lines.extend(
            [
                entry["title"],
                f"Completed: {entry['completed_items']}/{entry['total_items']} ({entry['progress_percent']:.0f}%)",
                f"Target: {entry['target_date'].strftime('%d %b %Y')} - {timing}",
                f"Open list: {entry['url']}",
                "",
            ]
        )
        timing_color = "#b91c1c" if entry["days_remaining"] <= 0 else "#9a5b00" if entry["days_remaining"] <= 7 else "#0f766e"
        cards.append(
            f"""
            <div style="border:1px solid #d9e0e4;border-radius:14px;padding:18px;margin:14px 0;background:#ffffff;">
              <div style="font-size:18px;font-weight:800;color:#1d3442;margin-bottom:8px;">{html.escape(entry['title'])}</div>
              <div style="font-size:13px;font-weight:700;color:{timing_color};margin-bottom:12px;">
                Target {entry['target_date'].strftime('%d %b %Y')} &middot; {html.escape(timing)}
              </div>
              <div style="display:flex;justify-content:space-between;font-size:13px;color:#52636d;margin-bottom:7px;">
                <span>{entry['completed_items']} of {entry['total_items']} completed</span>
                <strong style="color:#1d3442;">{entry['progress_percent']:.0f}%</strong>
              </div>
              <div style="height:9px;background:#e8edef;border-radius:999px;overflow:hidden;margin-bottom:14px;">
                <div style="height:9px;width:{max(0, min(100, entry['progress_percent'])):.0f}%;background:#16805b;border-radius:999px;"></div>
              </div>
              <a href="{html.escape(entry['url'])}" style="display:inline-block;padding:9px 14px;border-radius:9px;background:#1d3442;color:#ffffff;text-decoration:none;font-size:13px;font-weight:700;">Open list</a>
            </div>
            """
        )
    text_lines.extend(["Keep the target in view and close the highest-impact remaining items first.", "", f"Organization: {org.name}"])
    html_body = f"""
    <!doctype html>
    <html>
      <body style="margin:0;background:#f3f6f5;font-family:Arial,sans-serif;color:#1d3442;">
        <div style="max-width:680px;margin:0 auto;padding:28px 18px;">
          <div style="background:#123d39;border-radius:18px 18px 0 0;padding:26px;color:#ffffff;">
            <div style="font-size:12px;font-weight:800;letter-spacing:1.4px;text-transform:uppercase;color:#9ed8c8;">Target check-in</div>
            <h1 style="font-size:25px;line-height:1.2;margin:8px 0 6px;">Your list progress</h1>
            <p style="margin:0;color:#d9eee8;">Focus on the target, not just the latest update.</p>
          </div>
          <div style="background:#fdfefe;border:1px solid #d9e0e4;border-top:0;border-radius:0 0 18px 18px;padding:26px;">
            <p style="margin-top:0;">Hi {html.escape(user.full_name)},</p>
            <p style="color:#52636d;line-height:1.6;">You have {len(entries)} active target list{'s' if len(entries) != 1 else ''}. Here is what is completed and how much time remains.</p>
            {''.join(cards)}
            <p style="margin:22px 0 4px;font-weight:700;">Keep the target in view and close the highest-impact remaining items first.</p>
            <p style="margin:0;color:#71808a;font-size:12px;">ProtrackLite &middot; {html.escape(org.name)}</p>
          </div>
        </div>
      </body>
    </html>
    """
    return subject, "\n".join(text_lines), html_body


def run_reminders(
    target_emails: list[str] | None,
    org_slug: str | None,
    dry_run: bool,
    today: date,
) -> list[TargetReminderResult]:
    with SessionLocal() as db:
        list_stmt = (
            select(WorkList, Organization)
            .join(Organization, WorkList.org_id == Organization.id)
            .options(selectinload(WorkList.items), selectinload(WorkList.members))
            .where(
                WorkList.is_archived.is_(False),
                WorkList.target_date.is_not(None),
                Organization.is_active.is_(True),
            )
            .order_by(WorkList.target_date.asc(), WorkList.id.asc())
        )
        if org_slug:
            list_stmt = list_stmt.where(Organization.slug == org_slug.strip().lower())
        list_rows = db.execute(list_stmt).all()
        users = db.scalars(select(User).where(User.is_active.is_(True))).all()
        user_map = {user.id: user for user in users}

        grouped: dict[tuple[int, int], list[dict]] = defaultdict(list)
        org_map: dict[int, Organization] = {}
        for work_list, org in list_rows:
            total_items = len(work_list.items)
            completed_items = sum(1 for item in work_list.items if item.is_completed)
            if total_items == 0 or completed_items >= total_items or not work_list.target_date:
                continue
            days_remaining = (work_list.target_date - today).days
            if days_remaining > 7 and today.weekday() != 0:
                continue
            participant_ids = {work_list.owner_user_id, *(member.user_id for member in work_list.members)}
            entry = {
                "title": work_list.title,
                "target_date": work_list.target_date,
                "days_remaining": days_remaining,
                "total_items": total_items,
                "completed_items": completed_items,
                "progress_percent": (completed_items / total_items) * 100,
                "url": list_url(org, work_list),
            }
            org_map[org.id] = org
            for user_id in participant_ids:
                if user_id in user_map:
                    grouped[(user_id, org.id)].append(entry)

        normalized_targets = {email.strip().lower() for email in target_emails or [] if email.strip()}
        results: list[TargetReminderResult] = []
        for (user_id, org_id), entries in sorted(grouped.items(), key=lambda row: user_map[row[0][0]].email):
            user = user_map[user_id]
            if normalized_targets and user.email.lower() not in normalized_targets:
                continue
            org = org_map[org_id]
            subject, text_body, html_body = build_message(user, org, entries)
            if dry_run:
                results.append(TargetReminderResult(user.email, "dry-run", len(entries), subject, text_body))
                continue
            send_email(user.email, subject, text_body, html_body)
            results.append(TargetReminderResult(user.email, "sent", len(entries), subject))
        return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send target-focused Work List progress reminders.")
    parser.add_argument("--email", action="append", help="Restrict reminders to one or more email addresses.")
    parser.add_argument("--org-slug", help="Restrict reminders to one organization.")
    parser.add_argument("--today", help="Reference date in YYYY-MM-DD format. Defaults to today.")
    parser.add_argument("--dry-run", action="store_true", help="Print reminder content without sending email.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    today = datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else local_today()
    results = run_reminders(args.email, args.org_slug, args.dry_run, today)
    for result in results:
        print(f"[{result.status}] {result.email}: {result.list_count} list(s)")
        if result.subject:
            print(f"Subject: {result.subject}")
        if result.body:
            print(result.body)
    if args.email and not results:
        print("No target reminders matched the requested email filter.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
