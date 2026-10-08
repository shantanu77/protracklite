import os
os.environ['DATABASE_URL']='sqlite+pysqlite:///:memory:'
os.environ['USER_CONTENT_DIR']='/tmp/protracklite-test-user-content'
import unittest
from datetime import date, datetime
from unittest.mock import patch
from fastapi import HTTPException
from app.database import Base, SessionLocal, engine
from app.models import Organization, User, TodayPeopleSnapshot
from app.today_people import payload, start_sync, run_sync, collect_people
from app.zoho_people import ZohoAttendanceResult, ZohoLeaveListResult
DAY=date(2026,10,8)
if engine.dialect.name != 'sqlite': raise RuntimeError('Isolated tests only')
class TodayPeopleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): Base.metadata.create_all(engine)
    def setUp(self):
        self.db=SessionLocal(); self.org=Organization(name='People',slug='people'); self.db.add(self.org); self.db.flush()
        self.user=User(org_id=self.org.id,email='person@example.com',full_name='Person',password_hash='test',zoho_employee_id='123'); self.db.add(self.user); self.db.commit()
    def tearDown(self):
        self.db.close()
        with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables): conn.execute(table.delete())
    def test_shared_and_scoped_daily_saved_data(self):
        self.db.add(TodayPeopleSnapshot(org_id=self.org.id,day=DAY,synced_at=datetime.utcnow(),people_json=[{'user_id':self.user.id,'office':True,'leave':False}],status='done')); self.db.commit()
        with SessionLocal() as viewer:
            self.assertEqual(len(payload(viewer,self.org.id,DAY)['people']),1)
            self.assertEqual(payload(viewer,999,DAY)['people'],[])
            self.assertEqual(payload(viewer,self.org.id,date(2026,10,9))['people'],[])
    def test_concurrency_and_failure_keep_saved_data(self):
        stamp=start_sync(self.db,self.org.id,DAY)
        with self.assertRaises(HTTPException): start_sync(self.db,self.org.id,DAY)
        row=self.db.query(TodayPeopleSnapshot).one(); row.synced_at=datetime.utcnow(); row.people_json=[{'user_id':self.user.id,'office':True,'leave':False}]; self.db.commit()
        with patch('app.today_people.collect_people',side_effect=RuntimeError()): run_sync(self.org.id,DAY,stamp)
        self.db.expire_all(); result=payload(self.db,self.org.id,DAY)
        self.assertEqual(result['status'],'failed'); self.assertEqual(len(result['people']),1); self.assertTrue(result['synced_at'])
    def test_actual_office_only(self):
        for mode,punch,count in [('office',datetime(2026,10,8,10),1),('remote',datetime(2026,10,8,10),0),('unknown',datetime(2026,10,8,10),0),('office',None,0)]:
            with patch('app.today_people.fetch_zoho_attendance_entries',return_value=ZohoAttendanceResult(status='synced',entries=({'attendance_date':DAY,'work_mode':mode,'first_in':punch},))), patch('app.today_people.fetch_zoho_leave_requests',return_value=ZohoLeaveListResult(status='synced')):
                self.assertEqual(len(collect_people(self.db,self.org.id,DAY)[0]),count)
    def test_half_day_and_pending(self):
        raw={'employee_zoho_id':'123','approval_status':'APPROVED','leave_type_name':'Annual','start_date':DAY,'end_date':DAY,'day_counts':[(DAY,0.5)],'day_sessions':[(DAY,1)],'leave_days':0.5}
        def collect():
            with patch('app.today_people.fetch_zoho_attendance_entries',return_value=ZohoAttendanceResult(status='synced')), patch('app.today_people.fetch_zoho_leave_requests',return_value=ZohoLeaveListResult(status='synced',leaves=(raw,))): return collect_people(self.db,self.org.id,DAY)[0]
        self.assertEqual(collect()[0]['leave_count'],0.5); self.assertEqual(collect()[0]['session'],1)
        raw['approval_status']='PENDING'; self.assertEqual(collect(),[])
    def test_live_punch_uses_signed_in_user_and_server_time(self):
        from app.main import dashboard_live_punch
        from app.zoho_people import ZohoLeaveResult
        moment=datetime(2026,10,8,10,30)
        before=ZohoAttendanceResult(status='synced')
        after=ZohoAttendanceResult(status='synced',entries=({'attendance_date':DAY,'first_in':moment,'work_mode':'remote'},))
        with patch('app.main.local_now',return_value=moment), patch('app.main.fetch_zoho_attendance_entries',side_effect=[before,after]), patch('app.zoho_people.record_zoho_live_punch',return_value=ZohoLeaveResult(status='submitted')) as send:
            result=dashboard_live_punch('in',(self.org,self.user),self.db)
        self.assertIn('check-in recorded',result['message'])
        self.assertEqual(send.call_args.kwargs,{'employee_email':self.user.email,'moment':moment,'action':'in'})
    def test_live_punch_does_not_write_duplicate_or_invalid_checkout(self):
        from app.main import dashboard_live_punch
        current=ZohoAttendanceResult(status='synced',entries=({'attendance_date':DAY,'first_in':datetime(2026,10,8,10),'last_out':datetime(2026,10,8,19)},))
        with patch('app.main.local_now',return_value=datetime(2026,10,8,20)), patch('app.main.fetch_zoho_attendance_entries',return_value=current), patch('app.zoho_people.record_zoho_live_punch') as send:
            self.assertIn('already recorded',dashboard_live_punch('in',(self.org,self.user),self.db)['message'])
            with self.assertRaises(HTTPException): dashboard_live_punch('out',(self.org,self.user),self.db)
            send.assert_not_called()
    def test_live_punch_requires_source_confirmation(self):
        from app.main import dashboard_live_punch
        from app.zoho_people import ZohoLeaveResult
        with patch('app.main.local_now',return_value=datetime(2026,10,8,10)), patch('app.main.fetch_zoho_attendance_entries',return_value=ZohoAttendanceResult(status='synced')), patch('app.zoho_people.record_zoho_live_punch',return_value=ZohoLeaveResult(status='submitted')):
            with self.assertRaises(HTTPException) as error: dashboard_live_punch('in',(self.org,self.user),self.db)
            self.assertIn('not yet confirmed',error.exception.detail)
    def test_remote_punch_request_is_only_selected_action(self):
        import httpx
        from app.zoho_people import record_zoho_live_punch
        with patch('app.zoho_people._access_token',return_value=('test','')),patch('app.zoho_people.httpx.post',return_value=httpx.Response(200,json={'status':'success'})) as send:
            record_zoho_live_punch(employee_email='person@example.com',moment=datetime(2026,10,8,10),action='in')
        data=send.call_args.kwargs['data']
        self.assertEqual(data['emailId'],'person@example.com'); self.assertIn('checkIn',data); self.assertNotIn('checkOut',data); self.assertEqual(data['location'],'Noida')
