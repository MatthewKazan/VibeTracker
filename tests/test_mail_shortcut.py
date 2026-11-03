import unittest
from unittest.mock import patch
import mail_shortcut as shortcut

class ShortcutTests(unittest.TestCase):
 def test_legacy_app_can_still_read_confirmation_output(self):
  with patch.object(shortcut.ai,'generate',return_value={'kind':'confirmation','evidence':'Thanks'}):
   self.assertEqual(shortcut.process({'mode':'classify','model':'test','email':{'body':'Thanks'}})['kind'],'other')
 def test_new_protocol_preserves_confirmations_and_job_context(self):
  jobs=[{'id':7,'company':'Example','title':'Engineer'}]
  with patch.object(shortcut.ai,'generate',return_value={'kind':'confirmation'}) as generate:
   self.assertEqual(shortcut.process({'mode':'classify','model':'test','jobs':jobs,'email':{'body':'Thanks'}})['kind'],'confirmation')
   self.assertIn('"id": 7',generate.call_args.args[1]);self.assertIn('"company": "Example"',generate.call_args.args[1])
 def test_missing_batch_ids_can_only_be_recovered_from_unique_exact_quotes(self):
  emails=[{'message_id':'one','subject':'Receipt','body':'Received your application.'},{'message_id':'two','subject':'Update','body':'We are not proceeding.'}]
  result={'classifications':[{'kind':'confirmation','evidence':'Received your application.'},{'kind':'rejection','evidence':'We are not proceeding.'}]}
  with patch.object(shortcut.ai,'generate',return_value=result):output=shortcut.process({'mode':'classify','model':'test','jobs':[],'emails':emails})
  self.assertEqual([r['message_id'] for r in output['classifications']],['one','two'])
 def test_ambiguous_quote_never_guesses_batch_identity(self):
  emails=[{'message_id':str(i),'body':'Thanks for applying.'} for i in range(2)]
  with patch.object(shortcut.ai,'generate',return_value={'classifications':[{'kind':'confirmation','evidence':'Thanks for applying.'}]}):
   output=shortcut.process({'mode':'classify','model':'test','jobs':[],'emails':emails})
  self.assertNotIn('message_id',output['classifications'][0])
 def test_type_only_protocol_does_not_demote_confirmations_or_request_job_linking(self):
  with patch.object(shortcut.ai,'generate',return_value={'kind':'confirmation','evidence':'Received'}) as generate:
   output=shortcut.process({'mode':'classify','type_only':True,'model':'test','email':{'body':'Received your application.'}})
  self.assertEqual(output['kind'],'confirmation');self.assertIn('handled separately',generate.call_args.args[1]);self.assertNotIn('"jobs":',generate.call_args.args[1])
 def test_type_only_model_cannot_demote_an_explicit_receipt_with_conditional_interview(self):
  with patch.object(shortcut.ai,'generate',return_value={'kind':'other','evidence':'If selected'}):
   result=shortcut.process({'mode':'classify','type_only':True,'model':'test','email':{'subject':'Application received','body':'Thank you for applying. If selected we will invite you to interview.'}})
  self.assertEqual(result['kind'],'confirmation')
