"""Local leave approval decisions. Approval performs no Zoho calls."""
from dataclasses import replace
from datetime import date, datetime
from hashlib import sha256
import json
from threading import Lock

from sqlalchemy import select
from app.models import LeaveApproval

PENDING_STATUSES = {'PENDING', 'PENDING APPROVAL', 'PENDING_APPROVAL', 'SUBMITTED', 'APPLIED'}
_import_lock = Lock()
CANCELLED_STATUSES = {'CANCELLED', 'CANCELED', 'REJECTED', 'WITHDRAWN'}


def request_fingerprint(raw):
    fields = {key: raw.get(key) for key in ('start_date', 'end_date', 'leave_type_id', 'leave_type_name', 'leave_days', 'day_counts', 'day_sessions')}
    return sha256(json.dumps(fields, default=str, sort_keys=True).encode()).hexdigest()


def locally_approved(record):
    return bool(record.approved_at and record.approved_fingerprint == record.fingerprint
                and record.source_status not in CANCELLED_STATUSES)


def apply_local_leave_approvals(db, org_id, people, result):
    with _import_lock:
        return _apply_local_leave_approvals(db, org_id, people, result)


def _apply_local_leave_approvals(db, org_id, people, result):
    if result.status != 'synced':
        return result
    people_by_zoho = {person.zoho_employee_id: person for person in people if person.zoho_employee_id}
    existing = {(record.user_id, record.zoho_leave_id): record for record in db.scalars(select(LeaveApproval).where(
        LeaveApproval.org_id == org_id, LeaveApproval.user_id.in_([person.id for person in people]),
    ))}
    output = []
    for original in result.leaves:
        raw = dict(original)
        person = people_by_zoho.get(str(raw.get('employee_zoho_id') or ''))
        leave_id = str(raw.get('zoho_leave_id') or '')
        if not person or not leave_id:
            output.append(raw)
            continue
        key = (person.id, leave_id)
        record = existing.get(key)
        if record is None:
            record = LeaveApproval(org_id=org_id, user_id=person.id, zoho_leave_id=leave_id)
            db.add(record)
            existing[key] = record
        record.request_json = json.loads(json.dumps(original, default=str))
        record.fingerprint = request_fingerprint(original)
        record.source_status = str(original.get('approval_status') or '').strip().upper()
        db.flush()
        raw['source_fingerprint'] = record.fingerprint
        raw['local_approval_id'] = record.id
        raw['can_approve'] = record.source_status in PENDING_STATUSES and not locally_approved(record)
        if locally_approved(record):
            raw['approval_status'] = 'Approved'
            raw['approval_source'] = 'ProTrack'
            raw['approved_at'] = record.approved_at
        output.append(raw)
    db.commit()
    return replace(result, leaves=tuple(output))


def capacity_local_approvals(db, org_id):
    return {(record.user_id, record.zoho_leave_id): record for record in db.scalars(select(LeaveApproval).where(
        LeaveApproval.org_id == org_id, LeaveApproval.approved_at.is_not(None),
    )) if locally_approved(record)}


def overlay_capacity_approval(entry, records):
    record = records.get((entry['user_id'], entry.get('zoho_leave_id', '')))
    if not record and not entry.get('zoho_leave_id'):
        # Older saved snapshots predate request identifiers. Match only one exact request.
        matches = []
        for candidate in records.values():
            raw = candidate.request_json
            counts = dict(raw.get('day_counts') or [])
            if (candidate.user_id == entry['user_id']
                and raw.get('start_date') == entry.get('request_start')
                and raw.get('end_date') == entry.get('request_end')
                and raw.get('leave_type_name') == entry.get('type')
                and float(counts.get(entry['date'], -1)) == float(entry['count'])):
                matches.append(candidate)
        if len(matches) == 1:
            return {**entry, 'approval': 'Approved', 'approval_source': 'ProTrack'}
    if record and entry.get('request_fingerprint') == record.fingerprint:
        return {**entry, 'approval': 'Approved', 'approval_source': 'ProTrack'}
    return entry


def saved_leave_requests(db, org_id, people, start, end, failed_result):
    """Keep imported requests and local decisions reviewable during a Zoho outage."""
    from app.zoho_people import ZohoLeaveListResult
    output = []
    for record in db.scalars(select(LeaveApproval).where(LeaveApproval.org_id == org_id,
                                                       LeaveApproval.user_id.in_([person.id for person in people]))):
        raw = dict(record.request_json)
        first, last = date.fromisoformat(raw['start_date']), date.fromisoformat(raw['end_date'])
        if first > end or last < start:
            continue
        raw.update(start_date=first, end_date=last, saved_source=True)
        raw['day_dates'] = tuple(date.fromisoformat(day) for day in raw.get('day_dates', []))
        raw['day_counts'] = tuple((date.fromisoformat(day), count) for day, count in raw.get('day_counts', []))
        if raw.get('day_sessions') is not None:
            raw['day_sessions'] = tuple((date.fromisoformat(day), session) for day, session in raw['day_sessions'])
        output.append(raw)
    return ZohoLeaveListResult(status='synced', leaves=tuple(output)) if output else failed_result


def profile_saved_approvals(db, user_id, requests, today):
    """Show saved approval decisions on the default profile without an external refresh."""
    by_source = {item.get('zoho_leave_id'): item for item in requests if item.get('zoho_leave_id')}
    for record in db.scalars(select(LeaveApproval).where(LeaveApproval.user_id == user_id)):
        raw = record.request_json
        first, last = date.fromisoformat(raw['start_date']), date.fromisoformat(raw['end_date'])
        status = 'Approved' if locally_approved(record) else record.source_status.title()
        item = by_source.get(record.zoho_leave_id)
        if item is None:
            counts = raw.get('day_counts') or []
            year_days = sum(float(count) for day, count in counts if date.fromisoformat(day).year == today.year)
            item = {'request_key': f'zoho-{record.zoho_leave_id}', 'start_date': first.isoformat(), 'end_date': last.isoformat(),
                    'date_label': first.strftime('%d %b %Y') if first == last else f'{first:%d %b %Y} – {last:%d %b %Y}',
                    'leave_type_label': raw.get('duration_label') or 'Leave', 'leave_category_label': raw.get('leave_type_name') or 'Leave',
                    'reason': raw.get('reason') or '', 'backup_name': 'Not recorded', 'leave_days': float(raw.get('leave_days') or 0),
                    'year_leave_days': year_days, 'can_modify': False, 'created_at_label': raw.get('date_of_request') or 'Not recorded'}
            requests.append(item)
        item.update(approval_status=status, zoho_sync_status=status.casefold().replace(' ', '-'),
                    approval_source='ProTrack' if locally_approved(record) else 'Zoho',
                    approval_time=record.approved_at)
    return requests
