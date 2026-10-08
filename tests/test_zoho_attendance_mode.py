import os
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["USER_CONTENT_DIR"] = "/tmp/protracklite-test-user-content"

from app.main import zoho_profile_attendance_feed
from app.zoho_people import ZohoAttendanceResult, fetch_zoho_attendance_entries
from tests.test_zoho_people import zoho_response


class ZohoAttendanceModeTests(unittest.TestCase):
    @patch("app.zoho_people.get_settings")
    @patch("app.zoho_people._access_token", return_value=("access-token", ""))
    @patch("app.zoho_people.httpx.get")
    def test_protrack_api_punch_is_remote_in_profile(self, mock_get, _mock_token, mock_settings):
        mock_settings.return_value = SimpleNamespace(zoho_people_url="https://people.zoho.in")
        day = date(2026, 10, 8)
        for source in ("API", " api "):
            with self.subTest(source=source):
                mock_get.return_value = zoho_response({"status": "success", "data": [{
                    "entry_id": "protrack", "origin_day": "08-Oct-2026",
                    "employee": {"zoho_id": "employee-1"},
                    "punch_in": {"punch": "08-Oct-2026 09:00", "source": source, "location": "Noida"},
                }]})
                entries = fetch_zoho_attendance_entries(employee_zoho_id="employee-1", from_date=day, to_date=day)
                self.assertEqual(entries.entries[0]["work_mode"], "remote")
                with patch("app.main.fetch_zoho_attendance_entries", return_value=entries):
                    result = zoho_profile_attendance_feed(SimpleNamespace(zoho_employee_id="employee-1"), day, {})
                self.assertEqual(result["office_days"], 0)
                self.assertEqual(result["remote_days"], 1)
                self.assertEqual(result["rows"][0]["mode_label"], "Remote")
                self.assertEqual(result["rows"][0]["attendance_location"], "Noida")
                self.assertTrue(result["rows"][0]["is_open"])

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
