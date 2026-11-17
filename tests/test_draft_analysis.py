import unittest
from unittest.mock import patch
import intelligence as ai

class ReviewValidationTests(unittest.TestCase):
 def test_model_validated_once_per_review_and_again_on_next_review(self):
  def review(*args):
   ai.generate('local','first full prompt','system')
   ai.generate('local','second full prompt','system')
   return {'score':80}
  with patch.object(ai,'_analyze',side_effect=review),patch.object(ai,'validate_model') as validate,patch.object(ai,'call',return_value={'done':True,'response':'{}'}) as call:
   self.assertEqual(ai.analyze('posting','resume','local')['score'],80)
   self.assertEqual(validate.call_count,1)
   ai.analyze('posting','resume','local')
   self.assertEqual(validate.call_count,2)
   self.assertEqual(call.call_count,4)
   self.assertEqual(call.call_args.args[1]['options']['num_ctx'],16384)
  self.assertIsNone(ai.LOCAL.validated_models)
 def test_failed_review_restores_validation_scope(self):
  with patch.object(ai,'_analyze',side_effect=ValueError('failed')):
   with self.assertRaises(ValueError):ai.analyze('posting','resume','local')
  self.assertIsNone(ai.LOCAL.validated_models)

class DraftEndpointTests(unittest.TestCase):
 def request(self,body,config):
  import app,io,json
  handler=object.__new__(app.Handler);raw=json.dumps(body).encode()
  handler.path='/api/fit/draft';handler.headers={'X-Token':app.TOKEN,'X-Waypoint-Session':app.DESKTOP_TOKEN,'Content-Length':str(len(raw))};handler.rfile=io.BytesIO(raw)
  result=[];handler.reply=lambda data,status=200:result.append((data,status))
  with patch.object(app,'settings',return_value=config),patch.object(app,'ready_ai',return_value=('local',{})),patch.object(app,'connect') as db,patch.object(app.ai,'analyze',return_value={'score':80,'requirements':[]}) as analyze:
   handler.do_POST()
   db.assert_not_called()
  return result[0],analyze
 def test_keywords_require_no_model_and_preserve_quoted_context(self):
  (result,status),analyze=self.request({'description':'Python and SQL required.'},{'resume':'Python'})
  self.assertEqual(status,200);self.assertIn('python',result['matched']);self.assertEqual(result['missing'][0]['job_evidence'],'Python and SQL required.');analyze.assert_not_called()
 def test_full_draft_review_uses_complete_input_and_profile(self):
  config={'resume':'Full résumé','profile_memory':'Known facts','analysis_system':'System','analysis_instructions':'Instructions'}
  (result,status),analyze=self.request({'description':'Complete posting','analyze':True},config)
  self.assertEqual(status,200);self.assertEqual(result['analysis']['score'],80)
  analyze.assert_called_once_with('Complete posting','Full résumé','local','Known facts',[],'System','Instructions')
 def test_no_resume_and_invalid_description_do_not_start_model(self):
  for body in ({'description':'Python','analyze':True},{'description':['invalid']}):
   (result,status),analyze=self.request(body,{'resume':''});self.assertEqual(status,400);analyze.assert_not_called()

class ReviewProgressTests(unittest.TestCase):
 def test_analysis_reports_real_requirement_counts_without_changing_result(self):
  items=[{'req':'Python','sent':1,'importance':'required','kind':'skill','group':'1'},{'req':'SQL','sent':2,'importance':'required','kind':'skill','group':'2'}]
  events=[]
  with patch.object(ai,'extract_items',return_value=items):
   result=ai.analyze('Python required. SQL required.','Python and SQL','local',progress=lambda **p:events.append(p))
  self.assertEqual(result['score'],100)
  self.assertEqual(events[0]['stage'],'extracting')
  reviews=[p for p in events if p['stage']=='reviewing']
  self.assertEqual([p['completed'] for p in reviews],[0,1,1,2]);self.assertTrue(all(p['total']==2 for p in reviews));self.assertEqual(reviews[-1]['requirement'],'SQL');self.assertEqual(events[-1]['stage'],'finalizing')
 def test_progress_records_are_bounded_and_isolated(self):
  import app
  with patch.object(app,'DRAFT_PROGRESS',{}):
   app.draft_progress('one',{'stage':'reviewing','completed':2,'total':5});app.draft_progress('two',{'stage':'loading'})
   self.assertEqual(app.draft_progress('one')['completed'],2);self.assertEqual(app.draft_progress('two')['stage'],'loading')
   for i in range(150):app.draft_progress(str(i),{'stage':'complete'})
   self.assertLessEqual(len(app.DRAFT_PROGRESS),128)
