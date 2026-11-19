import json,unittest
from unittest.mock import patch
import posting_extraction as p
from test_posting_rules import RulesAPITests
RAW='<h1>Careers</h1><h2 class="role-title">Engineer</h2><b class="company-name">Example</b><p class="actual-place">Boston, Massachusetts, USA</p><article>Python required.</article>'
URL='https://example.test/jobs/1?company=example'
class LearningTests(unittest.TestCase):
 def rule(self):
  r=p.learn(RAW,URL,{'title':'Engineer','location':'Boston, MA'})['rule'];r['id']='a'*24;p.validate_learned([r]);return r
 def test_future_values_not_training_values(self):
  r=self.rule();self.assertNotIn('Engineer',json.dumps(r));self.assertNotIn('Boston',json.dumps(r))
  values,_=p.apply_learned(p.Tree(RAW.replace('Engineer','Scientist').replace('Boston, Massachusetts','Austin, Texas')),URL.replace('/1','/2'),[r]);self.assertEqual(values,{'title':'Scientist','location':'Austin, Texas, USA'})
 def test_scoped_host_path_and_tenant(self):
  for url in ['https://other.test/jobs/2?company=example','https://example.test/blog/2?company=example','https://example.test/jobs/2?company=other']:
   self.assertEqual(p.apply_learned(p.Tree(RAW),url,[self.rule()])[0],{})
 def test_missing_hidden_and_ambiguous_elements_are_skipped(self):
  r=self.rule()
  for raw in ['', '<h2 class="role-title" hidden>Other</h2>','<h2 class="role-title">One</h2><h2 class="role-title">Two</h2>']:
   self.assertEqual(p.apply_learned(p.Tree(raw),URL,[r])[0],{})
  self.assertFalse(p.learn('<h1 hidden>Engineer</h1>',URL,{'title':'Engineer'})['found'])
  self.assertFalse(p.learn(RAW,URL,{'title':'Unfindable'})['found'])
 def test_invalid_saved_rules_rejected(self):
  r=self.rule()
  for rules in [[{**r,'fields':{'description':[{'selector':'article'}]}}],[{**r,'path_exact':'/'}],[{**r,'fields':None}],[r,r]]:
   with self.assertRaises(ValueError):p.validate_learned(rules)
class LearningAPITests(RulesAPITests):
 def test_save_reload_extract_and_undo_without_changing_jobs(self):
  import app
  with patch.object(app,'fetch',return_value=RAW):proposal=self.request('autofill/learn',{'url':URL,'corrections':{'title':'Engineer','location':'Boston, MA'}})
  self.assertEqual(self.request('extraction-rules')['learned'],[])
  saved=self.request('autofill/learn/save',{'token':proposal['token']});app.init()
  self.assertEqual(len(self.request('extraction-rules')['learned']),1)
  with patch.object(app,'fetch',return_value=RAW.replace('Engineer','Scientist')):
   result=self.request('extract',{'url':URL});self.assertEqual(result['title'],'Scientist');self.assertIn('Python',result['description'])
  self.assertEqual(self.request('state')['jobs'],[])
  self.assertEqual(len(self.request('export')['settings']['autofill_learned_rules']),1)
  self.request('autofill/learn/undo',{'id':saved['id']});self.assertEqual(self.request('extraction-rules')['learned'],[])
  with self.assertRaises(Exception):self.request('autofill/learn/save',{'token':proposal['token']})
