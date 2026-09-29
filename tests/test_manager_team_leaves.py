import os
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["USER_CONTENT_DIR"] = "/tmp/protracklite-test-user-content"

from app.database import Base, SessionLocal, engine
from app.main import manager_team_leaves_page, templates
from app.models import Holiday, Organization, User


if engine.dialect.name != "sqlite":
    raise RuntimeError("Tests must never run against a non-SQLite database.")


class ManagerTeamLeavesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(engine)

    def setUp(self):
        self.db = SessionLocal()
        self.org = Organization(name="Leaves Example", slug="leaves-example")
        self.db.add(self.org)
        self.db.flush()
        self.member = User(
            org_id=self.org.id,
            email="member@example.com",
            full_name="Team Member",
            password_hash="test",
        )
        self.db.add_all([
            self.member,
            Holiday(org_id=self.org.id, holiday_date=date(2026, 9, 7), name="Holiday"),
        ])
        self.db.flush()

    def tearDown(self):
        self.db.close()
        with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(table.delete())

    def test_working_day_denominator_uses_attendance_range_and_excludes_holidays(self):
        with (
            patch("app.main.must_be_admin_or_manager"),
            patch("app.main.reporting_tree_people", return_value=[{"user": self.member}]),
            patch("app.main.local_today", return_value=date(2026, 9, 29)),
            patch("app.main.team_member_month_feed", return_value={
                "attendance": {"status": "synced", "total_days": 17},
            }),
            patch("app.main.templates.TemplateResponse") as render,
        ):
            manager_team_leaves_page(
                request=SimpleNamespace(url=SimpleNamespace(path="/leaves-example/manager/team-leaves"), query_params={}),
                member_id=self.member.id,
                month="2026-09",
                org_user=(self.org, self.member),
                db=self.db,
            )

        context = render.call_args.args[1]
        self.assertEqual(context["working_day_count"], 20)
        html = templates.env.get_template("manager_team_leaves.html").render(context)
        self.assertIn("17 / 20", html)

    def test_past_month_uses_full_month(self):
        with (
            patch("app.main.must_be_admin_or_manager"),
            patch("app.main.reporting_tree_people", return_value=[{"user": self.member}]),
            patch("app.main.local_today", return_value=date(2026, 9, 29)),
            patch("app.main.team_member_month_feed", return_value={"attendance": None}),
            patch("app.main.templates.TemplateResponse") as render,
        ):
            manager_team_leaves_page(
                request=SimpleNamespace(),
                member_id=self.member.id,
                month="2026-08",
                org_user=(self.org, self.member),
                db=self.db,
            )

        self.assertEqual(render.call_args.args[1]["working_day_count"], 21)


if __name__ == "__main__":
    unittest.main()
