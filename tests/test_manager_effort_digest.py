import os
import unittest
from datetime import date
from decimal import Decimal

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["USER_CONTENT_DIR"] = "/tmp/protracklite-test-user-content"

from app.database import Base, SessionLocal, engine
from app.manager_effort_digest import build_message, effort_rows, reporting_line, utilization_style
from app.models import ActivityType, Organization, OrgSettings, Project, Role, Task, TimeLog, User


if engine.dialect.name != "sqlite":
    raise RuntimeError("Tests must never run against a non-SQLite database.")


class ManagerEffortDigestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(engine)

    def setUp(self):
        self.db = SessionLocal()
        self.org = Organization(name="Digest Org", slug="digest-org")
        self.db.add(self.org)
        self.db.flush()
        self.db.add(OrgSettings(org_id=self.org.id, weekend_days=[5, 6], work_hours_per_day=Decimal("8")))
        self.manager = User(org_id=self.org.id, email="manager@example.com", full_name="Manager", password_hash="x", role=Role.MANAGER)
        self.direct = User(org_id=self.org.id, email="direct@example.com", full_name="Direct", password_hash="x", manager_id=None, role=Role.MANAGER)
        self.indirect = User(org_id=self.org.id, email="indirect@example.com", full_name="Indirect", password_hash="x")
        self.outsider = User(org_id=self.org.id, email="outside@example.com", full_name="Outside", password_hash="x")
        self.db.add_all([self.manager, self.direct, self.indirect, self.outsider])
        self.db.flush()
        self.direct.manager_id = self.manager.id
        self.indirect.manager_id = self.direct.id
        activity = ActivityType(org_id=self.org.id, code="DEV", name="Development")
        project = Project(org_id=self.org.id, code="DIG", name="Digest", created_by=self.manager.id)
        self.db.add_all([activity, project])
        self.db.flush()
        self.task = Task(task_id="DIG-1", org_id=self.org.id, project_id=project.id, assigned_to=self.direct.id, created_by=self.manager.id, name="Work", activity_type_id=activity.id)
        self.db.add(self.task)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(table.delete())

    def test_reporting_line_includes_direct_and_lower_levels_only(self):
        line = reporting_line(self.db, self.org.id, self.manager.id)
        self.assertEqual([(person.email, depth) for person, depth in line], [("direct@example.com", 1), ("indirect@example.com", 2)])

    def test_utilization_thresholds(self):
        self.assertEqual(utilization_style(84.9)[0], "Needs attention")
        self.assertEqual(utilization_style(85)[0], "Watch")
        self.assertEqual(utilization_style(99.9)[0], "Watch")
        self.assertEqual(utilization_style(100)[0], "On target")

    def test_digest_uses_previous_week_and_current_month_to_date(self):
        self.db.add_all([
            TimeLog(task_id=self.task.id, user_id=self.direct.id, log_date=date(2026, 9, 18), hours=Decimal("6"), notes="last week"),
            TimeLog(task_id=self.task.id, user_id=self.direct.id, log_date=date(2026, 9, 21), hours=Decimal("2"), notes="monday"),
        ])
        self.db.commit()

        rows, week_start, week_end, month_start = effort_rows(self.db, self.org, self.manager, date(2026, 9, 21))
        direct = next(row for row in rows if row["email"] == self.direct.email)
        self.assertEqual((week_start, week_end, month_start), (date(2026, 9, 14), date(2026, 9, 20), date(2026, 9, 1)))
        self.assertEqual(direct["last_week_available"], 40.0)
        self.assertEqual(direct["last_week_logged"], 6.0)
        self.assertEqual(direct["month_logged"], 8.0)
        self.assertEqual(direct["month_available"], 120.0)

        subject, text_body, html_body, count = build_message(self.db, self.org, self.manager, date(2026, 9, 21))
        self.assertEqual(count, 2)
        self.assertIn("14 Sep–20 Sep 2026", subject)
        self.assertIn("Indirect | Level 2 | 0.0% (Needs attention)", text_body)
        self.assertIn("Month to date", html_body)
        self.assertIn("#b42318", html_body)
        self.assertNotIn("40.00h", text_body)
        self.assertNotIn("40.00h", html_body)


if __name__ == "__main__":
    unittest.main()
