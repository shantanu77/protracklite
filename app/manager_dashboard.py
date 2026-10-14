"""Read-only manager overview. All queries are restricted to the supplied team."""
from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.capacity_sync import capacity_snapshots
from app.employee_dashboard import working_calendar
from app.leave_approvals import PENDING_STATUSES, capacity_local_approvals, locally_approved, overlay_capacity_approval
from app.models import (AttendanceRegularization, LeaveApproval, Task, TaskStatus, TimeLog,
                        WeeklyTaskPlan, WeeklyTaskPlanItem)
from app.reports import current_week_bounds


def build_manager_dashboard(db, org, viewer, members, goals, today):
    start, end = current_week_bounds(today)
    ids = [p.id for p in members]
    people = {p.id: p for p in members}
    prefix = f'/{org.slug}'
    calendar = working_calendar(db, org.id, start, end)
    snapshots = capacity_snapshots(db, org.id, start, end)
    decisions = capacity_local_approvals(db, org.id)
    absence = {}
    leaves = []
    for snapshot in snapshots.values():
        if not snapshot:
            continue
        for raw in snapshot.leave_days_json:
            entry = overlay_capacity_approval(raw, decisions)
            if entry['user_id'] not in people or not start.isoformat() <= entry['date'] <= end.isoformat():
                continue
            if str(entry.get('approval', '')).upper() != 'APPROVED':
                continue
            name = str(entry.get('type', '')).lower()
            if 'remote' in name or 'work from home' in name:
                continue
            day = date.fromisoformat(entry['date'])
            count = max(0, min(1, float(entry.get('count', 1))))
            absence[(entry['user_id'], day)] = min(1, absence.get((entry['user_id'], day), 0) + count)
            if day >= today and day in calendar:
                leaves.append({'name': people[entry['user_id']].full_name, 'date': day,
                               'days': count, 'type': entry.get('type', 'Leave'),
                               'url': f"{prefix}/manager/team-leaves?member_id={entry['user_id']}&month={day:%Y-%m}"})
    tasks = list(db.scalars(select(Task).options(selectinload(Task.project)).where(
        Task.org_id == org.id, Task.assigned_to.in_(ids), Task.is_archived.is_(False),
    ))) if ids else []
    planned_ids = set(db.scalars(select(WeeklyTaskPlanItem.task_id).join(
        WeeklyTaskPlan, WeeklyTaskPlanItem.weekly_task_plan_id == WeeklyTaskPlan.id).where(
        WeeklyTaskPlan.org_id == org.id, WeeklyTaskPlan.user_id.in_(ids), WeeklyTaskPlan.week_start == start,
    ))) if ids else set()
    logs = {(uid, day): float(hours) for uid, day, hours in db.execute(select(
        TimeLog.user_id, TimeLog.log_date, func.sum(TimeLog.hours)).join(Task).where(
        Task.org_id == org.id, Task.is_archived.is_(False), TimeLog.user_id.in_(ids),
        TimeLog.log_date >= start, TimeLog.log_date <= today,
    ).group_by(TimeLog.user_id, TimeLog.log_date))} if ids else {}
    by_person = defaultdict(list)
    by_project = defaultdict(list)
    for task in tasks:
        by_person[task.assigned_to].append(task)
        by_project[task.project_id].append(task)
    alerts, rows = [], []
    for person in members:
        own = by_person[person.id]
        opened = [t for t in own if t.status != TaskStatus.CLOSED]
        overdue = [t for t in opened if t.end_date and t.end_date < today]
        commitments = [t for t in opened if t.id in planned_ids or (
            t.end_date and t.end_date <= end and (not t.start_date or t.start_date <= end))]
        missing = sum(t.estimated_hours is None for t in commitments)
        planned = round(sum(max(0, float(t.estimated_hours or 0)-float(t.logged_hours or 0)) for t in commitments), 2)
        known = all(snapshot and person.id in snapshot.member_ids_json
                    for (year, month), snapshot in snapshots.items()
                    if any(d.year == year and d.month == month for d in calendar))
        available = round(sum(max(0, hours*(1-absence.get((person.id, day), 0))-logs.get((person.id, day), 0))
                              for day, hours in calendar.items() if day >= today), 2) if known else None
        elapsed = round(sum(hours*(1-absence.get((person.id, day), 0)) for day, hours in calendar.items() if day < today), 2) if known else None
        logged = round(sum(hours for (uid, day), hours in logs.items() if uid == person.id and day < today), 2)
        url = f'{prefix}/team/{person.id}/tasks'
        row = {'id': person.id, 'name': person.full_name,
               'department': person.department.name if person.department else 'No department',
               'planned': planned, 'available': available, 'missing_estimates': missing,
               'load_percent': round(planned/available*100) if available else None,
               'overloaded': available is not None and planned > available,
               'open': len(opened), 'overdue': len(overdue), 'logged': logged, 'elapsed': elapsed,
               'goal': goals.get(person.id), 'url': url}
        rows.append(row)
        for task in sorted([t for t in opened if t.status == TaskStatus.STALLED], key=lambda t: (t.end_date or end, t.id)):
            alerts.append({'type': 'delivery', 'title': task.name, 'detail': f'{person.full_name} · Blocked: {task.stalled_reason or "Reason not recorded"}', 'action': 'Review blocker', 'url': f'{prefix}/tasks/{task.task_id}'})
        if overdue:
            alerts.append({'type': 'delivery', 'title': f'{len(overdue)} overdue tasks · {person.full_name}', 'detail': 'Open tasks with a due date before today.', 'action': 'Review tasks', 'url': url})
        if row['overloaded']:
            alerts.append({'type': 'delivery', 'title': f'{person.full_name} is {planned-available:g}h over remaining capacity', 'detail': f'{planned:g}h estimated remaining work / {available:g}h available.', 'action': 'Review workload', 'url': url})
        if missing:
            alerts.append({'type': 'data', 'title': f'{missing} commitments need estimates · {person.full_name}', 'detail': 'Workload totals exclude tasks without an estimate.', 'action': 'Add estimates', 'url': url})
        if not known:
            alerts.append({'type': 'data', 'title': f'Leave data unavailable · {person.full_name}', 'detail': 'Capacity cannot be calculated until this member has a saved leave snapshot.', 'action': 'Review capacity data', 'url': f'{prefix}/manager/capacity?view=week'})
        if elapsed and logged < elapsed:
            alerts.append({'type': 'data', 'title': f'Effort records need review · {person.full_name}', 'detail': f'{logged:g}h recorded / {elapsed:g}h elapsed capacity through yesterday. This is not a productivity score.', 'action': 'Review effort', 'url': url})
    approvals = list(db.scalars(select(LeaveApproval).where(LeaveApproval.org_id == org.id,
        LeaveApproval.user_id.in_(ids), LeaveApproval.source_status.in_(PENDING_STATUSES)))) if ids else []
    for approval in approvals:
        if locally_approved(approval):
            continue
        raw = approval.request_json or {}
        alerts.append({'type': 'approval', 'title': f'Leave request · {people[approval.user_id].full_name}',
                       'detail': f"{raw.get('start_date', 'Date unavailable')} – {raw.get('end_date', '')} · Pending approval",
                       'action': 'Review request', 'url': f'{prefix}/manager/team-leaves?member_id={approval.user_id}&month={str(raw.get("start_date") or today.isoformat())[:7]}'})
    regularizations = list(db.scalars(select(AttendanceRegularization).where(
        AttendanceRegularization.org_id == org.id, AttendanceRegularization.user_id.in_(ids),
        AttendanceRegularization.manager_id == viewer.id, AttendanceRegularization.status == 'pending'))) if ids else []
    for item in regularizations:
        alerts.append({'type': 'approval', 'title': f'Attendance request · {people[item.user_id].full_name}',
                       'detail': 'Attendance regularization awaiting your review.', 'action': 'Review request',
                       'url': f'{prefix}/manager/team-leaves?member_id={item.user_id}'})
    projects = []
    for project_tasks in by_project.values():
        project = project_tasks[0].project
        opened = [t for t in project_tasks if t.status != TaskStatus.CLOSED]
        if not opened:
            continue
        blocked = sum(t.status == TaskStatus.STALLED for t in opened)
        overdue = sum(bool(t.end_date and t.end_date < today) for t in opened)
        done = len(project_tasks)-len(opened)
        projects.append({'name': project.name, 'total': len(project_tasks), 'done': done,
                         'progress': round(done/len(project_tasks)*100), 'blocked': blocked, 'overdue': overdue,
                         'status': 'Blocked' if blocked else 'At risk' if overdue else 'On track',
                         'url': f'{prefix}/tasks/{min(opened, key=lambda t: (t.end_date or end, t.id)).task_id}'})
    projects.sort(key=lambda p: (-p['blocked'], -p['overdue'], p['name']))
    alerts.sort(key=lambda a: {'delivery': 0, 'approval': 1, 'data': 2}[a['type']])
    return {'rows': rows, 'alerts': alerts, 'projects': projects, 'leaves': sorted(leaves, key=lambda l: (l['date'], l['name'])),
            'goals': [dict(goal, name=people[uid].full_name) for uid, goal in goals.items() if uid in people],
            'departments': sorted({r['department'] for r in rows}), 'start': start, 'end': end, 'today': today,
            'snapshots': [{'month': f'{year}-{month:02}', 'synced_at': snapshot.synced_at if snapshot else None}
                          for (year, month), snapshot in snapshots.items()],
            'overdue': sum(r['overdue'] for r in rows), 'overloaded': sum(r['overloaded'] for r in rows),
            'planned': round(sum(r['planned'] for r in rows), 2),
            'available': round(sum(r['available'] for r in rows), 2) if all(r['available'] is not None for r in rows) else None,
            'missing_estimates': sum(r['missing_estimates'] for r in rows),
            'at_risk': sum(p['status'] != 'On track' for p in projects),
            'approvals': sum(a['type'] == 'approval' for a in alerts)}
