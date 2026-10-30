import json,unittest
from unittest.mock import patch,MagicMock
import app

class ExtractionTests(unittest.TestCase):
 def extract(self,raw,fetch=None):
  with patch.object(app,'settings',return_value={'model':'installed'}),patch.object(app,'ready_ai') as ai_ready,patch.object(app,'fetch',side_effect=fetch or (lambda u:raw)),patch.object(app.location_tools,'normalize',side_effect=lambda loc,desc,fetch:(loc,False,False)):
   result=app.extract('https://example.com/careers/engineer')
   return result,ai_ready
 def test_complete_structured_fields_skip_assets_and_model(self):
  raw='<script type="application/ld+json">'+json.dumps({'@type':'JobPosting','title':'Engineer','hiringOrganization':{'name':'Acme'},'jobLocation':{'address':'Boston, MA'},'description':'Build robots.'})+'</script><script src="/unnecessary.js"></script>'
  calls=[]
  result,ready=self.extract(raw,lambda u:(calls.append(u),raw)[1])
  self.assertEqual(len(calls),1);self.assertEqual(result['title'],'Engineer');ready.assert_not_called()
 def test_matching_bundle_role_not_first_role(self):
  html='<meta name="author" content="Acme"><title>Acme | Company overview</title><script src="/roles.js"></script>'
  js='[{slug:"manager",title:"Engineering Manager",location:"NYC",summary:"Wrong role"},{slug:"engineer",title:"Robotics Engineer",location:"Boston, MA",summary:"Build robots",description:["Required: Python","Required: controls"],profile:`Engineering degree`}]'
  result,ready=self.extract(html,lambda u:js if u.endswith('.js') else html)
  self.assertEqual(result['title'],'Robotics Engineer');self.assertEqual(result['company'],'Acme');self.assertIn('Required: controls',result['description']);self.assertNotIn('Wrong role',result['description']);ready.assert_not_called()
 def test_full_body_wins_over_short_marketing_metadata(self):
  raw='<meta name="description" content="Join us"><h1>Robotics Engineer</h1><p>'+('Requirements: Python and hardware experience. '*10)+'</p>'
  result,_=self.extract(raw)
  self.assertIn('hardware experience',result['description']);self.assertEqual(result['title'],'Robotics Engineer')
 def test_external_scripts_are_never_fetched(self):
  raw='<script src="https://elsewhere.example/roles.js"></script>'
  with patch.object(app,'fetch') as fetch:app.source_posting(raw,'https://example.com/engineer')
  fetch.assert_not_called()
 def test_failed_asset_retains_metadata_instead_of_failing(self):
  with patch.object(app,'fetch',side_effect=OSError('offline')):
   result=app.source_posting('<meta name="description" content="Posting text"><script src="/roles.js"></script>','https://example.com/engineer')
  self.assertEqual(result['description'],'Posting text')
 def test_gem_api_reads_posting_and_location(self):
  response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps([{'data':{'oatsExternalJobPosting':{'title':'GNC Engineer','descriptionHtml':'<p>CRABI Robotics</p><p>Experience with sensors.</p>','locations':[{'name':'1 Cabot Rd, Medford','city':'Medford','isRemote':False}]}}}]).encode()
  with patch.object(app.urllib.request,'urlopen',return_value=response):result=app.source_posting('<title>GNC Engineer</title>','https://jobs.gem.com/board/role')
  self.assertEqual(result['company'],'CRABI Robotics');self.assertEqual(result['location'],'1 Cabot Rd, Medford');self.assertIn('\n',result['description'])
 def test_jsonld_nested_graph(self):
  raw='<script type="application/ld+json">'+json.dumps({'@graph':[{'@type':'WebSite','name':'Not a role'},{'@type':['Thing','JobPosting'],'title':'Controls Engineer','hiringOrganization':{'name':'Acme'},'jobLocationType':'TELECOMMUTE','description':'Build controls.'}]})+'</script>'
  result,ready=self.extract(raw);self.assertEqual(result['title'],'Controls Engineer');self.assertEqual(result['location'],'Remote');ready.assert_not_called()
