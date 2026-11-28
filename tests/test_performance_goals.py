import os
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["USER_CONTENT_DIR"] = "/tmp/protracklite-test-user-content"

from fastapi import HTTPException, Request

from app.database import Base, SessionLocal, engine
from app.main import (
    add_goal_discussion_comment,
    amend_performance_goal,
    calculate_goal_achievement_percent,
    calculate_kpi_achievement_percent,
    change_goal_discussion_member,
    can_update_plan_progress,
    close_performance_plan_page,
    complete_performance_review_page,
    finalize_performance_plan_page,
    financial_cycle_for_year,
    goal_discussion_for_access,
    goals_page,
    managed_user_ids,
    performance_goal_discussion_page,
    performance_plan_for_access,
    quick_create_goals_submit,
    start_performance_review_page,
    submit_performance_plan_page,
    toggle_performance_kpi_item_page,
    validate_plan_for_activation,
)
from app.performance_digest import run_digests
from app.models import (
    Organization,
    PerformanceGoal,
    PerformanceKPI,
    PerformanceKPIItem,
    PerformancePlan,
    Role,
    User,
)


if engine.dialect.name != "sqlite":
    raise RuntimeError("Tests must never run against a non-SQLite database.")


class PerformanceGoalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(engine)

    def setUp(self):
        self.db = SessionLocal()
        self.org = Organization(name="Goals Example", slug="goals-example")
        self.db.add(self.org)
        self.db.flush()
        self.manager = User(
            org_id=self.org.id,
            email="manager@example.com",
            full_name="Manager",
            password_hash="test",
            role=Role.MANAGER,
        )
        self.employee = User(
            org_id=self.org.id,
            email="employee@example.com",
            full_name="Employee",
            password_hash="test",
            role=Role.EMPLOYEE,
        )
        self.outsider = User(
            org_id=self.org.id,
            email="outsider@example.com",
            full_name="Outsider",
            password_hash="test",
            role=Role.EMPLOYEE,
        )
        self.db.add_all([self.manager, self.employee, self.outsider])
        self.db.flush()
        self.employee.manager_id = self.manager.id
        self.db.commit()

    def tearDown(self):
        self.db.close()
        with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(table.delete())

    def test_financial_cycle_runs_april_to_march(self):
        start, end, label = financial_cycle_for_year(2026)
        self.assertEqual(start, date(2026, 4, 1))
        self.assertEqual(end, date(2027, 3, 31))
        self.assertEqual(label, "FY 2026-27")

    def test_manager_scope_can_include_self_without_including_unrelated_people(self):
        self.assertEqual(managed_user_ids(self.db, self.org.id, self.manager), {self.employee.id})
        self.assertEqual(
            managed_user_ids(self.db, self.org.id, self.manager, include_self=True),
            {self.manager.id, self.employee.id},
        )

    def test_measurement_modes_calculate_achievement(self):
        higher = PerformanceKPI(
            title="Sales", measurement_type="numeric_higher", baseline_value=Decimal("100"),
            target_value=Decimal("200"), actual_value=Decimal("150"), weightage=Decimal("100"),
        )
        lower = PerformanceKPI(
            title="Resolution time", measurement_type="numeric_lower", baseline_value=Decimal("10"),
            target_value=Decimal("5"), actual_value=Decimal("7.5"), weightage=Decimal("100"),
        )
        binary = PerformanceKPI(
            title="Certification", measurement_type="binary", actual_value=Decimal("1"),
            weightage=Decimal("100"),
        )
        manual = PerformanceKPI(
            title="Leadership", measurement_type="manual", actual_value=Decimal("115"),
            weightage=Decimal("100"),
        )
        self.assertEqual(calculate_kpi_achievement_percent(higher), 50.0)
        self.assertEqual(calculate_kpi_achievement_percent(lower), 50.0)
        self.assertEqual(calculate_kpi_achievement_percent(binary), 100.0)
        self.assertEqual(calculate_kpi_achievement_percent(manual), 100.0)

    def test_reviewer_approved_value_overrides_owner_actual(self):
        kpi = PerformanceKPI(
            title="Revenue", measurement_type="percentage", target_value=Decimal("100"),
            actual_value=Decimal("90"), approved_value=Decimal("80"), weightage=Decimal("100"),
        )
        self.assertEqual(calculate_kpi_achievement_percent(kpi), 80.0)

    def test_activation_requires_complete_weighted_structure(self):
        plan = PerformancePlan(
            org_id=self.org.id, user_id=self.employee.id, year=2026, title="Plan",
            status="draft", created_by=self.manager.id,
        )
        goal = PerformanceGoal(title="Delivery", weightage=Decimal("100"))
        goal.kpis.append(PerformanceKPI(title="Milestones", measurement_type="checklist", weightage=Decimal("100")))
        plan.goals.append(goal)
        with self.assertRaises(HTTPException):
            validate_plan_for_activation(plan)
        goal.kpis[0].items.append(PerformanceKPIItem(title="Release", created_by=self.manager.id))
        validate_plan_for_activation(plan)

    def test_employee_and_manager_can_update_active_direct_report_plan(self):
        plan = PerformancePlan(
            org_id=self.org.id, user_id=self.employee.id, year=2026, title="Plan",
            status="active", created_by=self.manager.id,
        )
        self.assertTrue(can_update_plan_progress(self.db, self.employee, plan))
        self.assertTrue(can_update_plan_progress(self.db, self.manager, plan))
        self.assertFalse(can_update_plan_progress(self.db, self.outsider, plan))
        plan.status = "submitted_for_review"
        self.assertFalse(can_update_plan_progress(self.db, self.employee, plan))

    def test_manager_can_open_own_assigned_plan(self):
        plan = PerformancePlan(
            org_id=self.org.id, user_id=self.manager.id, year=2026, title="Manager Plan",
            status="active", created_by=self.manager.id, reviewer_id=self.manager.id,
        )
        self.db.add(plan)
        self.db.commit()
        self.assertEqual(
            performance_plan_for_access(self.db, self.org.id, self.manager, plan.id).id,
            plan.id,
        )

    def test_assigned_reviewer_can_open_plan_outside_reporting_line(self):
        self.outsider.role = Role.MANAGER
        plan = PerformancePlan(
            org_id=self.org.id, user_id=self.employee.id, year=2026, title="Cross-functional Plan",
            status="submitted_for_review", created_by=self.manager.id, reviewer_id=self.outsider.id,
        )
        self.db.add(plan)
        self.db.commit()
        self.assertEqual(
            performance_plan_for_access(self.db, self.org.id, self.outsider, plan.id).id,
            plan.id,
        )

    def test_full_lifecycle_requires_owner_then_reviewer(self):
        plan = PerformancePlan(
            org_id=self.org.id, user_id=self.employee.id, year=2026, title="Plan",
            status="draft", created_by=self.manager.id, reviewer_id=self.manager.id,
        )
        goal = PerformanceGoal(title="Delivery", weightage=Decimal("100"))
        kpi = PerformanceKPI(title="Milestones", measurement_type="checklist", weightage=Decimal("100"))
        kpi.items.append(PerformanceKPIItem(title="Release", created_by=self.manager.id))
        goal.kpis.append(kpi)
        plan.goals.append(goal)
        self.db.add(plan)
        self.db.commit()

        finalize_performance_plan_page("goals-example", plan.id, (self.org, self.manager), self.db)
        self.assertEqual(plan.status, "active")
        submit_performance_plan_page(
            "goals-example", plan.id, "Delivered the agreed release.", (self.org, self.employee), self.db
        )
        self.assertEqual(plan.status, "submitted_for_review")
        start_performance_review_page("goals-example", plan.id, (self.org, self.manager), self.db)
        self.assertEqual(plan.status, "under_review")
        complete_performance_review_page(
            "goals-example", plan.id, "Strong delivery with clear evidence.", Decimal("4.25"),
            (self.org, self.manager), self.db,
        )
        self.assertEqual(plan.status, "reviewed")
        close_performance_plan_page("goals-example", plan.id, (self.org, self.manager), self.db)
        self.assertEqual(plan.status, "closed")


    def test_manager_can_quick_create_for_self_and_downline(self):
        self.outsider.role = Role.MANAGER
        self.outsider.manager_id = self.manager.id
        self.employee.manager_id = self.outsider.id
        self.db.commit()
        for owner in (self.manager, self.employee):
            response = quick_create_goals_submit(
                self.org.slug, owner.id, 2026, "", "", "", None, "Plan",
                "# Deliver\n## Release\n- Ship", "delivery_execution",
                (self.org, self.manager), self.db,
            )
            plan_id = int(response.headers["location"].split("=")[-1])
            self.assertEqual(
                performance_plan_for_access(self.db, self.org.id, self.manager, plan_id).user_id, owner.id,
            )
        self.assertEqual(managed_user_ids(self.db, self.org.id, self.manager), {self.outsider.id})

    def test_shared_discussion_grants_goal_only_access_and_can_be_revoked(self):
        plan = self.make_active_plan()
        goal = plan.goals[0]
        change_goal_discussion_member(self.org.slug, goal.id, self.outsider.id, "add", (self.org, self.employee), self.db)
        add_goal_discussion_comment(self.org.slug, goal.id, "Can help with delivery", (self.org, self.outsider), self.db)
        self.assertIsNone(performance_plan_for_access(self.db, self.org.id, self.outsider, plan.id))
        self.assertEqual(goal_discussion_for_access(self.db, self.org.id, self.outsider, goal.id).id, goal.id)
        request = Request({"type": "http", "path": f"/{self.org.slug}/goals/goals/{goal.id}/discussion", "headers": []})
        page = performance_goal_discussion_page(request, goal.id, (self.org, self.outsider), self.db)
        self.assertIn(b"Can help with delivery", page.body)
        self.assertNotIn(b"Save goal weights", page.body)
        with self.assertRaises(HTTPException) as denied:
            change_goal_discussion_member(self.org.slug, goal.id, self.manager.id, "add", (self.org, self.outsider), self.db)
        self.assertEqual(denied.exception.status_code, 403)
        change_goal_discussion_member(self.org.slug, goal.id, self.outsider.id, "remove", (self.org, self.employee), self.db)
        with self.assertRaises(HTTPException):
            goal_discussion_for_access(self.db, self.org.id, self.outsider, goal.id)

    def test_reviewed_amendment_excludes_retired_work_and_rejects_stale_save(self):
        plan = self.make_active_plan()
        goal = plan.goals[0]
        kpi, extra = goal.kpis
        task = kpi.items[1]
        version = plan.revision
        arguments = (self.org.slug, goal.id, version, "kpis", [Decimal("100"), Decimal("50")],
                     "Agreed at check-in", [extra.id], [task.id])
        request = Request({"type": "http", "path": f"/{self.org.slug}/goals/goals/{goal.id}/discussion", "headers": []})
        page = performance_goal_discussion_page(request, goal.id, (self.org, self.manager), self.db)
        self.assertIn(b"Save KPI and task changes", page.body)
        with self.assertRaises(HTTPException) as denied:
            amend_performance_goal(*arguments, (self.org, self.employee), self.db)
        self.assertEqual(denied.exception.status_code, 403)
        response = amend_performance_goal(*arguments, (self.org, self.manager), self.db)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(plan.status, "active")
        self.assertIsNotNone(task.retired_at)
        self.assertIsNotNone(extra.retired_at)
        self.assertEqual(calculate_goal_achievement_percent(goal), 100)
        request = Request({"type": "http", "path": f"/{self.org.slug}/goals", "headers": []})
        page = goals_page(request, plan.id, (self.org, self.manager), self.db)
        self.assertIn(b"Retired KPI", page.body)
        self.assertIn(b"Goal Achieved", page.body)
        self.assertIn(b"Agreed at check-in", page.body)
        with self.assertRaises(HTTPException) as stale:
            amend_performance_goal(*arguments, (self.org, self.manager), self.db)
        self.assertEqual(stale.exception.status_code, 409)
        with self.assertRaises(HTTPException) as retired:
            toggle_performance_kpi_item_page(self.org.slug, task.id, (self.org, self.employee), self.db)
        self.assertEqual(retired.exception.status_code, 409)

    def test_digest_reports_status_deadline_inactivity_and_sends_once_per_day(self):
        plan = self.make_active_plan()
        goal = plan.goals[0]
        now = datetime(2026, 11, 23, 12)
        task = goal.kpis[0].items[1]
        task.target_date = date(2026, 11, 24)
        kpi = goal.kpis[0]
        kpi.updated_at = now - timedelta(days=8)
        for item in kpi.items:
            item.updated_at = kpi.updated_at
        self.db.commit()
        with patch("app.performance_digest.send_email") as send:
            self.assertEqual(run_digests(now=now), 0)
            self.assertEqual(send.call_count, 2)
            body = send.call_args.args[2]
            self.assertIn("[Open] Follow up", body)
            self.assertIn("at least 7 days", body)
            self.assertIn("is due 24 Nov 2026", body)
            self.assertEqual(run_digests(now=now), 0)
            self.assertEqual(send.call_count, 2)

    def make_active_plan(self):
        previous_week = datetime(2026, 11, 14, 12)
        plan = PerformancePlan(
            org_id=self.org.id, user_id=self.employee.id, year=2026, title="Plan",
            status="active", created_by=self.manager.id, reviewer_id=self.manager.id, activated_at=previous_week,
        )
        goal = PerformanceGoal(title="Delivery", weightage=Decimal("100"))
        kpi = PerformanceKPI(title="Milestones", measurement_type="checklist", weightage=Decimal("50"),
                             sort_order=1, created_at=previous_week, updated_at=previous_week)
        kpi.items.extend([
            PerformanceKPIItem(title="Release", created_by=self.manager.id, is_completed=True),
            PerformanceKPIItem(title="Follow up", created_by=self.manager.id),
        ])
        goal.kpis.extend([
            kpi, PerformanceKPI(title="Extra", measurement_type="binary", weightage=Decimal("50"), sort_order=2),
        ])
        plan.goals.append(goal)
        self.db.add(plan)
        self.db.commit()
        return plan

if __name__ == "__main__":
    unittest.main()
