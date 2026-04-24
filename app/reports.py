from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from math import ceil
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import ActivityType, Holiday, Leave, LeaveType, OrgSettings, Project, Task, TaskStatus, TimeLog


def current_week_bounds(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def previous_week_bounds(today: date | None = None) -> tuple[date, date]:
    monday, _ = current_week_bounds(today)
    prev_monday = monday - timedelta(days=7)
    return prev_monday, prev_monday + timedelta(days=6)


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
        select(func.coalesce(func.sum(TimeLog.hours), 0))
        .select_from(TimeLog)
        .join(Task, TimeLog.task_id == Task.id)
        .where(
            Task.org_id == org_id,
            Task.is_archived.is_(False),
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
            Task.org_id == org_id,
            Task.is_archived.is_(False),
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
        .where(
            Task.org_id == org_id,
            Task.is_archived.is_(False),
            TimeLog.user_id == user_id,
            TimeLog.log_date >= from_date,
            TimeLog.log_date <= to_date,
        )
        .group_by(ActivityType.name)
        .order_by(func.sum(TimeLog.hours).desc())
    ).all()

    by_project_rows = db.execute(
        select(Task.project_id, func.coalesce(func.sum(TimeLog.hours), 0))
        .select_from(TimeLog)
        .join(Task, TimeLog.task_id == Task.id)
        .where(
            Task.org_id == org_id,
            Task.is_archived.is_(False),
            TimeLog.user_id == user_id,
            TimeLog.log_date >= from_date,
            TimeLog.log_date <= to_date,
        )
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
    this_monday, this_sunday = current_week_bounds(today)
    prev_monday, prev_sunday = previous_week_bounds(today)
    two_week_cutoff = prev_monday - timedelta(days=7)
    null_end_date_last = case((Task.end_date.is_(None), 1), else_=0)

    last_week_rates = compute_work_rate(db, org_id, user_id, prev_monday, prev_sunday)

    this_week_tasks = db.scalars(
        select(Task)
        .where(
            Task.org_id == org_id,
            Task.assigned_to == user_id,
            Task.is_archived.is_(False),
            Task.status != TaskStatus.CLOSED,
            Task.status != TaskStatus.STALLED,
            Task.start_date >= this_monday,
            Task.start_date <= this_sunday,
            Task.end_date.is_not(None),
        )
        .order_by(null_end_date_last.asc(), Task.end_date.asc(), Task.start_date.asc(), Task.created_at.asc())
    ).all()

    pending_tasks = db.scalars(
        select(Task)
        .where(
            Task.org_id == org_id,
            Task.assigned_to == user_id,
            Task.is_archived.is_(False),
            Task.status != TaskStatus.CLOSED,
            Task.status != TaskStatus.STALLED,
            Task.start_date < this_monday,
            Task.start_date.is_not(None),
            Task.end_date.is_not(None),
        )
        .order_by(Task.start_date.asc(), null_end_date_last.asc(), Task.end_date.asc(), Task.created_at.asc())
    ).all()

    backlog_tasks = db.scalars(
        select(Task)
        .where(
            Task.org_id == org_id,
            Task.assigned_to == user_id,
            Task.is_archived.is_(False),
            Task.status != TaskStatus.CLOSED,
            Task.status != TaskStatus.STALLED,
            Task.start_date.is_(None),
            Task.end_date.is_(None),
            Task.estimated_hours.is_(None),
        )
        .order_by(Task.start_date.asc(), Task.created_at.asc())
    ).all()

    completed_tasks = db.scalars(
        select(Task)
        .where(
            Task.org_id == org_id,
            Task.assigned_to == user_id,
            Task.is_archived.is_(False),
            Task.status == TaskStatus.CLOSED,
            Task.closed_at.is_not(None),
            Task.closed_at >= datetime.combine(prev_monday, datetime.min.time()),
            Task.closed_at <= datetime.combine(prev_sunday, datetime.max.time()),
        )
        .order_by(Task.closed_at.desc(), Task.start_date.asc())
    ).all()

    stalled_tasks = db.scalars(
        select(Task)
        .where(
            Task.org_id == org_id,
            Task.assigned_to == user_id,
            Task.is_archived.is_(False),
            Task.status == TaskStatus.STALLED,
        )
        .order_by(null_end_date_last.asc(), Task.end_date.asc(), Task.start_date.asc(), Task.created_at.asc())
    ).all()

    report_task_ids = [
        task.id
        for task in [*this_week_tasks, *pending_tasks, *completed_tasks, *stalled_tasks]
    ]
    logs_by_task_id: dict[int, list[dict]] = defaultdict(list)
    if report_task_ids:
        report_logs = db.scalars(
            select(TimeLog)
            .where(TimeLog.task_id.in_(report_task_ids), TimeLog.user_id == user_id)
            .order_by(TimeLog.task_id.asc(), TimeLog.log_date.desc(), TimeLog.created_at.desc())
        ).all()
        for log in report_logs:
            logs_by_task_id[log.task_id].append(
                {
                    "date": log.log_date,
                    "hours": float(log.hours or 0),
                    "notes": log.notes or "",
                }
            )

    previous_week_booked_hours = last_week_rates["total_logged_hours"]
    previous_week_available_hours = last_week_rates["available_hours"]
    previous_week_target_hours = round(min(35.0, previous_week_available_hours), 2)
    previous_week_effort_rate = last_week_rates["total_rate"]

    booking_health_tone = "success"
    if previous_week_effort_rate < 80 or previous_week_booked_hours < previous_week_target_hours:
        booking_health_tone = "danger"
    elif previous_week_effort_rate < 90:
        booking_health_tone = "warning"

    pending_from_last_week_count = sum(1 for task in pending_tasks if task.start_date and prev_monday <= task.start_date <= prev_sunday)
    pending_more_than_two_weeks_count = sum(1 for task in pending_tasks if task.start_date and task.start_date < two_week_cutoff)
    total_open_task_count = len(this_week_tasks) + len(pending_tasks) + len(backlog_tasks) + len(stalled_tasks)

    booking_summary = (
        f"Last week: {previous_week_booked_hours:.2f}h booked against "
        f"{previous_week_target_hours:.2f}h target, {pending_from_last_week_count} task"
        f"{'' if pending_from_last_week_count == 1 else 's'} carried from last week, "
        f"{pending_more_than_two_weeks_count} older than 2 weeks."
    )

    def serialize_open_task(task: Task) -> dict:
        deadline_label = "No deadline"
        deadline_tone = "muted"
        overdue_days = None
        if task.end_date:
            day_delta = (task.end_date - today).days
            if day_delta < 0:
                overdue_days = abs(day_delta)
                deadline_label = f"Late by {overdue_days} day{'s' if overdue_days != 1 else ''}"
                deadline_tone = "late"
            elif day_delta == 0:
                deadline_label = "Due today"
                deadline_tone = "due"
            else:
                deadline_label = f"{day_delta} day{'s' if day_delta != 1 else ''} remaining"
                deadline_tone = "upcoming"

        return {
            "task_id": task.task_id,
            "name": task.name,
            "status": task.status.value,
            "description": task.description or "",
            "start_date": task.start_date,
            "end_date": task.end_date,
            "logged_hours": float(task.logged_hours or 0),
            "estimated_hours": float(task.estimated_hours) if task.estimated_hours is not None else None,
            "deadline_label": deadline_label,
            "deadline_tone": deadline_tone,
            "overdue_days": overdue_days,
            "stalled_reason": task.stalled_reason or "",
            "time_logs": logs_by_task_id.get(task.id, []),
        }

    def serialize_completed_task(task: Task) -> dict:
        estimated_hours = float(task.estimated_hours) if task.estimated_hours is not None else None
        logged_hours = float(task.logged_hours or 0)
        effort_percent = None
        effort_label = "No estimate"
        effort_tone = "muted"
        if estimated_hours and estimated_hours > 0:
            delta_percent = ((logged_hours - estimated_hours) / estimated_hours) * 100
            effort_percent = round(delta_percent, 2)
            if abs(delta_percent) < 0.01:
                effort_label = "On estimate"
                effort_tone = "upcoming"
            elif delta_percent > 0:
                effort_label = f"{abs(delta_percent):.2f}% over"
                effort_tone = "late"
            else:
                effort_label = f"{abs(delta_percent):.2f}% under"
                effort_tone = "upcoming"
        return {
            "task_id": task.task_id,
            "name": task.name,
            "status": task.status.value,
            "description": task.description or "",
            "start_date": task.start_date,
            "end_date": task.end_date,
            "closed_at": task.closed_at.date() if task.closed_at else None,
            "logged_hours": logged_hours,
            "estimated_hours": estimated_hours,
            "effort_percent": effort_percent,
            "effort_label": effort_label,
            "effort_tone": effort_tone,
            "time_logs": logs_by_task_id.get(task.id, []),
        }

    return {
        "week_start": this_monday,
        "week_end": this_sunday,
        "previous_week_start": prev_monday,
        "previous_week_end": prev_sunday,
        "previous_week_closed_count": len(completed_tasks),
        "previous_week_effort_hours": previous_week_booked_hours,
        "previous_week_available_hours": previous_week_available_hours,
        "previous_week_target_hours": previous_week_target_hours,
        "previous_week_effort_rate": previous_week_effort_rate,
        "previous_week_booking_tone": booking_health_tone,
        "pending_from_last_week_count": pending_from_last_week_count,
        "pending_more_than_two_weeks_count": pending_more_than_two_weeks_count,
        "total_open_task_count": total_open_task_count,
        "booking_summary": booking_summary,
        "this_week_tasks": [serialize_open_task(task) for task in this_week_tasks],
        "pending_tasks": [serialize_open_task(task) for task in pending_tasks],
        "backlog_tasks": [serialize_open_task(task) for task in backlog_tasks],
        "completed_tasks": [serialize_completed_task(task) for task in completed_tasks],
        "stalled_tasks": [serialize_open_task(task) for task in stalled_tasks],
        "previous_week_start": prev_monday,
    }


def reports_overview(db: Session, org_id: int, user_id: int, today: date | None = None) -> dict:
    today = today or date.today()
    now = datetime.now()
    this_monday, this_sunday = current_week_bounds(today)
    month_start = today.replace(day=1)

    week_effort = []
    for offset in range(3, -1, -1):
        week_start = this_monday - timedelta(days=7 * offset)
        week_end = week_start + timedelta(days=6)
        rates = compute_work_rate(db, org_id, user_id, week_start, week_end)
        week_effort.append(
            {
                "label": f"{week_start.strftime('%d %b')} - {week_end.strftime('%d %b')}",
                "booked_hours": rates["total_logged_hours"],
                "available_hours": rates["available_hours"],
            }
        )

    week_rates = compute_work_rate(db, org_id, user_id, this_monday, today)
    month_rates = compute_work_rate(db, org_id, user_id, month_start, today)

    top_task_rows = db.execute(
        select(
            Task.task_id,
            Task.name,
            Task.status,
            Project.code,
            func.coalesce(func.sum(TimeLog.hours), 0).label("hours"),
        )
        .select_from(TimeLog)
        .join(Task, TimeLog.task_id == Task.id)
        .join(Project, Task.project_id == Project.id)
        .where(
            Task.org_id == org_id,
            Task.is_archived.is_(False),
            TimeLog.user_id == user_id,
            TimeLog.log_date >= month_start,
            TimeLog.log_date <= today,
        )
        .group_by(Task.id, Task.task_id, Task.name, Task.status, Project.code)
        .order_by(func.sum(TimeLog.hours).desc(), Task.updated_at.desc())
        .limit(5)
    ).all()
    top_tasks = [
        {
            "task_id": row.task_id,
            "name": row.name,
            "status": row.status.value,
            "project_code": row.code,
            "hours": float(row.hours or 0),
        }
        for row in top_task_rows
    ]

    null_end_date_last = case((Task.end_date.is_(None), 1), else_=0)
    pending_rows = db.scalars(
        select(Task)
        .where(
            Task.org_id == org_id,
            Task.assigned_to == user_id,
            Task.is_archived.is_(False),
            Task.status.not_in([TaskStatus.CLOSED, TaskStatus.STALLED]),
            Task.start_date.is_not(None),
            Task.end_date.is_not(None),
        )
        .order_by(null_end_date_last.asc(), Task.end_date.asc(), Task.start_date.desc(), Task.created_at.desc())
    ).all()
    pending_tasks = []
    pending_delay_buckets = {
        "1-8h": 0,
        "8-24h": 0,
        "24-40h": 0,
        "40h+": 0,
    }
    for task in pending_rows:
        overdue_days = 0
        overdue_hours = 0
        if task.end_date and task.end_date < today:
            overdue_days = (today - task.end_date).days
            overdue_at = datetime.combine(task.end_date, datetime.max.time())
            overdue_hours = max(1, ceil((now - overdue_at).total_seconds() / 3600))
            if overdue_hours <= 8:
                pending_delay_buckets["1-8h"] += 1
            elif overdue_hours <= 24:
                pending_delay_buckets["8-24h"] += 1
            elif overdue_hours <= 40:
                pending_delay_buckets["24-40h"] += 1
            else:
                pending_delay_buckets["40h+"] += 1
        pending_tasks.append(
            {
                "task_id": task.task_id,
                "name": task.name,
                "status": task.status.value,
                "start_date": task.start_date,
                "end_date": task.end_date,
                "logged_hours": float(task.logged_hours or 0),
                "estimated_hours": float(task.estimated_hours) if task.estimated_hours is not None else None,
                "overdue_days": overdue_days,
                "overdue_hours": overdue_hours,
            }
        )
    pending_tasks.sort(
        key=lambda item: (item["overdue_hours"], item["overdue_days"], item["start_date"].toordinal() if item["start_date"] else 0),
        reverse=True,
    )

    burn_down = []
    for offset in range(4, -1, -1):
        week_start = this_monday - timedelta(days=7 * offset)
        week_end = week_start + timedelta(days=6)
        assigned_count = db.scalar(
            select(func.count())
            .select_from(Task)
            .where(
                Task.org_id == org_id,
                Task.assigned_to == user_id,
                Task.is_archived.is_(False),
                Task.created_at >= datetime.combine(week_start, datetime.min.time()),
                Task.created_at <= datetime.combine(week_end, datetime.max.time()),
            )
        )
        closed_count = db.scalar(
            select(func.count())
            .select_from(Task)
            .where(
                Task.org_id == org_id,
                Task.assigned_to == user_id,
                Task.is_archived.is_(False),
                Task.status == TaskStatus.CLOSED,
                Task.closed_at.is_not(None),
                Task.closed_at >= datetime.combine(week_start, datetime.min.time()),
                Task.closed_at <= datetime.combine(week_end, datetime.max.time()),
            )
        )
        burn_down.append(
            {
                "label": week_start.strftime("%d %b"),
                "assigned": int(assigned_count or 0),
                "closed": int(closed_count or 0),
            }
        )

    activity_allocation_rows = db.execute(
        select(
            ActivityType.name,
            func.coalesce(func.sum(TimeLog.hours), 0).label("hours"),
        )
        .select_from(TimeLog)
        .join(Task, TimeLog.task_id == Task.id)
        .join(ActivityType, Task.activity_type_id == ActivityType.id)
        .where(
            Task.org_id == org_id,
            Task.is_archived.is_(False),
            TimeLog.user_id == user_id,
            TimeLog.log_date >= month_start,
            TimeLog.log_date <= today,
        )
        .group_by(ActivityType.name)
        .order_by(func.sum(TimeLog.hours).desc(), ActivityType.name.asc())
    ).all()

    activity_allocation = [{"name": row.name, "hours": float(row.hours or 0)} for row in activity_allocation_rows]

    return {
        "week_effort": week_effort,
        "week_rates": week_rates,
        "month_rates": month_rates,
        "top_tasks": top_tasks,
        "pending_tasks": pending_tasks,
        "pending_task_count": len(pending_tasks),
        "pending_delay_buckets": [{"label": key, "count": value} for key, value in pending_delay_buckets.items()],
        "burn_down": burn_down,
        "activity_allocation": activity_allocation,
        "week_start": this_monday,
        "week_end": this_sunday,
        "month_start": month_start,
        "today": today,
    }
