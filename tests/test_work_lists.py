import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("USER_CONTENT_DIR", "/tmp/protracklite-test-user-content")

from sqlalchemy import func, select

from app.database import Base, SessionLocal, engine
from app.main import toggle_list_item_page, work_list_comment_page
from app.models import Organization, User, WorkList, WorkListComment, WorkListItem


class WorkListCompletionTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(engine)

    def setUp(self):
        self.db = SessionLocal()
        self.org = Organization(name="Example", slug="example")
        self.db.add(self.org)
        self.db.flush()
        self.user = User(
            org_id=self.org.id,
            email="divya@example.com",
            full_name="Divya Mishra",
            password_hash="test",
            avatar_24_url="/user-content/avatar-24.jpg",
        )
        self.db.add(self.user)
        self.db.flush()
        self.work_list = WorkList(org_id=self.org.id, owner_user_id=self.user.id, title="Release")
        self.db.add(self.work_list)
        self.db.flush()
        self.item = WorkListItem(work_list_id=self.work_list.id, title="Resolve defects")
        self.db.add(self.item)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(table.delete())

    async def test_duplicate_complete_requests_do_not_reopen_item(self):
        for _ in range(2):
            response = await toggle_list_item_page(
                "example",
                self.work_list.id,
                self.item.id,
                is_completed=True,
                org_user=(self.org, self.user),
                db=self.db,
            )
            self.assertTrue(response["is_completed"])

        self.db.refresh(self.item)
        self.assertTrue(self.item.is_completed)
        activity_count = self.db.scalar(
            select(func.count(WorkListComment.id)).where(WorkListComment.work_list_id == self.work_list.id)
        )
        self.assertEqual(activity_count, 1)

    async def test_activity_payload_uses_profile_picture(self):
        await toggle_list_item_page(
            "example",
            self.work_list.id,
            self.item.id,
            is_completed=True,
            org_user=(self.org, self.user),
            db=self.db,
        )

        comments = work_list_comment_page(self.db, self.work_list.id)["comments"]
        self.assertEqual(comments[0]["actor_avatar_url"], "/user-content/avatar-24.jpg")
        self.assertEqual(comments[0]["actor_name"], "Divya Mishra")
        self.assertEqual(comments[0]["item_ids"], [self.item.id])
        self.assertEqual(comments[0]["item_references"], f"#{self.item.id}")

    def test_historical_completion_activity_is_associated_by_item_title(self):
        self.db.add(
            WorkListComment(
                work_list_id=self.work_list.id,
                user_id=self.user.id,
                body=f"Divya Mishra completed task - {self.item.title}",
            )
        )
        self.db.commit()

        comment = work_list_comment_page(self.db, self.work_list.id)["comments"][0]
        self.assertEqual(comment["kind"], "activity")
        self.assertEqual(comment["item_ids"], [self.item.id])
        self.assertEqual(comment["item_references"], f"#{self.item.id}")


if __name__ == "__main__":
    unittest.main()
