"""Organization-wide persisted monthly Zoho leave snapshots."""
from calendar import monthrange
from datetime import date, datetime, timedelta
from threading import Lock

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.database import SessionLocal
from app.leave_approvals import apply_local_leave_approvals, request_fingerprint
from app.models import CapacityZohoSnapshot, CapacityZohoSyncRun, User
from app.zoho_people import fetch_zoho_employee_ids, fetch_zoho_leave_requests

_guard = Lock()


def months_in_period(start, end):
    cursor = start.replace(day=1)
    while cursor <= end:
        yield cursor
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)


def capacity_snapshots(db, org_id, start, end):
    months = list(months_in_period(start, end))
    stored = {(item.year, item.month): item for item in db.scalars(select(CapacityZohoSnapshot).where(
        CapacityZohoSnapshot.org_id == org_id, CapacityZohoSnapshot.year.in_({day.year for day in months}),
    ))}
    return {(day.year, day.month): stored.get((day.year, day.month)) for day in months}


def normalize_leave_days(leaves, people, start, end):
    by_zoho = {person.zoho_employee_id: person.id for person in people if person.zoho_employee_id}
    remote_type_id = get_settings().zoho_work_from_home_leave_type_id.strip()
    entries = {}
    for raw in leaves:
        user_id = by_zoho.get(str(raw.get('employee_zoho_id') or ''))
        approval = str(raw.get('approval_status') or '').strip().upper()
        name = str(raw.get('leave_type_name') or 'Leave')
        remote = 'remote' in name.casefold() or 'work from home' in name.casefold() or (
            remote_type_id and str(raw.get('leave_type_id') or '') == remote_type_id)
        if not user_id or approval in {'REJECTED', 'CANCELLED', 'CANCELED', 'WITHDRAWN'}:
            continue
        if approval not in {'APPROVED', 'PENDING', 'PENDING APPROVAL', 'PENDING_APPROVAL', 'SUBMITTED', 'APPLIED'}:
            continue
        sessions = dict(raw.get('day_sessions') or ())
        counts = raw.get('day_counts')
        if not counts:
            days = raw.get('day_dates')
            if not days:
                first, last = raw['start_date'], raw['end_date']
                days = [first + timedelta(days=i) for i in range((last-first).days + 1)]
            count = min(float(raw.get('leave_days') or len(days)) / max(len(days), 1), 1)
            counts = [(day, count) for day in days]
        for day, count in counts:
            if not start <= day <= end or float(count) <= 0:
                continue
            key = (user_id, day.isoformat())
            if remote:
                continue
            entry = {'user_id': user_id, 'date': day.isoformat(), 'count': min(float(count), 1),
                     'planned': 'sick' not in name.casefold(), 'type': name, 'approval': approval,
                     'zoho_leave_id': str(raw.get('zoho_leave_id') or ''),
                     'request_fingerprint': raw.get('source_fingerprint') or request_fingerprint(raw),
                     'approval_source': raw.get('approval_source', 'Zoho'),
                     'session': sessions.get(day), 'request_start': raw['start_date'].isoformat(),
                     'request_end': raw['end_date'].isoformat(), 'request_days': float(raw.get('leave_days') or sum(float(value) for _, value in counts))}
            if key not in entries:
                entries[key] = entry
            else:
                existing = entries[key]
                existing['count'] = min(existing['count'] + entry['count'], 1)
                existing['planned'] = existing['planned'] and entry['planned']
                existing['session'] = None
                if entry['type'] not in existing['type']:
                    existing['type'] += ' + ' + entry['type']
                existing['request_start'] = min(existing['request_start'], entry['request_start'])
                existing['request_end'] = max(existing['request_end'], entry['request_end'])
    return sorted(entries.values(), key=lambda entry: (entry['user_id'], entry['date']))


def sync_capacity_snapshots(db, org_id, start, end):
    people = list(db.scalars(select(User).where(User.org_id == org_id, User.is_active.is_(True))))
    missing = [person for person in people if not person.zoho_employee_id]
    if missing:
        directory = fetch_zoho_employee_ids(employee_emails=[person.email for person in missing])
        if directory.status != 'synced':
            raise HTTPException(503, 'Zoho employee lookup failed. The saved snapshot has been kept.')
        identifiers = dict(directory.employee_ids)
        for person in missing:
            person.zoho_employee_id = identifiers.get(person.email.strip().lower(), '')
    mapped = [person for person in people if person.zoho_employee_id]
    if people and not mapped:
        raise HTTPException(409, 'No employees could be linked to Zoho. The saved snapshot has been kept.')
    existing = capacity_snapshots(db, org_id, start, end)
    fetched = {}
    for month in months_in_period(start, end):
        last = month.replace(day=monthrange(month.year, month.month)[1])
        leaves = fetch_zoho_leave_requests(employee_zoho_ids=[person.zoho_employee_id for person in mapped],
                                          from_date=month, to_date=last)
        if leaves.status != 'synced':
            raise HTTPException(503, 'Zoho leave sync failed. The saved snapshot has been kept. Check the Zoho connection and try again.')
        leaves = apply_local_leave_approvals(db, org_id, mapped, leaves)
        leave_days = normalize_leave_days(leaves.leaves, mapped, month, last)
        fetched[(month.year, month.month)] = leave_days
    stamp = datetime.utcnow()
    for key, leave_days in fetched.items():
        snapshot = existing[key]
        if snapshot is None:
            snapshot = CapacityZohoSnapshot(org_id=org_id, year=key[0], month=key[1])
            db.add(snapshot)
        snapshot.synced_at = stamp
        snapshot.member_ids_json = [person.id for person in mapped]
        snapshot.leave_days_json = leave_days
    db.commit()
    return stamp


def start_capacity_sync(db, org_id):
    with _guard:
        # The database lock also coordinates multiple application workers.
        run = db.scalar(select(CapacityZohoSyncRun).where(CapacityZohoSyncRun.org_id == org_id).with_for_update())
        if run and run.status == 'running' and run.started_at and datetime.utcnow() - run.started_at < timedelta(minutes=20):
            db.rollback()
            raise HTTPException(409, 'An organization sync is already running. The saved view remains available.')
        if not run:
            run = CapacityZohoSyncRun(org_id=org_id)
            db.add(run)
        run.status, run.started_at, run.finished_at, run.error = 'running', datetime.utcnow().replace(microsecond=0), None, ''
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "An organization sync is already starting. Please try again shortly.") from None
        db.refresh(run)
        return run.started_at


def run_capacity_sync(org_id, start, end, started_at):
    with SessionLocal() as db:
        try:
            sync_capacity_snapshots(db, org_id, start, end)
            status, error = 'done', ''
        except Exception as exc:
            db.rollback()
            status = 'failed'
            error = str(exc.detail) if isinstance(exc, HTTPException) else 'Sync failed. The saved snapshot has been kept. Please try again.'
        run = db.scalar(select(CapacityZohoSyncRun).where(CapacityZohoSyncRun.org_id == org_id).with_for_update())
        if run and run.started_at == started_at:
            run.status, run.error, run.finished_at = status, error[:500], datetime.utcnow()
            db.commit()


def capacity_sync_status(db, org_id):
    run = db.scalar(select(CapacityZohoSyncRun).where(CapacityZohoSyncRun.org_id == org_id))
    if not run:
        return {'status': 'idle', 'error': ''}
    if run.status == 'running' and run.started_at and datetime.utcnow() - run.started_at >= timedelta(minutes=20):
        return {'status': 'failed', 'error': 'The previous sync did not finish. The saved snapshot is unchanged. You can try again.'}
    return {'status': run.status, 'error': run.error}
