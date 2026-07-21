from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

import httpx

from app.config import get_settings


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


def _date_label(value: date) -> str:
    return value.strftime("%d-%b-%Y")


def _access_token() -> tuple[str, str]:
    settings = get_settings()
    required = [settings.zoho_client_id, settings.zoho_client_secret, settings.zoho_refresh_token]
    if not all(value.strip() for value in required):
        return "", "Zoho integration is not configured"
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
        return str(response.json()["access_token"]), ""
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
