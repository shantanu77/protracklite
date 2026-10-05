import os
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

os.environ['DATABASE_URL'] = 'sqlite+pysqlite:///:memory:'
os.environ['USER_CONTENT_DIR'] = '/tmp/protracklite-test-user-content'

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select
from app.database import Base, SessionLocal, engine
from app.capacity import build_capacity_payload
from app.capacity_sync import capacity_snapshots, capacity_sync_status, normalize_leave_days, run_capacity_sync, start_capacity_sync, sync_capacity_snapshots
from app.main import manager_capacity_page, manager_capacity_sync
from app.models import CapacityZohoSnapshot, Leave, Organization, Role, User
from app.zoho_people import ZohoEmployeeDirectoryResult, ZohoLeaveListResult

if engine.dialect.name != 'sqlite':
    raise RuntimeError('Tests must use isolated SQLite.')
START, END = date(2026, 10, 1), date(2026, 10, 31)


class CapacitySyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(engine)

    def setUp(self):
        self.db = SessionLocal()
        self.org = Organization(name='Shared capacity', slug='shared-capacity')
        self.db.add(self.org); self.db.flush()
        self.manager = User(org_id=self.org.id, email='manager@example.com', full_name='Manager', role=Role.MANAGER, password_hash='test', zoho_employee_id='manager-zoho')
        self.db.add(self.manager); self.db.flush()
        self.employee = User(org_id=self.org.id, email='employee@example.com', full_name='Employee', password_hash='test', manager_id=self.manager.id, zoho_employee_id='employee-zoho')
        self.db.add(self.employee); self.db.commit()

    def tearDown(self):
        self.db.close()
        with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())

    def leave(self, **changes):
        raw = {'employee_zoho_id': 'employee-zoho', 'approval_status': 'APPROVED', 'leave_type_name': 'Annual leave',
               'leave_type_id': 'annual', 'start_date': date(2026,10,6), 'end_date': date(2026,10,6),
               'day_counts': [(date(2026,10,6),1)], 'leave_days': 1}
        raw.update(changes); return raw

    def sync(self, leaves=None, start=START, end=END):
        with patch('app.capacity_sync.fetch_zoho_leave_requests', return_value=ZohoLeaveListResult(status='synced', leaves=tuple(leaves if leaves is not None else [self.leave()]))) as fetch_leave:
            stamp = sync_capacity_snapshots(self.db,self.org.id,start,end)
            return stamp, fetch_leave

    def report(self, people=None, anchor=START, view='month'):
        from app.capacity import capacity_period
        start,end,_,_=capacity_period(view,anchor)
        return build_capacity_payload(self.db,self.org,people or [self.employee],anchor=anchor,view=view,
            today=date(2026,10,1),zoho_snapshots=capacity_snapshots(self.db,self.org.id,start,end))

    def test_sync_is_global_persistent_and_reads_do_not_fetch(self):
        stamp, leave_fetch = self.sync()
        self.assertEqual(set(leave_fetch.call_args.kwargs['employee_zoho_ids']), {'manager-zoho','employee-zoho'})
        with SessionLocal() as another_viewer:
            snapshots=capacity_snapshots(another_viewer,self.org.id,START,END)
            self.assertEqual(snapshots[(2026,10)].synced_at,stamp)
            self.assertEqual(set(snapshots[(2026,10)].member_ids_json),{self.manager.id,self.employee.id})
        with patch('app.capacity_sync.fetch_zoho_leave_requests',side_effect=AssertionError('Read must not fetch')):
            report=self.report()
        self.assertEqual(report['leave_entry_count'],1)
        self.db.add(Leave(user_id=self.employee.id,leave_date=date(2026,10,7)));self.db.commit()
        self.assertEqual(self.report()['leave_entry_count'],1)

    def test_failed_leave_sync_does_not_replace_previous_data_or_time(self):
        stamp,_=self.sync()
        with patch('app.capacity_sync.fetch_zoho_leave_requests',return_value=ZohoLeaveListResult(status='failed')):
            with self.assertRaises(HTTPException): sync_capacity_snapshots(self.db,self.org.id,START,END)
        self.db.rollback()
        saved=capacity_snapshots(self.db,self.org.id,START,END)[(2026,10)]
        self.assertEqual(saved.synced_at,stamp);self.assertEqual(len(saved.leave_days_json),1)

    def test_multi_month_failure_is_atomic(self):
        start,end=date(2026,10,26),date(2026,11,8)
        self.sync(start=start,end=end)
        before={key:s.synced_at for key,s in capacity_snapshots(self.db,self.org.id,start,end).items()}
        with patch('app.capacity_sync.fetch_zoho_leave_requests',side_effect=[ZohoLeaveListResult(status='synced'),ZohoLeaveListResult(status='failed')]):
            with self.assertRaises(HTTPException): sync_capacity_snapshots(self.db,self.org.id,start,end)
        self.db.rollback()
        after={key:s.synced_at for key,s in capacity_snapshots(self.db,self.org.id,start,end).items()}
        self.assertEqual(before,after)

    def test_explicit_resync_replaces_cancelled_leave(self):
        self.sync();self.sync(leaves=[self.leave(approval_status='CANCELLED')])
        self.assertEqual(self.report()['leave_entry_count'],0)

    def test_unsynced_period_and_unmapped_employee_are_unconfirmed(self):
        report=self.report()
        self.assertIn('unknown',{s['status'] for s in report['rows'][0]['segments']})
        self.employee.zoho_employee_id='';self.db.commit()
        with patch('app.capacity_sync.fetch_zoho_employee_ids',return_value=ZohoEmployeeDirectoryResult(status='synced')):
            self.sync()
        self.assertIn('unknown',{s['status'] for s in self.report()['rows'][0]['segments']})

    def test_remote_is_not_absence_and_pending_leave_is_shown(self):
        self.sync(leaves=[self.leave(leave_type_name='Work from home'), self.leave(approval_status='PENDING',day_counts=[(date(2026,10,8),.5)])])
        report=self.report();self.assertEqual(report['leave_entry_count'],1)
        segment=next(s for s in report['rows'][0]['segments'] if s['status']=='planned')
        self.assertIn('PENDING',segment['title']);self.assertIn('0.5',segment['title'])

    def test_org_and_member_scope_do_not_leak(self):
        self.sync()
        other=Organization(name='Other',slug='other-capacity');self.db.add(other);self.db.commit()
        self.assertIsNone(capacity_snapshots(self.db,other.id,START,END)[(2026,10)])
        self.assertEqual(self.report([self.manager])['leave_entry_count'],0)

    def test_cross_month_sprint_uses_independent_saved_months(self):
        self.sync(start=date(2026,10,26),end=date(2026,11,8))
        snapshots=capacity_snapshots(self.db,self.org.id,date(2026,10,26),date(2026,11,8))
        self.assertEqual(set(snapshots),{(2026,10),(2026,11)})
        self.assertTrue(all(s is not None for s in snapshots.values()))

    def test_sync_job_deduplicates_and_reports_failure_without_losing_snapshot(self):
        self.sync();stamp=start_capacity_sync(self.db,self.org.id)
        with self.assertRaises(HTTPException) as exc: start_capacity_sync(self.db,self.org.id)
        self.assertEqual(exc.exception.status_code,409)
        with patch('app.capacity_sync.sync_capacity_snapshots',side_effect=HTTPException(503,'Zoho unavailable')):
            run_capacity_sync(self.org.id,START,END,stamp)
        self.db.expire_all()
        self.assertEqual(capacity_sync_status(self.db,self.org.id)['status'],'failed')
        self.assertIsNotNone(capacity_snapshots(self.db,self.org.id,START,END)[(2026,10)])

    def test_job_completion_handles_database_second_precision(self):
        stamp=start_capacity_sync(self.db,self.org.id)
        self.assertEqual(stamp.microsecond,0)
        with patch('app.capacity_sync.sync_capacity_snapshots'):
            run_capacity_sync(self.org.id,START,END,stamp)
        self.db.expire_all()
        self.assertEqual(capacity_sync_status(self.db,self.org.id)['status'],'done')

    def test_employee_cannot_trigger_manager_sync(self):
        with self.assertRaises(HTTPException) as exc:
            manager_capacity_sync(BackgroundTasks(),view='month',anchor=START.isoformat(),org_user=(self.org,self.employee),db=self.db)
        self.assertEqual(exc.exception.status_code,403)

    def test_template_has_saved_timestamp_and_no_green_availability_marks(self):
        self.sync()
        request=SimpleNamespace(url=SimpleNamespace(path='/shared-capacity/manager/capacity'))
        with patch('app.main.local_today',return_value=START):
            html=manager_capacity_page(request=request,view='month',scope='team',anchor=START.isoformat(),org_user=(self.org,self.manager),db=self.db).body.decode()
        self.assertIn('<body class="capacity-page">',html)
        self.assertIn('Sync with Zoho',html);self.assertIn('Last synced',html)
        self.assertIn('capacity-status-bar is-planned',html);self.assertNotIn('capacity-status-bar is-available',html)
        self.assertNotIn('Active / Available',html)

    def test_half_days_and_rejected_or_remote_leave(self):
        entries=normalize_leave_days([self.leave(day_counts=[(date(2026,10,6),.5)]),self.leave(approval_status='REJECTED'),
            self.leave(leave_type_name='Remote',day_counts=[(date(2026,10,8),1)])],[self.employee],START,END)
        self.assertEqual(len(entries),1);self.assertEqual(entries[0]['count'],.5)
