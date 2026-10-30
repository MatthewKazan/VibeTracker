import unittest,tempfile,subprocess,os,sys,json,time,urllib.request,socket
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class HTTPRecoveryTests(unittest.TestCase):
 def test_crash_restart_and_atomic_import(self):
  with tempfile.TemporaryDirectory() as folder:
   with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
   env=dict(os.environ,JOB_MANAGER_DATA=folder,PORT=str(port));proc=None
   def start():
    nonlocal proc
    proc=subprocess.Popen([sys.executable,str(ROOT/'app.py')],env=env,stdout=subprocess.DEVNULL)
    for _ in range(100):
     try:return get('state')
     except Exception:time.sleep(.05)
    raise RuntimeError('Server did not start')
   def get(route):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/'+route) as r:return json.load(r)
   def post(route,body,token):
    req=urllib.request.Request(f'http://127.0.0.1:{port}/api/'+route,data=json.dumps(body).encode(),headers={'X-Token':token,'Content-Type':'application/json'})
    with urllib.request.urlopen(req) as r:return json.load(r)
   try:
    st=start();post('job',{'title':'Crash recovery','company':'Test','notes':'Must survive'},st['token'])
    proc.kill();proc.wait();st=start()
    self.assertEqual(st['jobs'][0]['notes'],'Must survive')
    with self.assertRaises(urllib.error.HTTPError):post('import',{'jobs':[{'title':'Valid'},{'title':''}]},st['token'])
    self.assertEqual(len(get('state')['jobs']),1)
    snaps=get('snapshots')['snapshots'];self.assertTrue(snaps)
    self.assertEqual(get('snapshot?name='+snaps[0])['jobs'][0]['title'],'Crash recovery')
    jobid=st['jobs'][0]['id']
    post('settings',{'resume':'Python SQL'},st['token'])
    post('job',{'id':jobid,'description':'Python SQL Docker'},st['token'])
    report=post('fit',{'id':jobid},st['token'])
    self.assertTrue(report['can_analyze'])
    self.assertIsNone(report['score'])
    rules=[{'field':'status','direction':1},{'field':'date_applied','direction':-1},{'field':'company','direction':1}]
    post('settings',{'sort_rules':rules,'profile_memory':'I graduated in 2026.','quit_model_policy':'keep','status_colors':{'Assessment':'#ff9900','Waiting':'#112233'}},st['token'])
    proc.kill();proc.wait();st=start()
    self.assertEqual(st['settings']['sort_rules'],rules)
    self.assertEqual(st['settings']['profile_memory'],'I graduated in 2026.')
    self.assertEqual(st['settings']['quit_model_policy'],'keep')
    self.assertEqual(st['settings']['status_colors']['Assessment'],'#ff9900')
    with self.assertRaises(urllib.error.HTTPError):post('settings',{'status_colors':{'Bad':'red;display:none'}},st['token'])
    self.assertIsNone(st['jobs'][0]['fit'])
    with self.assertRaises(urllib.error.HTTPError):post('settings',{'sort_rules':[{'field':'oops','direction':1}]},st['token'])
   finally:
    if proc:proc.terminate();proc.wait()
