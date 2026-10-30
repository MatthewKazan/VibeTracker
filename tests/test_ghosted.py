import os,sys,tempfile,unittest,datetime as dt
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
TEMP=tempfile.TemporaryDirectory();os.environ['JOB_MANAGER_DATA']=TEMP.name
import app
class GhostedTests(unittest.TestCase):
 def setUp(self):
  app.init()
  with app.connect() as c:c.execute('DELETE FROM jobs');c.execute("DELETE FROM settings WHERE key='ghost_exempt'")
 def add(self,status,days_ago=None,date=None):
  date=date if date is not None else (dt.date.today()-dt.timedelta(days=days_ago)).isoformat()
  with app.connect() as c:
   i=app.save_job(c,{'title':'T','status':status,'date_applied':date or None})
   if date=='':c.execute("UPDATE jobs SET date_applied='' WHERE id=?",(i,))
  return i
 def status(self,i):
  with app.connect() as c:return c.execute('SELECT status FROM jobs WHERE id=?',(i,)).fetchone()[0]
 def test_two_months_ago_handles_short_months_and_year_boundary(self):
  f=lambda y,m,d:app.two_months_ago(dt.date(y,m,d))
  self.assertEqual(f(2026,10,29),dt.date(2026,8,29));self.assertEqual(f(2026,1,15),dt.date(2025,11,15))
  self.assertEqual(f(2026,4,30),dt.date(2026,2,28));self.assertEqual(f(2026,3,31),dt.date(2026,1,31));self.assertEqual(f(2026,2,10),dt.date(2025,12,10))
 def test_only_old_waiting_jobs_become_ghosted(self):
  old=self.add('Waiting',90);recent=self.add('Waiting',30);interview=self.add('Interview 1',90);blank=self.add('Waiting',date='')
  boundary=self.add('Waiting',date=app.two_months_ago(dt.date.today()).isoformat())
  app.current_jobs()
  self.assertEqual([self.status(i) for i in (old,recent,interview,blank,boundary)],['Ghosted','Waiting','Interview 1','Waiting','Waiting'])
  with app.connect() as c:self.assertEqual(c.execute("SELECT status FROM history WHERE job_id=? ORDER BY id DESC",(old,)).fetchone()[0],'Ghosted')
 def test_job_set_back_to_waiting_by_the_user_stays_waiting(self):
  i=self.add('Ghosted',90)
  with app.connect() as c:app.save_job(c,{'status':'Waiting'},i);app.exempt_from_ghosting(c,i)
  app.current_jobs();self.assertEqual(self.status(i),'Waiting')
 def test_recent_job_edited_while_waiting_is_not_permanently_exempt(self):
  i=self.add('Waiting',10)
  with app.connect() as c:app.exempt_from_ghosting(c,i)
  self.assertNotIn(i,app.settings().get('ghost_exempt',[]))
if __name__=='__main__':unittest.main()
