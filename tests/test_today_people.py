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
