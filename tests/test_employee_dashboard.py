import json
import os
import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

os.environ['DATABASE_URL'] = 'sqlite+pysqlite:///:memory:'
os.environ['USER_CONTENT_DIR'] = '/tmp/protracklite-test-user-content'

from fastapi import HTTPException
from sqlalchemy import select
from app.database import Base, SessionLocal, engine
from app.employee_dashboard import DashboardSourceCache, build_employee_dashboard, personal_attendance_summary
from app.main import (add_time_log_page, dashboard, dashboard_attendance, dashboard_payload,
                      dashboard_request_regularization, request_attendance_regularization, resume_task_page)
from app.models import (ActivityType, AttendanceRegularization, Holiday, Leave, LeaveType, Organization,
                        OrgSettings, Project, Role, Task, TaskStatus, TimeLog, User, WeeklyTaskPlan, WeeklyTaskPlanItem)
from app.reports import week_allocation_summary
from app.zoho_people import ZohoLeaveListResult

TODAY = date(2026, 10, 8)
START = date(2026, 10, 5)
END = date(2026, 10, 11)
if engine.dialect.name != 'sqlite':
    raise RuntimeError('Tests must use an isolated SQLite database.')


class EmployeeDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(engine)

    def setUp(self):
        self.db = SessionLocal()
        self.org = Organization(name='Example', slug='example')
        self.db.add(self.org)
        self.db.flush()
        self.manager = User(org_id=self.org.id, email='manager@example.com', full_name='Manager', password_hash='test', role=Role.MANAGER)
        self.db.add(self.manager)
        self.db.flush()
        self.user = User(org_id=self.org.id, email='employee@example.com', full_name='Employee', password_hash='test',
                         manager_id=self.manager.id, zoho_employee_id='record-105')
        self.other = User(org_id=self.org.id, email='other@example.com', full_name='Other', password_hash='test')
        self.settings = OrgSettings(org_id=self.org.id, work_hours_per_day=Decimal('8'), weekend_days=[5, 6])
        self.activity = ActivityType(org_id=self.org.id, code='DEV', name='Development')
        self.db.add_all([self.user, self.other, self.settings, self.activity])
        self.db.flush()
        self.project = Project(org_id=self.org.id, code='APP', name='People platform', created_by=self.user.id)
        self.db.add(self.project)
        self.db.flush()
        self.overdue = self.task('APP1', end=date(2026, 10, 7), estimate=8)
        self.due = self.task('APP2', end=TODAY, estimate=None)
        self.blocked = self.task('APP3', end=TODAY, status=TaskStatus.STALLED, estimate=3)
        self.blocked.stalled_reason = 'Waiting for access'
        self.later = self.task('APP4', end=date(2026, 10, 15), estimate=2)
        self.done = self.task('APP5', end=date(2026, 10, 6), status=TaskStatus.CLOSED)
        self.done.closed_at = datetime(2026, 10, 6, 18)
        self.private = self.task('PRIVATE', assigned=self.other.id, end=TODAY)
        self.private.is_private = True
        self.plan = WeeklyTaskPlan(org_id=self.org.id, user_id=self.user.id, week_start=START, week_end=END)
        self.db.add(self.plan)
        self.db.flush()
        self.db.add_all([WeeklyTaskPlanItem(weekly_task_plan_id=self.plan.id, task_id=t.id) for t in (self.overdue, self.due, self.blocked, self.done, self.private)])
        self.db.add_all([
            Holiday(org_id=self.org.id, holiday_date=date(2026, 10, 7), name='Holiday'),
            Leave(user_id=self.user.id, leave_date=date(2026, 10, 9), leave_type=LeaveType.FULL),
            Leave(user_id=self.user.id, leave_date=date(2026, 10, 6), leave_type=LeaveType.HALF_AM),
            TimeLog(task_id=self.overdue.id, user_id=self.user.id, log_date=START, hours=Decimal('2'), notes='Test work'),
        ])
        self.overdue.logged_hours = Decimal('2')
        self.db.commit()

    def task(self, code, end=TODAY, estimate=4, status=TaskStatus.NOT_STARTED, assigned=None):
        task = Task(org_id=self.org.id, task_id=code, project_id=self.project.id, activity_type_id=self.activity.id,
                    created_by=self.user.id, assigned_to=assigned or self.user.id, name='Task ' + code,
                    start_date=date(2026, 10, 1), end_date=end, status=status, estimated_hours=estimate)
        self.db.add(task)
        self.db.flush()
        return task

    def tearDown(self):
        self.db.close()
        with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(table.delete())

    def payload(self):
        with patch('app.main.local_today', return_value=TODAY):
            groups = dashboard_payload(self.db, self.org, self.user)
        days = week_allocation_summary(self.db, self.org.id, self.user.id, START, END)
        return build_employee_dashboard(self.db, self.org, self.user, groups, days, TODAY)

    def test_personal_queue_deduplicates_groups_and_respects_plan_and_scope(self):
        result = self.payload()
        self.assertEqual([task['task_id'] for task in result['focus']], ['APP1', 'APP2'])
        self.assertEqual(result['counts'], {'today': 2, 'week': 3, 'blocked': 1, 'completed': 1, 'all': 5})
        self.assertEqual((result['plan_total'], result['plan_completed']), (4, 1))
        self.assertEqual(result['estimated_work'], 9)
        self.assertEqual(result['unknown_estimates'], 1)
        self.assertNotIn('PRIVATE', [task['task_id'] for task in result['queue']])
        self.assertTrue(all(task['project_name'] == 'People platform' for task in result['queue']))

    def test_capacity_respects_holiday_half_leave_and_only_past_day_gaps(self):
        result = self.payload()
        self.assertEqual(result['available_hours'], 20)
        self.assertEqual(result['remaining_available_hours'], 8)
        self.assertEqual([(day['date'], day['gap_hours']) for day in result['gap_days']], [(START, 6), (date(2026, 10, 6), 4)])
        self.assertEqual(result['attention_count'], 3)

    def test_empty_weekend_configuration_is_respected(self):
        self.settings.weekend_days = []
        self.db.commit()
        result = self.payload()
        self.assertEqual(result['available_hours'], 36)
        self.assertEqual(result['remaining_available_hours'], 24)

    def test_more_than_twelve_completions_have_correct_counts(self):
        for i in range(14):
            task = self.task(f'DONE{i}', status=TaskStatus.CLOSED)
            task.closed_at = datetime(2026, 10, 6, 18)
        self.db.commit()
        self.assertEqual(self.payload()['counts']['completed'], 15)

    def test_shared_work_cannot_be_presented_as_final_completion(self):
        self.due.is_shared = True
        self.due.created_by = self.manager.id
        self.db.commit()
        task = next(task for task in self.payload()['queue'] if task['task_id'] == 'APP2')
        self.assertFalse(task['can_complete'])

    def test_main_dashboard_renders_without_contacting_zoho(self):
        with patch('app.main.local_today', return_value=TODAY), patch('app.main.zoho_profile_attendance_feed', side_effect=AssertionError('Core page must not call Zoho')):
            response = dashboard(request=SimpleNamespace(url=SimpleNamespace(path='/example/dashboard')), org_user=(self.org, self.user), db=self.db)
        html = response.body.decode()
        self.assertIn('Your day, in focus.', html)
        self.assertIn('data-work-dashboard', html)
        self.assertIn('data-dashboard-daylog-form data-log-hours-form', html)
        self.assertNotIn('PRIVATE', html)
        self.assertNotIn('dashboard-visibility-toggles', html)
        # A single queue row per assignment, not copies in each view.
        self.assertEqual(html.count('data-work-task data-work-views='), 5)

    def feed(self):
        return {'status': 'synced', 'office_days': 1, 'remote_days': 0, 'total_days': 1, 'rows': [
            {'date': date(2026, 10, 1), 'first_in_label': '10:00 AM', 'last_out_label': '07:00 PM',
             'mode': 'office', 'mode_label': 'Office', 'attendance_source': 'Terminal', 'attendance_location': 'Office', 'is_open': False}
        ]}

    def leave_result(self):
        return ZohoLeaveListResult(status='synced', leaves=(
            {'employee_zoho_id': self.user.zoho_employee_id, 'approval_status': 'Approved', 'leave_type_name': 'Earned Leave',
             'start_date': date(2026, 10, 2), 'end_date': date(2026, 10, 2), 'day_counts': ((date(2026, 10, 2), 1),)},
            {'employee_zoho_id': self.user.zoho_employee_id, 'approval_status': 'Approved', 'leave_type_name': 'Earned Leave',
             'start_date': date(2026, 10, 6), 'end_date': date(2026, 10, 6), 'day_counts': ((date(2026, 10, 6), .5),)},
            {'employee_zoho_id': self.user.zoho_employee_id, 'approval_status': 'Approved', 'leave_type_name': 'Earned Leave',
             'start_date': date(2026, 10, 9), 'end_date': date(2026, 10, 9), 'day_counts': ((date(2026, 10, 9), 1),)},
            {'employee_zoho_id': self.user.zoho_employee_id, 'approval_status': 'Approved', 'leave_type_name': 'Work from home',
             'start_date': TODAY, 'end_date': TODAY, 'day_counts': ((TODAY, 1),)},
        ))

    def test_attendance_gaps_exclude_full_leave_holidays_and_pending_requests(self):
        self.db.add(AttendanceRegularization(org_id=self.org.id, user_id=self.user.id, manager_id=self.manager.id, attendance_date=START, status='pending'))
        self.db.commit()
        result = personal_attendance_summary(self.db, self.org, self.user, self.feed(), self.leave_result(), TODAY, datetime(2026, 10, 8, 12))
        self.assertEqual(result['missing_dates'], ['2026-10-06'])
        self.assertEqual(result['pending_count'], 1)
        self.assertEqual(result['available_hours'], 20)
        self.assertEqual(result['remaining_available_hours'], 8)
        self.assertIsNone(result['today'])

    def test_unknown_leave_status_never_creates_absence_warning(self):
        result = personal_attendance_summary(self.db, self.org, self.user, self.feed(), ZohoLeaveListResult(status='failed'), TODAY, datetime(2026, 10, 8, 12))
        self.assertEqual(result['missing_count'], 0)
        self.assertIsNone(result['available_hours'])

    def test_attendance_endpoint_is_self_scoped_and_uses_cache(self):
        with patch('app.main.local_today', return_value=TODAY), patch('app.main.source_cache', DashboardSourceCache()), \
             patch('app.main.zoho_profile_attendance_feed', return_value=self.feed()) as attendance, \
             patch('app.main.fetch_zoho_leave_requests', return_value=self.leave_result()) as leave:
            for _ in range(2):
                response = dashboard_attendance(org_user=(self.org, self.user), db=self.db)
            result = json.loads(response.body)
        self.assertEqual(attendance.call_count, 1)
        self.assertEqual(leave.call_count, 1)
        self.assertEqual(leave.call_args.kwargs['employee_zoho_ids'], ['record-105'])
        self.assertEqual(result['status'], 'synced')
        self.assertEqual(response.headers['cache-control'], 'private, no-store')

    def test_regularization_rejects_approved_full_day_leave_and_creates_no_request(self):
        with patch('app.main.local_today', return_value=TODAY), patch('app.main.zoho_profile_attendance_feed', return_value={'status': 'synced', 'rows': []}), \
             patch('app.main.fetch_zoho_leave_requests', return_value=self.leave_result()), patch('app.main.send_email') as email:
            with self.assertRaises(HTTPException) as error:
                request_attendance_regularization('example', date(2026, 10, 2), (self.org, self.user), self.db)
        self.assertEqual(error.exception.status_code, 409)
        self.assertIsNone(self.db.scalar(select(AttendanceRegularization)))
        email.assert_not_called()

    def test_remote_request_is_pending_and_notifies_manager_only_after_validating(self):
        with patch('app.main.local_today', return_value=TODAY), patch('app.main.zoho_profile_attendance_feed', return_value={'status': 'synced', 'rows': []}), \
             patch('app.main.fetch_zoho_leave_requests', return_value=ZohoLeaveListResult(status='synced')), patch('app.main.send_email') as email:
            response = dashboard_request_regularization('example', START, (self.org, self.user), self.db)
            with self.assertRaises(HTTPException):
                dashboard_request_regularization('example', START, (self.org, self.user), self.db)
        record = self.db.scalar(select(AttendanceRegularization))
        self.assertEqual((record.status, record.location, record.manager_id), ('pending', 'remote', self.manager.id))
        self.assertEqual(json.loads(response.body), {'status': 'pending'})
        self.assertEqual(email.call_count, 1)
        self.assertEqual(email.call_args.args[0], self.manager.email)

    def test_resume_requires_access_and_changes_only_blocked_work(self):
        with self.assertRaises(HTTPException):
            resume_task_page('example', 'PRIVATE', '', (self.org, self.manager), self.db)
        response = resume_task_page('example', 'APP3', '/example/dashboard', (self.org, self.user), self.db)
        self.assertEqual(response.status_code, 303)
        self.db.refresh(self.blocked)
        self.assertEqual(self.blocked.status, TaskStatus.STARTED)
        self.assertEqual(self.blocked.stalled_reason, '')
        with self.assertRaises(HTTPException):
            resume_task_page('example', 'APP3', '', (self.org, self.user), self.db)

    def test_dashboard_time_logs_reject_future_dates_and_nonpositive_hours(self):
        with patch('app.main.local_today', return_value=TODAY):
            for log_date, hours in [(TODAY + __import__('datetime').timedelta(days=1), Decimal('1')), (TODAY, Decimal('0'))]:
                with self.assertRaises(HTTPException):
                    add_time_log_page('example', 'APP1', log_date, hours, 'Detailed notes. ' * 8, False, '', (self.org, self.user), self.db)


class SourceCacheTests(unittest.TestCase):
    def test_cache_is_scoped_copied_and_invalidatable(self):
        cache = DashboardSourceCache()
        calls = []
        def loader():
            calls.append(1)
            return {'status': 'synced', 'rows': []}, ZohoLeaveListResult(status='synced')
        first = cache.get((1, 2, 'mapped', TODAY), loader)
        first[0]['rows'].append('mutation')
        self.assertEqual(cache.get((1, 2, 'mapped', TODAY), loader)[0]['rows'], [])
        cache.get((1, 3, 'mapped', TODAY), loader)
        self.assertEqual(len(calls), 2)
        cache.invalidate(1, 2)
        cache.get((1, 2, 'mapped', TODAY), loader)
        self.assertEqual(len(calls), 3)


if __name__ == '__main__':
    unittest.main()
