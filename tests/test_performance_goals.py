import os
import unittest
from datetime import date
from decimal import Decimal

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["USER_CONTENT_DIR"] = "/tmp/protracklite-test-user-content"

from fastapi import HTTPException

from app.database import Base, SessionLocal, engine
from app.main import (
    calculate_kpi_achievement_percent,
    can_update_plan_progress,
    close_performance_plan_page,
    complete_performance_review_page,
    finalize_performance_plan_page,
    financial_cycle_for_year,
    managed_user_ids,
    performance_plan_for_access,
    start_performance_review_page,
    submit_performance_plan_page,
    validate_plan_for_activation,
)
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


if __name__ == "__main__":
    unittest.main()
