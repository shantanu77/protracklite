from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.leave_approvals import apply_local_leave_approvals, CANCELLED_STATUSES
from app.models import Holiday, Organization, User
from app.time_utils import local_today
from app.zoho_people import fetch_zoho_employee_ids, fetch_zoho_leave_requests


settings = get_settings()


@dataclass
class DigestResult:
    organization: str
    status: str
    off_duty_count: int
    body: str


def build_daily_summary(db, org: Organization, summary_date: date) -> tuple[str, int]:
    people = list(db.scalars(select(User).where(
        User.org_id == org.id, User.is_active.is_(True)
    ).order_by(User.full_name.asc())).all())
    missing = [person for person in people if not person.zoho_employee_id]
    if missing:
        directory = fetch_zoho_employee_ids(employee_emails=[person.email for person in missing])
        if directory.status != "synced":
            raise RuntimeError(f"Zoho employee lookup failed for {org.name}: {directory.error}")
        identifiers = dict(directory.employee_ids)
        for person in missing:
            person.zoho_employee_id = identifiers.get(person.email.strip().lower(), "")
        db.flush()
    mapped = [person for person in people if person.zoho_employee_id]
    leave_result = fetch_zoho_leave_requests(
        employee_zoho_ids=[person.zoho_employee_id for person in mapped],
        from_date=summary_date,
        to_date=summary_date,
    )
    if leave_result.status != "synced":
        raise RuntimeError(f"Zoho leave lookup failed for {org.name}: {leave_result.error}")
    leave_result = apply_local_leave_approvals(db, org.id, mapped, leave_result)
    people_by_zoho = {person.zoho_employee_id: person for person in mapped}
    holiday = db.scalar(
        select(Holiday).where(Holiday.org_id == org.id, Holiday.holiday_date == summary_date)
    )

    planned: list[str] = []
    unplanned: list[str] = []
    rows = []
    for leave in leave_result.leaves:
        approval = str(leave.get("approval_status") or "Unknown").strip()
        if approval.upper() in CANCELLED_STATUSES:
            continue
        person = people_by_zoho.get(str(leave.get("employee_zoho_id") or ""))
        if not person:
            continue
        rows.append(leave)
        label = f"@{person.full_name}"
        if approval.upper() not in {"APPROVED"}:
            label += f" ({approval})"
        if "sick" not in str(leave.get("leave_type_name") or "").casefold():
            planned.append(label)
        else:
            unplanned.append(label)

    lines = [
        "**Off-Duty Summary (ProTrack Sync)**",
        summary_date.strftime("%A, %d %B %Y"),
        "",
    ]
    if holiday:
        lines.append(f"🟦 Public Holiday: {holiday.name}")
    if unplanned:
        lines.append(f"🤒 Unplanned: {', '.join(unplanned)}")
    if planned:
        lines.append(f"🏖️ Planned: {', '.join(planned)}")
    if not holiday and not rows:
        lines.append("✅ Everyone is available; no registered leave today.")
    lines.extend(["", f"Organization: {org.name}"])
    return "\n".join(lines), len(rows)


def post_to_teams(webhook_url: str, body: str) -> None:
    card = {
        "$schema": "https://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": body,
                "wrap": True,
            }
        ],
    }
    response = httpx.post(webhook_url, json=card, timeout=20.0)
    response.raise_for_status()


def run_digest(summary_date: date, org_slug: str | None = None, dry_run: bool = False) -> list[DigestResult]:
    with SessionLocal() as db:
        stmt = select(Organization).where(Organization.is_active.is_(True)).order_by(Organization.name.asc())
        if org_slug:
            stmt = stmt.where(Organization.slug == org_slug.strip().lower())
        organizations = db.scalars(stmt).all()
        results: list[DigestResult] = []
        for org in organizations:
            body, off_duty_count = build_daily_summary(db, org, summary_date)
            if dry_run:
                results.append(DigestResult(org.name, "dry-run", off_duty_count, body))
                continue
            webhook_url = settings.teams_availability_webhook_url.strip()
            if not webhook_url:
                results.append(DigestResult(org.name, "skipped-no-webhook", off_duty_count, body))
                continue
            post_to_teams(webhook_url, body)
            results.append(DigestResult(org.name, "posted", off_duty_count, body))
        return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post the daily ProTrack capacity summary to Microsoft Teams.")
    parser.add_argument("--date", help="Summary date in YYYY-MM-DD format. Defaults to today.")
    parser.add_argument("--org-slug", help="Restrict the summary to one organization.")
    parser.add_argument("--dry-run", action="store_true", help="Print the message without posting to Teams.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary_date = date.fromisoformat(args.date) if args.date else local_today()
    results = run_digest(summary_date, args.org_slug, args.dry_run)
    for result in results:
        print(f"[{result.status}] {result.organization}: {result.off_duty_count} off duty")
        if args.dry_run:
            print(result.body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
