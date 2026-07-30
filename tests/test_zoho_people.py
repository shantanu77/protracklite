import os
import unittest
from datetime import date
from unittest.mock import patch

import httpx

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

from app.zoho_people import fetch_zoho_employee_ids, fetch_zoho_leave_requests


def zoho_response(payload: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("GET", "https://people.zoho.in/test"),
    )


class ZohoPeopleReadTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
