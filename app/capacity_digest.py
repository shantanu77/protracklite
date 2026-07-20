from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date

import httpx
from sqlalchemy import select

from app.capacity import leave_is_planned
from app.config import get_settings
from app.database import SessionLocal
from app.models import Holiday, Leave, Organization, User
from app.time_utils import local_today


settings = get_settings()


@dataclass
class DigestResult:
    organization: str
    status: str
    off_duty_count: int
    body: str


def build_daily_summary(db, org: Organization, summary_date: date) -> tuple[str, int]:
    rows = db.execute(
        select(Leave, User)
        .join(User, Leave.user_id == User.id)
        .where(
            User.org_id == org.id,
            User.is_active.is_(True),
            Leave.leave_date == summary_date,
        )
        .order_by(User.full_name.asc())
    ).all()
    backup_ids = {leave.backup_user_id for leave, _ in rows if leave.backup_user_id}
    backup_map = {
        user.id: user
        for user in db.scalars(select(User).where(User.id.in_(backup_ids))).all()
    } if backup_ids else {}
    holiday = db.scalar(
        select(Holiday).where(Holiday.org_id == org.id, Holiday.holiday_date == summary_date)
    )

    planned: list[str] = []
    unplanned: list[str] = []
    for leave, employee in rows:
        label = f"@{employee.full_name}"
        backup = backup_map.get(leave.backup_user_id)
        if backup:
            label += f" (Cover: @{backup.full_name})"
        if leave_is_planned(leave):
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
