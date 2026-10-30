import unittest
from unittest.mock import patch
import intelligence as ai
class AnalysisTests(unittest.TestCase):
 def test_missing_input_has_no_score(self):
  self.assertIsNone(ai.coverage('Python','')['score'])
 def test_whole_word_and_punctuation(self):
  self.assertFalse(ai.contains('JavaScript','java'))
  self.assertTrue(ai.contains('Built C++ applications','c++'))
  self.assertFalse(ai.contains('C++','c#'))
 def test_keywords_and_evidence(self):
  r=ai.coverage('Required Python, SQL, Docker and machine learning. Python development.','Built Python and SQL tools.')
  self.assertIn('python',r['matched']);self.assertIn('docker',[x['term'] for x in r['missing']]);self.assertLess(r['score'],100)
  self.assertIn('Docker',next(x for x in r['missing'] if x['term']=='docker')['job_evidence'])
 def setUp(self):ai.STAGE1_CACHE.clear();ai.STAGE2_CACHE.clear()
 def test_second_analysis_of_same_inputs_makes_no_model_calls(self):
  stage1={'items':[self.item('Python',1),self.item('Docker',2)]};answers={'Python':{'evidence':['L1'],'level':4},'Docker':{'level':0}}
  first,_=self.run_analysis(stage1,answers)
  second,seen=self.run_analysis(stage1,answers)
  self.assertEqual(seen,[]);self.assertEqual(first['score'],second['score'])
 def test_stage2_results_are_shared_across_postings(self):
  r,_=self.run_analysis({'items':[self.item('Python',1)]},{'Python':{'evidence':['L1'],'level':4}},desc='Python required.')
  r2,seen=self.run_analysis({'items':[self.item('Python',1),self.item('Rust',2)]},{'Rust':{'level':0}},desc='Python needed. Rust preferred.')
  self.assertEqual(len(seen),2)  # stage 1 + Rust only; Python came from the cache
 def test_stop_hook_cancels_between_calls_and_keeps_completed_work(self):
  stage1={'items':[self.item('Python',1),self.item('Docker',2)]};calls=[]
  def gen(model,prompt,system,num_predict=3600):
   calls.append(prompt);return stage1 if prompt.startswith('TASK: List every') else {'evidence':['L1'],'level':4}
  ai.LOCAL.should_stop=lambda:len(calls)>=2  # stop after stage 1 and one judgement
  try:
   with patch.object(ai,'generate',side_effect=gen):
    with self.assertRaises(ai.Cancelled):ai.analyze('Python required. Docker preferred.','Built Python pipelines','test',shortcut=False)
  finally:ai.LOCAL.should_stop=None
  with patch.object(ai,'generate',side_effect=gen) as g:
   ai.analyze('Python required. Docker preferred.','Built Python pipelines','test',shortcut=False)
  self.assertEqual(g.call_count,1)  # only the unfinished requirement is re-judged
 def run_analysis(self,stage1,answers,desc='Python required. Docker preferred.',resume='Built Python pipelines\nSQL work',**kw):
  # Dispatch on prompt text so tests do not depend on call order.
  import re
  seen=[]
  def gen(model,prompt,system,num_predict=3600):
   seen.append(prompt)
   if prompt.startswith('TASK: List every'):return stage1
   a=answers[re.search(r'REQUIREMENT: "(.*?)"',prompt).group(1)]
   return a(len(seen)) if callable(a) else a
  with patch.object(ai,'generate',side_effect=gen):r=ai.analyze(desc,resume,'test',shortcut=False,**kw)
  return r,seen
 def item(self,req,sent,importance='required',kind='skill',group=None):return {'req':req,'sent':sent,'importance':importance,'kind':kind,'group':group or req}
 def test_invalid_sentence_ids_are_dropped(self):
  with self.assertRaises(ValueError):self.run_analysis({'items':[self.item('X',99)]},{})
 def test_graded_score_and_exact_line_citation(self):
  r,seen=self.run_analysis({'items':[self.item('Python',1),self.item('Docker',2,'preferred')]},{'Python':{'evidence':['L1'],'level':4},'Docker':{'evidence':['L2'],'level':2,'missing':'no containers','to_close':'Containerize a project.'}})
  py,dk=r['requirements']
  self.assertEqual((py['assessment'],py['resume_evidence'],py['evidence_verified']),('supported','Built Python pipelines',True))
  self.assertEqual((dk['assessment'],dk['level'],dk['suggestion']),('partial',2,'no containers Containerize a project.'))
  self.assertEqual(r['score'],83)  # (2*1 + 1*.5) / 3
 def test_invalid_line_id_retries_with_reason_then_scores_zero(self):
  r,seen=self.run_analysis({'items':[self.item('Python',1),self.item('Docker',2)]},{'Python':{'evidence':['L99'],'level':3},'Docker':{'level':0}})
  self.assertEqual(len(seen),4);self.assertIn('L99 does not exist',seen[2])
  self.assertEqual(r['requirements'][0]['level'],None)
 def test_failed_item_is_excluded_not_zeroed(self):
  r,_=self.run_analysis({'items':[self.item('Python',1),self.item('Docker',2)]},{'Python':{'evidence':['L1'],'level':4},'Docker':{'level':'lots'}})
  self.assertEqual((r['score'],r['scored'],r['total']),(100,1,2))
 def test_fact_citation_counts_as_evidence(self):
  r,seen=self.run_analysis({'items':[self.item('Docker',2)]},{'Docker':{'evidence':['F1'],'level':4}},memory='I use Docker daily')
  row=r['requirements'][0]
  self.assertEqual((row['assessment'],row['profile_evidence'],row['resume_evidence']),('supported','I use Docker daily',''))
  self.assertIn('F1 I use Docker daily',seen[1])
 def test_contradiction_caps_level_and_zero_level_ignores_evidence(self):
  r,_=self.run_analysis({'items':[self.item('PhD',1),self.item('Docker',2)]},{'PhD':{'evidence':['L1'],'level':4,'contradicted':True},'Docker':{'evidence':['L1'],'level':0}})
  self.assertEqual((r['requirements'][0]['level'],r['requirements'][0]['assessment']),(3,'partial'))
  self.assertEqual((r['requirements'][1]['assessment'],r['requirements'][1]['resume_lines']),('unclear',[]))
 def test_group_members_share_weight_and_eligibility_is_unscored(self):
  items=[self.item('A',1,group='g'),self.item('B',1,group='g'),self.item('Degree',2,kind='degree'),self.item('Visa',2,kind='eligibility')]
  r,_=self.run_analysis({'items':items},{'A':{'evidence':['L1'],'level':4},'B':{'evidence':['L1'],'level':4},'Degree':{'evidence':[],'level':0},'Visa':{'evidence':[],'level':0}})
  self.assertEqual([x['weight'] for x in r['requirements']],[1,1,2,0])
  self.assertEqual(r['score'],50)
 def test_skill_shortcut_makes_no_model_call(self):
  def gen(model,prompt,system,num_predict=3600):
   self.assertTrue(prompt.startswith('TASK: List every'));return {'items':[self.item('Python',1)]}
  with patch.object(ai,'generate',side_effect=gen):r=ai.analyze('Python required.','Built Python pipelines','test')
  self.assertEqual((r['score'],r['requirements'][0]['resume_evidence']),(100,'Built Python pipelines'))
 def test_stage2_prompts_share_prefix_and_dates_are_computed(self):
  r,seen=self.run_analysis({'items':[self.item('Python',1),self.item('Docker',2)]},{'Python':{'level':0},'Docker':{'level':0}},resume='Engineer  July 2025 - Present\nPlanner  June 2023 - December 2023',today=__import__('datetime').date(2026,10,29))
  self.assertEqual(seen[1].split('REQUIREMENT:')[0],seen[2].split('REQUIREMENT:')[0])
  self.assertIn('[16 months, ongoing]',seen[1]);self.assertIn('[7 months]',seen[1]);self.assertIn('TODAY: 2026-10-29',seen[1])
 def test_cloud_and_embedding_filters(self):
  with patch.object(ai,'call',side_effect=[{'models':[{'name':'qwen3:4b'},{'name':'nomic-embed-text'},{'name':'cloud-model','remote_host':'example.com'}]},{'models':[]} ]):
   self.assertEqual(ai.discover()['models'],['qwen3:4b'])
 def test_cloud_model_cannot_run(self):
  with patch.object(ai,'discover',return_value={'models':[]}):
   with self.assertRaises(ValueError):ai.validate_model('cloud-model')
 def test_existing_server_is_reused(self):
  with patch.object(ai,'discover',return_value={'connected':True,'models':[]}),patch.object(ai.subprocess,'Popen') as p:
   self.assertTrue(ai.ensure_server('/unused')['connected']);p.assert_not_called()

 def test_user_messages_become_numbered_facts(self):
  r,seen=self.run_analysis({'items':[self.item('Python',1)]},{'Python':{'level':0}},memory='Graduated in 2026',conversation=[{'role':'user','content':'Review my projects'},{'role':'assistant','content':'Sure'}])
  self.assertIn('F1 Graduated in 2026',seen[1]);self.assertIn('F2 Review my projects',seen[1]);self.assertNotIn('Sure',seen[1])
