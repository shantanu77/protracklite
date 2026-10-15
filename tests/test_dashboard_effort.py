import json
import os
import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

os.environ['DATABASE_URL'] = 'sqlite+pysqlite:///:memory:'
os.environ['USER_CONTENT_DIR'] = '/tmp/protracklite-test-user-content'

from fastapi import HTTPException
from sqlalchemy import func, select
from app.database import Base, engine, SessionLocal
from app.main import dashboard, dashboard_day_effort, dashboard_update_effort, effort_entry_revision, update_time_log_page
from app.models import ActivityType, Organization, OrgSettings, Project, Role, Task, TaskComment, TaskStatus, TimeLog, User
from app.reports import week_allocation_summary
from starlette.requests import Request

TODAY = date(2026, 10, 15)
WEDNESDAY = date(2026, 10, 14)
PREVIOUS_WEEK = date(2026, 10, 7)
NOTES = 'Implemented the data integration and verified the mappings with the client team. Completed regression checks.'
if engine.dialect.name != 'sqlite':
    raise RuntimeError('Tests require isolated SQLite.')


class DashboardEffortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(engine)

    def setUp(self):
        self.db = SessionLocal()
        self.org = Organization(name='Example', slug='example')
        self.other_org = Organization(name='Other organisation', slug='other')
        self.db.add_all([self.org, self.other_org])
        self.db.flush()
        self.user = User(org_id=self.org.id, email='owner@example.com', full_name='Owner', password_hash='test')
        self.manager = User(org_id=self.org.id, email='manager@example.com', full_name='Manager', password_hash='test', role=Role.MANAGER)
        self.outsider = User(org_id=self.other_org.id, email='outsider@example.com', full_name='Outsider', password_hash='test')
        self.activity = ActivityType(org_id=self.org.id, code='DEV', name='Development')
        self.db.add_all([self.user, self.manager, self.outsider, self.activity, OrgSettings(org_id=self.org.id, weekend_days=[5, 6], work_hours_per_day=Decimal('8'))])
        self.db.flush()
        self.project = Project(org_id=self.org.id, code='PL', name='Platform', created_by=self.user.id)
        self.db.add(self.project)
        self.db.flush()
        self.task = Task(org_id=self.org.id, task_id='PL1', name='Integration <script>', assigned_to=self.user.id, created_by=self.user.id, project_id=self.project.id, activity_type_id=self.activity.id, status=TaskStatus.CLOSED, start_date=date(2026, 10, 12), end_date=WEDNESDAY, closed_at=datetime(2026, 10, 14, 18), logged_hours=Decimal('10'))
        self.db.add(self.task)
        self.db.flush()
        self.log = TimeLog(task_id=self.task.id, user_id=self.user.id, log_date=WEDNESDAY, hours=Decimal('10'), notes=NOTES)
        self.db.add(self.log)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(table.delete())

    def read(self, day=WEDNESDAY):
        return json.loads(dashboard_day_effort(day, (self.org, self.user), self.db).body)

    def update(self, **changes):
        payload = dict(log_date=PREVIOUS_WEEK.isoformat(), hours='10', notes=NOTES, revision=effort_entry_revision(self.log))
        payload.update(changes)
        with patch('app.main.local_today', return_value=TODAY):
            return dashboard_update_effort(self.log.id, payload, (self.org, self.user), self.db)

    def test_day_breakdown_matches_total_and_contains_closed_tasks(self):
        self.db.add(TimeLog(task_id=self.task.id, user_id=self.user.id, log_date=WEDNESDAY, hours=Decimal('1.5'), notes='Second entry'))
        self.db.add(TimeLog(task_id=self.task.id, user_id=self.manager.id, log_date=WEDNESDAY, hours=Decimal('7'), notes='Private manager notes'))
        self.db.flush()
        data = self.read()
        self.assertEqual(data['total_hours'], 11.5)
        self.assertEqual(len(data['entries']), 2)
        self.assertEqual(data['entries'][0]['task_name'], 'Integration <script>')
        self.assertEqual(data['entries'][0]['status'], 'closed')
        self.assertNotIn('Private manager notes', str(data))
        self.assertEqual(dashboard_day_effort(WEDNESDAY, (self.org, self.user), self.db).headers['cache-control'], 'private, no-store')
        self.assertEqual(self.read(PREVIOUS_WEEK)['entries'], [])

    def test_move_to_last_week_updates_existing_entry_and_week_totals(self):
        response = self.update()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.log.log_date, PREVIOUS_WEEK)
        self.assertEqual(self.task.logged_hours, Decimal('10'))
        self.assertEqual(self.db.scalar(select(func.count()).select_from(TimeLog)), 1)
        self.assertEqual(self.read()['total_hours'], 0)
        self.assertEqual(self.read(PREVIOUS_WEEK)['total_hours'], 10)
        days = week_allocation_summary(self.db, self.org.id, self.user.id, date(2026, 10, 12), date(2026, 10, 18))
        last = week_allocation_summary(self.db, self.org.id, self.user.id, date(2026, 10, 5), date(2026, 10, 11))
        self.assertEqual(sum(d['hours'] for d in days), 0)
        self.assertEqual(sum(d['hours'] for d in last), 10)
        self.assertEqual(self.task.start_date, PREVIOUS_WEEK)
        self.assertEqual(self.task.status, TaskStatus.CLOSED)
        self.assertEqual(self.task.closed_at, datetime(2026, 10, 14, 18))
        self.assertIn('2026-10-14 (10h) → 2026-10-07 (10h)', self.db.scalar(select(TaskComment.body)))

    def test_update_hours_and_notes_recomputes_lifetime_total(self):
        self.db.add(TimeLog(task_id=self.task.id, user_id=self.manager.id, log_date=WEDNESDAY, hours=Decimal('2'), notes=NOTES))
        self.db.commit()
        self.update(hours='6.25', notes='  '+NOTES+'   More checks completed.  ')
        self.assertEqual(self.task.logged_hours, Decimal('8.25'))
        self.assertEqual(self.log.notes, NOTES+' More checks completed.')
        self.assertIn('Updated effort notes.', self.db.scalar(select(TaskComment.body)))

    def test_invalid_dates_hours_and_notes_leave_record_unchanged(self):
        for changes in [dict(log_date='2026-10-16'), dict(log_date='nonsense'), dict(hours='0'), dict(hours='-1'), dict(hours='NaN'), dict(hours='Infinity'), dict(hours='25'), dict(hours='1.234'), dict(hours='invalid'), dict(notes='Too short'), dict(notes=['Invalid'])]:
            with self.subTest(changes=changes):
                with self.assertRaises(HTTPException) as error:
                    self.update(**changes)
                self.assertEqual(error.exception.status_code, 400)
                self.assertEqual(self.log.log_date, WEDNESDAY)
                self.assertEqual(self.log.hours, Decimal('10'))
                self.assertEqual(self.log.notes, NOTES)
                self.assertEqual(self.db.scalar(select(func.count()).select_from(TaskComment)), 0)

    def test_other_users_and_organisations_cannot_read_or_change_entries(self):
        data = json.loads(dashboard_day_effort(WEDNESDAY, (self.org, self.manager), self.db).body)
        self.assertEqual(data['entries'], [])
        for identity in [(self.org, self.manager), (self.other_org, self.outsider), (self.other_org, self.user)]:
            with self.assertRaises(HTTPException) as error:
                dashboard_update_effort(self.log.id, {}, identity, self.db)
            self.assertEqual(error.exception.status_code, 404)
        self.assertEqual(self.log.log_date, WEDNESDAY)

    def test_stale_entry_is_rejected_and_legacy_notes_can_be_retained(self):
        with self.assertRaises(HTTPException) as error:
            self.update(revision='stale')
        self.assertEqual(error.exception.status_code, 409)
        self.log.notes = 'Imported note'
        self.db.commit()
        self.update(notes='Imported note')
        self.assertEqual(self.log.notes, 'Imported note')
        self.assertEqual(self.log.log_date, PREVIOUS_WEEK)

    def test_archived_entries_are_excluded_like_weekly_summary(self):
        self.task.is_archived = True
        self.db.commit()
        self.assertEqual(self.read()['total_hours'], 0)
        with self.assertRaises(HTTPException) as error:
            self.update()
        self.assertEqual(error.exception.status_code, 404)

    def test_own_historical_entry_remains_correctable_after_reassignment(self):
        self.task.assigned_to = self.manager.id
        self.db.commit()
        self.assertEqual(self.read()['total_hours'], 10)
        self.update()
        self.assertEqual(self.log.log_date, PREVIOUS_WEEK)

    def test_dashboard_renders_effort_controls_and_task_log_updates_validate(self):
        request = Request({'type': 'http', 'method': 'GET', 'path': '/example/dashboard', 'query_string': b'', 'headers': []})
        with patch('app.main.local_today', return_value=TODAY):
            html = dashboard(request, org_user=(self.org, self.user), db=self.db).body.decode()
            self.assertIn('data-work-effort-dialog', html)
            self.assertIn('View effort history', html)
            self.assertIn('View effort · 10h', html)
            for day, hours in [(date(2026, 10, 16), Decimal('2')), (WEDNESDAY, Decimal('0')), (WEDNESDAY, Decimal('NaN'))]:
                with self.assertRaises(HTTPException):
                    update_time_log_page('example', 'PL1', self.log.id, day, hours, NOTES, False, '', (self.org, self.user), self.db)
        self.assertEqual(self.log.log_date, WEDNESDAY)
