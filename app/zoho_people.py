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
_ACCESS_TOKEN_CACHE: tuple[str, float] = ("", 0.0)


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


def _date_label(value: date) -> str:
    return value.strftime("%d-%b-%Y")


def _access_token() -> tuple[str, str]:
    global _ACCESS_TOKEN_CACHE
    settings = get_settings()
    required = [settings.zoho_client_id, settings.zoho_client_secret, settings.zoho_refresh_token]
    if not all(value.strip() for value in required):
        return "", "Zoho integration is not configured"
    now = time.monotonic()
    if _ACCESS_TOKEN_CACHE[0] and _ACCESS_TOKEN_CACHE[1] > now:
        return _ACCESS_TOKEN_CACHE[0], ""
    with _ACCESS_TOKEN_LOCK:
        now = time.monotonic()
        if _ACCESS_TOKEN_CACHE[0] and _ACCESS_TOKEN_CACHE[1] > now:
            return _ACCESS_TOKEN_CACHE[0], ""
        try:
            response = httpx.post(
                f"{settings.zoho_accounts_url.rstrip('/')}/oauth/v2/token",
                data={
                    "client_id": settings.zoho_client_id,
                    "client_secret": settings.zoho_client_secret,
                    "refresh_token": settings.zoho_refresh_token,
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
            _ACCESS_TOKEN_CACHE = (token, now + max(expires_in - 60, 60))
            return token, ""
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            return "", f"Zoho authentication failed: {exc}"


def sync_zoho_leave(
    *,
    employee_email: str,
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
            status = "not_configured" if token_error == "Zoho integration is not configured" else "failed"
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
        if existing_leave_id:
            endpoint = f"{endpoint}/{existing_leave_id}"
        response = httpx.request(
            "PUT" if existing_leave_id else "POST",
            endpoint,
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            data={
                "employee_email_id": employee_email.strip().lower(),
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
        status = "not_configured" if token_error == "Zoho integration is not configured" else "failed"
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
    access_token, token_error = _access_token()
    if not access_token:
        status = "not_configured" if token_error == "Zoho integration is not configured" else "failed"
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
        status = "not_configured" if token_error == "Zoho integration is not configured" else "failed"
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
                        "leave_days": leave_days,
                        "duration_label": duration,
                        "leave_type_name": str(leave_type.get("name") or "Leave").strip(),
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
        status = "not_configured" if token_error == "Zoho integration is not configured" else "failed"
        return ZohoLeaveResult(status=status, error=token_error)
    try:
        response = httpx.patch(
            f"{settings.zoho_people_url.rstrip('/')}/api/v2/leavetracker/leaves/records/cancel/{leave_id.strip()}",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            params={"reason": reason},
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
