from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

import httpx

from app.config import get_settings


_ACCESS_TOKEN_LOCK = threading.Lock()
_ACCESS_TOKEN_CACHE: dict[str, tuple[str, float]] = {}


@dataclass(frozen=True)
class ZohoLeaveResult:
    status: str
    leave_id: str = ""
    error: str = ""


@dataclass(frozen=True)
class ZohoBalanceResult:
    status: str
    leave_types: tuple[dict[str, str | float], ...] = ()
    error: str = ""


@dataclass(frozen=True)
class ZohoEmployeeDirectoryResult:
    status: str
    employee_ids: tuple[tuple[str, str], ...] = ()
    error: str = ""


@dataclass(frozen=True)
class ZohoLeaveListResult:
    status: str
    leaves: tuple[dict[str, object], ...] = ()
    error: str = ""


@dataclass(frozen=True)
class ZohoAttendanceResult:
    status: str
    entries: tuple[dict[str, object], ...] = ()
    error: str = ""


def add_zoho_attendance_entry(*, employee_zoho_id: str, day: date, start_time: str, end_time: str) -> ZohoLeaveResult:
    """Add a manager approved attendance entry through Zoho People v3."""
    token, error = _access_token("attendance")
    if not token:
        return ZohoLeaveResult(status="failed", error=error)
    settings = get_settings()
    try:
        response = httpx.post(
            f"{settings.zoho_people_url.rstrip('/')}/people/api/v3/attendance/entries",
            headers={"Authorization": f"Zoho-oauthtoken {token}"},
            data={
                "punch_details": json.dumps([{
                    "employee_id": employee_zoho_id,
                    "punch_in": f"{day.isoformat()} {start_time}:00",
                    "punch_out": f"{day.isoformat()} {end_time}:00",
                }]),
                "datetime_format": "yyyy-MM-dd HH:mm:ss",
                "entries_timezone": settings.app_timezone,
                "storage_timezone": settings.app_timezone,
            },
            timeout=30.0,
        )
        payload = response.json()
        if not response.is_success or payload.get("status") != "success" or payload.get("data", {}).get("success_count") != 1:
            return ZohoLeaveResult(status="failed", error=str(payload.get("message") or "Zoho did not add the attendance entry"))
        return ZohoLeaveResult(status="synced")
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return ZohoLeaveResult(status="failed", error=f"Zoho attendance update failed: {exc}")


def _date_label(value: date) -> str:
    return value.strftime("%d-%b-%Y")


def _token_failure_status(error: str) -> str:
    return "not_configured" if error.endswith("is not configured") else "failed"


def _access_token(profile: str = "leave") -> tuple[str, str]:
    settings = get_settings()
    if profile == "attendance":
        client_id = settings.zoho_attendance_client_id or settings.zoho_client_id
        client_secret = settings.zoho_attendance_client_secret or settings.zoho_client_secret
        refresh_token = settings.zoho_attendance_refresh_token or settings.zoho_refresh_token
        configuration_error = "Zoho attendance write integration is not configured"
    elif profile == "read":
        client_id = settings.zoho_read_client_id
        client_secret = settings.zoho_read_client_secret
        refresh_token = settings.zoho_read_refresh_token
        configuration_error = "Zoho directory and attendance integration is not configured"
    else:
        client_id = settings.zoho_client_id
        client_secret = settings.zoho_client_secret
        refresh_token = settings.zoho_refresh_token
        configuration_error = "Zoho leave integration is not configured"
    required = [client_id, client_secret, refresh_token]
    if not all(value.strip() for value in required):
        return "", configuration_error
    now = time.monotonic()
    cached_token, cached_expiry = _ACCESS_TOKEN_CACHE.get(profile, ("", 0.0))
    if cached_token and cached_expiry > now:
        return cached_token, ""
    with _ACCESS_TOKEN_LOCK:
        now = time.monotonic()
        cached_token, cached_expiry = _ACCESS_TOKEN_CACHE.get(profile, ("", 0.0))
        if cached_token and cached_expiry > now:
            return cached_token, ""
        try:
            response = httpx.post(
                f"{settings.zoho_accounts_url.rstrip('/')}/oauth/v2/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=20.0,
            )
            response.raise_for_status()
            payload = response.json()
            token = str(payload["access_token"])
            try:
                expires_in = int(payload.get("expires_in") or 3600)
            except (TypeError, ValueError):
                expires_in = 3600
            _ACCESS_TOKEN_CACHE[profile] = (token, now + max(expires_in - 60, 60))
            return token, ""
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            return "", f"Zoho authentication failed: {exc}"


def sync_zoho_leave(
    *,
    employee_email: str,
    employee_zoho_id: str = "",
    leave_category: str,
    leave_type: str,
    working_dates: list[date],
    reason: str,
    existing_leave_id: str = "",
) -> ZohoLeaveResult:
    settings = get_settings()
    if not working_dates:
        return ZohoLeaveResult(status="failed", error="No working dates were available for Zoho")

    leave_type_id = (
        settings.zoho_unpaid_leave_type_id
        if leave_category == "unpaid"
        else settings.zoho_earned_leave_type_id
    ).strip()
    if not leave_type_id:
        return ZohoLeaveResult(status="failed", error="Zoho leave-type mapping is not configured")

    try:
        access_token, token_error = _access_token()
        if not access_token:
            status = _token_failure_status(token_error)
            return ZohoLeaveResult(status=status, error=token_error)

        leave_count = 0.5 if leave_type in {"half_am", "half_pm"} else 1.0
        days: dict[str, dict[str, float | int]] = {}
        for leave_date in working_dates:
            detail: dict[str, float | int] = {"leave_count": leave_count}
            if leave_type == "half_am":
                detail["session"] = 1
            elif leave_type == "half_pm":
                detail["session"] = 2
            days[_date_label(leave_date)] = detail

        endpoint = f"{settings.zoho_people_url.rstrip('/')}/people/api/v3/leave-tracker/leaves"
        employee_parameter = {"employee_email_id": employee_email.strip().lower()}
        if existing_leave_id:
            endpoint = f"{endpoint}/{existing_leave_id}"
            resolved_zoho_id = employee_zoho_id.strip()
            if not resolved_zoho_id:
                directory_result = fetch_zoho_employee_ids(employee_emails=[employee_email])
                if directory_result.status != "synced":
                    return ZohoLeaveResult(
                        status=directory_result.status,
                        leave_id=existing_leave_id,
                        error=directory_result.error or "Unable to map the employee to Zoho People",
                    )
                resolved_zoho_id = dict(directory_result.employee_ids).get(employee_email.strip().lower(), "")
            if not resolved_zoho_id:
                return ZohoLeaveResult(
                    status="failed",
                    leave_id=existing_leave_id,
                    error="The employee is not mapped to a Zoho People record",
                )
            employee_parameter = {"employee_zoho_id": resolved_zoho_id}
        response = httpx.request(
            "PUT" if existing_leave_id else "POST",
            endpoint,
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            data={
                **employee_parameter,
                "leave_type_id": leave_type_id,
                "from_date": _date_label(min(working_dates)),
                "to_date": _date_label(max(working_dates)),
                "reason": reason,
                "unit": "Days",
                "days": json.dumps(days, separators=(",", ":")),
            },
            timeout=25.0,
        )
        payload = response.json()
        if not response.is_success or payload.get("status") != "success":
            message = payload.get("message") or payload.get("error") or f"Zoho returned HTTP {response.status_code}"
            return ZohoLeaveResult(status="failed", error=str(message))
        leave_id = str((payload.get("data") or {}).get("id") or existing_leave_id or "")
        if not leave_id:
            return ZohoLeaveResult(status="failed", error="Zoho did not return a leave ID")
        return ZohoLeaveResult(status="synced", leave_id=leave_id)
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        return ZohoLeaveResult(status="failed", error=f"Zoho request failed: {exc}")


def fetch_zoho_leave_balance(*, employee_email: str) -> ZohoBalanceResult:
    settings = get_settings()
    access_token, token_error = _access_token()
    if not access_token:
        status = _token_failure_status(token_error)
        return ZohoBalanceResult(status=status, error=token_error)
    try:
        response = httpx.get(
            f"{settings.zoho_people_url.rstrip('/')}/people/api/leave/getLeaveTypeDetails",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            params={"userId": employee_email.strip().lower()},
            timeout=20.0,
        )
        payload = response.json()
        response_body = payload.get("response") or {}
        if not response.is_success or response_body.get("status") != 0:
            message = response_body.get("message") or payload.get("message") or f"Zoho returned HTTP {response.status_code}"
            return ZohoBalanceResult(status="failed", error=str(message))
        leave_types = []
        for raw in response_body.get("result") or []:
            if str(raw.get("Unit") or "").lower() not in {"day", "days"}:
                continue
            leave_types.append(
                {
                    "id": str(raw.get("Id") or ""),
                    "name": str(raw.get("Name") or "Leave"),
                    "unit": str(raw.get("Unit") or "Days"),
                    "permitted": float(raw.get("PermittedCount") or 0),
                    "availed": float(raw.get("AvailedCount") or 0),
                    "balance": float(raw.get("BalanceCount") or 0),
                }
            )
        return ZohoBalanceResult(status="synced", leave_types=tuple(leave_types))
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        return ZohoBalanceResult(status="failed", error=f"Zoho request failed: {exc}")


def _zoho_error(response: httpx.Response, payload: object) -> str:
    if isinstance(payload, dict):
        response_body = payload.get("response")
        if isinstance(response_body, dict):
            message = response_body.get("message")
            if message:
                return str(message)
        for key in ("message", "errorMessage", "error", "code"):
            value = payload.get(key)
            if value:
                if isinstance(value, dict):
                    return str(value.get("message") or value)
                return str(value)
    return f"Zoho returned HTTP {response.status_code}"


def _employee_rows(payload: object) -> list[tuple[str, dict[str, object]]]:
    if not isinstance(payload, dict):
        return []
    response_body = payload.get("response")
    if not isinstance(response_body, dict):
        return []
    raw_result = response_body.get("result") or []
    if isinstance(raw_result, dict):
        raw_result = [raw_result]
    rows: list[tuple[str, dict[str, object]]] = []
    for group in raw_result if isinstance(raw_result, list) else []:
        if not isinstance(group, dict):
            continue
        for record_id, records in group.items():
            if isinstance(records, dict):
                records = [records]
            for record in records if isinstance(records, list) else []:
                if isinstance(record, dict):
                    rows.append((str(record_id), record))
    return rows


def fetch_zoho_employee_ids(*, employee_emails: Iterable[str]) -> ZohoEmployeeDirectoryResult:
    requested = {str(email).strip().lower() for email in employee_emails if str(email).strip()}
    if not requested:
        return ZohoEmployeeDirectoryResult(status="synced")
    settings = get_settings()
    access_token, token_error = _access_token("read")
    if not access_token:
        status = _token_failure_status(token_error)
        return ZohoEmployeeDirectoryResult(status=status, error=token_error)
    try:
        matches: dict[str, str] = {}
        start_index = 1
        page_size = 200
        for _ in range(50):
            response = httpx.get(
                f"{settings.zoho_people_url.rstrip('/')}/people/api/forms/employee/getRecords",
                headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
                params={"sIndex": start_index, "limit": page_size},
                timeout=25.0,
            )
            payload = response.json()
            rows = _employee_rows(payload)
            response_body = payload.get("response") if isinstance(payload, dict) else None
            response_status = response_body.get("status") if isinstance(response_body, dict) else 0
            if not response.is_success or response_status not in {0, "0", None}:
                return ZohoEmployeeDirectoryResult(status="failed", error=_zoho_error(response, payload))
            for record_id, record in rows:
                email = str(
                    record.get("EmailID")
                    or record.get("Email address")
                    or record.get("Email")
                    or ""
                ).strip().lower()
                zoho_id = str(
                    record.get("Zoho_ID")
                    or record.get("recordId")
                    or record.get("ownerID")
                    or record_id
                    or ""
                ).strip()
                if email in requested and zoho_id:
                    matches[email] = zoho_id
            if requested.issubset(matches) or len(rows) < page_size:
                break
            start_index += page_size
        return ZohoEmployeeDirectoryResult(
            status="synced",
            employee_ids=tuple(sorted(matches.items())),
        )
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        return ZohoEmployeeDirectoryResult(status="failed", error=f"Zoho employee lookup failed: {exc}")


def _parse_zoho_date(value: object) -> date | None:
    raw = str(value or "").strip()
    for date_format in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, date_format).date()
        except (TypeError, ValueError):
            continue
    return None


def _parse_zoho_datetime(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw or raw == "-":
        return None
    for date_format in (
        "%d-%b-%Y %H:%M:%S",
        "%d-%b-%Y %H:%M",
        "%d-%b-%Y - %I:%M %p",
        "%d-%b-%Y %I:%M %p",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return datetime.strptime(raw, date_format)
        except (TypeError, ValueError):
            continue
    return None


def _attendance_rows(payload: object) -> list[dict[str, object]]:
    """Flatten each documented V3 grouping shape into attendance-entry rows."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    rows: list[dict[str, object]] = []

    def collect(value: object) -> None:
        if isinstance(value, list):
            for item in value:
                collect(item)
            return
        if not isinstance(value, dict):
            return
        if "employee" in value or "entry_id" in value or "origin_day" in value:
            rows.append(value)
            return
        for nested in value.values():
            collect(nested)

    collect(data)
    return rows


def _punch_work_mode(source: object) -> str:
    """Mirror Zoho's terminal-vs-remote attendance distinction."""
    normalized = str(source or "").strip().casefold()
    if "terminal" in normalized:
        return "office"
    if normalized in {"web", "mobile", "remote", "work from home", "wfh"}:
        return "remote"
    if normalized in {"access terminal", "biometric", "kiosk", "office"}:
        return "office"
    return ""


def fetch_zoho_attendance_entries(
    *,
    employee_zoho_id: str,
    from_date: date,
    to_date: date,
) -> ZohoAttendanceResult:
    """Fetch one employee's attendance and reduce multiple punches to daily first-in/last-out values."""
    zoho_id = employee_zoho_id.strip()
    if not zoho_id:
        return ZohoAttendanceResult(status="failed", error="The employee is not mapped to Zoho People")
    if to_date < from_date:
        return ZohoAttendanceResult(status="failed", error="Attendance end date cannot be before start date")
    settings = get_settings()
    access_token, token_error = _access_token("read")
    if not access_token:
        status = _token_failure_status(token_error)
        return ZohoAttendanceResult(status=status, error=token_error)
    try:
        response = httpx.get(
            f"{settings.zoho_people_url.rstrip('/')}/people/api/v3/attendance/entries",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            params={
                "employee_zoho_id": zoho_id,
                "from_date": _date_label(from_date),
                "to_date": _date_label(to_date),
                "group_entries_by_date": "true",
            },
            timeout=30.0,
        )
        payload = response.json()
        if (
            not response.is_success
            or not isinstance(payload, dict)
            or payload.get("status") != "success"
        ):
            return ZohoAttendanceResult(status="failed", error=_zoho_error(response, payload))

        days: dict[date, dict[str, object]] = {}
        for raw in _attendance_rows(payload):
            if raw.get("is_break") is True:
                continue
            employee = raw.get("employee") or {}
            if isinstance(employee, dict):
                row_employee_id = str(employee.get("zoho_id") or "").strip()
                if row_employee_id and row_employee_id != zoho_id:
                    continue
            origin_day = _parse_zoho_date(raw.get("origin_day"))
            punch_in = raw.get("punch_in") or {}
            punch_out = raw.get("punch_out") or {}
            if not isinstance(punch_in, dict):
                punch_in = {}
            if not isinstance(punch_out, dict):
                punch_out = {}
            first_in = _parse_zoho_datetime(punch_in.get("punch"))
            last_out = _parse_zoho_datetime(punch_out.get("punch"))
            attendance_date = origin_day or (first_in.date() if first_in else None) or (last_out.date() if last_out else None)
            if not attendance_date or attendance_date < from_date or attendance_date > to_date:
                continue
            day = days.setdefault(
                attendance_date,
                {
                    "attendance_date": attendance_date,
                    "first_in": None,
                    "last_out": None,
                    "first_in_source": "",
                    "first_in_location": "",
                    "last_out_source": "",
                    "last_out_location": "",
                    "office_source": "",
                    "office_location": "",
                    "punch_count": 0,
                },
            )
            for punch, punch_time in ((punch_in, first_in), (punch_out, last_out)):
                source = str(punch.get("source") or "").strip()
                if punch_time and _punch_work_mode(source) == "office":
                    day["office_source"] = source
                    day["office_location"] = str(punch.get("location") or "").strip()
            if first_in and (day["first_in"] is None or first_in < day["first_in"]):
                day["first_in"] = first_in
                day["first_in_source"] = str(punch_in.get("source") or "").strip()
                day["first_in_location"] = str(punch_in.get("location") or "").strip()
            if last_out and (day["last_out"] is None or last_out > day["last_out"]):
                day["last_out"] = last_out
                day["last_out_source"] = str(punch_out.get("source") or "").strip()
                day["last_out_location"] = str(punch_out.get("location") or "").strip()
            if first_in or last_out:
                day["punch_count"] = int(day["punch_count"]) + 1

        for day in days.values():
            source = day["office_source"] or day["first_in_source"] or day["last_out_source"]
            day["work_mode"] = "office" if day["office_source"] else _punch_work_mode(source)
            day["attendance_source"] = source
            day["attendance_location"] = day["office_location"] or day["first_in_location"] or day["last_out_location"]

        return ZohoAttendanceResult(
            status="synced",
            entries=tuple(days[day] for day in sorted(days)),
        )
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        return ZohoAttendanceResult(status="failed", error=f"Zoho attendance lookup failed: {exc}")


def fetch_zoho_leave_requests(
    *,
    employee_zoho_ids: Iterable[str],
    from_date: date,
    to_date: date,
) -> ZohoLeaveListResult:
    requested_ids = {str(value).strip() for value in employee_zoho_ids if str(value).strip()}
    if not requested_ids:
        return ZohoLeaveListResult(status="synced")
    settings = get_settings()
    access_token, token_error = _access_token()
    if not access_token:
        status = _token_failure_status(token_error)
        return ZohoLeaveListResult(status=status, error=token_error)
    try:
        records: list[dict[str, object]] = []
        offset = 1
        page_size = 200
        for _ in range(50):
            response = httpx.get(
                f"{settings.zoho_people_url.rstrip('/')}/people/api/v3/leave-tracker/leaves",
                headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
                params={
                    "from_date": _date_label(from_date),
                    "to_date": _date_label(to_date),
                    "employee_zoho_ids": json.dumps(sorted(requested_ids)),
                    "approval_status": "ALL",
                    "data_select": "ALL",
                    "offset": offset,
                    "limit": page_size,
                    "sort": "-from_date",
                },
                timeout=30.0,
            )
            payload = response.json()
            if (
                not response.is_success
                or not isinstance(payload, dict)
                or payload.get("status") != "success"
            ):
                return ZohoLeaveListResult(status="failed", error=_zoho_error(response, payload))
            raw_records = payload.get("data") or []
            if not isinstance(raw_records, list):
                return ZohoLeaveListResult(status="failed", error="Zoho returned an invalid leave list")
            for raw in raw_records:
                if not isinstance(raw, dict):
                    continue
                employee = raw.get("employee") or {}
                leave_type = raw.get("leave_type") or {}
                if not isinstance(employee, dict) or not isinstance(leave_type, dict):
                    continue
                employee_zoho_id = str(employee.get("zoho_id") or "").strip()
                if employee_zoho_id not in requested_ids:
                    continue
                start = _parse_zoho_date(raw.get("from_date"))
                end = _parse_zoho_date(raw.get("to_date"))
                if not start or not end:
                    continue
                day_values: list[tuple[date, float, int | None]] = []
                days = raw.get("days") or {}
                if isinstance(days, dict):
                    for day_label, detail in days.items():
                        leave_day = _parse_zoho_date(day_label)
                        if not leave_day or not isinstance(detail, dict):
                            continue
                        try:
                            leave_count = float(detail.get("leave_count") or 0)
                        except (TypeError, ValueError):
                            leave_count = 0.0
                        try:
                            session = int(detail["session"]) if detail.get("session") is not None else None
                        except (TypeError, ValueError):
                            session = None
                        day_values.append((leave_day, leave_count, session))
                leave_days = sum(item[1] for item in day_values)
                if not day_values:
                    leave_days = float(max((end - start).days + 1, 1))
                duration = "Full day"
                if len(day_values) == 1 and day_values[0][1] == 0.5:
                    duration = "Half day (AM)" if day_values[0][2] == 1 else "Half day (PM)"
                elif len(day_values) > 1:
                    duration = f"{leave_days:g} days"
                records.append(
                    {
                        "zoho_leave_id": str(raw.get("leave_id") or raw.get("id") or ""),
                        "employee_zoho_id": employee_zoho_id,
                        "employee_name": str(employee.get("name") or "").strip(),
                        "start_date": start,
                        "end_date": end,
                        "day_dates": tuple(item[0] for item in day_values),
                        "day_counts": tuple((item[0], item[1]) for item in day_values),
                        "leave_days": leave_days,
                        "duration_label": duration,
                        "leave_type_name": str(leave_type.get("name") or "Leave").strip(),
                        "leave_type_id": str(leave_type.get("id") or "").strip(),
                        "leave_type_kind": str(leave_type.get("type") or "").strip(),
                        "approval_status": str(raw.get("approval_status") or "Unknown").strip(),
                        "reason": str(raw.get("reason") or "").strip(),
                        "date_of_request": str(raw.get("date_of_request") or "").strip(),
                    }
                )
            if len(raw_records) < page_size:
                break
            offset += page_size
        return ZohoLeaveListResult(status="synced", leaves=tuple(records))
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        return ZohoLeaveListResult(status="failed", error=f"Zoho leave lookup failed: {exc}")


def cancel_zoho_leave(*, leave_id: str, reason: str = "Cancelled from ProTrack") -> ZohoLeaveResult:
    if not leave_id.strip():
        return ZohoLeaveResult(status="not_required")
    settings = get_settings()
    access_token, token_error = _access_token()
    if not access_token:
        status = _token_failure_status(token_error)
        return ZohoLeaveResult(status=status, error=token_error)
    try:
        response = httpx.patch(
            f"{settings.zoho_people_url.rstrip('/')}/people/api/v3/leave-tracker/leaves/{leave_id.strip()}",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            data={"reason": reason},
            timeout=20.0,
        )
        payload = response.json()
        if not response.is_success or payload.get("status") != "success":
            error = payload.get("message") or payload.get("error") or f"Zoho returned HTTP {response.status_code}"
            if isinstance(error, dict):
                error = error.get("message") or str(error)
            return ZohoLeaveResult(status="failed", leave_id=leave_id, error=str(error))
        return ZohoLeaveResult(status="cancelled", leave_id=leave_id)
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        return ZohoLeaveResult(status="failed", leave_id=leave_id, error=f"Zoho request failed: {exc}")
