from __future__ import annotations

import argparse
import logging
import smtplib
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import SessionLocal
from app.main import (
    calculate_goal_achievement_percent,
    calculate_kpi_achievement_percent,
    calculate_plan_achievement_percent,
    performance_goal_alerts,
    performance_progress_query,
    send_email,
)
from app.models import Organization, PerformanceDigestDelivery, PerformanceGoal, PerformancePlan, Role, User
from app.time_utils import local_datetime

logger = logging.getLogger(__name__)


def plan_update_lines(plan, today, cutoff, now, weekly):
    recent = [
        event for event in plan.events
        if cutoff <= event.created_at < now and event.event_type != "goal_discussion_shared"
    ]
    regular_summary = weekly and plan.status in {"draft", "active", "submitted_for_review", "under_review"}
    alerts = performance_goal_alerts(plan, today)
    if not regular_summary and not recent:
        previous_alerts = set(performance_goal_alerts(plan, local_datetime(cutoff).date()))
        alerts = [alert for alert in alerts if alert not in previous_alerts]
        if not alerts:
            return []

    lines = [f"{plan.title} · {calculate_plan_achievement_percent(plan):g}% done"]
    for goal in sorted(plan.goals, key=lambda entry: (entry.sort_order, entry.id)):
        progress = calculate_goal_achievement_percent(goal)
        achievement = " · achieved" if progress >= 100 else ""
        lines.append(f"  {goal.title} · {progress:g}% done{achievement}")
        for kpi in sorted(goal.kpis, key=lambda entry: (entry.sort_order, entry.id)):
            if kpi.retired_at:
                continue
            lines.append(f"    {kpi.title} · {calculate_kpi_achievement_percent(kpi):g}% done")
            if regular_summary:
                for item in sorted(kpi.items, key=lambda entry: (entry.sort_order, entry.id)):
                    if not item.retired_at:
                        status = "Done" if item.is_completed else "Open"
                        deadline = f" · due {item.target_date:%d %b %Y}" if item.target_date else ""
                        lines.append(f"      [{status}] {item.title}{deadline}")
    for event in sorted(recent, key=lambda entry: (entry.created_at, entry.id)):
        label = event.event_type.replace("_", " ").capitalize()
        # Keep the decision reason and comment text in the app.
        details = event.details if event.event_type in {"goal_created", "goal_achieved", "checklist_item_completed"} else ""
        lines.append(f"  {label}" + (f" · {details}" if details else ""))
    lines.extend(f"  Alert · {alert}" for alert in alerts)
    return lines


def goal_discussion_update(goal, comments, member, cutoff, now):
    if cutoff <= member.invited_at < now:
        return f"Discussion invitation · {goal.title}"
    if any(max(cutoff, member.invited_at) <= comment.created_at < now
           for comment in comments if comment.author_id != member.user_id):
        return f"New discussion activity · {goal.title}"
    return ""


def run_digests(*, dry_run=False, org_slug=None, now=None):
    now = (now or datetime.utcnow()).replace(microsecond=0)
    today = local_datetime(now).date()
    week_start = today - timedelta(days=today.weekday())
    domain = get_settings().base_domain.strip().rstrip("/")
    base_url = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"
    failures = 0
    with SessionLocal() as db:
        orgs = select(Organization).where(Organization.is_active.is_(True))
        if org_slug:
            orgs = orgs.where(Organization.slug == org_slug)
        for org in db.scalars(orgs):
            people = {person.id: person for person in db.scalars(
                select(User).where(User.org_id == org.id, User.is_active.is_(True))
            )}
            plans = db.scalars(performance_progress_query(org.id).options(
                selectinload(PerformancePlan.events),
                selectinload(PerformancePlan.comments),
                selectinload(PerformancePlan.goals).selectinload(PerformanceGoal.members),
            )).all()
            assigned = defaultdict(list)
            shared = defaultdict(list)
            for plan in plans:
                owner = people.get(plan.user_id)
                if not owner:
                    continue
                recipients = {owner.id}
                for person_id in (plan.reviewer_id, owner.manager_id):
                    reviewer = people.get(person_id)
                    if reviewer and reviewer.role in {Role.ADMIN, Role.MANAGER}:
                        recipients.add(person_id)
                for person_id in recipients:
                    assigned[person_id].append((plan, owner))
                comments = defaultdict(list)
                for comment in plan.comments:
                    comments[comment.performance_goal_id].append(comment)
                for goal in plan.goals:
                    for member in goal.members:
                        if member.user_id in people:
                            shared[member.user_id].append((goal, comments[goal.id], member))
            deliveries = select(PerformanceDigestDelivery).where(
                PerformanceDigestDelivery.user_id.in_(assigned.keys() | shared.keys()),
                PerformanceDigestDelivery.digest_date <= today,
            ).order_by(PerformanceDigestDelivery.digest_date.desc())
            latest = {}
            for delivery in db.scalars(deliveries):
                latest.setdefault(delivery.user_id, delivery)
            for person_id in sorted(assigned.keys() | shared.keys()):
                previous = latest.get(person_id)
                if previous and previous.digest_date == today and not dry_run:
                    continue
                cutoff = previous.processed_at if previous else now - timedelta(days=1)
                weekly = not previous or previous.digest_date < week_start
                lines = []
                for plan, owner in assigned[person_id]:
                    updates = plan_update_lines(plan, today, cutoff, now, weekly)
                    if updates:
                        lines.extend([owner.full_name, *updates,
                                      f"{base_url}/{org.slug}/goals?plan_id={plan.id}", ""])
                for goal, comments, member in shared[person_id]:
                    update = goal_discussion_update(goal, comments, member, cutoff, now)
                    if update:
                        lines.extend([update, f"{base_url}/{org.slug}/goals/goals/{goal.id}/discussion", ""])
                person = people[person_id]
                subject = "Weekly goal status" if weekly else "Goal updates and alerts"
                body = "\n".join([f"Hi {person.full_name},", "", *lines])
                if dry_run:
                    if lines:
                        print(f"{person.email} · {subject}\n{body}")
                    continue
                db.add(PerformanceDigestDelivery(user_id=person_id, digest_date=today, processed_at=now))
                try:
                    db.flush()
                except IntegrityError:
                    db.rollback()
                    if db.get(PerformanceDigestDelivery, (person_id, today)):
                        continue
                    raise
                try:
                    if lines:
                        send_email(person.email, subject, body)
                except (OSError, smtplib.SMTPException):
                    logger.exception("Goal digest delivery failed for user %s", person_id)
                    failures += 1
                    db.rollback()
                    continue
                db.commit()
    return failures


def main():
    parser = argparse.ArgumentParser(description="Send goal updates, alerts, and weekly progress.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--org-slug")
    args = parser.parse_args()
    raise SystemExit(bool(run_digests(dry_run=args.dry_run, org_slug=args.org_slug)))


if __name__ == "__main__":
    main()
