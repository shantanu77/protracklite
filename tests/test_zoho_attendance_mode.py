import os
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["USER_CONTENT_DIR"] = "/tmp/protracklite-test-user-content"

from app.main import zoho_profile_attendance_feed
from app.zoho_people import ZohoAttendanceResult


class ZohoAttendanceModeTests(unittest.TestCase):
    @patch("app.main.fetch_zoho_attendance_entries")
    def test_punch_source_drives_office_and_remote_counts(self, mock_fetch):
        mock_fetch.return_value = ZohoAttendanceResult(
            status="synced",
            entries=(
                {
                    "attendance_date": date(2026, 9, 1),
                    "first_in": datetime(2026, 9, 1, 9, 0),
                    "last_out": datetime(2026, 9, 1, 18, 0),
                    "work_mode": "office",
                    "attendance_source": "Access Terminal",
                    "attendance_location": "VASANT KUNJ",
                },
                {
                    "attendance_date": date(2026, 9, 2),
                    "first_in": datetime(2026, 9, 2, 9, 15),
                    "last_out": datetime(2026, 9, 2, 18, 15),
                    "work_mode": "remote",
                    "attendance_source": "Web",
                    "attendance_location": "GURGAON",
                },
            ),
        )
        user = SimpleNamespace(zoho_employee_id="employee-1")

        result = zoho_profile_attendance_feed(
            user,
            date(2026, 9, 3),
            {
                date(2026, 9, 1): 1.0,
                date(2026, 9, 3): 1.0,
            },
        )

        self.assertEqual(result["office_days"], 1.0)
        self.assertEqual(result["remote_days"], 1.0)
        self.assertEqual(result["total_days"], 2.0)
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(result["rows"][0]["mode"], "remote")
        self.assertEqual(result["rows"][0]["attendance_source"], "Web")

    @patch("app.main.fetch_zoho_attendance_entries")
    def test_approved_wfh_is_only_fallback_when_source_is_missing(self, mock_fetch):
        mock_fetch.return_value = ZohoAttendanceResult(
            status="synced",
            entries=(
                {
                    "attendance_date": date(2026, 9, 1),
                    "first_in": datetime(2026, 9, 1, 9, 0),
                    "last_out": datetime(2026, 9, 1, 18, 0),
                    "work_mode": "",
                    "attendance_source": "Regularization",
                    "attendance_location": "",
                },
            ),
        )
        user = SimpleNamespace(zoho_employee_id="employee-1")

        result = zoho_profile_attendance_feed(
            user,
            date(2026, 9, 2),
            {date(2026, 9, 1): 0.5},
        )

        self.assertEqual(result["office_days"], 0.5)
        self.assertEqual(result["remote_days"], 0.5)
        self.assertEqual(result["rows"][0]["mode"], "hybrid")


if __name__ == "__main__":
    unittest.main()
