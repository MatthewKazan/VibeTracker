import concurrent.futures
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

class InterviewPrepTests(unittest.TestCase):
 def test_forks_concurrent_edits_restart_and_backup_restore(self):
  with tempfile.TemporaryDirectory() as folder:
   with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
   origin=f'http://127.0.0.1:{port}/api/';proc=None
   def get(route):
    with urllib.request.urlopen(origin+route) as r:return json.load(r)
   def start():
    nonlocal proc
    proc=subprocess.Popen([sys.executable,str(ROOT/'app.py')],env=dict(os.environ,JOB_MANAGER_DATA=folder,PORT=str(port)),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for _ in range(100):
     try:return get('state')['token']
     except Exception:time.sleep(.05)
    raise RuntimeError('Server did not start')
   def post(route,body):
    req=urllib.request.Request(origin+route,data=json.dumps(body).encode(),headers={'X-Token':token,'Content-Type':'application/json'})
    try:
     with urllib.request.urlopen(req) as r:return r.status,json.load(r)
    except urllib.error.HTTPError as e:return e.code,json.load(e)
   try:
    token=start();sheets=get('interview-prep')['sheets'];general=sheets[0]
    self.assertEqual([s['id'] for s in sheets],['general','crabi'])
    self.assertIn('Kabsch',general['technical']);self.assertIn(r'H\delta=b',general['technical'])
    status,r=post('interview-prep',dict(action='fork',id='general',expected_revision=1,title='My interview',role_description='Simulation and sensor fusion with hardware',role_url='https://example.com/job'))
    self.assertEqual(status,200);ident=r['selected_id'];fork=next(s for s in r['sheets'] if s['id']==ident)
    self.assertEqual(fork['technical'],general['technical']);self.assertIn('Focus for this interview',fork['about']);self.assertIn('Simulation',fork['role_description'])
    payload=dict(action='save',id=ident,expected_revision=1,title='My interview',about='Edited personally',technical='Kabsch and GN')
    with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:post('interview-prep',payload),range(2)))
    self.assertEqual(sorted(r[0] for r in results),[200,409])
    saved=get('export');stored=saved['settings']['interview_sheets']
    self.assertEqual(next(s for s in stored if s['id']==ident)['about'],'Edited personally')
    self.assertEqual(next(s for s in stored if s['id']=='general')['about'],general['about'])
    # Invalid imports roll back atomically and cannot bypass revision checks.
    self.assertEqual(post('settings',{'interview_sheets':stored})[0],400)
    self.assertEqual(post('restore',{'jobs':[],'settings':{'interview_sheets':[{}]}})[0],400)
    self.assertEqual(post('interview-prep',dict(action='delete',id='general',expected_revision=1))[0],400)
    self.assertEqual(post('restore',saved)[0],200)
    restored=next(s for s in get('interview-prep')['sheets'] if s['id']==ident)
    self.assertEqual(restored['revision'],3)
    self.assertEqual(post('interview-prep',{**payload,'expected_revision':2})[0],409)
    proc.terminate();proc.wait();token=start()
    self.assertEqual(next(s for s in get('interview-prep')['sheets'] if s['id']==ident)['about'],'Edited personally')
    self.assertEqual(post('interview-prep',dict(action='delete',id=ident,expected_revision=3))[0],200)
    self.assertFalse(any(s['id']==ident for s in get('interview-prep')['sheets']))
   finally:
    if proc:proc.terminate();proc.wait()

class InterviewDraftTests(unittest.TestCase):
 def test_focus_only_links_existing_experience_and_draft_requires_current_source(self):
  import sqlite3
  import interview_prep
  with sqlite3.connect(':memory:') as c:
   c.row_factory=sqlite3.Row;c.execute('create table settings (key text primary key,value text)');interview_prep.initialize(c)
   focus=interview_prep.role_focus('State estimation, simulation, hardware-in-the-loop and Python')
   self.assertIn('Locus',focus);self.assertIn('Twelve',focus)
   prompt=interview_prep.draft_prompt(c,dict(id='general',expected_revision=1,role_description='Robotics localization role'))
   self.assertIn('Do not infer experience from job requirements',prompt)
   with self.assertRaises(interview_prep.Conflict):interview_prep.draft_prompt(c,dict(id='general',expected_revision=0,role_description='Robotics'))

 def test_math_migration_preserves_custom_text_and_runs_once(self):
  import sqlite3
  import interview_prep
  with sqlite3.connect(':memory:') as c:
   c.row_factory=sqlite3.Row;c.execute('create table settings (key text primary key,value text)');interview_prep.initialize(c)
   sheets=interview_prep.read(c);sheets[0]['technical']='My custom explanation. **(Jᵀ W J) δ = −Jᵀ W r**';c.execute('update settings set value=? where key=?',(json.dumps(sheets),interview_prep.KEY))
   interview_prep.initialize(c);first=interview_prep.read(c)[0]
   self.assertIn('My custom explanation.',first['technical']);self.assertIn(r'\[',first['technical']);self.assertEqual(first['revision'],2)
   interview_prep.initialize(c);self.assertEqual(interview_prep.read(c)[0],first)

 def test_extra_sections_validation_and_legacy_saves_preserve_sections(self):
  import sqlite3
  import interview_prep
  with sqlite3.connect(':memory:') as c:
   c.row_factory=sqlite3.Row;c.execute('create table settings (key text primary key,value text)');interview_prep.initialize(c);c.commit()
   base=interview_prep.read(c)[0]
   extras=[{'id':'questions','title':'Questions for them','content':'## First\nA question'}]
   with c:result=interview_prep.mutate(c,dict(action='save',id='general',expected_revision=1,title=base['title'],about=base['about'],technical=base['technical'],sections=extras))
   with c:fork=interview_prep.mutate(c,dict(action='fork',id='general',expected_revision=2,title='New interview'))
   copied=next(s for s in fork['sheets'] if s['id']==fork['selected_id']);self.assertEqual(copied['sections'],extras)
   with c:interview_prep.mutate(c,dict(action='save',id='general',expected_revision=2,title=base['title'],about='Updated',technical=base['technical']))
   self.assertEqual(interview_prep.read(c)[0]['sections'],extras)
   for bad in ([{}],extras*2,[{'id':'about','title':'Bad','content':''}],[{'id':'safe','title':'Bad\nName','content':''}]):
    with self.assertRaises(ValueError):interview_prep.validate_sections(bad)
   with c:interview_prep.restore(c,result['sheets'])
   self.assertEqual(interview_prep.read(c)[0]['sections'],extras)


 def test_concise_math_moves_once_and_keeps_other_notes(self):
  import sqlite3
  import interview_prep
  with sqlite3.connect(':memory:') as c:
   c.row_factory=sqlite3.Row;c.execute('create table settings (key text primary key,value text)');interview_prep.initialize(c)
   sheets=interview_prep.read(c);sheet=sheets[0]
   manifest=json.loads((ROOT/'static/interview-technical-move.json').read_text())
   for change in manifest['replace']:sheet['technical']=sheet['technical'].replace(change['new'],change['old'])
   sheet['technical_math_version']=0
   details=next(s for s in sheet['sections'] if s['id']=='math-details');details['content']+='\n\n'+'\n\n'.join(manifest['remove'])+'\n\n## Keep my note\nPersonal text'
   c.execute('update settings set value=? where key=?',(json.dumps(sheets),interview_prep.KEY));interview_prep.initialize(c)
   moved=interview_prep.read(c)[0];self.assertEqual(moved['revision'],2)
   self.assertIn('## Jacobians · derivation in my conventions',moved['technical'])
   updated=next(s for s in moved['sections'] if s['id']=='math-details')['content'];self.assertIn('Personal text',updated)
   self.assertNotIn('## ICP · objective and update',updated)
   interview_prep.initialize(c);self.assertEqual(interview_prep.read(c)[0],moved)

 def test_vocabulary_is_added_once_without_replacing_custom_sections(self):
  import sqlite3
  import interview_prep
  with sqlite3.connect(':memory:') as c:
   c.row_factory=sqlite3.Row;c.execute('create table settings (key text primary key,value text)');interview_prep.initialize(c)
   sheets=interview_prep.read(c);sheet=sheets[0];sheet.pop('vocabulary_version');sheet['sections']=[s for s in sheet['sections'] if s['id']!='vocabulary'];sheet['sections'].append({'id':'personal','title':'My reminders','content':'Keep this'})
   c.execute('update settings set value=? where key=?',(json.dumps(sheets),interview_prep.KEY));interview_prep.initialize(c);updated=interview_prep.read(c)[0]
   vocab=next(s for s in updated['sections'] if s['id']=='vocabulary');self.assertIn('**ViT:**',vocab['content']);self.assertIn('**Adjoint:**',vocab['content']);self.assertTrue(any(s['content']=='Keep this' for s in updated['sections']))
   interview_prep.initialize(c);self.assertEqual(interview_prep.read(c)[0],updated)

 def test_layout_forks_and_restores_and_rejects_invalid_positions(self):
  import sqlite3
  import interview_prep
  with sqlite3.connect(':memory:') as c:
   c.row_factory=sqlite3.Row;c.execute('create table settings (key text primary key,value text)');interview_prep.initialize(c);c.commit();base=interview_prep.read(c)[0]
   layout=[{'field':'technical','column':'right'},{'field':'about','column':'both'}];columns={'about':['left','right']}
   with c:interview_prep.mutate(c,dict(action='save',id='general',expected_revision=1,title=base['title'],about=base['about'],technical=base['technical'],section_layout=layout,card_columns=columns))
   with c:r=interview_prep.mutate(c,dict(action='fork',id='general',expected_revision=2,title='Layout copy'))
   fork=next(s for s in r['sheets'] if s['id']==r['selected_id']);self.assertEqual(fork['section_layout'],layout);self.assertEqual(fork['card_columns'],columns)
   with c:interview_prep.restore(c,r['sheets'])
   self.assertEqual(next(s for s in interview_prep.read(c) if s['id']==fork['id'])['card_columns'],columns)
   for changes in ({'section_layout':[{'field':'missing','column':'both'}]},{'section_layout':[{'field':'about','column':'center'}]},{'card_columns':{'about':['wrong']}},{'card_columns':{'missing':['left']}}):
    with self.assertRaises(ValueError):interview_prep.validate([{**base,**changes}])
