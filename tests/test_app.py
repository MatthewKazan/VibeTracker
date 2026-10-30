import os,sys,tempfile,unittest,json,sqlite3,io,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
TEMP=tempfile.TemporaryDirectory();os.environ['JOB_MANAGER_DATA']=TEMP.name
import app
class PersistenceTests(unittest.TestCase):
 def setUp(self):
  app.init()
  with app.connect() as c:c.execute('DELETE FROM jobs')
 def test_committed_record_survives_reopen_and_backup(self):
  with app.connect() as c:i=app.save_job(c,{'title':'Engineer','company':'Acme','notes':'Keep this'})
  filename=app.backup()
  with app.connect() as c:self.assertEqual(c.execute('SELECT notes FROM jobs WHERE id=?',(i,)).fetchone()[0],'Keep this')
  with sqlite3.connect(app.DATA/'backups'/filename) as c:self.assertEqual(c.execute('SELECT count(*) FROM jobs').fetchone()[0],1)
 def test_import_transaction_rolls_back(self):
  with self.assertRaises(ValueError):
   with app.connect() as c:
    app.save_job(c,{'title':'valid'})
    app.save_job(c,{'title':''})
  with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
 def test_partial_update_preserves_notes(self):
  with app.connect() as c:i=app.save_job(c,{'title':'A','notes':'Keep','status':'Waiting'})
  with app.connect() as c:app.save_job(c,{'status':'Interview 2'},i)
  with app.connect() as c:r=dict(c.execute('SELECT * FROM jobs').fetchone())
  self.assertEqual(r['notes'],'Keep');self.assertEqual(r['status'],'Interview 2')
 def test_jsonld_extraction(self):
  raw='<script type="application/ld+json">'+json.dumps({'@type':'JobPosting','title':'Engineer','hiringOrganization':{'name':'Acme'},'jobLocation':{'address':{'addressLocality':'Boston','addressRegion':'MA'}},'description':'Python engineering'})+'</script>'
  j=app.extract('https://example.com/job',raw)
  self.assertEqual(j['company'],'Acme');self.assertEqual(j['location'],'Boston, MA');self.assertIsNone(j['fit'])
 def test_csv(self):self.assertEqual(app.parse_sheet(b'Title,Company\nEngineer,Acme\n','a.csv')[1],['Engineer','Acme'])
 def test_xlsx_sparse_and_shared(self):
  b=io.BytesIO()
  with zipfile.ZipFile(b,'w') as z:
   z.writestr('xl/sharedStrings.xml','<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>Engineer</t></si></sst>')
   z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row><c r="A1" t="s"><v>0</v></c><c r="C1" t="inlineStr"><is><t>Acme</t></is></c></row></sheetData></worksheet>')
  self.assertEqual(app.parse_sheet(b.getvalue(),'a.xlsx'),[['Engineer','','Acme']])
 def test_private_url_blocked(self):
  with self.assertRaises(ValueError):app.fetch('http://127.0.0.1/secret')
if __name__=='__main__':unittest.main()

class InterviewHistoryTests(unittest.TestCase):
 def test_rounds_survive_rejection_and_export(self):
  app.init()
  with app.connect() as c:
   ident=app.save_job(c,{'title':'Interview path','status':'Interview 3'})
   app.save_job(c,{'status':'Rejected'},ident)
  job=next(j for j in app.current_jobs() if j['id']==ident)
  self.assertEqual(job['interviews_completed'],3)
  with app.connect() as c:
   restored=app.save_job(c,job)
  self.assertEqual(next(j for j in app.current_jobs() if j['id']==restored)['interviews_completed'],3)
