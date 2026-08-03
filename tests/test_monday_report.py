import os
import unittest
from datetime import date

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["USER_CONTENT_DIR"] = "/tmp/protracklite-test-user-content"

from app.database import Base, SessionLocal, engine
from app.models import ActivityType, Organization, Project, Task, TimeLog, User
from app.reports import monday_report

if engine.dialect.name != "sqlite":
    raise RuntimeError("Tests must never run against a non-SQLite database.")


class MondayReportPendingTaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(engine)

    def setUp(self):
        self.db = SessionLocal()
        self.org = Organization(name="Monday Example", slug="monday-example")
        self.db.add(self.org)
        self.db.flush()
        self.user = User(
            org_id=self.org.id,
            email="monday@example.com",
            full_name="Monday User",
            password_hash="test",
        )
        self.db.add(self.user)
        self.db.flush()
        self.activity = ActivityType(org_id=self.org.id, code="DEV", name="Development")
        self.project = Project(
            org_id=self.org.id,
            code="MON",
            name="Monday Project",
            created_by=self.user.id,
        )
        self.db.add_all([self.activity, self.project])
        self.db.flush()

    def tearDown(self):
        self.db.close()
        with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(table.delete())

    def add_task(self, task_id: str, start_date: date | None) -> None:
        self.db.add(
            Task(
                task_id=task_id,
                org_id=self.org.id,
                project_id=self.project.id,
                assigned_to=self.user.id,
                created_by=self.user.id,
                name=f"Task {task_id}",
                activity_type_id=self.activity.id,
                start_date=start_date,
            )
        )

    def test_pending_tasks_include_current_week_and_unscheduled_tasks(self):
        self.add_task("MON-OLD", date(2026, 7, 31))
        self.add_task("MON-NEW", date(2026, 8, 3))
        self.add_task("MON-BACKLOG", None)
        self.db.commit()

        report = monday_report(self.db, self.org.id, self.user.id, today=date(2026, 8, 3))

        self.assertEqual(
            {task["task_id"] for task in report["pending_tasks"]},
            {"MON-OLD", "MON-NEW", "MON-BACKLOG"},
        )
        self.assertEqual(report["total_open_task_count"], 3)

    def test_worked_last_week_excludes_archived_tasks(self):
        self.add_task("MON-ACTIVE", date(2026, 7, 27))
        self.add_task("MON-ARCHIVED", date(2026, 7, 27))
        self.db.flush()
        tasks = {task.task_id: task for task in self.db.query(Task).all()}
        tasks["MON-ARCHIVED"].is_archived = True
        self.db.add_all(
            [
                TimeLog(task_id=task.id, user_id=self.user.id, log_date=date(2026, 7, 30), hours=1, notes="x" * 80)
                for task in tasks.values()
            ]
        )
        self.db.commit()

        report = monday_report(self.db, self.org.id, self.user.id, today=date(2026, 8, 3))

        self.assertEqual([task["task_id"] for task in report["worked_last_week_tasks"]], ["MON-ACTIVE"])


if __name__ == "__main__":
    unittest.main()
