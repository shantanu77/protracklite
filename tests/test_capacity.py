import os
import unittest
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("USER_CONTENT_DIR", "/tmp/protracklite-test-user-content")

from app.capacity import build_capacity_payload
from app.database import Base, SessionLocal, engine
from app.models import Leave, Organization, User


class CapacityAlertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(engine)

    def setUp(self):
        self.db = SessionLocal()
        self.org = Organization(name="Capacity Example", slug="capacity-example")
        self.db.add(self.org)
        self.db.flush()
        self.people = [
            User(
                org_id=self.org.id,
                email=f"person{index}@example.com",
                full_name=f"Person {index}",
                password_hash="test",
            )
            for index in range(1, 3)
        ]
        self.db.add_all(self.people)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(table.delete())

    def report(self):
        return build_capacity_payload(
            self.db,
            self.org,
            self.people,
            view="month",
            anchor=date(2026, 7, 27),
            today=date(2026, 7, 27),
        )

    def test_past_overlapping_leave_is_not_alerted(self):
        self.db.add_all(
            Leave(user_id=person.id, leave_date=date(2026, 7, 20))
            for person in self.people
        )
        self.db.commit()

        report = self.report()

        self.assertEqual(report["conflict_tone"], "clear")
        self.assertEqual(report["conflict_text"], "No upcoming leave conflicts detected for this period.")

    def test_future_overlapping_leave_still_triggers_alert(self):
        self.db.add_all(
            Leave(user_id=person.id, leave_date=date(2026, 7, 29))
            for person in self.people
        )
        self.db.commit()

        report = self.report()

        self.assertEqual(report["conflict_tone"], "warning")
        self.assertIn("2 team members unavailable on 29 Jul", report["conflict_text"])

    def test_weekend_columns_are_narrower_than_weekdays(self):
        report = build_capacity_payload(
            self.db,
            self.org,
            self.people,
            view="week",
            anchor=date(2026, 7, 27),
            today=date(2026, 7, 27),
        )

        weekday = next(column for column in report["day_columns"] if not column["is_weekend"])
        weekend = next(column for column in report["day_columns"] if column["is_weekend"])
        self.assertLess(weekend["width_percent"], weekday["width_percent"])
        self.assertAlmostEqual(
            sum(column["width_percent"] for column in report["day_columns"]),
            100,
            places=4,
        )


if __name__ == "__main__":
    unittest.main()
