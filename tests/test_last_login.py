import os
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["USER_CONTENT_DIR"] = "/tmp/protracklite-test-user-content"

from app.main import record_successful_login
from app.models import User
from app.security import create_refresh_token, token_issued_at


ROOT = Path(__file__).resolve().parents[1]


class LastLoginTests(unittest.TestCase):
    def test_successful_login_records_timestamp_and_commits(self):
        user = User(
            org_id=1,
            email="person@example.com",
            full_name="Example Person",
            password_hash="not-used",
        )
        db = MagicMock()
        timestamp = datetime(2026, 9, 22, 12, 30)

        record_successful_login(db, user, timestamp)

        self.assertEqual(user.last_login_at, timestamp)
        db.commit.assert_called_once_with()

    def test_existing_session_exposes_its_original_login_time(self):
        before = datetime.utcnow().replace(microsecond=0)
        token = create_refresh_token("2:example")
        issued_at = token_issued_at(token, "refresh")
        after = datetime.utcnow().replace(microsecond=0)

        self.assertIsNotNone(issued_at)
        self.assertGreaterEqual(issued_at, before)
        self.assertLessEqual(issued_at, after)

    def test_admin_user_list_shows_last_login_instead_of_created_date(self):
        template = (ROOT / "app/templates/admin_users.html").read_text()

        self.assertIn("<th>Last Login</th>", template)
        self.assertIn("person.last_login_at", template)
        self.assertIn(">Not recorded yet</span>", template)
        self.assertNotIn("<th>Created</th>", template)

    def test_inactive_users_are_hidden_by_default_and_reminders_are_disabled(self):
        main_source = (ROOT / "app/main.py").read_text()
        template = (ROOT / "app/templates/admin_users.html").read_text()

        self.assertIn('else "active"', main_source)
        self.assertIn('value="all"', template)
        self.assertIn("not person.is_active", template)
        self.assertIn("disabled title=", template)


if __name__ == "__main__":
    unittest.main()
