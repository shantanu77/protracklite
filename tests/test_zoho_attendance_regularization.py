import os
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["USER_CONTENT_DIR"] = "/tmp/protracklite-test-user-content"

from app.zoho_people import add_zoho_attendance_entry


class ZohoAttendanceRegularizationTests(unittest.TestCase):
    @patch("app.zoho_people.httpx.post")
    @patch("app.zoho_people._access_token", return_value=("token", ""))
    @patch("app.zoho_people.get_settings")
    def test_add_entry_requires_zoho_success_count(self, settings, token, post):
        settings.return_value = SimpleNamespace(zoho_people_url="https://people.zoho.in", app_timezone="Asia/Kolkata")
        post.return_value = SimpleNamespace(is_success=True, json=lambda: {
            "status": "success", "data": {"success_count": 0}, "message": "Skipped entry"
        })
        result = add_zoho_attendance_entry(employee_zoho_id="HRM3", day=date(2026, 9, 2),
                                           start_time="10:00", end_time="19:00")
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error, "Skipped entry")

        post.return_value = SimpleNamespace(is_success=True, json=lambda: {
            "status": "success", "data": {"success_count": 1}
        })
        result = add_zoho_attendance_entry(employee_zoho_id="HRM3", day=date(2026, 9, 2),
                                           start_time="10:00", end_time="19:00")
        self.assertEqual(result.status, "synced")
        self.assertIn("2026-09-02 10:00:00", post.call_args.kwargs["data"]["punch_details"])


if __name__ == "__main__":
    unittest.main()
