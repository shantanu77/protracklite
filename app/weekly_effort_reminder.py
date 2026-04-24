from __future__ import annotations

import argparse
import os
import smtplib
from dataclasses import dataclass
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings


settings = get_settings()

if not settings.database_url.strip():
    local_db = Path("protracklite.db")
    if local_db.exists():
        os.environ["DATABASE_URL"] = "sqlite:///./protracklite.db"
        get_settings.cache_clear()
        settings = get_settings()

from app.database import SessionLocal
from app.models import Organization, User
from app.reports import compute_work_rate, current_week_bounds


@dataclass
class ReminderResult:
    email: str
    status: str
    subject: str | None = None
    body: str | None = None
    logged_hours: float | None = None
    available_hours: float | None = None
    effort_rate: float | None = None
    reason: str | None = None


def send_email(recipient: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_username:
            server.starttls()
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)


def build_message(user: User, org: Organization, week_start: date, week_end: date, threshold: float) -> tuple[str, str, float, float, float] | None:
    with SessionLocal() as db:
        rates = compute_work_rate(db, org.id, user.id, week_start, week_end)

    available_hours = float(rates["available_hours"] or 0)
    logged_hours = float(rates["total_logged_hours"] or 0)
    effort_rate = float(rates["total_rate"] or 0)

    if available_hours <= 0:
        return None
    if logged_hours > 0 and effort_rate >= threshold:
        return None

    subject = f"ProtrackLite reminder: book your effort for {week_start.isoformat()} to {week_end.isoformat()}"
    if logged_hours <= 0:
        body = (
            f"Hi {user.full_name},\n\n"
            f"You have not booked any progress in this week ({week_start.isoformat()} to {week_end.isoformat()}).\n"
            f"Your current booked effort is 0.00h against {available_hours:.2f}h available hours.\n\n"
            f"Please update your effort book in ProtrackLite.\n\n"
            f"Organization: {org.name}\n"
            f"User: {user.email}\n"
        )
    else:
        body = (
            f"Hi {user.full_name},\n\n"
            f"Your booked effort for this week ({week_start.isoformat()} to {week_end.isoformat()}) is below "
            f"{threshold:.0f}% allocation.\n"
            f"You have booked {logged_hours:.2f}h against {available_hours:.2f}h available hours "
            f"({effort_rate:.2f}% booked).\n\n"
            f"Please book your remaining effort in ProtrackLite.\n\n"
            f"Organization: {org.name}\n"
            f"User: {user.email}\n"
        )
    return subject, body, logged_hours, available_hours, effort_rate


def run_reminders(target_emails: list[str] | None, org_slug: str | None, threshold: float, dry_run: bool, today: date) -> list[ReminderResult]:
    week_start, week_end = current_week_bounds(today)
    with SessionLocal() as db:
        stmt = (
            select(User, Organization)
            .join(Organization, User.org_id == Organization.id)
            .where(User.is_active.is_(True), Organization.is_active.is_(True))
            .order_by(User.email.asc())
        )
        if target_emails:
            normalized = [item.strip().lower() for item in target_emails if item.strip()]
            stmt = stmt.where(User.email.in_(normalized))
        if org_slug:
            stmt = stmt.where(Organization.slug == org_slug.strip().lower())
        rows = db.execute(stmt).all()

    results: list[ReminderResult] = []
    for user, org in rows:
        message_data = build_message(user, org, week_start, week_end, threshold)
        if message_data is None:
            results.append(
                ReminderResult(
                    email=user.email,
                    status="skipped",
                    logged_hours=None,
                    available_hours=None,
                    effort_rate=None,
                    reason="meets-threshold-or-no-available-hours",
                )
            )
            continue

        subject, body, logged_hours, available_hours, effort_rate = message_data
        if dry_run:
            results.append(
                ReminderResult(
                    email=user.email,
                    status="dry-run",
                    subject=subject,
                    body=body,
                    logged_hours=logged_hours,
                    available_hours=available_hours,
                    effort_rate=effort_rate,
                )
            )
            continue

        send_email(user.email, subject, body)
        results.append(
            ReminderResult(
                email=user.email,
                status="sent",
                subject=subject,
                body=body,
                logged_hours=logged_hours,
                available_hours=available_hours,
                effort_rate=effort_rate,
            )
        )
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send weekly effort booking reminders.")
    parser.add_argument("--email", action="append", help="Send reminder only for the given user email. Can be passed multiple times.")
    parser.add_argument("--org-slug", help="Restrict reminders to a single organization slug.")
    parser.add_argument("--threshold", type=float, default=85.0, help="Minimum booked effort percentage required to avoid reminders.")
    parser.add_argument("--today", help="Reference date in YYYY-MM-DD format. Defaults to today.")
    parser.add_argument("--dry-run", action="store_true", help="Do not send email. Print reminder payloads instead.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    today = datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else date.today()
    results = run_reminders(args.email, args.org_slug, args.threshold, args.dry_run, today)

    if args.email and not results:
        print("No active users matched the requested email filter.")
        return 1

    for item in results:
        print(f"[{item.status}] {item.email}")
        if item.subject:
            print(f"Subject: {item.subject}")
        if item.logged_hours is not None and item.available_hours is not None and item.effort_rate is not None:
            print(
                f"Booked: {item.logged_hours:.2f}h / {item.available_hours:.2f}h "
                f"({item.effort_rate:.2f}%)"
            )
        if item.reason:
            print(f"Reason: {item.reason}")
        if item.body:
            print(item.body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
