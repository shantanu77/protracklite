from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta
from math import ceil
from decimal import Decimal

from sqlalchemy import case, false, func, or_, select
from sqlalchemy.orm import Session

from app.models import ActivityType, Holiday, Leave, LeaveType, OrgSettings, Project, Task, TaskStatus, TimeLog, User


def current_week_bounds(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def previous_week_bounds(today: date | None = None) -> tuple[date, date]:
    monday, _ = current_week_bounds(today)
    prev_monday = monday - timedelta(days=7)
    return prev_monday, prev_monday + timedelta(days=6)


def month_bounds(month_anchor: date) -> tuple[date, date]:
    month_start = month_anchor.replace(day=1)
    month_end = month_anchor.replace(day=calendar.monthrange(month_anchor.year, month_anchor.month)[1])
    return month_start, month_end


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

    def format_short_date(value: date | None) -> str | None:
        if not value:
            return None
        return value.strftime("%d %b %Y")

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
    latest_log_moment_by_task_id: dict[int, datetime] = {}
    if report_task_ids:
        report_logs = db.scalars(
            select(TimeLog)
            .where(TimeLog.task_id.in_(report_task_ids), TimeLog.user_id == user_id)
            .order_by(TimeLog.task_id.asc(), TimeLog.log_date.desc(), TimeLog.created_at.desc())
        ).all()
        for log in report_logs:
            latest_log_moment_by_task_id.setdefault(
                log.task_id,
                datetime.combine(log.log_date, datetime.max.time()) if log.log_date else log.created_at,
            )
            logs_by_task_id[log.task_id].append(
                {
                    "date": log.log_date,
                    "hours": float(log.hours or 0),
                    "notes": log.notes or "",
                }
            )

    def sort_tasks_by_latest_log(tasks: list[Task]) -> list[Task]:
        def ordering_value(value: datetime | None) -> float:
            if not value:
                return float("-inf")
            return value.timestamp()

        return sorted(
            tasks,
            key=lambda task: (
                latest_log_moment_by_task_id.get(task.id) is None,
                -ordering_value(latest_log_moment_by_task_id.get(task.id)),
                -ordering_value(task.updated_at or task.created_at),
            ),
        )

    this_week_tasks = sort_tasks_by_latest_log(this_week_tasks)
    pending_tasks = sort_tasks_by_latest_log(pending_tasks)
    completed_tasks = sort_tasks_by_latest_log(completed_tasks)
    stalled_tasks = sort_tasks_by_latest_log(stalled_tasks)

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
            "start_date_label": format_short_date(task.start_date),
            "end_date_label": format_short_date(task.end_date),
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
            "start_date_label": format_short_date(task.start_date),
            "end_date_label": format_short_date(task.end_date),
            "closed_at_label": format_short_date(task.closed_at.date() if task.closed_at else None),
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

    top_task_hours = (
        select(
            TimeLog.task_id.label("task_pk"),
            func.coalesce(func.sum(TimeLog.hours), 0).label("hours"),
        )
        .where(
            TimeLog.user_id == user_id,
            TimeLog.log_date >= month_start,
            TimeLog.log_date <= today,
        )
        .group_by(TimeLog.task_id)
        .subquery()
    )

    top_task_rows = db.execute(
        select(
            Task.task_id,
            Task.name,
            Task.status,
            Project.code,
            top_task_hours.c.hours,
        )
        .select_from(top_task_hours)
        .join(Task, top_task_hours.c.task_pk == Task.id)
        .join(Project, Task.project_id == Project.id)
        .where(
            Task.org_id == org_id,
            Task.is_archived.is_(False),
        )
        .order_by(top_task_hours.c.hours.desc(), Task.updated_at.desc())
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


def admin_leaderboard_report(db: Session, org_id: int, today: date | None = None) -> dict:
    today = today or date.today()
    month_start = today.replace(day=1)
    recent_window_start = max(month_start, today - timedelta(days=6))
    previous_window_end = recent_window_start - timedelta(days=1)
    previous_window_start = max(month_start, previous_window_end - timedelta(days=6)) if previous_window_end >= month_start else None

    team = db.scalars(
        select(User)
        .where(User.org_id == org_id, User.is_active.is_(True))
        .order_by(User.full_name.asc())
    ).all()
    member_ids = [member.id for member in team]

    leaderboard_rows: list[dict] = []
    if not member_ids:
        return {
            "today": today,
            "month_start": month_start,
            "leaders": [],
            "awards": [],
            "summary": {
                "active_people": 0,
                "hours_logged": 0.0,
                "tasks_completed": 0,
                "active_log_days": 0,
            },
            "charts": {
                "hours": [],
                "delivery": [],
                "performance": [],
            },
            "leaderboard": leaderboard_rows,
        }

    month_time_rows = db.execute(
        select(
            TimeLog.user_id,
            func.coalesce(func.sum(TimeLog.hours), 0).label("logged_hours"),
            func.count(func.distinct(TimeLog.log_date)).label("active_days"),
        )
        .select_from(TimeLog)
        .join(Task, TimeLog.task_id == Task.id)
        .where(
            Task.org_id == org_id,
            Task.is_archived.is_(False),
            TimeLog.user_id.in_(member_ids),
            TimeLog.log_date >= month_start,
            TimeLog.log_date <= today,
        )
        .group_by(TimeLog.user_id)
    ).all()
    month_stats_by_user = {
        row.user_id: {
            "logged_hours": float(row.logged_hours or 0),
            "active_days": int(row.active_days or 0),
        }
        for row in month_time_rows
    }

    month_chargeable_rows = db.execute(
        select(TimeLog.user_id, func.coalesce(func.sum(TimeLog.hours), 0).label("chargeable_hours"))
        .select_from(TimeLog)
        .join(Task, TimeLog.task_id == Task.id)
        .join(ActivityType, Task.activity_type_id == ActivityType.id)
        .where(
            Task.org_id == org_id,
            Task.is_archived.is_(False),
            TimeLog.user_id.in_(member_ids),
            TimeLog.log_date >= month_start,
            TimeLog.log_date <= today,
            ActivityType.is_chargeable.is_(True),
        )
        .group_by(TimeLog.user_id)
    ).all()
    chargeable_hours_by_user = {
        row.user_id: float(row.chargeable_hours or 0)
        for row in month_chargeable_rows
    }

    closed_task_rows = db.execute(
        select(
            Task.assigned_to.label("user_id"),
            func.count(Task.id).label("completed_tasks"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            Task.end_date.is_not(None)
                            & Task.closed_at.is_not(None)
                            & (func.date(Task.closed_at) <= Task.end_date),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("on_time_tasks"),
        )
        .where(
            Task.org_id == org_id,
            Task.is_archived.is_(False),
            Task.assigned_to.in_(member_ids),
            Task.status == TaskStatus.CLOSED,
            Task.closed_at.is_not(None),
            Task.closed_at >= datetime.combine(month_start, datetime.min.time()),
            Task.closed_at <= datetime.combine(today, datetime.max.time()),
        )
        .group_by(Task.assigned_to)
    ).all()
    completed_stats_by_user = {
        row.user_id: {
            "completed_tasks": int(row.completed_tasks or 0),
            "on_time_tasks": int(row.on_time_tasks or 0),
        }
        for row in closed_task_rows
    }

    open_task_rows = db.execute(
        select(
            Task.assigned_to.label("user_id"),
            func.coalesce(
                func.sum(case((Task.status != TaskStatus.CLOSED, 1), else_=0)),
                0,
            ).label("open_tasks"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Task.status != TaskStatus.CLOSED)
                            & Task.end_date.is_not(None)
                            & (Task.end_date < today),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("overdue_tasks"),
        )
        .where(
            Task.org_id == org_id,
            Task.is_archived.is_(False),
            Task.assigned_to.in_(member_ids),
        )
        .group_by(Task.assigned_to)
    ).all()
    open_stats_by_user = {
        row.user_id: {
            "open_tasks": int(row.open_tasks or 0),
            "overdue_tasks": int(row.overdue_tasks or 0),
        }
        for row in open_task_rows
    }

    current_window_rows = db.execute(
        select(TimeLog.user_id, func.coalesce(func.sum(TimeLog.hours), 0).label("hours"))
        .select_from(TimeLog)
        .join(Task, TimeLog.task_id == Task.id)
        .where(
            Task.org_id == org_id,
            Task.is_archived.is_(False),
            TimeLog.user_id.in_(member_ids),
            TimeLog.log_date >= recent_window_start,
            TimeLog.log_date <= today,
        )
        .group_by(TimeLog.user_id)
    ).all()
    current_window_hours_by_user = {row.user_id: float(row.hours or 0) for row in current_window_rows}

    previous_window_hours_by_user: dict[int, float] = {}
    if previous_window_start and previous_window_end >= previous_window_start:
        previous_window_rows = db.execute(
            select(TimeLog.user_id, func.coalesce(func.sum(TimeLog.hours), 0).label("hours"))
            .select_from(TimeLog)
            .join(Task, TimeLog.task_id == Task.id)
            .where(
                Task.org_id == org_id,
                Task.is_archived.is_(False),
                TimeLog.user_id.in_(member_ids),
                TimeLog.log_date >= previous_window_start,
                TimeLog.log_date <= previous_window_end,
            )
            .group_by(TimeLog.user_id)
        ).all()
        previous_window_hours_by_user = {row.user_id: float(row.hours or 0) for row in previous_window_rows}

    def compact_name(full_name: str) -> str:
        parts = [part for part in full_name.strip().split() if part]
        if not parts:
            return ""
        if len(parts) == 1:
            return parts[0].title()
        return f"{parts[0].title()} {parts[-1][0].upper()}."

    compact_names_by_user = {member.id: compact_name(member.full_name) for member in team}
    compact_name_counts: dict[str, int] = defaultdict(int)
    for value in compact_names_by_user.values():
        compact_name_counts[value] += 1
    short_names_by_user = {}
    for member in team:
        compact_value = compact_names_by_user[member.id]
        first_name = (member.full_name.strip().split() or [""])[0].title()
        short_names_by_user[member.id] = compact_value if compact_name_counts[compact_value] == 1 else first_name

    for member in team:
        rates = compute_work_rate(db, org_id, member.id, month_start, today)
        month_stats = month_stats_by_user.get(member.id, {})
        completed_stats = completed_stats_by_user.get(member.id, {})
        open_stats = open_stats_by_user.get(member.id, {})
        logged_hours = float(month_stats.get("logged_hours", 0))
        completed_tasks = int(completed_stats.get("completed_tasks", 0))
        on_time_tasks = int(completed_stats.get("on_time_tasks", 0))
        active_days = int(month_stats.get("active_days", 0))
        chargeable_hours = float(chargeable_hours_by_user.get(member.id, 0))
        available_hours = float(rates["available_hours"] or 0)
        utilization_rate = round((logged_hours / available_hours * 100) if available_hours else 0, 2)
        chargeable_share = round((chargeable_hours / logged_hours * 100) if logged_hours else 0, 2)
        on_time_rate = round((on_time_tasks / completed_tasks * 100) if completed_tasks else 0, 2)
        current_window_hours = float(current_window_hours_by_user.get(member.id, 0))
        previous_window_hours = float(previous_window_hours_by_user.get(member.id, 0))
        momentum_delta = round(current_window_hours - previous_window_hours, 2)
        leaderboard_rows.append(
            {
                "member_id": member.id,
                "name": member.full_name,
                "short_name": short_names_by_user.get(member.id, member.full_name),
                "logged_hours": round(logged_hours, 2),
                "chargeable_hours": round(chargeable_hours, 2),
                "active_days": active_days,
                "completed_tasks": completed_tasks,
                "on_time_tasks": on_time_tasks,
                "on_time_rate": on_time_rate,
                "available_hours": round(available_hours, 2),
                "utilization_rate": utilization_rate,
                "chargeable_share": chargeable_share,
                "open_tasks": int(open_stats.get("open_tasks", 0)),
                "overdue_tasks": int(open_stats.get("overdue_tasks", 0)),
                "current_window_hours": round(current_window_hours, 2),
                "previous_window_hours": round(previous_window_hours, 2),
                "momentum_delta": momentum_delta,
            }
        )

    leaderboard_rows = [
        row
        for row in leaderboard_rows
        if row["logged_hours"] > 0 or row["completed_tasks"] > 0 or row["current_window_hours"] > 0 or row["previous_window_hours"] > 0
    ]

    if not leaderboard_rows:
        return {
            "today": today,
            "month_start": month_start,
            "leaders": [],
            "awards": [],
            "summary": {
                "active_people": 0,
                "hours_logged": 0.0,
                "tasks_completed": 0,
                "active_log_days": 0,
            },
            "charts": {
                "hours": [],
                "delivery": [],
                "performance": [],
            },
            "leaderboard": [],
            "recent_window_start": recent_window_start,
            "previous_window_start": previous_window_start,
            "previous_window_end": previous_window_end,
        }

    def normalized(value: float, max_value: float) -> float:
        return (value / max_value) if max_value > 0 else 0.0

    max_logged = max((row["logged_hours"] for row in leaderboard_rows), default=0.0)
    max_completed = max((row["completed_tasks"] for row in leaderboard_rows), default=0)
    max_active_days = max((row["active_days"] for row in leaderboard_rows), default=0)
    max_utilization = max((row["utilization_rate"] for row in leaderboard_rows), default=0.0)
    max_chargeable = max((row["chargeable_hours"] for row in leaderboard_rows), default=0.0)

    for row in leaderboard_rows:
        score = (
            normalized(row["logged_hours"], max_logged) * 0.35
            + normalized(row["completed_tasks"], max_completed) * 0.25
            + normalized(row["active_days"], max_active_days) * 0.15
            + normalized(row["utilization_rate"], max_utilization) * 0.15
            + normalized(row["chargeable_hours"], max_chargeable) * 0.05
            + (row["on_time_rate"] / 100.0) * 0.05
        )
        row["score"] = round(score * 100, 1)
        row["star_count"] = max(1, min(5, ceil(row["score"] / 20)))

    leaderboard_rows.sort(
        key=lambda row: (
            row["score"],
            row["logged_hours"],
            row["completed_tasks"],
            row["active_days"],
            row["chargeable_hours"],
        ),
        reverse=True,
    )

    for index, row in enumerate(leaderboard_rows, start=1):
        row["rank"] = index

    medal_labels = ["Gold", "Silver", "Bronze"]
    leaders = []
    for index, row in enumerate(leaderboard_rows[:3]):
        leaders.append(
            {
                **row,
                "medal": medal_labels[index],
                "spotlight": [
                    f"{row['logged_hours']:.2f}h booked",
                    f"{row['completed_tasks']} tasks completed",
                    f"{row['utilization_rate']:.1f}% utilization",
                ],
            }
        )

    def build_award(title: str, subtitle: str, metric_key: str, suffix: str, tone: str) -> dict | None:
        if not leaderboard_rows:
            return None
        winner = max(
            leaderboard_rows,
            key=lambda row: (
                row[metric_key],
                row["score"],
                row["logged_hours"],
                row["completed_tasks"],
            ),
        )
        if winner[metric_key] <= 0:
            return None
        metric_value = winner[metric_key]
        if isinstance(metric_value, float):
            metric_text = f"{metric_value:.2f}{suffix}"
        else:
            metric_text = f"{metric_value}{suffix}"
        return {
            "title": title,
            "subtitle": subtitle,
            "winner": winner["name"],
            "metric_text": metric_text,
            "tone": tone,
        }

    awards = [
        build_award("Hours Crown", "Most effort booked this month", "logged_hours", "h", "gold"),
        build_award("Closer Cup", "Most tasks completed this month", "completed_tasks", "", "coral"),
        build_award("Chargeable Ace", "Highest chargeable hours delivered", "chargeable_hours", "h", "mint"),
        build_award("Consistency Star", "Most active booking days", "active_days", " days", "sky"),
        build_award("Momentum Rocket", "Strongest recent lift inside this month", "momentum_delta", "h", "sun"),
    ]
    awards = [award for award in awards if award]

    summary = {
        "active_people": len(leaderboard_rows),
        "hours_logged": round(sum(row["logged_hours"] for row in leaderboard_rows), 2),
        "tasks_completed": sum(row["completed_tasks"] for row in leaderboard_rows),
        "active_log_days": sum(row["active_days"] for row in leaderboard_rows),
    }

    hour_chart_rows = sorted(
        [row for row in leaderboard_rows if row["logged_hours"] > 0 or row["chargeable_hours"] > 0],
        key=lambda row: (row["logged_hours"], row["chargeable_hours"], row["score"]),
        reverse=True,
    )[:6]
    delivery_chart_rows = sorted(
        [row for row in leaderboard_rows if row["completed_tasks"] > 0 or row["active_days"] > 0],
        key=lambda row: (row["completed_tasks"], row["active_days"], row["on_time_rate"], row["score"]),
        reverse=True,
    )[:6]
    performance_chart_rows = sorted(
        [row for row in leaderboard_rows if row["logged_hours"] > 0 or row["completed_tasks"] > 0],
        key=lambda row: (row["score"], row["logged_hours"], row["completed_tasks"]),
        reverse=True,
    )[:6]

    charts = {
        "hours": [
            {
                "name": row["short_name"],
                "logged_hours": row["logged_hours"],
                "chargeable_hours": row["chargeable_hours"],
            }
            for row in hour_chart_rows
        ],
        "delivery": [
            {
                "name": row["short_name"],
                "completed_tasks": row["completed_tasks"],
                "active_days": row["active_days"],
                "on_time_rate": row["on_time_rate"],
            }
            for row in delivery_chart_rows
        ],
        "performance": [
            {
                "name": row["short_name"],
                "utilization_rate": row["utilization_rate"],
                "completed_tasks": row["completed_tasks"],
                "logged_hours": row["logged_hours"],
                "score": row["score"],
            }
            for row in performance_chart_rows
        ],
    }

    return {
        "today": today,
        "month_start": month_start,
        "leaders": leaders,
        "awards": awards,
        "summary": summary,
        "charts": charts,
        "leaderboard": leaderboard_rows,
        "recent_window_start": recent_window_start,
        "previous_window_start": previous_window_start,
        "previous_window_end": previous_window_end,
    }


def calendar_month_report(db: Session, org_id: int, user_id: int, month_anchor: date, selected_day: date | None = None) -> dict:
    today = date.today()
    month_start, month_end = month_bounds(month_anchor)
    selected_day = selected_day or (today if month_start <= today <= month_end else month_start)
    if selected_day < month_start:
        selected_day = month_start
    if selected_day > month_end:
        selected_day = month_end

    month_log_rows = db.execute(
        select(TimeLog, Task)
        .join(Task, TimeLog.task_id == Task.id)
        .where(
            Task.org_id == org_id,
            Task.assigned_to == user_id,
            Task.is_archived.is_(False),
            TimeLog.user_id == user_id,
            TimeLog.log_date >= month_start,
            TimeLog.log_date <= month_end,
        )
        .order_by(TimeLog.log_date.desc(), TimeLog.created_at.desc())
    ).all()
    log_task_ids = {task.id for _, task in month_log_rows}

    task_query = select(Task).where(
        Task.org_id == org_id,
        Task.assigned_to == user_id,
        Task.is_archived.is_(False),
        or_(
            Task.id.in_(log_task_ids) if log_task_ids else false(),
            (
                Task.start_date.is_not(None)
                & (
                    (
                        Task.end_date.is_not(None)
                        & (Task.start_date <= month_end)
                        & (Task.end_date >= month_start)
                    )
                    | (Task.end_date.is_(None) & (Task.start_date >= month_start) & (Task.start_date <= month_end))
                )
            ),
            Task.end_date.is_not(None) & (Task.end_date >= month_start) & (Task.end_date <= month_end),
            (
                Task.closed_at.is_not(None)
                & (Task.closed_at >= datetime.combine(month_start, datetime.min.time()))
                & (Task.closed_at <= datetime.combine(month_end, datetime.max.time()))
            ),
        ),
    )
    tasks = db.scalars(task_query.order_by(Task.updated_at.desc(), Task.id.desc())).all()

    logs_by_task_id: dict[int, list[dict]] = defaultdict(list)
    log_dates_by_task_id: dict[int, set[date]] = defaultdict(set)
    for log, task in month_log_rows:
        logs_by_task_id[task.id].append(
            {
                "date": log.log_date,
                "hours": float(log.hours or 0),
                "notes": log.notes or "",
            }
        )
        log_dates_by_task_id[task.id].add(log.log_date)

    project_map = {project.id: project for project in db.scalars(select(Project).where(Project.org_id == org_id)).all()}
    activity_type_map = {item.id: item for item in db.scalars(select(ActivityType).where(ActivityType.org_id == org_id)).all()}

    day_entries: dict[date, list[dict]] = defaultdict(list)

    def task_day_matches(task: Task, day: date) -> list[str]:
        reasons: list[str] = []
        if task.start_date and task.start_date == day:
            reasons.append("start")
        if task.end_date and task.end_date == day:
            reasons.append("deadline")
        if task.start_date and task.end_date and task.start_date <= day <= task.end_date:
            if "start" not in reasons and "deadline" not in reasons:
                reasons.append("scheduled")
        if day in log_dates_by_task_id.get(task.id, set()):
            reasons.append("logged")
        if task.closed_at and task.closed_at.date() == day:
            reasons.append("closed")
        return reasons

    for task in tasks:
        serialized = {
            "task_id": task.task_id,
            "name": task.name,
            "status": task.status.value,
            "project_code": project_map.get(task.project_id).code if project_map.get(task.project_id) else "",
            "project_name": project_map.get(task.project_id).name if project_map.get(task.project_id) else "",
            "activity_type_name": activity_type_map.get(task.activity_type_id).name if activity_type_map.get(task.activity_type_id) else "",
            "start_date": task.start_date,
            "end_date": task.end_date,
            "closed_at": task.closed_at.date() if task.closed_at else None,
            "logged_hours": float(task.logged_hours or 0),
            "estimated_hours": float(task.estimated_hours) if task.estimated_hours is not None else None,
            "logs": logs_by_task_id.get(task.id, []),
            "is_backlog": task.start_date is None and task.end_date is None and task.estimated_hours is None,
        }
        for day in daterange(month_start, month_end):
            reasons = task_day_matches(task, day)
            if reasons:
                day_entries[day].append(
                    {
                        **serialized,
                        "day_reasons": reasons,
                    }
                )

    for day in day_entries:
        day_entries[day].sort(
            key=lambda item: (
                "logged" not in item["day_reasons"],
                item["status"] == TaskStatus.CLOSED.value,
                -(item["logs"][0]["hours"] if item["logs"] else 0),
                item["task_id"],
            )
        )

    month_weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(month_start.year, month_start.month)
    day_cells = []
    for week in month_weeks:
        week_cells = []
        for day in week:
            entries = day_entries.get(day, [])
            week_cells.append(
                {
                    "date": day,
                    "in_month": day.month == month_start.month,
                    "is_today": day == today,
                    "is_selected": day == selected_day,
                    "task_count": len(entries),
                    "open_count": sum(1 for item in entries if item["status"] != TaskStatus.CLOSED.value),
                    "logged_count": sum(1 for item in entries if "logged" in item["day_reasons"]),
                    "sample_tasks": [item["task_id"] for item in entries[:2]],
                }
            )
        day_cells.append(week_cells)

    previous_month_anchor = (month_start - timedelta(days=1)).replace(day=1)
    next_month_anchor = (month_end + timedelta(days=1)).replace(day=1)

    return {
        "month_anchor": month_start,
        "month_start": month_start,
        "month_end": month_end,
        "selected_day": selected_day,
        "previous_month": previous_month_anchor,
        "next_month": next_month_anchor,
        "weeks": day_cells,
        "selected_day_tasks": day_entries.get(selected_day, []),
        "selected_day_total": len(day_entries.get(selected_day, [])),
        "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    }
