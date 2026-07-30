from __future__ import annotations

from datetime import date
from typing import Any


SEVERITY_PRIORITY = {
    "critical": 0,
    "urgent": 1,
    "warning": 2,
    "planning": 3,
}


def overdue_bucket(overdue_days: int) -> str:
    if overdue_days >= 6:
        return "6-plus"
    if overdue_days >= 3:
        return "3-to-5"
    return "1-to-2"


def build_today_alert_candidates(
    *,
    today: date,
    week_start: date,
    tasks_needing_action: list[dict[str, Any]],
    delayed_tasks: list[dict[str, Any]],
    stalled_tasks: list[dict[str, Any]],
    week_logged_hours: float,
    expected_week_hours: float,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    alerted_task_ids: set[int] = set()

    for task in delayed_tasks:
        overdue_days = int(task.get("overdue_days") or 1)
        tone = "critical" if overdue_days >= 3 else "urgent"
        task_id = int(task["id"])
        alerted_task_ids.add(task_id)
        alerts.append(
            {
                "alert_key": (
                    f"task:{task_id}:overdue:{task['end_date'].isoformat()}:{overdue_bucket(overdue_days)}"
                ),
                "kind": "overdue",
                "tone": tone,
                "eyebrow": "Delivery risk" if tone == "critical" else "Overdue",
                "title": f"{task['task_id']} is {overdue_days} day{'s' if overdue_days != 1 else ''} overdue",
                "message": (
                    "The deadline has passed. Record progress, complete the task, replan it, or explain the blocker."
                ),
                "task": task,
                "sort_key": (SEVERITY_PRIORITY[tone], -overdue_days, task["task_id"]),
            }
        )

    for task in tasks_needing_action:
        task_id = int(task["id"])
        if task_id in alerted_task_ids:
            continue
        alerted_task_ids.add(task_id)
        alerts.append(
            {
                "alert_key": f"task:{task_id}:due:{today.isoformat()}",
                "kind": "due_today",
                "tone": "urgent",
                "eyebrow": "Due today",
                "title": f"{task['task_id']} still needs action",
                "message": "No effort has been recorded today. Choose the next action before the deadline passes.",
                "task": task,
                "sort_key": (SEVERITY_PRIORITY["urgent"], 0, task["task_id"]),
            }
        )

    for task in stalled_tasks:
        task_id = int(task["id"])
        if task_id in alerted_task_ids:
            continue
        stale_days = int(task.get("stale_days") or 2)
        alerts.append(
            {
                "alert_key": (
                    f"task:{task_id}:stalled:{task['last_activity_date'].isoformat()}"
                ),
                "kind": "stale_blocker",
                "tone": "warning",
                "eyebrow": "Blocker needs an update",
                "title": f"{task['task_id']} has been stalled for {stale_days} day{'s' if stale_days != 1 else ''}",
                "message": "Update the blocker, ask for help, or record the next recovery step.",
                "task": task,
                "sort_key": (SEVERITY_PRIORITY["warning"], -stale_days, task["task_id"]),
            }
        )

    if expected_week_hours >= 4 and week_logged_hours < expected_week_hours * 0.7:
        shortfall = max(expected_week_hours - week_logged_hours, 0)
        alerts.append(
            {
                "alert_key": f"booking:{week_start.isoformat()}",
                "kind": "booking_pace",
                "tone": "planning",
                "eyebrow": "Booking pace",
                "title": f"{shortfall:.1f}h behind the expected weekly pace",
                "message": (
                    f"{week_logged_hours:.1f}h is recorded against approximately "
                    f"{expected_week_hours:.1f}h expected by now."
                ),
                "task": None,
                "sort_key": (SEVERITY_PRIORITY["planning"], -shortfall, "booking"),
            }
        )

    alerts.sort(key=lambda item: item["sort_key"])
    return alerts
