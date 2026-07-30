import os
import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["USER_CONTENT_DIR"] = "/tmp/protracklite-test-user-content"

from app.database import Base, SessionLocal, engine
from app.main import today_payload
from app.models import (
    ActivityType,
    Organization,
    OrgSettings,
    Project,
    Task,
    TodayAlertAcknowledgement,
    User,
)


class TodayPayloadAlertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(engine)

    def setUp(self):
        self.db = SessionLocal()
        self.org = Organization(name="Today Example", slug="today-example")
        self.db.add(self.org)
        self.db.flush()
        self.user = User(
            org_id=self.org.id,
            email="today@example.com",
            full_name="Today User",
            password_hash="test",
        )
        self.db.add(self.user)
        self.db.flush()
        self.db.add(
            OrgSettings(
                org_id=self.org.id,
                weekend_days=[5, 6],
                work_hours_per_day=Decimal("8.00"),
            )
        )
        self.activity = ActivityType(
            org_id=self.org.id,
            code="DEV",
            name="Development",
        )
        self.project = Project(
            org_id=self.org.id,
            code="TOD",
            name="Today Project",
            created_by=self.user.id,
        )
        self.db.add_all([self.activity, self.project])
        self.db.flush()
        self.task = Task(
            task_id="TOD-1",
            org_id=self.org.id,
            project_id=self.project.id,
            assigned_to=self.user.id,
            created_by=self.user.id,
            name="Resolve overdue work",
            activity_type_id=self.activity.id,
            start_date=date(2026, 7, 20),
            end_date=date(2026, 7, 27),
            estimated_hours=Decimal("8.00"),
        )
        self.db.add(self.task)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(table.delete())

    @patch("app.main.local_today", return_value=date(2026, 7, 30))
    @patch("app.main.local_now", return_value=datetime(2026, 7, 30, 14, 0))
    def test_acknowledged_alert_is_hidden_for_the_day(self, _mock_now, _mock_today):
        first = today_payload(self.db, self.org, self.user)
        overdue = next(alert for alert in first["alerts"] if alert["kind"] == "overdue")
        self.db.add(
            TodayAlertAcknowledgement(
                org_id=self.org.id,
                user_id=self.user.id,
                alert_key=overdue["alert_key"],
                action="acknowledged",
                acknowledged_on=date(2026, 7, 30),
            )
        )
        self.db.commit()

        second = today_payload(self.db, self.org, self.user)

        self.assertNotIn(overdue["alert_key"], [alert["alert_key"] for alert in second["alerts"]])
        self.assertEqual(second["alert_handled_today"], 1)


if __name__ == "__main__":
    unittest.main()
