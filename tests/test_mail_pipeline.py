import json
import unittest
from unittest.mock import patch
import app
import mail_integration as mail
import mail_pipeline as pipeline
import test_mail as base

class PipelineTests(unittest.TestCase):
    setUp=base.MailTests.setUp
    tearDown=base.MailTests.tearDown
    message=base.MailTests.message
    status=base.MailTests.status
    def collect(self,messages):
        with app.connect() as c:
            jobs=[dict(r) for r in c.execute('SELECT * FROM jobs')]
            return pipeline.collect(c,messages,jobs,'test-account')
    def classify(self,id,kind,evidence=''):
        with app.connect() as c:pipeline.classify_one(c,dict(c.execute('SELECT * FROM emails WHERE message_id=?',(id,)).fetchone()),{'kind':kind,'evidence':evidence})
    def test_company_only_message_is_collected_even_without_any_hiring_keywords(self):
        m=self.message();m['subject']='Acme engineering newsletter';m['body']='This month we redesigned the robot arm.'
        self.assertEqual(self.collect([m]),1)
        with app.connect() as c:
            e=mail.inbox(c)['messages'][0];self.assertEqual(set(e['job_ids']),{self.a,self.b});self.assertEqual(e['analysis_state'],'queued');self.assertEqual(e['review'],'none')
        self.assertEqual(self.status(self.a),'Interview 2')
    def test_activity_explains_delivered_alerts_and_read_does_not_approve(self):
        self.collect([self.message()]);self.classify('one','interview','')
        with app.connect() as c:
            c.execute('UPDATE email_events SET delivered=1')
            feed=pipeline.activity(c);self.assertEqual(len(feed['items']),1)
            item=feed['items'][0];self.assertTrue(item['urgent']);self.assertEqual(item['proposed_status'],'Interview pending')
            self.assertEqual(feed['unread'],1)
            pipeline.mark_activity_seen(c,item['event_id'],'one')
            feed=pipeline.activity(c);self.assertEqual(feed['unread'],0);self.assertEqual(feed['pending'],1)
            self.assertEqual(c.execute("SELECT review FROM emails WHERE message_id='one'").fetchone()[0],'pending')
            mail.review(c,'one','approve',[self.a],app.save_job)
            feed=pipeline.activity(c);self.assertEqual(feed['pending'],0);self.assertEqual(feed['items'][0]['review'],'approved')
    def test_activity_read_checkpoint_preserves_new_alerts_and_other_accounts(self):
        self.collect([self.message()])
        with app.connect() as c:checkpoint=pipeline.activity(c)['items'][0]['event_id']
        self.classify('one','rejection','')
        with app.connect() as c:
            pipeline.mark_activity_seen(c,checkpoint,'one');self.assertEqual(pipeline.activity(c)['unread'],1)
            c.execute('UPDATE email_accounts SET account_id=?',('other-account',))
            self.assertEqual(pipeline.activity(c)['total'],0)
            pipeline.mark_activity_seen(c,1000)
            self.assertEqual(c.execute('SELECT min(seen) FROM email_events').fetchone()[0],0)
    def test_manual_links_survive_collection_and_can_be_changed_after_approval(self):
        m=self.message();self.collect([m]);self.classify('one','rejection','')
        with app.connect() as c:
            mail.review(c,'one','approve',[self.a],app.save_job)
            mail.review(c,'one','link',[self.b],app.save_job)
        self.collect([m])
        with app.connect() as c:
            self.assertEqual([r[0] for r in c.execute('SELECT job_id FROM email_jobs WHERE message_id=?',('one',))],[self.b])
            self.assertEqual(c.execute('SELECT job_id FROM email_decisions WHERE message_id=?',('one',)).fetchone()[0],self.a)
        self.assertEqual(self.status(self.a),'Rejected');self.assertNotEqual(self.status(self.b),'Rejected')
    def test_unrelated_email_is_not_sent_to_ai_or_stored(self):
        m=self.message();m['subject']='Weekend';m['sender']='Friend';m['body']='See you Saturday'
        self.assertEqual(self.collect([m]),0)
        with patch.object(mail,'run_shortcut') as model:pipeline.analyze_pending(app);model.assert_not_called()
    def test_collection_calls_mail_search_with_companies_and_commits_before_ai(self):
        with patch.object(mail,'read_mail',return_value=[self.message()]) as reader,patch.object(mail,'run_shortcut') as model:mail.sync(app);model.assert_not_called()
        self.assertEqual(reader.call_args.args[0],self.bounds_start);self.assertIn('Acme',reader.call_args.args[3][0]['terms'])
        with app.connect() as c:self.assertTrue(mail.checkpoint(c,'test-account')['through']);self.assertEqual(mail.inbox(c)['total'],1)
    def test_shortcut_failure_keeps_email_and_scan_checkpoint_and_other_work_continues(self):
        with app.connect() as c:c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('mail_use_shortcut','true'))
        with patch.object(mail,'read_mail',return_value=[self.message('one'),self.message('two')]):mail.sync(app)
        with patch.object(mail,'run_shortcut',side_effect=[ValueError('Shortcut failed'),{'kind':'confirmation','evidence':''}]):pipeline.analyze_pending(app)
        with app.connect() as c:
            self.assertTrue(mail.checkpoint(c,'test-account')['through']);self.assertEqual(mail.inbox(c)['total'],2)
            self.assertEqual(c.execute("SELECT count(*) FROM emails WHERE analysis_state='failed'").fetchone()[0],1)
            self.assertEqual(c.execute("SELECT count(*) FROM emails WHERE analysis_state='done'").fetchone()[0],1)
    def test_typographic_quote_normalization_avoids_false_rejection_of_evidence(self):
        m=self.message();m['body']='We’re not moving\n forward with your application.';self.collect([m]);self.classify('one','rejection',"We're not moving forward with your application.")
        with app.connect() as c:
            e=mail.inbox(c)['messages'][0];self.assertEqual(e['review'],'pending');self.assertEqual(e['analysis_state'],'done')
    def test_unverified_quote_still_keeps_original_and_warns_for_human_review(self):
        self.collect([self.message()]);self.classify('one','rejection','A fabricated phrase')
        with app.connect() as c:
            e=mail.inbox(c)['messages'][0];self.assertEqual(e['analysis_state'],'warning');self.assertEqual(e['evidence'],'');self.assertIn('not moving forward',e['body']);self.assertEqual(e['review'],'pending')
        self.assertEqual(self.status(self.a),'Interview 2')
    def test_pending_positive_is_in_application_metadata_without_changing_saved_status(self):
        m=self.message();m['body']='Please book an interview for Backend Engineer.';self.collect([m]);self.classify('one','interview',m['body'])
        j=next(j for j in app.current_jobs() if j['id']==self.a)
        self.assertTrue(j['pending_positive']);self.assertEqual(j['pending_changes'][0]['proposed_status'],'Interview pending');self.assertEqual(j['status'],'Interview 2')
    def test_offer_is_a_manual_positive_proposal(self):
        m=self.message();m['body']='We are pleased to offer you the Backend Engineer role.';self.collect([m]);self.classify('one','offer',m['body'])
        self.assertEqual(self.status(self.a),'Interview 2')
        with app.connect() as c:mail.review(c,'one','approve',[self.a],app.save_job)
        self.assertEqual(self.status(self.a),'Offer')
    def test_old_email_is_ignored_only_after_all_company_roles_have_approved_later_statuses(self):
        old=self.message('old',role='');old['received_at']='2026-09-01T12:00:00+00:00'
        a=self.message('a');a['received_at']='2026-10-01T12:00:00+00:00'
        b=self.message('b',role='Product Designer');b['received_at']='2026-10-05T12:00:00+00:00'
        self.collect([old,a,b]);self.classify('old','interview','');self.classify('a','rejection','');self.classify('b','rejection','')
        with app.connect() as c:
            mail.review(c,'a','approve',[self.a],app.save_job);self.assertNotEqual(c.execute("SELECT review FROM emails WHERE message_id='old'").fetchone()[0],'ignored')
            mail.review(c,'b','approve',[self.b],app.save_job);row=c.execute("SELECT * FROM emails WHERE message_id='old'").fetchone()
            self.assertEqual(row['review'],'ignored');self.assertEqual(row['ignore_source'],'superseded')
            mail.review(c,'old','unignore',[],app.save_job);pipeline.auto_ignore(c)
            self.assertEqual(c.execute("SELECT review FROM emails WHERE message_id='old'").fetchone()[0],'pending')
    def test_confirmed_status_cutoff_also_skips_ai_for_newly_collected_older_mail(self):
        for ident,role in [('a','Backend Engineer'),('b','Product Designer')]:
            m=self.message(ident,role);m['received_at']='2026-11-01T12:00:00+00:00';self.collect([m]);self.classify(ident,'rejection','')
            with app.connect() as c:mail.review(c,ident,'approve',[self.a if ident=='a' else self.b],app.save_job)
        old=self.message('older',role='');old['received_at']='2026-09-01T12:00:00+00:00';self.collect([old])
        with patch.object(mail,'run_shortcut') as model:pipeline.analyze_pending(app);model.assert_not_called()
        with app.connect() as c:self.assertEqual(c.execute("SELECT review FROM emails WHERE message_id='older'").fetchone()[0],'ignored')
    def test_missing_specific_role_is_suggested_but_never_added_automatically(self):
        m=self.message();m['body']='We received your application for Data Engineer at Acme.';self.collect([m]);self.classify('one','confirmation','')
        with app.connect() as c:
            s=c.execute('SELECT * FROM email_missing').fetchone();self.assertEqual(s['title'],'Data Engineer');self.assertEqual(s['state'],'suggested');self.assertEqual(c.execute('SELECT count(*) FROM jobs').fetchone()[0],2)
    def test_confirmation_for_an_existing_role_does_not_create_missing_hint(self):
        m=self.message();m['body']='We received your application for Backend Engineer at Acme.';self.collect([m]);self.classify('one','confirmation','')
        with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM email_missing').fetchone()[0],0)
    def test_receipt_boilerplate_and_missing_space_do_not_invent_missing_roles(self):
        for body in ['Your application for Backend Engineer has been received.', 'Application received, Backend Engineerat Acme role']:
            m=self.message();m['subject']='Thank you';m['body']=body
            self.assertEqual(pipeline.extract_missing_title(m),'Backend Engineer')
        m=self.message();m['subject']='Application received, Backend Engineerat Acme role';m['body']='Thank you for applying.'
        self.assertEqual(pipeline.extract_missing_title(m),'Backend Engineer')
    def test_missing_role_lookup_verifies_title_and_company_and_preserves_fallback(self):
        m=self.message();m['body']='We received your application for Data Engineer at Acme. https://jobs.example.test/jobs/data';self.collect([m]);self.classify('one','confirmation','')
        with app.connect() as c:ident=c.execute('SELECT id FROM email_missing').fetchone()[0]
        raw='<script type="application/ld+json">'+json.dumps({'@type':'JobPosting','title':'Data Engineer','hiringOrganization':{'name':'Acme'},'description':'Build pipelines'})+'</script>'
        with patch.object(app,'fetch',return_value=raw):pipeline.lookup_missing(app,ident)
        with app.connect() as c:self.assertEqual(c.execute('SELECT lookup_state FROM email_missing').fetchone()[0],'found')
        with patch.object(app,'fetch',side_effect=ValueError('Network unavailable')):pipeline.lookup_missing(app,ident)
        with app.connect() as c:
            s=c.execute('SELECT * FROM email_missing').fetchone();self.assertEqual(s['lookup_state'],'not_found');self.assertEqual(s['title'],'Data Engineer');self.assertEqual(s['state'],'suggested')
    def test_notifications_are_durable_and_urgent_only_for_pending_status(self):
        m=self.message();self.collect([m]);self.classify('one','rejection','')
        with app.connect() as c:
            kinds={e['kind'] for e in pipeline.notifications(c)};self.assertEqual(kinds,{'status:rejection'});self.assertEqual(pipeline.activity(c)['total'],1)
            mail.review(c,'one','ignore',[],app.save_job);self.assertEqual(pipeline.notifications(c),[])
    def test_total_and_queue_counts_are_for_selected_account(self):
        self.collect([self.message()])
        with app.connect() as c:
            s=pipeline.summary(c);self.assertEqual(s['total'],1);self.assertEqual(s['queued'],1);self.assertEqual(s['pending'],0)
            self.classify('one','interview','')
            s=pipeline.summary(c);self.assertEqual(s['pending'],1);self.assertEqual(s['queued'],0)
    def test_missing_suggestion_and_approval_survive_export_restore_id_remapping(self):
        m=self.message();m['body']='We received your application for Data Engineer at Acme.';self.collect([m]);self.classify('one','confirmation','')
        reject=self.message('reject');self.collect([reject]);self.classify('reject','rejection','')
        with app.connect() as c:
            mail.review(c,'reject','approve',[self.a],app.save_job);data=mail.export(c)
            c.execute('DELETE FROM email_missing');c.execute('DELETE FROM job_status_approvals');mail.restore(c,data,{self.a:self.a,self.b:self.b})
            self.assertEqual(c.execute('SELECT title FROM email_missing').fetchone()[0],'Data Engineer');self.assertTrue(c.execute('SELECT 1 FROM job_status_approvals').fetchone())
    def test_list_preview_is_small_but_full_body_is_searchable_and_loadable(self):
        m=self.message();m['body']='Acme '+('long paragraph '*300)+' unique-body-needle';self.collect([m])
        with app.connect() as c:
            data=mail.inbox(c,include_body=False,query='unique-body-needle');self.assertEqual(len(data['messages']),1)
            self.assertLessEqual(len(data['messages'][0]['body']),800);self.assertEqual(mail.message_detail(c,'one')['body'],m['body'])
            self.assertEqual(mail.inbox(c,include_body=False,query='unmatched-query')['total'],1)
            self.assertEqual(mail.inbox(c,include_body=False,query='unmatched-query')['messages'],[])
    def test_public_lookup_does_not_follow_applicant_or_assessment_links(self):
        self.assertEqual(pipeline.public_posting_url('https://jobs.example.com/applications/private?token=secret'),'')
        self.assertEqual(pipeline.public_posting_url('https://jobs.example.com/interview/private'),'')
        self.assertEqual(pipeline.public_posting_url('https://jobs.example.com/jobs/123?candidate=private&token=secret&gh_jid=123'),'https://jobs.example.com/jobs/123?gh_jid=123')
    def test_missing_role_is_not_assigned_to_unrelated_existing_roles(self):
        m=self.message();m['body']='We received your application for Data Engineer at Acme.';self.collect([m])
        with app.connect() as c:
            e=mail.inbox(c)['messages'][0];self.assertEqual(e['job_ids'],[]);self.assertEqual(e['match_kind'],'missing');self.assertEqual(e['missing'][0]['title'],'Data Engineer')
    def test_repeated_missing_role_receipts_share_one_suggestion(self):
        messages=[{**self.message(str(i)),'body':'We received your application for Data Engineer at Acme.'} for i in range(2)]
        self.collect(messages)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM email_missing').fetchone()[0],1)
            self.assertTrue(all(len(m['missing'])==1 for m in mail.inbox(c)['messages']))
    def test_collection_history_is_newest_first_and_resumes_after_a_failed_window(self):
        bounds={'oldest':'2026-08-01T00:00:00+00:00'}
        calls=[]
        def reader(start,end,*args):
            calls.append((start,end))
            if len(calls)==2:raise ValueError('Mail unavailable')
            return [self.message()]
        with patch.object(mail,'read_bounds',return_value=bounds),patch.object(mail,'read_mail',side_effect=reader):mail.sync(app)
        with app.connect() as c:
            checkpoint=mail.checkpoint(c,'test-account');self.assertEqual(checkpoint['history_before'],calls[0][0]);self.assertTrue(mail.inbox(c)['messages'])
        self.assertGreater(calls[0][0],calls[1][0])
        with patch.object(mail,'read_mail',return_value=[]) as read:mail.sync(app)
        # The first request checks new arrivals; remaining history resumes at the persisted boundary.
        self.assertEqual(read.call_args_list[1].args[1],checkpoint['history_before'])
    def test_mail_timeout_splits_only_the_unfinished_window(self):
        bounds={'oldest':self.bounds_start};calls=[]
        def reader(start,end,*args):
            calls.append((start,end))
            if len(calls)==1:raise ValueError('Mail timed out')
            return []
        with patch.object(mail,'read_bounds',return_value=bounds),patch.object(mail,'read_mail',side_effect=reader):mail.sync(app)
        self.assertGreaterEqual(len(calls),3)
        with app.connect() as c:self.assertEqual(mail.checkpoint(c,'test-account')['history_before'],self.bounds_start)
    def test_http_preview_search_retry_missing_draft_and_notification_ack(self):
        import threading,urllib.request,urllib.parse
        m=self.message();m['body']+=' '+('long text '*150)+' needle-outside-preview';self.collect([m]);self.classify('one','interview','invented quote')
        receipt=self.message('missing');receipt['body']='We received your application for Data Engineer at Acme.';self.collect([receipt])
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def get(route):
            with urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+'/api/'+route) as r:return json.load(r)
        def post(route,data):
            req=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+'/api/'+route,data=json.dumps(data).encode(),headers={'X-Token':app.TOKEN,'Content-Type':'application/json'})
            with urllib.request.urlopen(req) as r:return json.load(r)
        try:
            preview=get('emails?query=needle-outside-preview');self.assertEqual(len(preview['messages']),1);self.assertEqual(preview['total'],2);self.assertLessEqual(len(preview['messages'][0]['body']),800)
            self.assertEqual(get('emails/message?message_id=one')['body'],m['body'])
            post('emails/retry',{'message_id':'one'})
            with app.connect() as c:self.assertEqual(c.execute("SELECT analysis_state FROM emails WHERE message_id='one'").fetchone()[0],'queued');suggestion=c.execute('SELECT id FROM email_missing').fetchone()[0]
            created=post('job',{'title':'Data Engineer','company':'Acme','date_applied':__import__('datetime').date.today().isoformat(),'status':'Waiting','mail_suggestion':suggestion})
            detail=get('emails/message?message_id=missing');self.assertIn(created['id'],detail['job_ids']);self.assertEqual(detail['missing'][0]['state'],'added')
            state=get('state');self.assertTrue(next(j for j in state['jobs'] if j['id']==self.a)['pending_positive'])
            events=get('emails/notifications')['events'];self.assertTrue(events);post('emails/notifications/ack',{'ids':[e['id'] for e in events]});self.assertEqual(get('emails/notifications')['events'],[])
        finally:server.shutdown();server.server_close();thread.join()
    def test_manual_terminal_statuses_suppress_old_interviews_without_changing_job_statuses(self):
        m=self.message();m['received_at']='2026-10-01T12:00:00+00:00';m['body']='Please book your interview for Backend Engineer.';self.collect([m]);self.classify('one','interview',m['body'])
        with app.connect() as c:
            app.save_job(c,{'status':'Rejected'},self.a);self.assertEqual(c.execute('SELECT review FROM emails').fetchone()[0],'pending')
            app.save_job(c,{'status':'Rejected'},self.b);self.assertEqual(c.execute('SELECT review FROM emails').fetchone()[0],'ignored')
        self.assertEqual(self.status(self.a),'Rejected');self.assertEqual(self.status(self.b),'Rejected')
    def test_notes_edit_does_not_move_manual_terminal_cutoff(self):
        with app.connect() as c:
            app.save_job(c,{'status':'Rejected'},self.a);app.save_job(c,{'status':'Rejected'},self.b)
            c.execute("UPDATE job_status_approvals SET effective_at='2026-11-01T12:00:00+00:00'")
        m=self.message();m['received_at']='2026-11-01T18:00:00+00:00';self.collect([m])
        with app.connect() as c:
            app.save_job(c,{'status':'Rejected','notes':'Notes only'},self.a);pipeline.auto_ignore(c)
            self.assertNotEqual(c.execute('SELECT review FROM emails').fetchone()[0],'ignored')
            self.assertEqual(c.execute('SELECT effective_at FROM job_status_approvals WHERE job_id=?',(self.a,)).fetchone()[0],'2026-11-01T12:00:00+00:00')
    def test_existing_manual_terminal_history_is_migrated_conservatively(self):
        m=self.message();m['received_at']='2026-10-01T12:00:00+00:00';self.collect([m])
        with app.connect() as c:
            app.save_job(c,{'status':'Rejected'},self.a);app.save_job(c,{'status':'Rejected'},self.b);c.execute('DELETE FROM job_status_approvals');pipeline.init(c)
            self.assertEqual(c.execute('SELECT count(*) FROM job_status_approvals').fetchone()[0],2)
            self.assertEqual(c.execute('SELECT review FROM emails').fetchone()[0],'ignored')
    def test_restored_terminal_status_uses_original_record_date_not_restore_time(self):
        with app.connect() as c:
            ident=app.save_job(c,{'title':'Older role','company':'OldCo','status':'Rejected','_restoring':True,'_restored_at':'2026-10-01T12:00:00+00:00'})
            pipeline.restore(c,{},{});row=c.execute('SELECT * FROM job_status_approvals WHERE job_id=?',(ident,)).fetchone()
            self.assertEqual(row['effective_at'],'2026-10-01T12:00:00+00:00')
            m={**self.message('later'),'sender':'OldCo','subject':'Older role invitation','body':'Please book an interview for Older role.','received_at':'2026-10-15T12:00:00+00:00'}
            pipeline.collect(c,[m],[dict(r) for r in c.execute('SELECT * FROM jobs')],'test-account');self.assertNotEqual(c.execute("SELECT review FROM emails WHERE message_id='later'").fetchone()[0],'ignored')
