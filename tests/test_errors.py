import unittest,errno,sqlite3,urllib.error,zipfile
from errors import explain
class ErrorTests(unittest.TestCase):
 def test_disk_full(self):self.assertIn('Free disk space',explain(OSError(errno.ENOSPC,'full')))
 def test_locked(self):self.assertIn('retry',explain(sqlite3.OperationalError('database is locked')))
 def test_bad_workbook(self):self.assertIn('.xlsx',explain(zipfile.BadZipFile()))
 def test_blocked_site(self):self.assertIn('Paste',explain(urllib.error.HTTPError('https://example.com',403,'Forbidden',{},None)))
 def test_timeout(self):self.assertIn('smaller model',explain(TimeoutError()))
 def test_invalid_model_json_has_action(self):
  import intelligence as ai
  from unittest.mock import patch
  with patch.object(ai,'validate_model'),patch.object(ai,'call',return_value={'done':True,'response':'not json'}):
   with self.assertRaisesRegex(ValueError,'select a different model'):ai.generate('test','test','test')
 def test_bad_requirements_type(self):
  import intelligence as ai
  from unittest.mock import patch
  with patch.object(ai,'generate',return_value={'requirements':None}):
   with self.assertRaisesRegex(ValueError,'could not list'):ai.analyze('job description here','resume','model')
 def test_single_column_csv(self):
  import app
  self.assertEqual(app.parse_sheet(b'Title\nEngineer\n','jobs.csv'),[['Title'],['Engineer']])
 def test_empty_csv(self):
  import app
  with self.assertRaisesRegex(ValueError,'empty'):app.parse_sheet(b'','jobs.csv')
 def test_post_commit_backup_failure_is_warning_not_failed_save(self):
  import app,threading,json,urllib.request
  from unittest.mock import patch
  app.init()
  server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with patch.object(app,'backup',side_effect=['before',OSError(errno.ENOSPC,'full')]):
    req=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+'/api/job',data=json.dumps({'title':'Save survives snapshot failure'}).encode(),headers={'X-Token':app.TOKEN,'Content-Type':'application/json'})
    result=json.load(urllib.request.urlopen(req));self.assertIn('Saved successfully',result['warning'])
    with app.connect() as c:self.assertIsNotNone(c.execute('SELECT id FROM jobs WHERE id=?',(result['id'],)).fetchone())
  finally:server.shutdown();server.server_close();thread.join()
