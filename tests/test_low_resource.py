import json,sys,tempfile,threading,time,unittest,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
import activity,app,mail_integration as mail,mail_pipeline as pipeline

class ActivityTests(unittest.TestCase):
 def setUp(self):activity.configure(False)
 def tearDown(self):
  if activity.STARTUP_TIMER:activity.STARTUP_TIMER.cancel()
  activity.READY.set();activity.STARTUP_UNTIL=0;activity.configure(False)
 def test_pause_cancels_registered_work_and_invalidates_old_results_after_resume(self):
  epoch=activity.ticket();cancelled=[]
  with activity.cancellable(lambda:cancelled.append(True),epoch):
   activity.configure(True);activity.configure(False)
   with self.assertRaises(activity.Paused):activity.check(epoch)
  self.assertEqual(cancelled,[True]);self.assertFalse(activity.CANCEL)
 def test_default_grace_is_thirty_seconds(self):
  activity.startup_grace();self.assertEqual(activity.STARTUP_TIMER.interval,30);self.assertGreater(activity.result()['startup_remaining'],29)
 def test_workers_sleep_through_grace_and_remain_asleep_when_paused(self):
  activity.startup_grace(.08);done=threading.Event()
  worker=threading.Thread(target=lambda:(activity.wait(),done.set()),daemon=True);worker.start()
  self.assertFalse(done.wait(.02));activity.configure(True)
  self.assertFalse(done.wait(.1));activity.configure(False);self.assertTrue(done.wait(.2));worker.join()
 def test_pause_terminates_owned_classifier_process(self):
  caught=[]
  def run():
   try:activity.run_process([sys.executable,'-c','import time;time.sleep(30)'],capture_output=True,timeout=40)
   except activity.Paused:caught.append(True)
  thread=threading.Thread(target=run);thread.start()
  deadline=time.monotonic()+2
  while not activity.CANCEL and time.monotonic()<deadline:time.sleep(.005)
  self.assertTrue(activity.CANCEL);activity.configure(True);thread.join(2)
  self.assertFalse(thread.is_alive());self.assertEqual(caught,[True]);self.assertFalse(activity.CANCEL)
 def test_pause_closes_a_stalled_http_response(self):
  entered=threading.Event();release=threading.Event();caught=[]
  class Stalled(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    self.send_response(200);self.end_headers();self.wfile.write(b'part');self.wfile.flush();entered.set();release.wait(3)
  server=ThreadingHTTPServer(('127.0.0.1',0),Stalled);threading.Thread(target=server.serve_forever,daemon=True).start()
  def read():
   try:
    with activity.open_url('http://127.0.0.1:'+str(server.server_port)) as r:r.read()
   except activity.Paused:caught.append(True)
  thread=threading.Thread(target=read);thread.start()
  try:
   self.assertTrue(entered.wait(2));activity.configure(True);thread.join(1)
   self.assertFalse(thread.is_alive());self.assertEqual(caught,[True])
  finally:release.set();server.shutdown();server.server_close();thread.join(3)

class LowResourceAPITests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.data=patch.object(app,'DATA',Path(self.tmp.name));self.db=patch.object(app,'DB',Path(self.tmp.name)/'jobs.sqlite3');self.data.start();self.db.start();app.init()
  self.server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
 def tearDown(self):
  self.server.shutdown();self.server.server_close();self.thread.join();activity.configure(False);self.db.stop();self.data.stop();self.tmp.cleanup()
 def request(self,route,body=None):
  req=urllib.request.Request('http://127.0.0.1:'+str(self.server.server_port)+'/api/'+route,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','X-Token':app.TOKEN})
  with urllib.request.urlopen(req) as r:return json.load(r)
 def test_pause_preserves_preferences_and_saved_views_and_survives_restart(self):
  self.request('settings',{'auto_start':True,'auto_analyze':True,'questions':[{'question':'Why?','answer':'Robots','group':'General'}]})
  self.request('job',{'title':'Synthetic Engineer','company':'Synthetic QA','notes':'Saved'})
  with patch.object(app.ai,'call') as ai:
   self.assertTrue(self.request('activity',{'paused':True})['paused'])
   state=self.request('state');self.assertEqual(state['jobs'][0]['notes'],'Saved')
   self.assertEqual(state['settings']['questions'][0]['answer'],'Robots');self.assertTrue(state['settings']['auto_start']);self.assertTrue(state['settings']['auto_analyze'])
   self.assertFalse(self.request('queue')['active']);self.assertEqual(self.request('emails/notifications')['events'],[]);ai.assert_not_called()
   for route,body in [('ai/start',{}),('ai/load',{}),('emails/sync',{}),('questions/search',{'query':'Robots'})]:
    with self.assertRaises(urllib.error.HTTPError) as error:self.request(route,body)
    self.assertIn('Low-resource',error.exception.read().decode())
   result=self.request('extract',{'text':'Job title: Robot engineer\nCompany: Synthetic QA\nLocation: Remote\nPython required.'});self.assertEqual(result['title'],'Robot engineer');ai.assert_not_called()
   app.init();self.assertTrue(activity.paused());self.request('activity',{'paused':False});self.assertFalse(activity.paused())
 def test_interrupted_classification_remains_queued_without_a_status_change(self):
  with app.connect() as c:
   ident=app.save_job(c,{'title':'Engineer','company':'Synthetic QA','status':'Waiting'})
   c.execute('INSERT INTO settings VALUES (?,?)',('mail_account',json.dumps({'id':'test'})))
   c.execute("INSERT INTO emails(message_id,sender,subject,body,received_at,company,match_kind,evidence,rejection,review,analysis_state) VALUES ('test','hr@synthetic.test','Engineer update','We cannot move forward.','2026-11-01T00:00:00+00:00','Synthetic QA','company','',0,'none','queued')")
   c.execute("INSERT INTO email_accounts VALUES ('test','test')")
  def interrupted(*args):
   activity.configure(True);activity.configure(False)
   return {'kind':'rejection','evidence':'We cannot move forward.'}
  with patch.object(mail,'run_shortcut',side_effect=interrupted):self.assertEqual(pipeline.analyze_pending(app),0)
  with app.connect() as c:
   self.assertEqual(c.execute('SELECT analysis_state FROM emails').fetchone()[0],'queued');self.assertEqual(c.execute('SELECT status FROM jobs WHERE id=?',(ident,)).fetchone()[0],'Waiting')

 def test_pause_unloads_only_jobtracker_models_and_exposes_retry_errors(self):
  self.request('settings',{'model':'selected-model'})
  def fake(route,body=None,timeout=None):
   if route=='ps':return {'models':[{'name':'selected-model:latest'},{'name':'another-app:latest'}]}
   raise ValueError('Synthetic unload failure')
  with patch.object(app.ai,'call',side_effect=fake) as calls:
   result=self.request('activity',{'paused':True});self.assertTrue(result['paused']);self.assertIn('Synthetic unload failure',result['unload_error'])
   self.assertEqual([c.args[1]['model'] for c in calls.call_args_list if c.args[0]=='generate'],['selected-model:latest'])
  with patch.object(app.ai,'call',return_value={'models':[]}):self.assertFalse(self.request('activity',{'paused':True})['unload_error'])

class PostingLookupPauseTests(unittest.TestCase):
 def tearDown(self):activity.configure(False)
 def test_paused_lookup_uses_public_fetch_and_never_starts_model(self):
  from unittest.mock import MagicMock
  activity.configure(True)
  response=MagicMock();response.__enter__.return_value.read.return_value=b'<h1>Robotics engineer</h1><p>Python required.</p>'
  opener=MagicMock();opener.open.return_value=response
  with patch.object(app,'settings',return_value={'model':'installed'}),patch.object(app,'ready_ai') as ready,patch.object(app.ai,'generate') as generate,patch.object(app.urllib.request,'build_opener',return_value=opener),patch.object(app.socket,'getaddrinfo',return_value=[(None,None,None,None,('93.184.216.34',443))]),patch.object(app.location_tools,'normalize',side_effect=lambda loc,desc,fetch:(loc,False,False)):
   result=app.extract('https://example.test/job')
   self.assertIn('Python',result['description']);opener.open.assert_called();ready.assert_not_called();generate.assert_not_called()
  self.assertFalse(app.POSTING_LOCAL.manual)
  with self.assertRaises(activity.Paused):app.fetch('https://example.test/job')
 def test_paused_manual_lookup_still_rejects_private_destinations(self):
  activity.configure(True)
  with self.assertRaisesRegex(ValueError,'public'):app.extract('http://127.0.0.1/job')
