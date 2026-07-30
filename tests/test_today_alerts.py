import unittest
from datetime import date

from app.today_alerts import build_today_alert_candidates


def task_summary(
    task_id: int,
    code: str,
    *,
    end_date: date,
    overdue_days: int | None = None,
    stale_days: int | None = None,
) -> dict:
    return {
        "id": task_id,
        "task_id": code,
        "name": f"Task {code}",
        "end_date": end_date,
        "overdue_days": overdue_days,
        "last_activity_date": date(2026, 7, 25),
        "stale_days": stale_days,
    }


class TodayAlertCandidateTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 7, 30)
        self.week_start = date(2026, 7, 27)

    def alerts(self, **overrides):
        payload = {
            "today": self.today,
            "week_start": self.week_start,
            "tasks_needing_action": [],
            "delayed_tasks": [],
            "stalled_tasks": [],
            "week_logged_hours": 20.0,
            "expected_week_hours": 20.0,
        }
        payload.update(overrides)
        return build_today_alert_candidates(**payload)

    def test_three_day_overdue_task_is_critical(self):
        task = task_summary(
            1,
            "SOL-1",
            end_date=date(2026, 7, 27),
            overdue_days=3,
        )
        task["project_name"] = "Solulever"
        alerts = self.alerts(
            delayed_tasks=[task]
        )

        self.assertEqual(alerts[0]["tone"], "critical")
        self.assertIn("3-to-5", alerts[0]["alert_key"])
        self.assertEqual(alerts[0]["title"], "Solulever · Task SOL-1 is 3 days overdue")

    def test_overdue_alert_suppresses_duplicate_stale_blocker(self):
        task = task_summary(
            1,
            "SOL-1",
            end_date=date(2026, 7, 27),
            overdue_days=3,
            stale_days=5,
        )

        alerts = self.alerts(delayed_tasks=[task], stalled_tasks=[task])

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["kind"], "overdue")

    def test_due_today_alert_is_created_for_untouched_task(self):
        alerts = self.alerts(
            tasks_needing_action=[
                task_summary(2, "SOL-2", end_date=self.today)
            ]
        )

        self.assertEqual(alerts[0]["kind"], "due_today")
        self.assertEqual(alerts[0]["tone"], "urgent")

    def test_booking_alert_requires_material_shortfall(self):
        no_alert = self.alerts(week_logged_hours=2.0, expected_week_hours=3.0)
        alert = self.alerts(week_logged_hours=4.0, expected_week_hours=8.0)

        self.assertFalse(no_alert)
        self.assertEqual(alert[0]["kind"], "booking_pace")
        self.assertEqual(alert[0]["tone"], "planning")


if __name__ == "__main__":
    unittest.main()
