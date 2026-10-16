"""Month-level profile attendance facts from saved records; no integration calls."""
from datetime import date, timedelta
from sqlalchemy import select
from app.config import get_settings
from app.employee_dashboard import working_calendar
from app.leave_approvals import CANCELLED_STATUSES, PENDING_STATUSES, locally_approved
from app.models import AttendanceRegularization, Leave, LeaveApproval, LeaveType


def profile_attendance_summary(db, org_id, user_id, attendance, today):
    start = today.replace(day=1)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    calendar = working_calendar(db, org_id, start, end)
    remote_type = get_settings().zoho_work_from_home_leave_type_id.strip()
    records = list(db.scalars(select(LeaveApproval).where(LeaveApproval.org_id == org_id, LeaveApproval.user_id == user_id)))
    by_id = {r.zoho_leave_id: r for r in records}
    applied, approved = {}, {}
    def add(day, count, is_approved):
        if day not in calendar:
            return
        count = max(0, min(1, float(count)))
        applied[day] = min(1, applied.get(day, 0) + count)
        if is_approved:
            approved[day] = min(1, approved.get(day, 0) + count)
    for record in records:
        raw = record.request_json or {}
        status = record.source_status.strip().upper()
        name = str(raw.get('leave_type_name') or '').casefold()
        if status in CANCELLED_STATUSES or 'remote' in name or 'work from home' in name or (remote_type and str(raw.get('leave_type_id')) == remote_type):
            continue
        is_approved = status == 'APPROVED' or locally_approved(record)
        if not is_approved and status not in PENDING_STATUSES:
            continue
        counts = raw.get('day_counts') or []
        if not counts:
            try:
                first, last = date.fromisoformat(raw['start_date']), date.fromisoformat(raw['end_date'])
            except (KeyError, TypeError, ValueError):
                continue
            # Imported records without per-day counts allocate across their working dates.
            days = list(working_calendar(db, org_id, first, last))
            weight = min(1, float(raw.get('leave_days') or len(days)) / max(1, len(days)))
            counts = [(d.isoformat(), weight) for d in days]
        for day, count in counts:
            try:
                add(date.fromisoformat(str(day)), count, is_approved)
            except (ValueError, TypeError):
                continue
    for leave in db.scalars(select(Leave).where(Leave.user_id == user_id, Leave.leave_date >= start, Leave.leave_date <= end)):
        if leave.zoho_leave_id and leave.zoho_leave_id in by_id:
            continue  # Imported request status and dates are authoritative; do not double count.
        add(leave.leave_date, 1 if leave.leave_type == LeaveType.FULL else .5, False)
    result = {'applied_leave': round(sum(applied.values()), 2), 'approved_leave': round(sum(approved.values()), 2),
              'pending_leave': round(sum(applied.values())-sum(approved.values()), 2),
              'unmarked': None, 'missing_days': [], 'month_label': today.strftime('%B')}
    if attendance.get('status') != 'synced':
        return result
    requests = {r.attendance_date: r for r in db.scalars(select(AttendanceRegularization).where(
        AttendanceRegularization.org_id == org_id, AttendanceRegularization.user_id == user_id,
        AttendanceRegularization.attendance_date >= start, AttendanceRegularization.attendance_date <= today))}
    marked = {row['date'] for row in attendance.get('rows', [])
              if row.get('first_in_label', '—') != '—' or row.get('last_out_label', '—') != '—'}
    regularized = {d for d, r in requests.items() if r.status == 'approved'}
    rows = [r for r in attendance.get('rows', []) if r['date'] in marked]
    attendance['office_days'] = round(sum(r.get('office_count', .5 if r.get('mode') == 'hybrid' else 1 if r.get('mode') == 'office' else 0) for r in rows), 2)
    attendance['remote_days'] = round(sum(r.get('remote_count', .5 if r.get('mode') == 'hybrid' else 1 if r.get('mode') == 'remote' else 0) for r in rows) + len(regularized - marked), 2)
    attendance['total_days'] = round(attendance['office_days'] + attendance['remote_days'], 2)
    missing = [{'date': d, 'label': d.strftime('%a, %d %b'), 'request': requests.get(d),
                'days': round(1-approved.get(d, 0), 2)}
               for d in calendar if d < today and d not in marked and d not in regularized and approved.get(d, 0) < 1]
    result.update(unmarked=round(sum(d['days'] for d in missing), 2), missing_days=missing)
    return result
