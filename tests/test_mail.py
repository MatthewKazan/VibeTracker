import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import app
import mail_integration as mail
import mail_pipeline as pipeline

class MailTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.data=patch.object(app,'DATA',Path(self.tmp.name));self.data.start()
        self.db=patch.object(app,'DB',Path(self.tmp.name)/'jobs.sqlite3');self.db.start()
        app.init()
        with app.connect() as c:c.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",("mail_use_shortcut","false"))
        with app.connect() as c:
            self.a=app.save_job(c,{'title':'Backend Engineer','company':'Acme','status':'Interview 2'})
            self.b=app.save_job(c,{'title':'Product Designer','company':'Acme','status':'Waiting'})
        with app.connect() as c:c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('mail_account',json.dumps({'id':'test-account','name':'Job search','addresses':['jobs@example.test']})))
        self.bounds_start=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=2)).isoformat();self.bounds_patch=patch.object(mail,'read_bounds',return_value={'oldest':self.bounds_start});self.bounds_patch.start()
        mail.SYNC.update(running=False,error='',summary='')
    def tearDown(self):
        self.bounds_patch.stop();self.db.stop();self.data.stop();self.tmp.cleanup()
    def message(self,id='one',role='Backend Engineer'):
        return dict(message_id=id,sender='Acme Recruiting <jobs@acme.com>',subject='Your application '+role,body='Thank you for applying. We are not moving forward with your application for '+role+'.',received_at='2026-11-01T12:00:00+00:00')
    def ingest(self,*messages):
        with app.connect() as c:return mail.ingest(c,messages,app.save_job,account_id='test-account')
    def status(self,id):
        with app.connect() as c:return c.execute('SELECT status FROM jobs WHERE id=?',(id,)).fetchone()[0]
    def test_exact_role_pending_then_approve(self):
        self.ingest(self.message())
        self.assertEqual(self.status(self.a),'Interview 2');self.assertEqual(self.status(self.b),'Waiting')
        with app.connect() as c:
            self.assertEqual(mail.inbox(c)['messages'][0]['job_ids'],[self.a])
            mail.review(c,'one','approve',[self.a],app.save_job)
        self.assertEqual(self.status(self.a),'Rejected')
        self.assertEqual(next(j for j in app.current_jobs() if j['id']==self.a)['interviews_completed'],2)
    def test_company_only_requires_selection_and_links_all(self):
        self.ingest(self.message(role=''))
        with app.connect() as c:
            self.assertEqual(set(mail.inbox(c)['messages'][0]['job_ids']),{self.a,self.b})
            with self.assertRaises(ValueError):mail.review(c,'one','approve',[],app.save_job)
            mail.review(c,'one','approve',[self.b],app.save_job)
        self.assertEqual(self.status(self.a),'Interview 2');self.assertEqual(self.status(self.b),'Rejected')
    def test_dismiss_preserves_subsequent_manual_edit(self):
        self.ingest(self.message())
        with app.connect() as c:app.save_job(c,{'status':'Offer'},self.a);mail.review(c,'one','dismiss',[],app.save_job)
        self.assertEqual(self.status(self.a),'Offer')
    def test_dismiss_restores_original_and_duplicates_skip(self):
        self.assertEqual(self.ingest(self.message()),1)
        self.assertEqual(self.ingest(self.message()),0)
        with app.connect() as c:mail.review(c,'one','dismiss',[],app.save_job)
        self.assertEqual(self.status(self.a),'Interview 2')
    def test_multiple_proposals_restore_only_after_last_dismissal(self):
        self.ingest(self.message(),self.message('two'))
        with app.connect() as c:mail.review(c,'one','dismiss',[],app.save_job)
        self.assertEqual(self.status(self.a),'Interview 2')
        with app.connect() as c:mail.review(c,'two','dismiss',[],app.save_job)
        self.assertEqual(self.status(self.a),'Interview 2')
    def test_approve_then_dismiss_other_does_not_revert(self):
        self.ingest(self.message(),self.message('two'))
        with app.connect() as c:mail.review(c,'one','approve',[self.a],app.save_job);mail.review(c,'two','dismiss',[],app.save_job)
        self.assertEqual(self.status(self.a),'Rejected')
    def test_company_word_boundary_and_unmatched_retained(self):
        m=self.message();m['sender']='Acmeology';m['body']='An application for Acmeology';m['subject']='Acmeology'
        self.ingest(m)
        with app.connect() as c:self.assertEqual(mail.inbox(c)['messages'][0]['job_ids'],[])
    def test_not_every_company_email_is_a_rejection(self):
        m=self.message();m['body']='Thank you for applying for Backend Engineer. We have received your application.'
        self.ingest(m)
        self.assertEqual(self.status(self.a),'Interview 2')
    def test_relink_unmatched_and_review(self):
        m=self.message();m['sender']='Recruiter';m['body']='Your application was rejected.';m['subject']='Update'
        self.ingest(m)
        with app.connect() as c:
            mail.review(c,'one','link',[self.b],app.save_job)
            mail.review(c,'one','approve',[self.b],app.save_job)
        self.assertEqual(self.status(self.b),'Rejected')
    def test_atomic_scan_no_checkpoint_on_failure_then_catchup(self):
        with patch.object(mail,'read_mail',side_effect=ValueError('Mail unavailable')):mail.sync(app)
        with app.connect() as c:self.assertFalse(mail.checkpoint(c,'test-account'))
        with patch.object(mail,'read_mail',return_value=[self.message()]):mail.sync(app)
        with app.connect() as c:
            checkpoint=mail.checkpoint(c,'test-account')
            self.assertEqual(checkpoint['last_message_id'],'one')
        with patch.object(mail,'read_mail',return_value=[self.message()]) as reader:mail.sync(app)
        self.assertLess(dt.datetime.fromisoformat(reader.call_args.args[0]),dt.datetime.fromisoformat(checkpoint['through']))
        with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM emails').fetchone()[0],1)
    def test_bad_message_rolls_back_whole_batch_and_checkpoint(self):
        with patch.object(mail,'read_mail',return_value=[self.message(),{'bad':'record'}]):mail.sync(app)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM emails').fetchone()[0],0)
            self.assertFalse(mail.checkpoint(c,'test-account'))
        self.assertEqual(self.status(self.a),'Interview 2')
    def test_export_restore_remaps_links_and_preserves_decision(self):
        self.ingest(self.message())
        with app.connect() as c:
            mail.review(c,'one','approve',[self.a],app.save_job)
            data=json.loads(json.dumps(mail.export(c)))
            c.execute('DELETE FROM emails');c.execute('DELETE FROM email_jobs')
            mail.restore(c,data,{self.a:self.b})
            self.assertEqual(mail.inbox(c)['messages'][0]['job_ids'],[self.b])
            self.assertEqual(mail.inbox(c)['messages'][0]['review'],'approved')
    def test_cannot_approve_unlinked_or_already_reviewed(self):
        self.ingest(self.message())
        with app.connect() as c:
            with self.assertRaises(ValueError):mail.review(c,'one','approve',[self.b],app.save_job)
            mail.review(c,'one','approve',[self.a],app.save_job)
            with self.assertRaises(ValueError):mail.review(c,'one','approve',[self.a],app.save_job)

    def test_interview_and_technical_test_requests_pin_pending(self):
        for n,body in enumerate(['We would like to invite you to an interview for Backend Engineer.', 'Please complete the technical assessment for Backend Engineer by Friday.', 'Please share your availability for an interview for Backend Engineer.']):
            m=self.message('invite'+str(n));m['subject']='Acme next steps';m['body']=body
            self.ingest(m)
            self.assertEqual(self.status(self.a),'Interview 2')
            with app.connect() as c:
                email=next(e for e in mail.inbox(c)['messages'] if e['message_id']==m['message_id'])
                self.assertEqual(email['invitation'],1)
                self.assertEqual(email['rejection'],0)
    def test_conditional_and_generic_interview_mentions_do_not_change_status(self):
        for n,body in enumerate(['Thanks for your application. If we want to continue we will invite you to interview.', 'If selected, please schedule your interview.', 'We may invite you to a technical assessment.', 'The next stage in our hiring process is a technical test.', 'Thank you for applying. We will contact you if we want to arrange an interview.']):
            m=self.message('generic'+str(n));m['body']=body
            self.ingest(m)
            self.assertEqual(self.status(self.a),'Interview 2')
    def test_company_only_interview_request_requires_job_choice(self):
        m=self.message(role='');m['body']='Please book an interview with our team.'
        self.ingest(m)
        self.assertEqual(self.status(self.a),'Interview 2');self.assertEqual(self.status(self.b),'Waiting')
        with app.connect() as c:mail.review(c,'one','approve',[self.b],app.save_job)
        self.assertEqual(self.status(self.b),'Interview pending')

    def test_disapproval_shortcut_proposes_prompt_without_applying(self):
        self.ingest(self.message())
        with app.connect() as c:
            mail.review(c,'one','dismiss',[],app.save_job)
            c.execute('INSERT INTO email_feedback (message_id,reason,base_prompt) VALUES (?,?,?)',('one','Conditional text',mail.get_prompt(c)))
        proposal=mail.DEFAULT_PROMPT+' Ignore conditional invitations.'
        with patch.object(mail,'run_shortcut',return_value={'proposed_prompt':proposal,'explanation':'Conditional wording was misread.'}) as runner:
            mail.analyze_feedback(app,'one')
            self.assertEqual(runner.call_args.args[0],'JobTracker Email Review')
            self.assertEqual(runner.call_args.args[1]['mode'],'feedback')
        with app.connect() as c:
            self.assertEqual(mail.get_prompt(c),mail.DEFAULT_PROMPT)
            self.assertEqual(c.execute('SELECT state FROM email_feedback').fetchone()[0],'ready')
            mail.apply_feedback(c,'one')
            self.assertEqual(mail.get_prompt(c),proposal)
        self.assertEqual(self.status(self.a),'Interview 2')
    def test_failed_shortcut_retains_feedback_and_status(self):
        self.ingest(self.message())
        with app.connect() as c:c.execute('INSERT INTO email_feedback (message_id,reason,base_prompt) VALUES (?,?,?)',('one','Wrong company',mail.get_prompt(c)))
        with patch.object(mail,'run_shortcut',side_effect=ValueError('Shortcut unavailable')):mail.analyze_feedback(app,'one')
        with app.connect() as c:
            feedback=c.execute('SELECT * FROM email_feedback').fetchone()
            self.assertEqual(feedback['state'],'failed');self.assertIn('unavailable',feedback['error'])
            self.assertEqual(mail.get_prompt(c),mail.DEFAULT_PROMPT)
        self.assertEqual(self.status(self.a),'Interview 2')
    def test_stale_prompt_proposal_cannot_overwrite_new_prompt(self):
        with app.connect() as c:
            c.execute("INSERT INTO email_feedback (message_id,reason,base_prompt,proposal,state) VALUES (?,?,?,?,'ready')",('one','Wrong',mail.DEFAULT_PROMPT,'Proposed'))
            c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('mail_prompt',json.dumps('New current prompt')))
            with self.assertRaises(ValueError):mail.apply_feedback(c,'one')
    def test_shortcut_classification_still_requires_manual_approval(self):
        with app.connect() as c:c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('mail_use_shortcut','true'))
        m=self.message();m['body']='Please book an interview for Backend Engineer at Acme.'
        with patch.object(mail,'read_mail',return_value=[m]):mail.sync(app)
        with patch.object(mail,'run_shortcut',return_value={'kind':'interview','evidence':m['body']}):pipeline.analyze_pending(app)
        self.assertEqual(self.status(self.a),'Interview 2')
        with app.connect() as c:
            self.assertEqual(mail.inbox(c)['messages'][0]['invitation'],1)
            mail.review(c,'one','approve',[self.a],app.save_job)
        self.assertEqual(self.status(self.a),'Interview pending')

    def test_unverified_quote_is_visible_for_manual_review_without_stalling_collection(self):
        with app.connect() as c:c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('mail_use_shortcut','true'))
        with patch.object(mail,'read_mail',return_value=[self.message()]):mail.sync(app)
        with patch.object(mail,'run_shortcut',return_value={'kind':'interview','evidence':'Invented quote'}):pipeline.analyze_pending(app)
        with app.connect() as c:
            self.assertTrue(mail.checkpoint(c,'test-account'))
            email=mail.inbox(c)['messages'][0]
            self.assertEqual(email['analysis_state'],'warning');self.assertEqual(email['review'],'none');self.assertEqual(email['evidence'],'')
        self.assertEqual(self.status(self.a),'Interview 2')

    def test_sync_requires_explicit_account_before_reading_mail(self):
        with app.connect() as c:c.execute("DELETE FROM settings WHERE key='mail_account'")
        with patch.object(mail,'read_mail') as reader:mail.sync(app);reader.assert_not_called()
        self.assertIn('Choose',mail.SYNC['error'])
    def test_sync_passes_only_selected_account_to_reader(self):
        with patch.object(mail,'read_mail',return_value=[]) as reader:mail.sync(app)
        self.assertEqual(reader.call_args.args[2],'test-account')
    def test_switch_accounts_has_independent_checkpoint_and_messages(self):
        with patch.object(mail,'read_mail',return_value=[self.message()]):mail.sync(app)
        with app.connect() as c:
            first=mail.checkpoint(c,'test-account')
            self.assertTrue(first['through'])
        accounts=[{'id':'other-account','name':'Other','addresses':['other@example.test']},{'id':'test-account','name':'Jobs','addresses':['jobs@example.test']}]
        with patch.object(mail,'list_accounts',return_value=accounts):mail.select_account(app,'other-account')
        with app.connect() as c:
            self.assertEqual(mail.inbox(c)['messages'],[])
            self.assertEqual(mail.inbox(c)['sync'],{})
        other=self.message('other-message')
        with patch.object(mail,'read_mail',return_value=[other]) as reader:mail.sync(app)
        self.assertEqual(reader.call_args.args[2],'other-account')
        with app.connect() as c:
            self.assertEqual([m['message_id'] for m in mail.inbox(c)['messages']],['other-message'])
            self.assertEqual(mail.checkpoint(c,'test-account'),first)
        with patch.object(mail,'list_accounts',return_value=accounts):mail.select_account(app,'test-account')
        with app.connect() as c:self.assertEqual([m['message_id'] for m in mail.inbox(c)['messages']],['one'])
    def test_invalid_or_busy_account_change_keeps_selection(self):
        with patch.object(mail,'list_accounts',return_value=[]):
            with self.assertRaises(ValueError):mail.select_account(app,'missing-account')
        mail.SYNC_LOCK.acquire()
        try:
            with patch.object(mail,'list_accounts') as reader:
                with self.assertRaises(ValueError):mail.select_account(app,'other-account')
                reader.assert_not_called()
        finally:mail.SYNC_LOCK.release()
        with app.connect() as c:self.assertEqual(mail.get_setting(c,'mail_account')['id'],'test-account')
    def test_shared_message_id_can_belong_to_two_accounts_without_duplication(self):
        self.ingest(self.message())
        with app.connect() as c:
            mail.ingest(c,[self.message()],app.save_job,account_id='other-account')
            c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('mail_account',json.dumps({'id':'other-account'})))
            self.assertEqual(len(mail.inbox(c)['messages']),1)
            self.assertEqual(c.execute('SELECT count(*) FROM emails').fetchone()[0],1)

    def test_ignore_and_restore_do_not_change_status_or_create_feedback(self):
        self.ingest(self.message())
        with app.connect() as c:
            mail.review(c,'one','ignore',[],app.save_job)
            self.assertEqual(c.execute('SELECT review FROM emails').fetchone()[0],'ignored')
            self.assertEqual(c.execute('SELECT count(*) FROM email_feedback').fetchone()[0],0)
            mail.review(c,'one','unignore',[],app.save_job)
            self.assertEqual(c.execute('SELECT review FROM emails').fetchone()[0],'pending')
        self.assertEqual(self.status(self.a),'Interview 2')
    def test_ignoring_older_interview_preserves_newer_rejection(self):
        invite=self.message('old-interview');invite['body']='Please book an interview for Backend Engineer.'
        reject=self.message('new-rejection');reject['received_at']='2026-11-02T12:00:00+00:00'
        self.ingest(invite,reject)
        with app.connect() as c:
            mail.review(c,'new-rejection','approve',[self.a],app.save_job)
            mail.review(c,'old-interview','ignore',[],app.save_job)
        self.assertEqual(self.status(self.a),'Rejected')
    def test_confirmation_is_retained_without_status_change(self):
        m=self.message();m['sender']='Automated receipt';m['subject']='Thanks for applying';m['body']='Thank you for your interest. We will be in touch.'
        self.ingest(m)
        with app.connect() as c:
            email=mail.inbox(c)['messages'][0]
            self.assertEqual(email['category'],'confirmation');self.assertEqual(email['review'],'none')
        self.assertEqual(self.status(self.a),'Interview 2')
    def test_type_classifier_only_receives_saved_company_email(self):
        with app.connect() as c:c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('mail_use_shortcut','true'))
        m=self.message();m['sender']='Acme';m['subject']='We got it';m['body']='Thanks! Your details are with our team.'
        with patch.object(mail,'read_mail',return_value=[m]):mail.sync(app)
        with patch.object(mail,'run_shortcut',return_value={'kind':'confirmation','evidence':'Thanks!'}) as runner:pipeline.analyze_pending(app)
        payload=runner.call_args.args[1]
        self.assertTrue(payload['type_only']);self.assertNotIn('jobs',payload)
        with app.connect() as c:
            email=mail.inbox(c)['messages'][0];self.assertEqual(email['category'],'confirmation');self.assertEqual(set(email['job_ids']),{self.a,self.b})

    def test_company_scope_expands_ai_link_to_all_company_roles(self):
        with app.connect() as c:
            mail.ingest(c,[self.message()],app.save_job,{'one':{'kind':'confirmation','evidence':'','job_ids':[self.a],'match_kind':'company'}},'test-account')
            self.assertEqual(set(mail.inbox(c)['messages'][0]['job_ids']),{self.a,self.b})
    def test_ai_job_ids_cannot_override_deterministic_links(self):
        with app.connect() as c:c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('mail_use_shortcut','true'))
        with patch.object(mail,'read_mail',return_value=[self.message()]):mail.sync(app)
        with patch.object(mail,'run_shortcut',return_value={'kind':'confirmation','job_ids':[999999],'evidence':''}):pipeline.analyze_pending(app)
        with app.connect() as c:
            self.assertTrue(mail.checkpoint(c,'test-account'));self.assertEqual(mail.inbox(c)['messages'][0]['job_ids'],[self.a])

    def test_collection_is_committed_before_individual_classification(self):
        with app.connect() as c:c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('mail_use_shortcut','true'))
        messages=[self.message(str(i)) for i in range(3)]
        with patch.object(mail,'read_mail',return_value=messages),patch.object(mail,'run_shortcut') as runner:mail.sync(app);runner.assert_not_called()
        with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM emails').fetchone()[0],3)
        with patch.object(mail,'run_shortcut',return_value={'kind':'confirmation','evidence':''}) as runner:pipeline.analyze_pending(app)
        self.assertEqual(runner.call_count,3)
        with app.connect() as c:self.assertEqual(c.execute("SELECT count(*) FROM emails WHERE category='confirmation'").fetchone()[0],3)

    def test_bad_classifier_response_does_not_block_other_saved_emails(self):
        with app.connect() as c:c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('mail_use_shortcut','true'))
        with patch.object(mail,'read_mail',return_value=[self.message('one'),self.message('two')]):mail.sync(app)
        with patch.object(mail,'run_shortcut',side_effect=[{'classifications':[]},{'kind':'confirmation','evidence':''}]):pipeline.analyze_pending(app)
        with app.connect() as c:
            self.assertTrue(mail.checkpoint(c,'test-account'));self.assertEqual(c.execute("SELECT count(*) FROM emails WHERE analysis_state='failed'").fetchone()[0],1)
            self.assertEqual(c.execute("SELECT count(*) FROM emails WHERE analysis_state='done'").fetchone()[0],1)

    def test_old_checkpoint_causes_recovery_scan(self):
        with app.connect() as c:c.execute('INSERT INTO mail_checkpoints VALUES (?,?,?)',('test-account','through','2026-11-01T12:00:00+00:00'))
        with patch.object(mail,'read_mail',return_value=[]) as reader:mail.sync(app)
        with app.connect() as c:earliest=c.execute('SELECT min(date_applied) FROM jobs').fetchone()[0]
        self.assertEqual(reader.call_args_list[0].args[0],self.bounds_start)
    def test_rescan_reanalyzes_legacy_unreviewed_email_but_preserves_decision(self):
        m=self.message();m['body']='Thank you for applying for Backend Engineer.'
        self.ingest(m)
        with app.connect() as c:c.execute("UPDATE emails SET analysis_version='',company='',match_kind='unlinked'")
        with app.connect() as c:
            mail.ingest(c,[m],app.save_job,{'one':{'kind':'confirmation','evidence':'','job_ids':[self.a],'match_kind':'role'}},'test-account')
            self.assertEqual(mail.inbox(c)['messages'][0]['job_ids'],[self.a])
        self.ingest(self.message('rejection'))
        with app.connect() as c:
            mail.review(c,'rejection','approve',[self.a],app.save_job)
            c.execute("UPDATE emails SET analysis_version='' WHERE message_id='rejection'")
            mail.ingest(c,[self.message('rejection')],app.save_job,{'rejection':{'kind':'confirmation','evidence':''}},'test-account')
            self.assertEqual(c.execute("SELECT review FROM emails WHERE message_id='rejection'").fetchone()[0],'approved')
    def test_recovery_preserves_manually_selected_application_links(self):
        m=self.message();m['body']='Thank you for applying.'
        self.ingest(m)
        with app.connect() as c:
            mail.review(c,'one','link',[self.b],app.save_job)
            c.execute("UPDATE emails SET analysis_version='' WHERE message_id='one'")
            mail.ingest(c,[m],app.save_job,{'one':{'kind':'confirmation','job_ids':[self.a],'match_kind':'role','evidence':''}},'test-account')
            email=mail.inbox(c)['messages'][0]
            self.assertEqual(email['job_ids'],[self.b]);self.assertEqual(email['match_kind'],'manual')
