from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Holiday, Leave, LeaveType, Organization, User
from app.time_utils import local_datetime


CAPACITY_VIEWS = {"month", "sprint", "week"}
STATUS_LABELS = {
    "available": "Avl",
    "planned": "PL",
    "unplanned": "UL/Sick",
    "holiday": "PH",
    "weekend": "Wknd",
}


def capacity_period(view: str, anchor: date) -> tuple[date, date, date, date]:
    normalized_view = view if view in CAPACITY_VIEWS else "month"
    if normalized_view == "month":
        period_start = anchor.replace(day=1)
        period_end = anchor.replace(day=monthrange(anchor.year, anchor.month)[1])
        previous_anchor = (period_start - timedelta(days=1)).replace(day=1)
        next_anchor = (period_end + timedelta(days=1)).replace(day=1)
    else:
        period_start = anchor - timedelta(days=anchor.weekday())
        duration = 14 if normalized_view == "sprint" else 7
        period_end = period_start + timedelta(days=duration - 1)
        previous_anchor = period_start - timedelta(days=duration)
        next_anchor = period_start + timedelta(days=duration)
    return period_start, period_end, previous_anchor, next_anchor


def short_person_name(full_name: str) -> str:
    parts = [part for part in full_name.split() if part]
    if len(parts) <= 1:
        return full_name
    return f"{parts[0]} {parts[-1][0]}."


def leave_is_planned(leave: Leave) -> bool:
    submitted_date = local_datetime(leave.created_at).date() if leave.created_at else leave.leave_date
    return leave.leave_date > submitted_date


def date_range_label(start_date: date, end_date: date) -> str:
    if start_date == end_date:
        return start_date.strftime("%d %b %Y")
    if start_date.month == end_date.month and start_date.year == end_date.year:
        return f"{start_date.strftime('%d')}–{end_date.strftime('%d %b %Y')}"
    return f"{start_date.strftime('%d %b %Y')} – {end_date.strftime('%d %b %Y')}"


def _contiguous_segments(statuses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not statuses:
        return []
    segments: list[dict[str, Any]] = []
    segment_start = 0
    current_key = (statuses[0]["status"], statuses[0].get("detail", ""))
    for index in range(1, len(statuses) + 1):
        next_key = None if index == len(statuses) else (statuses[index]["status"], statuses[index].get("detail", ""))
        if next_key == current_key:
            continue
        start_day = statuses[segment_start]["date"]
        end_day = statuses[index - 1]["date"]
        status = current_key[0]
        detail = current_key[1]
        title = f"{STATUS_LABELS[status]} · {date_range_label(start_day, end_day)}"
        if detail:
            title = f"{title} · {detail}"
        segments.append(
            {
                "start": segment_start,
                "span": index - segment_start,
                "status": status,
                "title": title,
                "start_date": start_day,
                "end_date": end_day,
            }
        )
        segment_start = index
        current_key = next_key
    return segments


def build_capacity_payload(
    db: Session,
    org: Organization,
    members: list[User],
    *,
    view: str = "month",
    anchor: date | None = None,
    scope: str = "team",
) -> dict[str, Any]:
    normalized_view = view if view in CAPACITY_VIEWS else "month"
    reference_date = anchor or date.today()
    period_start, period_end, previous_anchor, next_anchor = capacity_period(normalized_view, reference_date)
    days = [period_start + timedelta(days=offset) for offset in range((period_end - period_start).days + 1)]
    member_ids = [member.id for member in members]

    leaves = []
    if member_ids:
        leaves = db.scalars(
            select(Leave).where(
                Leave.user_id.in_(member_ids),
                Leave.leave_date >= period_start,
                Leave.leave_date <= period_end,
            )
        ).all()
    leave_map = {(leave.user_id, leave.leave_date): leave for leave in leaves}
    holidays = db.scalars(
        select(Holiday)
        .where(Holiday.org_id == org.id, Holiday.holiday_date >= period_start, Holiday.holiday_date <= period_end)
        .order_by(Holiday.holiday_date.asc())
    ).all()
    holiday_map = {holiday.holiday_date: holiday for holiday in holidays}

    unavailable_by_day: dict[date, list[User]] = defaultdict(list)
    planned_dates: list[date] = []
    rows: list[dict[str, Any]] = []
    for member in members:
        statuses: list[dict[str, Any]] = []
        for day in days:
            holiday = holiday_map.get(day)
            leave = leave_map.get((member.id, day))
            if holiday:
                status = "holiday"
                detail = holiday.name
            elif day.weekday() in {5, 6}:
                status = "weekend"
                detail = day.strftime("%A")
            elif leave:
                status = "planned" if leave_is_planned(leave) else "unplanned"
                detail = {
                    LeaveType.FULL: "Full day",
                    LeaveType.HALF_AM: "Half day AM",
                    LeaveType.HALF_PM: "Half day PM",
                }[leave.leave_type]
                unavailable_by_day[day].append(member)
                if status == "planned":
                    planned_dates.append(day)
            else:
                status = "available"
                detail = ""
            statuses.append({"date": day, "status": status, "detail": detail})
        rows.append(
            {
                "user": member,
                "display_name": short_person_name(member.full_name),
                "role_label": member.department.name if member.department else member.role.value.replace("_", " ").title(),
                "segments": _contiguous_segments(statuses),
            }
        )

    holiday_statuses = [
        {"date": day, "status": "holiday" if day in holiday_map else "available", "detail": holiday_map[day].name if day in holiday_map else ""}
        for day in days
    ]
    holiday_bands = [segment for segment in _contiguous_segments(holiday_statuses) if segment["status"] == "holiday"]
    weekend_statuses = [
        {
            "date": day,
            "status": "available" if day in holiday_map or day.weekday() not in {5, 6} else "weekend",
            "detail": day.strftime("%A") if day.weekday() in {5, 6} else "",
        }
        for day in days
    ]
    weekend_bands = [segment for segment in _contiguous_segments(weekend_statuses) if segment["status"] == "weekend"]

    max_unavailable = max((len(people) for people in unavailable_by_day.values()), default=0)
    conflict_dates = [day for day, people in unavailable_by_day.items() if len(people) == max_unavailable] if max_unavailable else []
    if max_unavailable >= 2:
        shown_dates = ", ".join(day.strftime("%d %b") for day in conflict_dates[:3])
        conflict_text = f"CONFLICT ALERT: {max_unavailable} team members unavailable on {shown_dates}."
        conflict_tone = "warning"
    elif max_unavailable == 1:
        conflict_text = "No overlapping leave conflicts in this period. One person is unavailable on the busiest leave day."
        conflict_tone = "clear"
    else:
        conflict_text = "No leave conflicts detected for this period."
        conflict_tone = "clear"

    if period_start.year == period_end.year and period_start.month == period_end.month:
        period_label = period_start.strftime("%B %Y")
    else:
        period_label = f"{period_start.strftime('%d %b')} – {period_end.strftime('%d %b %Y')}"
    planned_label = "PL"
    if planned_dates:
        planned_label = f"PL ({date_range_label(min(planned_dates), max(planned_dates))})"

    return {
        "view": normalized_view,
        "scope": scope,
        "period_start": period_start,
        "period_end": period_end,
        "previous_anchor": previous_anchor,
        "next_anchor": next_anchor,
        "period_label": period_label,
        "days": days,
        "day_count": len(days),
        "rows": rows,
        "holiday_bands": holiday_bands,
        "weekend_bands": weekend_bands,
        "conflict_text": conflict_text,
        "conflict_tone": conflict_tone,
        "planned_legend_label": planned_label,
        "member_count": len(members),
        "leave_entry_count": len(leaves),
        "holiday_count": len(holidays),
    }
