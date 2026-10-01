import os
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["USER_CONTENT_DIR"] = "/tmp/protracklite-test-user-content"

from app.main import profile_page


class ProfileZohoRefreshTests(unittest.TestCase):
    def test_profile_loads_attendance_and_uses_local_leave_until_refresh(self):
        org = SimpleNamespace(id=1, slug="test")
        user = SimpleNamespace(id=2)
        local_leave = {"year_leave_days": 1.0}
        with (
            patch("app.main.reporting_tree_people", return_value=[]),
            patch("app.main.local_today", return_value=date(2026, 9, 29)),
            patch("app.main.profile_leave_requests", return_value=[local_leave]),
            patch("app.main.team_profile_leave_requests", return_value=[]),
            patch("app.main.org_people", return_value=[]),
            patch("app.main.user_avatar_emoji", return_value="🌸"),
            patch("app.main.zoho_profile_leave_feed") as leave_feed,
            patch("app.main.zoho_profile_attendance_feed", return_value={"status": "synced"}) as attendance_feed,
            patch("app.main.regularization_attendance_context", return_value={"status": "synced"}) as regularization_context,
            patch("app.main.templates.TemplateResponse") as render,
        ):
            profile_page(
                request=SimpleNamespace(),
                refresh_zoho=False,
                org_user=(org, user),
                db=SimpleNamespace(scalars=lambda query: SimpleNamespace(all=lambda: [])),
            )

        leave_feed.assert_not_called()
        attendance_feed.assert_called_once()
        regularization_context.assert_called_once()
        context = render.call_args.args[1]
        self.assertEqual(context["leave_requests"], [local_leave])
        self.assertEqual(context["zoho_attendance"]["status"], "synced")
        self.assertEqual(context["zoho_leave_feed_status"], "pending")

    def test_refresh_loads_zoho_feeds(self):
        org = SimpleNamespace(id=1, slug="test")
        user = SimpleNamespace(id=2)
        zoho_leave = {"year_leave_days": 2.0}
        with (
            patch("app.main.reporting_tree_people", return_value=[]),
            patch("app.main.local_today", return_value=date(2026, 9, 29)),
            patch("app.main.profile_leave_requests", return_value=[]),
            patch("app.main.team_profile_leave_requests", return_value=[]),
            patch("app.main.org_people", return_value=[]),
            patch("app.main.user_avatar_emoji", return_value="🌸"),
            patch("app.main.zoho_profile_leave_feed", return_value={
                "status": "synced", "message": "Loaded", "range_label": "2026–2027",
                "mine": [zoho_leave], "team": [], "remote_dates": {},
            }) as leave_feed,
            patch("app.main.zoho_profile_attendance_feed", return_value={"status": "synced"}) as attendance_feed,
            patch("app.main.regularization_attendance_context", return_value={"status": "synced"}),
            patch("app.main.templates.TemplateResponse") as render,
        ):
            profile_page(
                request=SimpleNamespace(),
                refresh_zoho=True,
                org_user=(org, user),
                db=SimpleNamespace(scalars=lambda query: SimpleNamespace(all=lambda: [])),
            )

        leave_feed.assert_called_once()
        attendance_feed.assert_called_once()
        context = render.call_args.args[1]
        self.assertEqual(context["leave_requests"], [zoho_leave])
        self.assertTrue(context["refresh_zoho"])


if __name__ == "__main__":
    unittest.main()
