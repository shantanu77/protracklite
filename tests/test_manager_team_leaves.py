import os
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["USER_CONTENT_DIR"] = "/tmp/protracklite-test-user-content"

from app.database import Base, SessionLocal, engine
from app.main import download_team_attendance, manager_regularize_attendance, manager_team_leaves_page, regularization_attendance_context, templates
from app.models import AttendanceRegularization, Holiday, Organization, User
from sqlalchemy import select


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
                "attendance": {
                    "status": "synced", "office_days": 12, "remote_days": 5,
                    "total_days": 17, "rows": [], "message": "Loaded",
                },
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
        self.assertIn('data-regularization-modal', html)
        self.assertIn('attendance-missing-row', html)
        self.assertIn('attendance.csv?', html)

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

    def test_missing_working_days_fill_attendance_rows_and_skip_holiday(self):
        attendance = {
            "status": "synced", "office_days": 1.0, "remote_days": 0.0,
            "total_days": 1.0, "rows": [{
                "date": date(2026, 9, 1), "date_label": "Tue, 01 Sep",
                "first_in_label": "10:00 AM", "last_out_label": "07:00 PM",
                "mode": "office", "mode_label": "Office", "attendance_source": "Terminal",
                "attendance_location": "Office", "is_open": False,
            }],
        }
        with patch("app.main.local_today", return_value=date(2026, 10, 1)):
            result = regularization_attendance_context(
                self.db, self.org.id, self.member.id, attendance,
                date(2026, 9, 1), date(2026, 9, 8), include_missing_rows=True,
            )
        self.assertEqual(result["working_day_count"], 5)
        self.assertEqual([row["date"] for row in result["rows"] if row["mode"] == "missing"],
                         [date(2026, 9, 8), date(2026, 9, 4), date(2026, 9, 3), date(2026, 9, 2)])
        self.assertEqual(result["unmarked_count"], 4)

    def test_csv_export_contains_missing_days(self):
        with (
            patch("app.main.must_be_admin_or_manager"),
            patch("app.main.reporting_tree_people", return_value=[{"user": self.member}]),
            patch("app.main.local_today", return_value=date(2026, 10, 1)),
            patch("app.main.team_member_month_feed", return_value={"attendance": {
                "status": "synced", "office_days": 0.0, "remote_days": 0.0,
                "total_days": 0.0, "rows": [], "message": "Loaded",
            }}),
        ):
            response = download_team_attendance(member_id=self.member.id, month="2026-09",
                                                org_user=(self.org, self.member), db=self.db)
        self.assertIn(b"2026-09-01,", response.body)
        self.assertIn(b"No attendance", response.body)
        self.assertNotIn(b"2026-09-07,", response.body)

    def test_bulk_regularization_records_each_successful_day(self):
        with (
            patch("app.main.must_be_admin_or_manager"),
            patch("app.main.reporting_tree_people", return_value=[{"user": self.member}]),
            patch("app.main.local_today", return_value=date(2026, 10, 1)),
            patch("app.main.zoho_profile_attendance_feed", return_value={"status": "synced", "rows": []}),
            patch("app.main.add_zoho_attendance_entry", return_value=SimpleNamespace(status="synced")) as add,
        ):
            response = manager_regularize_attendance(
                org_slug=self.org.slug, member_id=self.member.id, month="2026-09",
                attendance_dates=[date(2026, 9, 2), date(2026, 9, 3)],
                start_time="10:00", end_time="19:00", location="remote",
                org_user=(self.org, self.member), db=self.db,
            )
        self.assertEqual(add.call_count, 2)
        self.assertIn("regularized=2", response.headers["location"])
        records = self.db.scalars(select(AttendanceRegularization).order_by(AttendanceRegularization.attendance_date)).all()
        self.assertEqual([record.status for record in records], ["approved", "approved"])


if __name__ == "__main__":
    unittest.main()
