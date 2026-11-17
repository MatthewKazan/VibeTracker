import json,tempfile,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import app,activity,posting_extraction as posting

class PostingRulesTests(unittest.TestCase):
 def extract(self,raw,url='https://example.test/jobs/12345678',rules=None):
  with patch.object(app,'settings',return_value={}),patch.object(app,'fetch',return_value=raw):return app.extract(url,rules=rules)
 def test_google_detail_wins_over_other_jobs_and_generic_heading(self):
  raw='''<title>Research Scientist — Google Careers</title><h1>job details</h1><div><h2>Wrong job</h2><span class="r0wTof">Austin, TX</span></div><div class="DkhPwc"><h2 class="p1N2lc">Research Scientist, Robotics, DeepMind</h2><span class="RP7SMd"><i aria-hidden="true">corporate_fare</i><span>DeepMind</span></span><span class="r0wTof">Cambridge, MA, USA</span><div class="KwJkGe"><h3>Minimum qualifications</h3><p>Robotics research.</p></div><div class="aG5W3"><h3>About the job</h3><p>Develop models.</p></div><div class="BDNOWe"><h3>Responsibilities</h3><p>Evaluate robots.</p></div></div>'''
  r=self.extract(raw,'https://www.google.com/about/careers/applications/jobs/results/12345678-role')
  self.assertEqual((r['title'],r['company'],r['location']),('Research Scientist, Robotics, DeepMind','DeepMind','Cambridge, MA'))
  self.assertIn('Evaluate robots.',r['description']);self.assertNotIn('Wrong job',r['description']);self.assertNotIn('corporate_fare',r['company'])
 def test_multiple_jsonld_postings_match_requested_id_instead_of_first(self):
  jobs=[{'@type':'JobPosting','identifier':{'value':'99999999'},'title':'Wrong','description':'Wrong description'},{'@type':'JobPosting','identifier':{'value':'12345678'},'title':'Right','description':'Right description','hiringOrganization':{'name':'Example'},'jobLocation':{'name':'Boston, Massachusetts, USA'}}]
  r=self.extract('<script type="application/ld+json">'+json.dumps(jobs)+'</script>')
  self.assertEqual(r['title'],'Right');self.assertEqual(r['location'],'Boston, MA');self.assertEqual(r['description'],'Right description')
  for j in jobs:j.pop('identifier')
  with self.assertRaisesRegex(ValueError,'several jobs'):self.extract('<script type="application/ld+json">'+json.dumps(jobs)+'</script>')
 def test_location_markup_without_model(self):
  for markup in ['<div class="job__location">Boston, Massachusetts, USA</div>','<div class="posting-categories"><div class="location">Boston, Massachusetts, USA</div></div>','<div data-automation-id="locations">Boston, Massachusetts, USA</div>','<p>Location:</p><p>Boston, Massachusetts, USA</p>','<div itemprop="jobLocation"><span itemprop="addressLocality">Boston</span><meta itemprop="addressRegion" content="Massachusetts"><span itemprop="addressCountry">USA</span></div>']:
   self.assertEqual(self.extract('<h1>Engineer</h1>'+markup)['location'],'Boston, MA')
 def test_remote_eligibility_and_multiple_addresses_are_preserved(self):
  result=posting.structured_locations({'jobLocationType':'TELECOMMUTE','applicantLocationRequirements':[{'name':'United States'},{'name':'Canada'}],'jobLocation':[{'address':{'addressLocality':'Boston','addressRegion':'MA'}},{'name':'Toronto, ON, Canada'}]})
  self.assertEqual(result,'Remote — United States, Canada; Boston, MA; Toronto, ON, Canada')
 def test_rule_host_scope_attributes_and_escaping(self):
  rule={'name':'Example','host':'example.test','scope':'#role','fields':{'title':[{'selector':'meta[property="og:title"]','attribute':'content'}],'location':[{'selector':'.city'}]}}
  tree=posting.Tree('<div class="city">Wrong</div><section id="role"><meta property="og:title" content="Robotics &amp; AI"><span class="city">Boston, MA</span></section>')
  self.assertEqual(posting.apply(tree,'https://example.test/jobs',[rule])[0],{'title':'Robotics & AI','location':'Boston, MA'})
  self.assertEqual(posting.apply(tree,'https://example.test.evil/jobs',[rule])[0],{})
  self.assertEqual(posting.apply(posting.Tree('<section id="role"></section><section id="role"></section>'),'https://example.test/jobs',[rule])[0],{})
 def test_validation_rejects_executable_or_unbounded_rules(self):
  base={'name':'Rule','host':'example.test','fields':{'title':[{'selector':'h1'}]}}
  for invalid in [None,[{**base,'host':'https://example.test'}],[{**base,'fields':{'title':[{'selector':'h1:has(script)'}]}}],[{**base,'script':'alert(1)'}],[{**base,'fields':{'location':[{'selector':'x'*301}]}}]]:
   with self.assertRaises(ValueError):posting.validate(invalid)

class RulesAPITests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.data=patch.object(app,'DATA',Path(self.tmp.name));self.db=patch.object(app,'DB',Path(self.tmp.name)/'jobs.sqlite3');self.data.start();self.db.start();app.init()
  self.server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
 def tearDown(self):
  self.server.shutdown();self.server.server_close();self.thread.join();activity.configure(False);self.db.stop();self.data.stop();self.tmp.cleanup()
 def request(self,route,body=None):
  req=urllib.request.Request('http://127.0.0.1:'+str(self.server.server_port)+'/api/'+route,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','X-Token':app.TOKEN})
  with urllib.request.urlopen(req) as response:return json.load(response)
 def test_preview_then_saved_rules_apply_immediately_and_survive_reload(self):
  rules=[{'name':'Example role','host':'example.test','scope':'#job','fields':{'title':[{'selector':'h2'}],'company':[{'selector':'.company'}],'location':[{'selector':'.place'}],'description':[{'selector':'.description'}]}}]
  raw='<h1>Unrelated page heading</h1><section id="job"><h2>Engineer</h2><b class="company">Example</b><p class="place">Boston, MA</p><p class="description">Python skills required.</p></section>'
  initial=self.request('extraction-rules')['rules']
  with patch.object(app,'fetch',return_value=raw),patch.object(app.ai,'generate') as model:
   preview=self.request('extraction-rules/preview',{'url':'https://example.test/jobs','rules':rules});self.assertEqual(preview['title'],'Engineer');self.assertEqual(self.request('extraction-rules')['rules'],initial)
   self.request('settings',{'extraction_rules':rules});self.assertEqual(self.request('extract',{'url':'https://example.test/jobs'})['location'],'Boston, MA')
   self.assertEqual(len(self.request('state')['jobs']),0);model.assert_not_called()
  app.init();self.assertEqual(self.request('extraction-rules')['rules'],rules)
  exported=self.request('export');self.assertEqual(exported['settings']['extraction_rules'],rules)
  with self.assertRaises(urllib.error.HTTPError):self.request('settings',{'extraction_rules':[{'bad':'rule'}]})
  self.assertEqual(self.request('extraction-rules')['rules'],rules)
