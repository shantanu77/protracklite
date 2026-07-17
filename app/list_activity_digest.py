from __future__ import annotations

import argparse
import html
import smtplib
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import SessionLocal
from app.models import Organization, User, WorkList, WorkListActivityDigestDelivery
from app.time_utils import local_datetime


settings = get_settings()


@dataclass
class DigestResult:
    email: str
    status: str
    list_count: int
    subject: str | None = None
    body: str | None = None


def list_url(org: Organization, work_list: WorkList) -> str:
    domain = (settings.base_domain or "").strip().rstrip("/")
    base_url = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"
    return f"{base_url}/{org.slug}/lists?list_id={work_list.id}"


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


def latest_list_activity(work_list: WorkList) -> datetime:
    timestamps = [work_list.created_at, work_list.updated_at]
    for item in work_list.items:
        timestamps.extend((item.created_at, item.updated_at))
    return max(timestamp for timestamp in timestamps if timestamp is not None)


def build_message(user: User, org: Organization, work_lists: list[WorkList]) -> tuple[str, str, str]:
    subject = f"Daily shared-list activity: {len(work_lists)} list{'s' if len(work_lists) != 1 else ''} updated"
    text_lines = [
        f"Hi {user.full_name},",
        "",
        "There has been activity in the following shared task lists:",
        "",
    ]
    cards: list[str] = []
    for work_list in work_lists:
        total_items = len(work_list.items)
        completed_items = sum(1 for item in work_list.items if item.is_completed)
        progress = (completed_items / total_items * 100) if total_items else 0
        url = list_url(org, work_list)
        text_lines.extend(
            [
                work_list.title,
                f"Progress: {completed_items}/{total_items} completed ({progress:.0f}%)",
                f"Open list: {url}",
                "",
            ]
        )
        cards.append(
            f"""
            <div style="border:1px solid #d9e0e4;border-radius:12px;padding:16px;margin:12px 0;background:#ffffff;">
              <div style="font-size:17px;font-weight:800;color:#1d3442;">{html.escape(work_list.title)}</div>
              <div style="font-size:13px;color:#52636d;margin:7px 0 12px;">{completed_items} of {total_items} completed ({progress:.0f}%)</div>
              <a href="{html.escape(url)}" style="display:inline-block;padding:9px 14px;border-radius:9px;background:#1d3442;color:#ffffff;text-decoration:none;font-size:13px;font-weight:700;">Open list</a>
            </div>
            """
        )
    text_lines.extend(["This is your single end-of-day shared-list activity reminder.", "", f"Organization: {org.name}"])
    html_body = f"""
    <!doctype html>
    <html>
      <body style="margin:0;background:#f3f6f5;font-family:Arial,sans-serif;color:#1d3442;">
        <div style="max-width:680px;margin:0 auto;padding:28px 18px;">
          <div style="background:#123d39;border-radius:18px 18px 0 0;padding:26px;color:#ffffff;">
            <div style="font-size:12px;font-weight:800;letter-spacing:1.4px;text-transform:uppercase;color:#9ed8c8;">Daily activity</div>
            <h1 style="font-size:25px;line-height:1.2;margin:8px 0 6px;">Your shared lists were updated</h1>
            <p style="margin:0;color:#d9eee8;">One end-of-day reminder for today&apos;s list activity.</p>
          </div>
          <div style="background:#fdfefe;border:1px solid #d9e0e4;border-top:0;border-radius:0 0 18px 18px;padding:26px;">
            <p style="margin-top:0;">Hi {html.escape(user.full_name)},</p>
            <p style="color:#52636d;line-height:1.6;">There has been activity in {len(work_lists)} shared task list{'s' if len(work_lists) != 1 else ''}.</p>
            {''.join(cards)}
            <p style="margin:20px 0 0;color:#71808a;font-size:12px;">ProtrackLite &middot; {html.escape(org.name)}</p>
          </div>
        </div>
      </body>
    </html>
    """
    return subject, "\n".join(text_lines), html_body


def run_digests(
    target_emails: list[str] | None = None,
    org_slug: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> list[DigestResult]:
    processed_at = now or datetime.utcnow()
    digest_date = local_datetime(processed_at).date()
    normalized_targets = {email.strip().lower() for email in target_emails or [] if email.strip()}

    with SessionLocal() as db:
        stmt = (
            select(WorkList, Organization)
            .join(Organization, WorkList.org_id == Organization.id)
            .options(selectinload(WorkList.items), selectinload(WorkList.members))
            .where(WorkList.is_archived.is_(False), Organization.is_active.is_(True))
            .order_by(WorkList.id.asc())
        )
        if org_slug:
            stmt = stmt.where(Organization.slug == org_slug.strip().lower())
        rows = [(work_list, org) for work_list, org in db.execute(stmt).all() if work_list.members]

        active_users = db.scalars(select(User).where(User.is_active.is_(True))).all()
        user_map = {user.id: user for user in active_users}
        grouped: dict[tuple[int, int], list[WorkList]] = defaultdict(list)
        org_map: dict[int, Organization] = {}
        for work_list, org in rows:
            org_map[org.id] = org
            participant_ids = {work_list.owner_user_id, *(member.user_id for member in work_list.members)}
            for user_id in participant_ids:
                user = user_map.get(user_id)
                if user and user.org_id == org.id:
                    grouped[(user_id, org.id)].append(work_list)

        deliveries = db.scalars(
            select(WorkListActivityDigestDelivery).order_by(WorkListActivityDigestDelivery.processed_at.desc())
        ).all()
        latest_delivery: dict[tuple[int, int], WorkListActivityDigestDelivery] = {}
        delivered_today: set[tuple[int, int]] = set()
        for delivery in deliveries:
            key = (delivery.user_id, delivery.org_id)
            latest_delivery.setdefault(key, delivery)
            if delivery.digest_date == digest_date:
                delivered_today.add(key)

        results: list[DigestResult] = []
        for key, work_lists in sorted(grouped.items(), key=lambda entry: user_map[entry[0][0]].email.lower()):
            user_id, org_id = key
            user = user_map[user_id]
            if normalized_targets and user.email.lower() not in normalized_targets:
                continue
            if key in delivered_today and not dry_run:
                results.append(DigestResult(user.email, "already-processed", 0))
                continue

            cutoff = processed_at - timedelta(days=1)
            if not dry_run and key in latest_delivery:
                cutoff = latest_delivery[key].processed_at
            active_lists = [
                work_list
                for work_list in work_lists
                if cutoff < latest_list_activity(work_list) <= processed_at
            ]
            active_lists.sort(key=latest_list_activity, reverse=True)

            if not active_lists:
                results.append(DigestResult(user.email, "no-activity", 0))
                if not dry_run:
                    db.add(
                        WorkListActivityDigestDelivery(
                            org_id=org_id,
                            user_id=user_id,
                            digest_date=digest_date,
                            status="no_activity",
                            processed_at=processed_at,
                        )
                    )
                    db.commit()
                continue

            org = org_map[org_id]
            subject, text_body, html_body = build_message(user, org, active_lists)
            if dry_run:
                results.append(DigestResult(user.email, "dry-run", len(active_lists), subject, text_body))
                continue

            send_email(user.email, subject, text_body, html_body)
            db.add(
                WorkListActivityDigestDelivery(
                    org_id=org_id,
                    user_id=user_id,
                    digest_date=digest_date,
                    status="sent",
                    processed_at=processed_at,
                )
            )
            db.commit()
            results.append(DigestResult(user.email, "sent", len(active_lists), subject))
        return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send one daily email for activity in shared Work Lists.")
    parser.add_argument("--email", action="append", help="Restrict the run to one or more email addresses.")
    parser.add_argument("--org-slug", help="Restrict the run to one organization.")
    parser.add_argument("--dry-run", action="store_true", help="Print messages without sending or recording delivery.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results = run_digests(args.email, args.org_slug, args.dry_run)
    for result in results:
        print(f"[{result.status}] {result.email}: {result.list_count} list(s)")
        if result.subject:
            print(f"Subject: {result.subject}")
        if result.body:
            print(result.body)
    if args.email and not results:
        print("No shared lists matched the requested email filter.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
