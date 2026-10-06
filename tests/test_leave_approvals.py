import os
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

os.environ['DATABASE_URL']='sqlite+pysqlite:///:memory:'
os.environ['USER_CONTENT_DIR']='/tmp/protracklite-test-user-content'

from fastapi import HTTPException
from sqlalchemy import select
from app.database import Base,SessionLocal,engine
from app.models import Organization,User,Role,LeaveApproval,CapacityZohoSnapshot
from app.zoho_people import ZohoLeaveListResult
from app.leave_approvals import apply_local_leave_approvals,saved_leave_requests,overlay_capacity_approval,capacity_local_approvals
from app.main import manager_approve_leave,team_member_month_feed,zoho_profile_leave_feed,manager_team_leaves_page
from app.capacity_sync import normalize_leave_days
from app.capacity import build_capacity_payload
from app.employee_dashboard import approved_absence_counts

if engine.dialect.name!='sqlite':raise RuntimeError('Tests must use isolated SQLite.')

class LocalLeaveApprovalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):Base.metadata.create_all(engine)

    def setUp(self):
        self.db=SessionLocal();self.org=Organization(name='Approvals',slug='approvals');self.db.add(self.org);self.db.flush()
        self.manager=User(org_id=self.org.id,email='manager@example.com',full_name='Manager',password_hash='test',role=Role.MANAGER,zoho_employee_id='manager')
        self.other=User(org_id=self.org.id,email='other@example.com',full_name='Other manager',password_hash='test',role=Role.MANAGER,zoho_employee_id='other')
        self.db.add_all([self.manager,self.other]);self.db.flush()
        self.member=User(org_id=self.org.id,email='member@example.com',full_name='Employee',password_hash='test',manager_id=self.manager.id,zoho_employee_id='employee')
        self.db.add(self.member);self.db.commit()
        self.raw={'zoho_leave_id':'request-1','employee_zoho_id':'employee','start_date':date(2026,10,8),'end_date':date(2026,10,9),
                  'day_counts':[(date(2026,10,8),1),(date(2026,10,9),1)],'day_dates':(date(2026,10,8),date(2026,10,9)),
                  'leave_days':2,'leave_type_name':'Earned Leave','leave_type_id':'annual','approval_status':'Pending',
                  'duration_label':'2 days','reason':'Family event'}
        self.result=ZohoLeaveListResult(status='synced',leaves=(self.raw,))
        apply_local_leave_approvals(self.db,self.org.id,[self.member],self.result)
        self.record=self.db.scalar(select(LeaveApproval))

    def tearDown(self):
        self.db.close()
        with engine.begin() as c:
            for table in reversed(Base.metadata.sorted_tables):c.execute(table.delete())

    def approve(self,manager=None,request_id=None,member_id=None):
        return manager_approve_leave(request_id=request_id or self.record.id,member_id=member_id or self.member.id,
                                     org_user=(self.org,manager or self.manager),db=self.db)

    def test_approval_is_local_audited_and_idempotent_without_any_zoho_call(self):
        with patch('httpx.get',side_effect=AssertionError('Approval must not call Zoho')),patch('httpx.post',side_effect=AssertionError('Approval must not call Zoho')):
            self.assertEqual(self.approve()['status'],'approved')
            stamp=self.record.approved_at
            self.assertEqual(self.approve()['status'],'approved')
        self.assertEqual(self.record.approved_at,stamp)
        self.assertEqual(self.record.approved_by,self.manager.id)
        with SessionLocal() as another_session:
            record=another_session.get(LeaveApproval,self.record.id)
            self.assertIsNotNone(record.approved_at)

    def test_role_reporting_scope_request_member_and_org_are_enforced(self):
        for manager in [self.other,self.member]:
            with self.assertRaises(HTTPException):self.approve(manager=manager)
        with self.assertRaises(HTTPException):self.approve(member_id=self.manager.id)
        with self.assertRaises(HTTPException):self.approve(request_id=self.record.id+100)
        self.assertIsNone(self.record.approved_at)
        other_org=Organization(name='Other',slug='other-approvals');self.db.add(other_org);self.db.flush()
        self.record.org_id=other_org.id;self.db.commit()
        with self.assertRaises(HTTPException):self.approve()

    def test_cancelled_or_already_source_approved_request_cannot_be_approved(self):
        for status in ['CANCELLED','REJECTED','APPROVED']:
            self.record.source_status=status;self.db.commit()
            with self.assertRaises(HTTPException) as exc:self.approve()
            self.assertEqual(exc.exception.status_code,409)

    def test_resync_pending_cannot_undo_local_approval_and_capacity_reflects_it(self):
        normalized=apply_local_leave_approvals(self.db,self.org.id,[self.member],self.result)
        snapshot=CapacityZohoSnapshot(org_id=self.org.id,year=2026,month=10,synced_at=__import__('datetime').datetime(2026,10,1),
            member_ids_json=[self.member.id],leave_days_json=normalize_leave_days(normalized.leaves,[self.member],date(2026,10,1),date(2026,10,31)))
        self.db.add(snapshot);self.db.commit();stamp=snapshot.synced_at
        self.approve()
        refreshed=apply_local_leave_approvals(self.db,self.org.id,[self.member],self.result)
        self.assertEqual(refreshed.leaves[0]['approval_status'],'Approved')
        self.assertFalse(refreshed.leaves[0]['can_approve'])
        report=build_capacity_payload(self.db,self.org,[self.member],anchor=date(2026,10,1),zoho_snapshots={(2026,10):snapshot})
        segment=next(s for s in report['rows'][0]['segments'] if s['status']=='planned')
        self.assertEqual(segment['approval'],'Approved');self.assertEqual(snapshot.synced_at,stamp)
        self.assertEqual(approved_absence_counts(refreshed,'employee')[date(2026,10,8)],1)

    def test_older_saved_capacity_snapshot_reflects_local_approval_without_resync(self):
        normalized=normalize_leave_days((self.raw,),[self.member],date(2026,10,1),date(2026,10,31))
        old_entry={key:value for key,value in normalized[0].items() if key not in {'zoho_leave_id','request_fingerprint'}}
        self.approve()
        records=capacity_local_approvals(self.db,self.org.id)
        self.assertEqual(overlay_capacity_approval(old_entry,records)['approval'],'Approved')
        other={**old_entry,'type':'Sick leave'}
        self.assertEqual(overlay_capacity_approval(other,records)['approval'],'PENDING')

    def test_changed_request_requires_new_review(self):
        self.approve()
        changed={**self.raw,'end_date':date(2026,10,10),'leave_days':3,'day_counts':self.raw['day_counts']+[(date(2026,10,10),1)]}
        result=apply_local_leave_approvals(self.db,self.org.id,[self.member],ZohoLeaveListResult(status='synced',leaves=(changed,)))
        self.assertEqual(result.leaves[0]['approval_status'],'Pending');self.assertTrue(result.leaves[0]['can_approve'])

    def test_manager_and_employee_feeds_show_local_approval(self):
        self.approve()
        with patch('app.main.fetch_zoho_leave_requests',return_value=self.result),patch('app.main.zoho_profile_attendance_feed',return_value={'status':'failed'}):
            feed=team_member_month_feed(self.db,self.member,date(2026,10,1),date(2026,10,31),date(2026,10,6))
            own=zoho_profile_leave_feed(self.db,self.member,[],date(2026,10,6))
        self.assertEqual(feed['approved_days'],2);self.assertEqual(feed['pending_days'],0)
        self.assertEqual(feed['leaves'][0]['approval_source'],'ProTrack')
        self.assertEqual(own['mine'][0]['approval_status'],'Approved')

    def test_approval_and_saved_feed_work_when_zoho_is_unavailable(self):
        self.approve()
        with patch('app.main.fetch_zoho_leave_requests',return_value=ZohoLeaveListResult(status='failed')),patch('app.main.zoho_profile_attendance_feed',return_value={'status':'failed'}):
            feed=team_member_month_feed(self.db,self.member,date(2026,10,1),date(2026,10,31),date(2026,10,6))
        self.assertEqual(feed['approved_days'],2)
        self.assertEqual(feed['leaves'][0]['approval_source'],'ProTrack')
        self.assertIn('saved',feed['leave_message'])

    def test_review_popup_approves_here_without_external_links(self):
        request=SimpleNamespace(url=SimpleNamespace(path='/approvals/manager/team-leaves'))
        with patch('app.main.fetch_zoho_leave_requests',return_value=self.result),patch('app.main.zoho_profile_attendance_feed',return_value={'status':'failed','message':'Unavailable','rows':[]}),patch('app.main.local_today',return_value=date(2026,10,6)):
            response=manager_team_leaves_page(request=request,member_id=self.member.id,month='2026-10',org_user=(self.org,self.manager),db=self.db)
        html=response.body.decode()
        self.assertIn('data-leave-approve-form',html);self.assertIn('data-request-id=',html)
        self.assertNotIn('Approve in Zoho',html);self.assertNotIn('Open Zoho approvals',html)
