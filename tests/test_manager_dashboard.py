import os
import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

os.environ['DATABASE_URL'] = 'sqlite+pysqlite:///:memory:'
os.environ['USER_CONTENT_DIR'] = '/tmp/protracklite-test-user-content'

from fastapi import HTTPException
from starlette.requests import Request
from app.database import Base, SessionLocal, engine
from app.main import manager_dashboard_page
from app.manager_dashboard import build_manager_dashboard
from app.models import (ActivityType, CapacityZohoSnapshot, Department, Holiday, LeaveApproval,
                        Organization, OrgSettings, Project, Role, Task, TaskStatus, TimeLog, User,
                        WeeklyTaskPlan, WeeklyTaskPlanItem)

TODAY = date(2026, 10, 13)
if engine.dialect.name != 'sqlite':
    raise RuntimeError('Tests require an isolated SQLite database.')


class ManagerDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(engine)

    def setUp(self):
        self.db = SessionLocal()
        self.org = Organization(name='Example', slug='example')
        self.db.add(self.org)
        self.db.flush()
        self.manager = User(org_id=self.org.id, full_name='Manager', email='manager@example.com', password_hash='test', role=Role.MANAGER)
        self.dept = Department(org_id=self.org.id, name='Engineering')
        self.db.add_all([self.manager, self.dept])
        self.db.flush()
        self.member = User(org_id=self.org.id, full_name='Aarav <script>', email='aarav@example.com', password_hash='test', manager_id=self.manager.id, department_id=self.dept.id)
        self.other = User(org_id=self.org.id, full_name='Other team', email='other@example.com', password_hash='test')
        self.activity = ActivityType(org_id=self.org.id, name='Development', code='DEV')
        self.db.add_all([self.member, self.other, self.activity, OrgSettings(org_id=self.org.id, work_hours_per_day=Decimal('8'), weekend_days=[5, 6])])
        self.db.flush()
        self.project = Project(org_id=self.org.id, name='Platform', code='PL', created_by=self.manager.id)
        self.db.add(self.project)
        self.db.flush()
        self.snapshot = CapacityZohoSnapshot(org_id=self.org.id, year=2026, month=10, synced_at=datetime(2026, 10, 13, 3), member_ids_json=[self.member.id], leave_days_json=[])
        self.db.add(self.snapshot)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())

    def task(self, code='PL1', **changes):
        values = dict(task_id=code, org_id=self.org.id, project_id=self.project.id, assigned_to=self.member.id, created_by=self.manager.id, name=code, activity_type_id=self.activity.id, status=TaskStatus.STARTED, end_date=date(2026, 10, 16), estimated_hours=Decimal('12'), logged_hours=Decimal('2'))
        values.update(changes)
        task = Task(**values)
        self.db.add(task)
        self.db.flush()
        return task

    def payload(self):
        self.db.flush()
        return build_manager_dashboard(self.db, self.org, self.manager, [self.member], {}, TODAY)

    def entry(self, day, count=1, approval='APPROVED', **changes):
        return dict(user_id=self.member.id, date=day, count=count, approval=approval, type='Annual leave', **changes)

    def request(self):
        return Request({'type': 'http', 'method': 'GET', 'path': '/example/manager/dashboard', 'query_string': b'', 'headers': [], 'scheme': 'http', 'server': ('test', 80)})

    def test_remaining_capacity_and_elapsed_effort(self):
        t = self.task()
        self.db.add_all([TimeLog(task_id=t.id, user_id=self.member.id, log_date=date(2026, 10, 12), hours=Decimal('6')), TimeLog(task_id=t.id, user_id=self.member.id, log_date=TODAY, hours=Decimal('2'))])
        self.snapshot.leave_days_json = [self.entry('2026-10-14', .5), self.entry('2026-10-15', approval='PENDING')]
        d = self.payload()
        self.assertEqual(d['rows'][0]['planned'], 10)
        self.assertEqual(d['rows'][0]['available'], 26)
        self.assertEqual(d['rows'][0]['elapsed'], 8)
        self.assertEqual(d['rows'][0]['logged'], 6)
        self.assertEqual(len(d['leaves']), 1)

    def test_scoped_tasks_archives_and_due_today(self):
        self.task(end_date=TODAY)
        self.task('PL2', end_date=date(2026, 10, 12), status=TaskStatus.STALLED, stalled_reason='Need access')
        self.task('OTHER_SECRET', assigned_to=self.other.id)
        self.task('ARCHIVED_SECRET', is_archived=True)
        d = self.payload()
        self.assertEqual(d['overdue'], 1)
        self.assertEqual(d['rows'][0]['open'], 2)
        self.assertEqual(d['projects'][0]['total'], 2)
        self.assertEqual(d['projects'][0]['status'], 'Blocked')
        self.assertNotIn('SECRET', str(d))
        self.assertEqual(d['alerts'][0]['type'], 'delivery')

    def test_missing_snapshot_does_not_invent_capacity(self):
        self.task()
        self.db.delete(self.snapshot)
        d = self.payload()
        self.assertIsNone(d['available'])
        self.assertIsNone(d['rows'][0]['elapsed'])
        self.assertFalse(d['rows'][0]['overloaded'])
        self.assertTrue(any('Leave data unavailable' in a['title'] for a in d['alerts']))

    def test_unknown_member_and_empty_team(self):
        self.snapshot.member_ids_json = []
        self.assertIsNone(self.payload()['available'])
        empty = build_manager_dashboard(self.db, self.org, self.manager, [], {}, TODAY)
        self.assertEqual(empty['rows'], [])
        self.assertEqual(empty['alerts'], [])

    def test_missing_estimates_and_weekly_plan_membership(self):
        self.task(estimated_hours=None)
        future = self.task('PL2', end_date=date(2026, 11, 1))
        self.task('PL3', end_date=date(2026, 11, 1), estimated_hours=Decimal('100'))
        plan = WeeklyTaskPlan(org_id=self.org.id, user_id=self.member.id, week_start=date(2026, 10, 12), week_end=date(2026, 10, 18))
        self.db.add(plan)
        self.db.flush()
        self.db.add(WeeklyTaskPlanItem(weekly_task_plan_id=plan.id, task_id=future.id))
        d = self.payload()
        self.assertEqual(d['missing_estimates'], 1)
        self.assertEqual(d['planned'], 10)

    def test_local_approval_overlay_and_pending_queue(self):
        approval = LeaveApproval(org_id=self.org.id, user_id=self.member.id, zoho_leave_id='z1', fingerprint='f', source_status='PENDING', request_json={'start_date': '2026-10-14', 'end_date': '2026-10-14'}, approved_fingerprint='f', approved_at=datetime(2026, 10, 13))
        pending = LeaveApproval(org_id=self.org.id, user_id=self.member.id, zoho_leave_id='z2', fingerprint='f2', source_status='PENDING', request_json={'start_date': '2026-10-16', 'end_date': '2026-10-16'})
        self.db.add_all([approval, pending])
        self.snapshot.leave_days_json = [self.entry('2026-10-14', approval='PENDING', zoho_leave_id='z1', request_fingerprint='f')]
        d = self.payload()
        self.assertEqual(d['available'], 24)
        self.assertEqual(d['approvals'], 1)

    def test_holiday_zero_capacity_and_overload(self):
        self.task(estimated_hours=Decimal('50'))
        self.snapshot.leave_days_json = [self.entry(f'2026-10-{day}') for day in range(13, 17)]
        d = self.payload()
        self.assertEqual(d['available'], 0)
        self.assertEqual(d['overloaded'], 1)
        self.assertIsNone(d['rows'][0]['load_percent'])
        self.snapshot.leave_days_json = []
        self.db.add(Holiday(org_id=self.org.id, holiday_date=date(2026, 10, 14), name='Holiday'))
        self.assertEqual(self.payload()['available'], 24)

    def test_route_render_department_filter_and_permissions(self):
        self.task()
        with patch('app.main.local_today', return_value=TODAY):
            response = manager_dashboard_page(self.request(), department='Engineering', org_user=(self.org, self.manager), db=self.db)
            html = response.body.decode()
            self.assertIn('Make room for better work.', html)
            self.assertIn('Aarav &lt;script&gt;', html)
            self.assertNotIn('Other team', html)
            self.assertIn('synced', html)
            with self.assertRaises(HTTPException) as error:
                manager_dashboard_page(self.request(), department='Outside team', org_user=(self.org, self.manager), db=self.db)
            self.assertEqual(error.exception.status_code, 400)
        with self.assertRaises(HTTPException) as error:
            manager_dashboard_page(self.request(), department='', org_user=(self.org, self.member), db=self.db)
        self.assertEqual(error.exception.status_code, 403)
