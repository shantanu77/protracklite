"""Personal dashboard calculations; no external integrations in the main-page path."""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future
from copy import deepcopy
from datetime import date, timedelta
from threading import Lock
from time import monotonic
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AttendanceRegularization, Holiday, Leave, OrgSettings, Project, Task, TaskStatus, TimeLog, WeeklyTaskPlan, WeeklyTaskPlanItem
from app.reports import current_week_bounds
from app.time_utils import local_now


def working_calendar(db: Session, org_id: int, start: date, end: date) -> dict[date, float]:
    settings = db.scalar(select(OrgSettings).where(OrgSettings.org_id == org_id))
    weekends = set(settings.weekend_days if settings and settings.weekend_days is not None else [5, 6])
    daily_hours = float(settings.work_hours_per_day if settings else 8)
    holidays = set(db.scalars(select(Holiday.holiday_date).where(
        Holiday.org_id == org_id, Holiday.holiday_date >= start, Holiday.holiday_date <= end,
    )))
    return {
        start + timedelta(days=i): daily_hours
        for i in range((end - start).days + 1)
        if (start + timedelta(days=i)).weekday() not in weekends and start + timedelta(days=i) not in holidays
    }


def build_employee_dashboard(db: Session, org: Any, user: Any, groups: dict, week_days: list[dict], today: date) -> dict:
    start, end = current_week_bounds(today)
    # Current-week completions include more than the history widget's old 12-row cap.
    rows = {task['task_id']: dict(task) for task in [*groups['all_unclosed'], *groups['completed']]}
    project_ids = {task['project_id'] for task in rows.values()}
    projects = {project.id: project for project in db.scalars(select(Project).where(
        Project.org_id == org.id, Project.id.in_(project_ids),
    ))} if project_ids else {}
    plan = db.scalar(select(WeeklyTaskPlan).where(
        WeeklyTaskPlan.org_id == org.id, WeeklyTaskPlan.user_id == user.id, WeeklyTaskPlan.week_start == start,
    ))
    plan_tasks = db.scalars(select(Task).join(WeeklyTaskPlanItem, WeeklyTaskPlanItem.task_id == Task.id).where(
        WeeklyTaskPlanItem.weekly_task_plan_id == plan.id, Task.org_id == org.id,
        Task.assigned_to == user.id, Task.is_archived.is_(False),
    )).all() if plan else []
    planned_ids = {task.task_id for task in plan_tasks}
    focus, week, blocked, done = [], [], [], []
    for task in rows.values():
        closed = task['status'] == 'closed'
        stalled = task['status'] == 'stalled'
        task['project_name'] = projects[task['project_id']].name if task['project_id'] in projects else 'Project unavailable'
        task['remaining_hours'] = round(max(float(task['estimated_hours']) - float(task['logged_hours'] or 0), 0), 2) if task['estimated_hours'] is not None else None
        task['can_complete'] = not closed and (not task['is_shared'] or task['created_by'] == user.id or user.role.value == 'admin')
        # Dates determine focus; blocked work gets its own actionable view.
        in_focus = not closed and not stalled and (
            (task['end_date'] is not None and task['end_date'] <= today) or task['start_date'] == today
        )
        in_week = not closed and (task['task_id'] in planned_ids or (task['end_date'] is not None and start <= task['end_date'] <= end))
        task['views'] = ' '.join(['all'] + (['today'] if in_focus else []) + (['week'] if in_week else []) + (['blocked'] if stalled else []) + (['completed'] if closed else []))
        if closed:
            task['focus_reason'] = task.get('completion_delay_label') or 'Completed this week.'
        elif stalled:
            task['focus_reason'] = task['stalled_reason'] or 'Review the blocker and agree the next step.'
        elif task['end_date'] and task['end_date'] < today and not closed:
            task['focus_reason'] = f"Overdue by {(today - task['end_date']).days} day(s). Review the next step or agree a new date."
        elif task['end_date'] == today and not closed:
            task['focus_reason'] = 'Due today. Finish the outcome or arrange a handoff.'
        elif task['start_date'] == today and not closed:
            task['focus_reason'] = 'Scheduled to start today.'
        elif task['task_id'] in planned_ids:
            task['focus_reason'] = 'Included in your saved weekly plan.'
        elif closed:
            task['focus_reason'] = task.get('completion_delay_label') or 'Completed this week.'
        else:
            task['focus_reason'] = 'No deadline set.' if task['end_date'] is None else 'Upcoming work. Plan the next step.'
        if in_focus: focus.append(task)
        if in_week: week.append(task)
        if stalled: blocked.append(task)
        if closed: done.append(task)
    queue = sorted(rows.values(), key=lambda task: (
        task['status'] == 'closed', task['end_date'] or date.max, task.get('dashboard_rank', 0), task['task_id'],
    ))
    scheduled = working_calendar(db, org.id, start, end)
    gap_days = []
    for day in week_days:
        hours = scheduled.get(day['date'], 0)
        if day['leave_type'] == 'full': hours = 0
        elif day['leave_type'] in {'half_am', 'half_pm'}: hours /= 2
        day['available_hours'] = hours
        day['can_log_effort'] = day['date'] < today and hours > 0
        day['can_log_base'] = day['date'] < today and day['date'] in scheduled
        if day['can_log_effort'] and day['hours'] < hours:
            day['gap_hours'] = round(hours - day['hours'], 2)
            gap_days.append(day)
    estimated_work = sum(task['remaining_hours'] or 0 for task in week)
    unknown_estimates = sum(task['remaining_hours'] is None for task in week)
    upcoming = db.scalar(select(Leave).where(Leave.user_id == user.id, Leave.leave_date > today).order_by(Leave.leave_date).limit(1))
    conflicts = [task for task in queue if task['status'] != 'closed' and upcoming and task['end_date'] == upcoming.leave_date]
    return {
        'queue': queue, 'focus': focus, 'week': week, 'blocked': blocked, 'done': done,
        'counts': {'today': len(focus), 'week': len(week), 'blocked': len(blocked), 'completed': len(done), 'all': len(queue)},
        'gap_days': gap_days, 'attention_count': len(blocked) + len(gap_days),
        'available_hours': round(sum(day['available_hours'] for day in week_days), 2),
        'remaining_available_hours': round(sum(max(day['available_hours'] - day['hours'], 0) for day in week_days if day['date'] >= today), 2),
        'estimated_work': round(estimated_work, 2), 'unknown_estimates': unknown_estimates,
        'plan_total': len(plan_tasks) if plan else None,
        'plan_completed': sum(task.status == TaskStatus.CLOSED for task in plan_tasks),
        'upcoming_leave': upcoming, 'leave_conflicts': conflicts,
        'latest_effort_day': gap_days[-1] if gap_days else next((day for day in reversed(week_days) if day['can_log_effort']), None),
        'projects': sorted(projects.values(), key=lambda project: project.name.lower()),
    }


class DashboardSourceCache:
    """Bounded per-employee cache with concurrent fetches across employees."""
    def __init__(self):
        self.entries: OrderedDict = OrderedDict()
        self.inflight: dict = {}
        self.lock = Lock()

    def get(self, key: tuple, loader: Callable) -> tuple:
        with self.lock:
            cached = self.entries.get(key)
            if cached and cached[0] > monotonic():
                self.entries.move_to_end(key)
                return deepcopy(cached[1])
            existing = self.inflight.get(key)
            if existing is None:
                future = Future()
                self.inflight[key] = future
        if existing is not None:
            return deepcopy(existing.result())
        try:
            data = loader()
            stamped = (*data, local_now())
            ttl = 300 if data[0].get('status') == 'synced' and data[1].status == 'synced' else 30
            with self.lock:
                self.entries[key] = (monotonic() + ttl, stamped)
                self.entries.move_to_end(key)
                while len(self.entries) > 256:
                    self.entries.popitem(last=False)
            future.set_result(stamped)
            return deepcopy(stamped)
        except Exception as exc:
            future.set_exception(exc)
            raise
        finally:
            with self.lock:
                self.inflight.pop(key, None)

    def invalidate(self, org_id: int, user_id: int):
        with self.lock:
            for key in list(self.entries):
                if key[:2] == (org_id, user_id):
                    self.entries.pop(key, None)


source_cache = DashboardSourceCache()


def approved_absence_counts(leaves: Any, employee_zoho_id: str, work_from_home_type_id: str = '') -> dict[date, float]:
    approved_absence: dict[date, float] = {}
    if leaves.status == 'synced':
        for leave in leaves.leaves:
            if leave.get('employee_zoho_id') != employee_zoho_id or str(leave.get('approval_status', '')).strip().upper() != 'APPROVED':
                continue
            name = str(leave.get('leave_type_name', '')).casefold()
            if 'remote' in name or 'work from home' in name or (work_from_home_type_id and str(leave.get('leave_type_id')) == work_from_home_type_id):
                continue
            day_counts = leave.get('day_counts')
            if not day_counts:
                dates = leave.get('day_dates') or tuple(leave['start_date'] + timedelta(days=i) for i in range((leave['end_date'] - leave['start_date']).days + 1))
                count = min(float(leave.get('leave_days') or len(dates)) / max(len(dates), 1), 1)
                day_counts = [(day, count) for day in dates]
            for day, count in day_counts:
                approved_absence[day] = min(approved_absence.get(day, 0) + max(float(count), 0), 1)
    return approved_absence


def personal_attendance_summary(db: Session, org: Any, user: Any, attendance: dict, leaves: Any, today: date, synced_at: Any, work_from_home_type_id: str = '') -> dict:
    start, end = current_week_bounds(today)
    calendar = working_calendar(db, org.id, min(today.replace(day=1), start), max(today, end))
    approved_absence = approved_absence_counts(leaves, user.zoho_employee_id, work_from_home_type_id)
    requests = db.scalars(select(AttendanceRegularization).where(
        AttendanceRegularization.org_id == org.id, AttendanceRegularization.user_id == user.id,
        AttendanceRegularization.attendance_date >= today.replace(day=1), AttendanceRegularization.attendance_date < today,
    )).all()
    request_days = {record.attendance_date for record in requests if record.status in {'approved', 'pending'}}
    marked = {row['date'] for row in attendance.get('rows', []) if row['first_in_label'] != '—' or row['last_out_label'] != '—'}
    # Suppress absence notices when either source is unknown; no inferred leave.
    missing = [day for day in calendar if today.replace(day=1) <= day < today and day not in marked and day not in request_days and approved_absence.get(day, 0) < 1] if attendance['status'] == 'synced' and leaves.status == 'synced' else []
    today_row = next((row for row in attendance.get('rows', []) if row['date'] == today), None)
    logged_today = float(db.scalar(select(func.coalesce(func.sum(TimeLog.hours), 0)).join(Task, Task.id == TimeLog.task_id).where(
        Task.org_id == org.id, Task.is_archived.is_(False), TimeLog.user_id == user.id, TimeLog.log_date == today,
    )) or 0)
    remaining_hours = sum(max(hours * (1 - approved_absence.get(day, 0)) - (logged_today if day == today else 0), 0) for day, hours in calendar.items() if today <= day <= end)
    return {
        'status': attendance['status'], 'leave_status': leaves.status,
        'synced_at': synced_at.strftime('%d %b, %I:%M %p'),
        'today': {key: today_row[key] for key in ('mode_label', 'attendance_location', 'attendance_source', 'first_in_label', 'last_out_label', 'is_open')} if today_row else None,
        'missing_count': len(missing), 'missing_dates': [day.isoformat() for day in missing],
        'pending_count': sum(record.status == 'pending' for record in requests),
        'can_request': bool(user.manager_id),
        'remaining_available_hours': round(remaining_hours, 2) if leaves.status == 'synced' else None,
        'available_hours': round(sum(hours * (1 - approved_absence.get(day, 0)) for day, hours in calendar.items() if start <= day <= end), 2) if leaves.status == 'synced' else None,
    }
