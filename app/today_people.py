"""Persisted organization-wide daily office and approved leave snapshot."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Lock

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.capacity_sync import normalize_leave_days
from app.database import SessionLocal
from app.leave_approvals import apply_local_leave_approvals
from app.models import AttendanceRegularization, TodayPeopleSnapshot, User
from app.time_utils import format_local_datetime
from app.zoho_people import fetch_zoho_attendance_entries, fetch_zoho_employee_ids, fetch_zoho_leave_requests

_guard = Lock()


def snapshot(db, org_id, day, lock=False):
    query = select(TodayPeopleSnapshot).where(TodayPeopleSnapshot.org_id == org_id, TodayPeopleSnapshot.day == day)
    return db.scalar(query.with_for_update() if lock else query)


def running(row):
    return bool(row and row.status == 'running' and row.started_at and datetime.utcnow() - row.started_at < timedelta(minutes=20))


def start_sync(db, org_id, day):
    with _guard:
        row = snapshot(db, org_id, day, True)
        if running(row):
            db.rollback()
            raise HTTPException(409, 'A shared refresh is already running.')
        if row is None:
            row = TodayPeopleSnapshot(org_id=org_id, day=day)
            db.add(row)
        row.status, row.error, row.started_at = 'running', '', datetime.utcnow().replace(microsecond=0)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, 'A shared refresh is already starting.') from None
        db.refresh(row)
        return row.started_at


def collect_people(db, org_id, day):
    people = list(db.scalars(select(User).where(User.org_id == org_id, User.is_active.is_(True))))
    missing = [person for person in people if not person.zoho_employee_id]
    if missing:
        directory = fetch_zoho_employee_ids(employee_emails=[person.email for person in missing])
        if directory.status != 'synced':
            raise RuntimeError('Employee lookup failed')
        ids = dict(directory.employee_ids)
        for person in missing:
            person.zoho_employee_id = ids.get(person.email.strip().lower(), '')
    mapped = [person for person in people if person.zoho_employee_id]
    if people and not mapped:
        raise RuntimeError('No employees mapped')
    def attendance(person):
        return fetch_zoho_attendance_entries(employee_zoho_id=person.zoho_employee_id, from_date=day, to_date=day)
    # Worker threads perform HTTP only; they never access the database session.
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attendance, mapped))
    if any(result.status != 'synced' for result in results):
        raise RuntimeError('Attendance refresh failed')
    leaves = fetch_zoho_leave_requests(employee_zoho_ids=[person.zoho_employee_id for person in mapped], from_date=day, to_date=day) if mapped else None
    if leaves is not None and leaves.status != 'synced':
        raise RuntimeError('Leave refresh failed')
    leave_days = []
    if leaves is not None:
        leaves = apply_local_leave_approvals(db, org_id, mapped, leaves)
        leave_days = normalize_leave_days([raw for raw in leaves.leaves if str(raw.get('approval_status', '')).upper() == 'APPROVED'], mapped, day, day)
    by_user = {entry['user_id']: entry for entry in leave_days}
    remote = set(db.scalars(select(AttendanceRegularization.user_id).where(
        AttendanceRegularization.org_id == org_id, AttendanceRegularization.attendance_date == day,
        AttendanceRegularization.status == 'approved')))
    entries = []
    for person, result in zip(mapped, results):
        office = person.id not in remote and any(entry.get('attendance_date') == day and entry.get('work_mode') == 'office' and (entry.get('first_in') or entry.get('last_out')) for entry in result.entries)
        leave = by_user.get(person.id)
        if office or leave:
            entries.append({'user_id': person.id, 'office': office, 'leave': bool(leave),
                            'leave_count': leave['count'] if leave else 0, 'session': leave['session'] if leave else None})
    return entries, len(missing) - sum(bool(person.zoho_employee_id) for person in missing)


def run_sync(org_id, day, started_at):
    with SessionLocal() as db:
        try:
            entries, unmapped = collect_people(db, org_id, day)
            row = snapshot(db, org_id, day, True)
            if row and row.started_at == started_at:
                row.people_json, row.unmapped_count = entries, unmapped
                row.synced_at, row.status, row.error = datetime.utcnow(), 'done', ''
                db.commit()
        except Exception:
            db.rollback()
            row = snapshot(db, org_id, day, True)
            if row and row.started_at == started_at:
                row.status, row.error = 'failed', 'Refresh failed. The last saved information has been kept. Please try again.'
                db.commit()


def payload(db, org_id, day):
    row = snapshot(db, org_id, day)
    people = {person.id: person for person in db.scalars(select(User).where(User.org_id == org_id, User.is_active.is_(True)))}
    entries = []
    for entry in row.people_json if row else []:
        person = people.get(entry['user_id'])
        if person:
            entries.append({**entry, 'name': person.full_name, 'avatar': person.avatar_128_url or person.avatar_24_url or ''})
    entries.sort(key=lambda entry: (not entry['office'], entry['name'].casefold()))
    status = row.status if row else 'idle'
    if status == 'running' and not running(row):
        status = 'failed'
    return {'day': day.isoformat(), 'people': entries, 'status': status,
            'synced_at': format_local_datetime(row.synced_at) if row else '',
            'unmapped_count': row.unmapped_count if row else 0,
            'error': (row.error or 'The previous refresh did not finish. Please try again.') if status == 'failed' else ''}
