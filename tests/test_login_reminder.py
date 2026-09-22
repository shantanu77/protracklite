import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["USER_CONTENT_DIR"] = "/tmp/protracklite-test-user-content"

from app.main import build_login_reminder_message
from app.models import Organization, User


ROOT = Path(__file__).resolve().parents[1]


class LoginReminderTests(unittest.TestCase):
    def test_message_contains_login_details_and_safe_reset_steps(self):
        org = Organization(id=1, name="Example Org", slug="example")
        user = User(
            id=2,
            org_id=1,
            email="person@example.com",
            full_name="Example Person",
            password_hash="not-used",
        )

        with patch("app.main.settings.base_domain", "tasks.example.com"), patch(
            "app.main.settings.app_name", "ProtrackLite"
        ):
            subject, body = build_login_reminder_message(org, user)

        self.assertEqual(subject, "Reminder: sign in to ProtrackLite")
        self.assertIn("https://tasks.example.com/example/login", body)
        self.assertIn("Login email: person@example.com", body)
        self.assertIn("Use the password you already set", body)
        self.assertIn("Forgot Password?", body)
        self.assertIn("valid for 24 hours", body)
        self.assertIn("does not contain or change your current password", body)

    def test_admin_user_list_has_send_reminder_action(self):
        template = (ROOT / "app/templates/admin_users.html").read_text()

        self.assertIn("/send-login-reminder", template)
        self.assertIn("Send Reminder", template)
        self.assertIn("not person.is_active", template)


if __name__ == "__main__":
    unittest.main()
