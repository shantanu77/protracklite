from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ActivityType, Holiday, Leave, LeaveType, OrgSettings, Task, TaskStatus, TimeLog


def current_week_bounds(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    friday = monday + timedelta(days=4)
    return monday, friday


def previous_week_bounds(today: date | None = None) -> tuple[date, date]:
    monday, _ = current_week_bounds(today)
    prev_monday = monday - timedelta(days=7)
    return prev_monday, prev_monday + timedelta(days=4)


def leave_weight(leave_type: LeaveType) -> Decimal:
    if leave_type == LeaveType.FULL:
        return Decimal("1.0")
    return Decimal("0.5")


def daterange(start_date: date, end_date: date):
    cursor = start_date
    while cursor <= end_date:
        yield cursor
        cursor += timedelta(days=1)


def compute_work_rate(db: Session, org_id: int, user_id: int, from_date: date, to_date: date) -> dict:
    settings = db.scalar(select(OrgSettings).where(OrgSettings.org_id == org_id))
    weekend_days = set((settings.weekend_days if settings else [5, 6]) or [5, 6])
    work_hours_per_day = Decimal(str(settings.work_hours_per_day if settings else "8.00"))

    holidays = {
        item.holiday_date
        for item in db.scalars(select(Holiday).where(Holiday.org_id == org_id, Holiday.holiday_date >= from_date, Holiday.holiday_date <= to_date))
    }
    leaves = {
        item.leave_date: leave_weight(item.leave_type)
        for item in db.scalars(select(Leave).where(Leave.user_id == user_id, Leave.leave_date >= from_date, Leave.leave_date <= to_date))
    }

    available_days = Decimal("0")
    for day in daterange(from_date, to_date):
        if day.weekday() in weekend_days or day in holidays:
            continue
        available_days += Decimal("1.0") - leaves.get(day, Decimal("0"))

    available_hours = available_days * work_hours_per_day

    total_hours = db.scalar(
        select(func.coalesce(func.sum(TimeLog.hours), 0)).where(
            TimeLog.user_id == user_id,
            TimeLog.log_date >= from_date,
            TimeLog.log_date <= to_date,
        )
    )
    chargeable_hours = db.scalar(
        select(func.coalesce(func.sum(TimeLog.hours), 0))
        .select_from(TimeLog)
        .join(Task, TimeLog.task_id == Task.id)
        .join(ActivityType, Task.activity_type_id == ActivityType.id)
        .where(
            TimeLog.user_id == user_id,
            TimeLog.log_date >= from_date,
            TimeLog.log_date <= to_date,
            ActivityType.is_chargeable.is_(True),
        )
    )

    by_activity_rows = db.execute(
        select(ActivityType.name, func.coalesce(func.sum(TimeLog.hours), 0))
        .select_from(TimeLog)
        .join(Task, TimeLog.task_id == Task.id)
        .join(ActivityType, Task.activity_type_id == ActivityType.id)
        .where(TimeLog.user_id == user_id, TimeLog.log_date >= from_date, TimeLog.log_date <= to_date)
        .group_by(ActivityType.name)
        .order_by(func.sum(TimeLog.hours).desc())
    ).all()

    by_project_rows = db.execute(
        select(Task.project_id, func.coalesce(func.sum(TimeLog.hours), 0))
        .select_from(TimeLog)
        .join(Task, TimeLog.task_id == Task.id)
        .where(TimeLog.user_id == user_id, TimeLog.log_date >= from_date, TimeLog.log_date <= to_date)
        .group_by(Task.project_id)
        .order_by(func.sum(TimeLog.hours).desc())
    ).all()

    total_rate = (Decimal(str(total_hours)) / available_hours * Decimal("100")) if available_hours else Decimal("0")
    effective_rate = (Decimal(str(chargeable_hours)) / available_hours * Decimal("100")) if available_hours else Decimal("0")

    return {
        "available_hours": float(available_hours),
        "total_logged_hours": float(total_hours or 0),
        "chargeable_hours": float(chargeable_hours or 0),
        "total_rate": round(float(total_rate), 2),
        "effective_rate": round(float(effective_rate), 2),
        "by_activity": [{"label": label, "hours": float(hours)} for label, hours in by_activity_rows],
        "by_project": [{"project_id": project_id, "hours": float(hours)} for project_id, hours in by_project_rows],
    }


def monday_report(db: Session, org_id: int, user_id: int, today: date | None = None) -> dict:
    today = today or date.today()
    this_monday, this_friday = current_week_bounds(today)
    prev_monday, prev_friday = previous_week_bounds(today)

    pending = db.scalars(
        select(Task)
        .where(
            Task.org_id == org_id,
            Task.assigned_to == user_id,
            Task.status != TaskStatus.CLOSED,
            Task.created_at < datetime.combine(this_monday, datetime.min.time()),
        )
        .order_by(Task.created_at.asc())
    ).all()

    completed = db.scalars(
        select(Task)
        .where(
            Task.org_id == org_id,
            Task.assigned_to == user_id,
            Task.status == TaskStatus.CLOSED,
            Task.closed_at.is_not(None),
            Task.closed_at >= datetime.combine(prev_monday, datetime.min.time()),
            Task.closed_at <= datetime.combine(prev_friday, datetime.max.time()),
        )
        .order_by(Task.closed_at.desc())
    ).all()

    planned = db.scalars(
        select(Task)
        .where(
            Task.org_id == org_id,
            Task.assigned_to == user_id,
            Task.start_date >= this_monday,
            Task.start_date <= this_friday,
        )
        .order_by(Task.start_date.asc())
    ).all()

    return {"pending": pending, "completed": completed, "planned": planned}
