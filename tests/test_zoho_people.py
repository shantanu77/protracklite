import os
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

import httpx

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

from app.zoho_people import (
    cancel_zoho_leave,
    fetch_zoho_attendance_entries,
    fetch_zoho_employee_ids,
    fetch_zoho_employee_codes,
    fetch_zoho_leave_requests,
    sync_zoho_leave,
)


def zoho_response(payload: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("GET", "https://people.zoho.in/test"),
    )


class ZohoPeopleReadTests(unittest.TestCase):
    @patch("app.zoho_people._access_token", return_value=("access-token", ""))
    @patch("app.zoho_people.httpx.get")
    def test_attendance_code_is_distinct_from_internal_record_id(self, mock_get, _mock_token):
        mock_get.return_value = zoho_response({"response": {"status": 0, "result": [
            {"24413000002777017": [{"EmailID": "priya@example.com", "EmployeeID": "105",
                                   "Zoho_ID": "24413000002777017"}]}]}})
        codes = fetch_zoho_employee_codes(employee_emails=["PRIYA@example.com"])
        self.assertEqual(dict(codes.employee_ids), {"priya@example.com": "105"})
        ids = fetch_zoho_employee_ids(employee_emails=["priya@example.com"])
        self.assertEqual(dict(ids.employee_ids), {"priya@example.com": "24413000002777017"})

    @patch("app.zoho_people._access_token", return_value=("access-token", ""))
    @patch("app.zoho_people.httpx.get")
    def test_employee_directory_maps_email_to_zoho_record_id(self, mock_get, _mock_token):
        mock_get.return_value = zoho_response(
            {
                "response": {
                    "status": 0,
                    "result": [
                        {
                            "244130000000123001": [
                                {
                                    "EmailID": "manager@solulever.com",
                                    "Zoho_ID": "244130000000123001",
                                }
                            ]
                        }
                    ],
                }
            }
        )

        result = fetch_zoho_employee_ids(employee_emails=["MANAGER@solulever.com"])

        self.assertEqual(result.status, "synced")
        self.assertEqual(dict(result.employee_ids), {"manager@solulever.com": "244130000000123001"})
        self.assertEqual(mock_get.call_count, 1)

    @patch("app.zoho_people._access_token", return_value=("access-token", ""))
    @patch("app.zoho_people.httpx.get")
    def test_leave_fetch_filters_employees_and_parses_half_day(self, mock_get, _mock_token):
        mock_get.return_value = zoho_response(
            {
                "status": "success",
                "data": [
                    {
                        "leave_id": "leave-1",
                        "from_date": "30-Jul-2026",
                        "to_date": "30-Jul-2026",
                        "date_of_request": "28-Jul-2026",
                        "approval_status": "Pending",
                        "reason": "Medical appointment",
                        "employee": {
                            "zoho_id": "244130000000123001",
                            "name": "Team Member",
                            "id": "E12",
                        },
                        "leave_type": {
                            "id": "type-1",
                            "name": "Earned Leave",
                            "type": "PAID",
                        },
                        "days": {
                            "30-Jul-2026": {
                                "leave_count": "0.5",
                                "session": 2,
                            }
                        },
                    },
                    {
                        "leave_id": "outside-team",
                        "from_date": "30-Jul-2026",
                        "to_date": "30-Jul-2026",
                        "approval_status": "Approved",
                        "employee": {"zoho_id": "someone-else", "name": "Outside"},
                        "leave_type": {"name": "Earned Leave", "type": "PAID"},
                        "days": {"30-Jul-2026": {"leave_count": "1.0"}},
                    },
                ],
            }
        )

        result = fetch_zoho_leave_requests(
            employee_zoho_ids=["244130000000123001"],
            from_date=date(2026, 1, 1),
            to_date=date(2027, 12, 31),
        )

        self.assertEqual(result.status, "synced")
        self.assertEqual(len(result.leaves), 1)
        leave = result.leaves[0]
        self.assertEqual(leave["zoho_leave_id"], "leave-1")
        self.assertEqual(leave["leave_days"], 0.5)
        self.assertEqual(leave["duration_label"], "Half day (PM)")
        self.assertEqual(leave["approval_status"], "Pending")

    @patch("app.zoho_people.get_settings")
    @patch("app.zoho_people._access_token", return_value=("access-token", ""))
    @patch("app.zoho_people.httpx.get")
    def test_half_day_reads_capitalized_session(self, mock_get, _mock_token, mock_settings):
        mock_settings.return_value = SimpleNamespace(zoho_people_url="https://people.zoho.in")
        mock_get.return_value = zoho_response({"status": "success", "data": [{
            "from_date": "24-Sep-2026", "to_date": "24-Sep-2026", "approval_status": "APPROVED",
            "employee": {"zoho_id": "employee-1"}, "leave_type": {"name": "Earned Leave"},
            "days": {"24-Sep-2026": {"leave_count": "0.5", "Session": 1}}
        }]})
        result=fetch_zoho_leave_requests(employee_zoho_ids=["employee-1"],from_date=date(2026,9,1),to_date=date(2026,9,30))
        self.assertEqual(result.leaves[0]["duration_label"],"Half day (AM)")
        self.assertEqual(result.leaves[0]["day_sessions"],((date(2026,9,24),1),))

    @patch("app.zoho_people.get_settings")
    @patch("app.zoho_people._access_token", return_value=("access-token", ""))
    @patch("app.zoho_people.httpx.get")
    def test_attendance_reduces_daily_entries_to_first_login_and_last_logout(
        self, mock_get, _mock_token, mock_settings
    ):
        mock_settings.return_value = SimpleNamespace(zoho_people_url="https://people.zoho.in")
        mock_get.return_value = zoho_response(
            {
                "status": "success",
                "data": {
                    "244130000000123001": {
                        "21-Sep-2026": [
                            {
                                "entry_id": "one",
                                "origin_day": "21-Sep-2026",
                                "employee": {"zoho_id": "244130000000123001"},
                                "punch_in": {"punch": "21-Sep-2026 09:12", "source": "Mobile", "location": "Delhi"},
                                "punch_out": {"punch": "21-Sep-2026 13:00", "source": "Mobile", "location": "Delhi"},
                                "is_break": False,
                            },
                            {
                                "entry_id": "two",
                                "origin_day": "21-Sep-2026",
                                "employee": {"zoho_id": "244130000000123001"},
                                "punch_in": {"punch": "21-Sep-2026 14:00"},
                                "punch_out": {"punch": "21-Sep-2026 18:35"},
                                "is_break": False,
                            },
                            {
                                "entry_id": "break",
                                "origin_day": "21-Sep-2026",
                                "employee": {"zoho_id": "244130000000123001"},
                                "punch_in": {"punch": "21-Sep-2026 13:00"},
                                "punch_out": {"punch": "21-Sep-2026 14:00"},
                                "is_break": True,
                            },
                        ]
                    }
                },
            }
        )

        result = fetch_zoho_attendance_entries(
            employee_zoho_id="244130000000123001",
            from_date=date(2026, 9, 1),
            to_date=date(2026, 9, 30),
        )

        self.assertEqual(result.status, "synced")
        self.assertEqual(len(result.entries), 1)
        self.assertEqual(result.entries[0]["first_in"], datetime(2026, 9, 21, 9, 12))
        self.assertEqual(result.entries[0]["last_out"], datetime(2026, 9, 21, 18, 35))
        self.assertEqual(result.entries[0]["work_mode"], "remote")
        self.assertEqual(result.entries[0]["attendance_source"], "Mobile")
        self.assertEqual(result.entries[0]["attendance_location"], "Delhi")
        self.assertEqual(mock_get.call_args.kwargs["params"]["employee_zoho_id"], "244130000000123001")

    @patch("app.zoho_people.get_settings")
    @patch("app.zoho_people._access_token", return_value=("access-token", ""))
    @patch("app.zoho_people.httpx.get")
    def test_terminal_logout_makes_mixed_punch_day_office(self, mock_get, _mock_token, mock_settings):
        mock_settings.return_value = SimpleNamespace(zoho_people_url="https://people.zoho.in")
        mock_get.return_value = zoho_response({
            "status": "success",
            "data": [
                {
                    "entry_id": "one",
                    "origin_day": "28-Sep-2026",
                    "employee": {"zoho_id": "employee-1"},
                    "punch_in": {"punch": "28-Sep-2026 09:00", "source": "Web"},
                    "punch_out": {"punch": "28-Sep-2026 12:00", "source": "Web"},
                },
                {
                    "entry_id": "two",
                    "origin_day": "28-Sep-2026",
                    "employee": {"zoho_id": "employee-1"},
                    "punch_in": {"punch": "28-Sep-2026 13:00", "source": "Mobile"},
                    "punch_out": {"punch": "28-Sep-2026 18:00", "source": "Access Terminal - Gate 1", "location": "Office"},
                },
            ],
        })

        result = fetch_zoho_attendance_entries(
            employee_zoho_id="employee-1",
            from_date=date(2026, 9, 28),
            to_date=date(2026, 9, 28),
        )

        self.assertEqual(result.entries[0]["work_mode"], "office")
        self.assertEqual(result.entries[0]["attendance_source"], "Access Terminal - Gate 1")
        self.assertEqual(result.entries[0]["attendance_location"], "Office")
        self.assertEqual(result.entries[0]["first_in"], datetime(2026, 9, 28, 9, 0))
        self.assertEqual(result.entries[0]["last_out"], datetime(2026, 9, 28, 18, 0))

    @patch("app.zoho_people.get_settings")
    @patch("app.zoho_people._access_token", return_value=("access-token", ""))
    @patch("app.zoho_people.httpx.request")
    def test_leave_edit_uses_required_zoho_employee_id(self, mock_request, _mock_token, mock_settings):
        mock_settings.return_value = SimpleNamespace(
            zoho_people_url="https://people.zoho.in",
            zoho_earned_leave_type_id="earned-id",
            zoho_unpaid_leave_type_id="unpaid-id",
        )
        mock_request.return_value = zoho_response(
            {"status": "success", "data": {"id": "leave-1"}}
        )

        result = sync_zoho_leave(
            employee_email="manager@solulever.com",
            employee_zoho_id="244130000000123001",
            leave_category="planned",
            leave_type="full",
            working_dates=[date(2026, 10, 1)],
            reason="Planned leave with a documented handover and sufficient context for the team.",
            existing_leave_id="leave-1",
        )

        self.assertEqual(result.status, "synced")
        sent_data = mock_request.call_args.kwargs["data"]
        self.assertEqual(sent_data["employee_zoho_id"], "244130000000123001")
        self.assertNotIn("employee_email_id", sent_data)
        self.assertTrue(mock_request.call_args.args[1].endswith("/people/api/v3/leave-tracker/leaves/leave-1"))

    @patch("app.zoho_people.get_settings")
    @patch("app.zoho_people._access_token", return_value=("access-token", ""))
    @patch("app.zoho_people.httpx.patch")
    def test_leave_cancel_uses_v3_endpoint(self, mock_patch, _mock_token, mock_settings):
        mock_settings.return_value = SimpleNamespace(zoho_people_url="https://people.zoho.in")
        mock_patch.return_value = zoho_response(
            {"status": "success", "data": {"id": "leave-1"}}
        )

        result = cancel_zoho_leave(leave_id="leave-1", reason="Cancelled in ProTrack")

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(
            mock_patch.call_args.args[0],
            "https://people.zoho.in/people/api/v3/leave-tracker/leaves/leave-1",
        )
        self.assertEqual(mock_patch.call_args.kwargs["data"]["reason"], "Cancelled in ProTrack")


if __name__ == "__main__":
    unittest.main()
