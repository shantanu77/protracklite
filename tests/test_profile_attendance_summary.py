import os
os.environ['DATABASE_URL']='sqlite+pysqlite:///:memory:'
os.environ['USER_CONTENT_DIR']='/tmp/protracklite-test-user-content'
import unittest
from datetime import date
from decimal import Decimal
from sqlalchemy import select
from app.database import Base, SessionLocal, engine
from app.models import Organization, User, OrgSettings, Leave, LeaveType, LeaveApproval, AttendanceRegularization, Holiday
from app.profile_attendance import profile_attendance_summary
DAY=date(2026,10,16)
if engine.dialect.name != 'sqlite': raise RuntimeError('Isolated database required')
class ProfileAttendanceSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): Base.metadata.create_all(engine)
    def setUp(self):
        self.db=SessionLocal();self.org=Organization(name='Example',slug='example');self.db.add(self.org);self.db.flush()
        self.user=User(org_id=self.org.id,email='owner@example.com',full_name='Owner',password_hash='test');self.db.add(self.user)
        self.db.add(OrgSettings(org_id=self.org.id,weekend_days=[5,6],work_hours_per_day=Decimal('8')));self.db.flush()
    def tearDown(self):
        self.db.close()
        with engine.begin() as conn:
            for t in reversed(Base.metadata.sorted_tables): conn.execute(t.delete())
    def record(self,ident,day,count=1,status='APPROVED',name='Annual leave'):
        self.db.add(LeaveApproval(org_id=self.org.id,user_id=self.user.id,zoho_leave_id=ident,fingerprint=ident,source_status=status,request_json={'start_date':day,'end_date':day,'day_counts':[[day,count]],'leave_type_name':name}))
        self.db.flush()
    def summary(self,attendance=None):
        self.db.flush();return profile_attendance_summary(self.db,self.org.id,self.user.id,attendance or {'status':'synced','rows':[]},DAY)
    def test_counts_actual_applied_leave_not_future_unmarked_days(self):
        self.record('a','2026-10-12');self.record('b','2026-10-20',.5,'PENDING');self.record('c','2026-10-13',status='CANCELLED');self.record('d','2026-10-14',name='Work from home')
        result=self.summary()
        self.assertEqual(result['applied_leave'],1.5);self.assertEqual(result['approved_leave'],1);self.assertEqual(result['pending_leave'],.5)
        self.assertTrue(all(row['date'] < DAY for row in result['missing_days']))
        self.assertNotIn(date(2026,10,12),[r['date'] for r in result['missing_days']])
        # Oct 1–15 has 11 weekdays; approved leave removes one.
        self.assertEqual(result['unmarked'],10)
    def test_half_days_holidays_local_duplicates_and_pending_requests(self):
        self.record('a','2026-10-12',.5)
        self.db.add_all([Leave(user_id=self.user.id,leave_date=date(2026,10,12),zoho_leave_id='a'),Leave(user_id=self.user.id,leave_date=date(2026,10,20),leave_type=LeaveType.HALF_AM),Holiday(org_id=self.org.id,holiday_date=date(2026,10,14),name='Holiday'),AttendanceRegularization(org_id=self.org.id,user_id=self.user.id,manager_id=self.user.id,attendance_date=date(2026,10,13),status='pending')])
        result=self.summary();self.assertEqual(result['applied_leave'],1);self.assertEqual(result['unmarked'],9.5)
        row=next(r for r in result['missing_days'] if r['date']==date(2026,10,13));self.assertEqual(row['request'].status,'pending')
    def test_approved_regularization_and_marked_days_not_missing(self):
        self.db.add(AttendanceRegularization(org_id=self.org.id,user_id=self.user.id,manager_id=self.user.id,attendance_date=date(2026,10,12),status='approved'))
        attendance={'status':'synced','rows':[{'date':date(2026,10,13),'first_in_label':'10 AM','last_out_label':'—','mode':'office','office_count':1,'remote_count':0}]}
        result=self.summary(attendance);self.assertEqual(result['unmarked'],9);self.assertEqual(attendance['total_days'],2);self.assertEqual(attendance['remote_days'],1)
    def test_source_failure_does_not_invent_missing_days(self):
        self.record('a','2026-10-12');result=self.summary({'status':'failed','rows':[]})
        self.assertIsNone(result['unmarked']);self.assertEqual(result['applied_leave'],1);self.assertEqual(result['missing_days'],[])

    def test_profile_renders_separate_leave_and_red_unmarked_action(self):
        from unittest.mock import patch
        from starlette.requests import Request
        from app.main import profile_page
        request=Request({'type':'http','method':'GET','path':'/example/profile','query_string':b'','headers':[]})
        attendance={'status':'synced','rows':[],'office_days':0,'remote_days':0,'total_days':0,'message':'Loaded','range_label':'October'}
        with patch('app.main.local_today',return_value=DAY), patch('app.main.zoho_profile_attendance_feed',return_value=attendance):
            response=profile_page(request,org_user=(self.org,self.user),db=self.db)
        html=response.body.decode()
        self.assertIn('🌴 Applied leave',html)
        self.assertIn('class="is-unmarked"',html)
        self.assertIn('data-open-profile-regularization',html)
        self.assertIn('id="profile-regularization"',html)
        self.assertNotIn('Total leave / unmarked days',html)
