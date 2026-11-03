import datetime as dt
import json
import time
import unittest
from unittest.mock import patch
import app
import mail_integration as mail
import mail_pipeline as pipeline
import test_mail as base

class HardeningTests(unittest.TestCase):
    setUp=base.MailTests.setUp
    tearDown=base.MailTests.tearDown
    message=base.MailTests.message
    status=base.MailTests.status
    def collect(self,messages):
        with app.connect() as c:return pipeline.collect(c,messages,[dict(r) for r in c.execute('SELECT * FROM jobs')],'test-account')
    def classify(self,id,kind):
        with app.connect() as c:pipeline.classify_one(c,dict(c.execute('SELECT * FROM emails WHERE message_id=?',(id,)).fetchone()),{'kind':kind,'evidence':''})
    def test_manual_links_survive_inflight_confirmation_and_repeated_collection(self):
        m=self.message();m['body']='We received your application for Data Engineer at Acme.';self.collect([m])
        with app.connect() as c:
            stale=dict(c.execute("SELECT * FROM emails WHERE message_id='one'").fetchone())
            mail.review(c,'one','link',[self.b],app.save_job)
            pipeline.classify_one(c,stale,{'kind':'confirmation'})
        self.collect([m])
        with app.connect() as c:
            self.assertEqual([r[0] for r in c.execute("SELECT job_id FROM email_jobs WHERE message_id='one'")],[self.b])
            self.assertEqual(c.execute("SELECT match_kind FROM emails WHERE message_id='one'").fetchone()[0],'manual')
    def test_stale_proposal_and_changed_job_are_rejected_without_status_write(self):
        self.collect([self.message()]);self.classify('one','interview')
        with app.connect() as c:old=mail.message_detail(c,'one')['review_token']
        self.classify('one','rejection')
        with app.connect() as c:
            with self.assertRaisesRegex(ValueError,'proposal changed'):mail.review(c,'one','approve',[self.a],app.save_job,old)
            latest=mail.message_detail(c,'one')['review_token']
            self.assertNotEqual(old,latest)
            app.save_job(c,{'status':'Offer'},self.a)
            with self.assertRaisesRegex(ValueError,'proposal changed'):mail.review(c,'one','approve',[self.a],app.save_job,latest)
            current=mail.message_detail(c,'one')['review_token'];mail.review(c,'one','approve',[self.a],app.save_job,current)
        self.assertEqual(self.status(self.a),'Rejected')
    def test_preview_and_header_tokens_are_identical(self):
        self.collect([self.message()]);self.classify('one','rejection')
        with app.connect() as c:self.assertEqual(mail.inbox(c,False)['messages'][0]['review_token'],mail.message_detail(c,'one')['review_token'])
    def test_late_body_recovers_and_stale_inference_cannot_override_it(self):
        m=self.message();full=m['body'];m['body']='';self.collect([m]);self.classify('one','other')
        with app.connect() as c:old=dict(c.execute("SELECT * FROM emails WHERE message_id='one'").fetchone())
        m['body']=full;self.collect([m])
        with app.connect() as c:
            pipeline.classify_one(c,old,{'kind':'other'})
            row=c.execute("SELECT body,analysis_state,body_version FROM emails WHERE message_id='one'").fetchone()
            self.assertEqual(row['body'],full);self.assertEqual(row['analysis_state'],'queued');self.assertEqual(row['body_version'],1)
        self.classify('one','rejection')
        with app.connect() as c:
            token=mail.message_detail(c,'one')['review_token'];mail.review(c,'one','approve',[self.a],app.save_job,token)
        m['body']=full+' Additional details.';self.collect([m])
        with app.connect() as c:self.assertEqual(c.execute("SELECT review FROM emails WHERE message_id='one'").fetchone()[0],'approved')
        m['body']='';self.collect([m])
        with app.connect() as c:self.assertIn('Additional details.',mail.message_detail(c,'one')['body'])
    def test_old_empty_body_gets_an_explicit_recovery_window(self):
        m=self.message();m['body']='';m['received_at']='2026-01-01T12:00:00+00:00';self.collect([m])
        profiles=pipeline.company_profiles([{'company':'Acme','title':'Backend Engineer'},{'company':'Acme','title':'Product Designer'}])
        import hashlib
        # Use the actual company-profile fingerprint, including url values from persisted jobs.
        with app.connect() as c:
            profiles=pipeline.company_profiles([dict(r) for r in c.execute('SELECT * FROM jobs')])
            fingerprint=hashlib.sha256(json.dumps(profiles,sort_keys=True).encode()).hexdigest()
            for k,v in {'collection_version':pipeline.VERSION,'companies':fingerprint,'through':'2026-11-01T12:00:00+00:00','history_oldest':m['received_at'],'history_before':m['received_at']}.items():c.execute('INSERT OR REPLACE INTO mail_checkpoints VALUES (?,?,?)',('test-account',k,v))
        with patch.object(mail,'read_mail',return_value=[]) as reader:pipeline.sync(app)
        self.assertTrue(any(call.args[0]<=m['received_at'] for call in reader.call_args_list))
    def test_notification_backup_restores_seen_delivered_and_pending(self):
        self.collect([self.message()]);self.classify('one','rejection')
        with app.connect() as c:
            c.execute('UPDATE email_events SET seen=1,delivered=1');data=mail.export(c)
            for table in ('email_events','email_jobs','email_accounts','emails'):c.execute('DELETE FROM '+table)
            mail.restore(c,data,{self.a:self.a,self.b:self.b})
            feed=pipeline.activity(c);self.assertEqual(feed['total'],1);self.assertEqual(feed['unread'],0);self.assertEqual(feed['pending'],1);self.assertEqual(pipeline.notifications(c),[])
            # A repeated merge does not duplicate the same notification.
            mail.restore(c,data,{self.a:self.a,self.b:self.b});self.assertEqual(pipeline.activity(c)['total'],1)
    def test_legacy_backup_rebuilds_pending_alerts_quietly_for_other_mail(self):
        self.collect([self.message()]);self.classify('one','rejection')
        with app.connect() as c:
            data=mail.export(c);data.pop('events')
            for table in ('email_events','email_jobs','email_accounts','emails'):c.execute('DELETE FROM '+table)
            mail.restore(c,data,{self.a:self.a,self.b:self.b});feed=pipeline.activity(c)
            self.assertEqual(feed['pending'],1);self.assertEqual(len(pipeline.notifications(c)),1)
    def test_server_pages_filter_all_results_and_bound_query_count(self):
        # Raw seeding avoids testing the unrelated per-message company scanner here.
        with app.connect() as c:
            for i in range(650):
                ident=f'm{i:04}';category='rejection' if i%2 else 'confirmation'
                c.execute("INSERT INTO emails(message_id,sender,subject,body,received_at,company,category,review,analysis_state) VALUES (?,?,?,?,?,?,?,'none','done')",(ident,'Acme','Receipt '+str(i),'body '+'x'*1200+(' needle' if i==400 else ''),f'2026-10-{1+i%28:02}T12:00:00+00:00','Acme',category))
                c.execute('INSERT INTO email_accounts VALUES (?,?)',(ident,'test-account'));c.execute('INSERT INTO email_jobs VALUES (?,?)',(ident,self.a))
            queries=[];c.set_trace_callback(queries.append)
            first=mail.inbox(c,False,options={'limit':'200','offset':'0','type':'rejection'})
            second=mail.inbox(c,False,options={'limit':'200','offset':'200','type':'rejection'})
            self.assertEqual(first['matching'],325);self.assertTrue(first['has_more']);self.assertEqual(len(second['messages']),125)
            self.assertFalse(set(m['message_id'] for m in first['messages'])&set(m['message_id'] for m in second['messages']))
            self.assertLess(len(queries),50)
            self.assertEqual(mail.inbox(c,False,query='needle',options={'limit':200})['messages'][0]['message_id'],'m0400')
            self.assertTrue(all(len(m['body'])<=800 for m in first['messages']))
    def test_other_account_proposals_cannot_be_reviewed_or_pin_applications(self):
        self.collect([self.message()]);self.classify('one','interview')
        with app.connect() as c:
            c.execute("UPDATE settings SET value=? WHERE key='mail_account'",(json.dumps({'id':'different'}),))
            with self.assertRaisesRegex(ValueError,'selected account'):mail.review(c,'one','approve',[self.a],app.save_job)
            jobs=pipeline.pending_for_jobs(c,[{'id':self.a}]);self.assertFalse(jobs[0]['pending_positive'])
    def test_default_classifier_uses_current_bundled_python_on_every_os(self):
        with patch.object(mail.sys,'platform','linux'),patch.object(mail.subprocess,'run') as run:
            run.return_value.returncode=0;run.return_value.stdout='{"ok":true}';run.return_value.stderr=''
            self.assertEqual(mail.run_shortcut('JobTracker Email Review',{'mode':'selftest'}),{'ok':True})
            self.assertEqual(run.call_args.args[0][0],mail.sys.executable);self.assertTrue(run.call_args.args[0][-1].endswith('mail_shortcut.py'))
    def test_failed_old_inference_does_not_mark_hydrated_message_failed(self):
        m=self.message();m['body']='Acme header';self.collect([m])
        with app.connect() as c:c.execute("UPDATE settings SET value='true' WHERE key='mail_use_shortcut'")
        def fail_after_download(*args):
            m['body']='Full Acme rejection: we are not moving forward with your application.';self.collect([m]);raise ValueError('Old request failed')
        with patch.object(mail,'run_shortcut',side_effect=fail_after_download):pipeline.analyze_pending(app)
        with app.connect() as c:self.assertEqual(c.execute("SELECT analysis_state FROM emails WHERE message_id='one'").fetchone()[0],'queued')
    def test_retry_of_pending_warning_survives_restart_initialization(self):
        self.collect([self.message()]);self.classify('one','rejection')
        with app.connect() as c:c.execute("UPDATE emails SET analysis_state='queued' WHERE message_id='one'")
        app.init()
        with app.connect() as c:self.assertEqual(c.execute("SELECT analysis_state FROM emails WHERE message_id='one'").fetchone()[0],'queued')
    def test_http_approval_requires_displayed_token_and_rejects_stale_one(self):
        import threading,urllib.request,urllib.error
        self.collect([self.message()]);self.classify('one','interview')
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def post(data):
            request=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+'/api/emails/review',data=json.dumps(data).encode(),headers={'X-Token':app.TOKEN,'Content-Type':'application/json'})
            try:
                with urllib.request.urlopen(request) as r:return r.status,json.load(r)
            except urllib.error.HTTPError as e:return e.code,json.load(e)
        try:
            data={'message_id':'one','action':'approve','job_ids':[self.a]}
            self.assertEqual(post(data)[0],400)
            with app.connect() as c:data['expected_token']=mail.message_detail(c,'one')['review_token']
            self.classify('one','rejection');self.assertIn('proposal changed',post(data)[1]['error']);self.assertEqual(self.status(self.a),'Interview 2')
            with app.connect() as c:data['expected_token']=mail.message_detail(c,'one')['review_token']
            self.assertEqual(post(data)[0],200);self.assertEqual(self.status(self.a),'Rejected')
        finally:server.shutdown();server.server_close();thread.join()
    def test_notification_history_can_page_past_two_hundred_alerts(self):
        with app.connect() as c:
            for i in range(205):
                ident=str(i);c.execute("INSERT INTO emails(message_id,sender,subject,body,received_at,category,review) VALUES (?,'Acme','Update','body','2026-11-02T12:00:00Z','rejection','pending')",(ident,));c.execute('INSERT INTO email_accounts VALUES (?,?)',(ident,'test-account'));pipeline.event(c,ident,'status:rejection')
            first=pipeline.activity(c);all_items=pipeline.activity(c,400)
            self.assertEqual(first['total'],205);self.assertEqual(len(first['items']),200);self.assertEqual(len(all_items['items']),205)
            pipeline.mark_activity_seen(c,first['through']);self.assertEqual(pipeline.activity(c)['unread'],0);self.assertEqual(pipeline.activity(c)['pending'],205)
    def test_auto_ignore_uses_one_header_pass_without_loading_bodies(self):
        self.collect([self.message()])
        with app.connect() as c:
            for ident in (self.a,self.b):app.save_job(c,{'status':'Rejected'},ident)
            queries=[];c.set_trace_callback(queries.append);pipeline.auto_ignore(c)
            self.assertFalse(any('SELECT * FROM emails' in q for q in queries));self.assertLess(len(queries),10)
    def test_urgent_alerts_jump_a_large_backfill_without_replaying_normal_alert(self):
        messages=[]
        for i in range(140):
            m=self.message(str(i));m['body']='Acme engineering newsletter.';messages.append(m)
        self.collect(messages);self.classify('139','interview')
        with app.connect() as c:
            events=pipeline.notifications(c);self.assertEqual(events[0]['message_id'],'139');self.assertEqual(events[0]['kind'],'status:interview')
            self.assertFalse(any(e['message_id']=='139' and e['kind']=='added' for e in events))
            self.assertEqual(pipeline.activity(c)['total'],140)
    def test_account_switch_invalidates_pending_job_metadata_immediately(self):
        self.collect([self.message()]);self.classify('one','interview')
        with app.connect() as c:before=pipeline.revision(c)
        with patch.object(mail,'list_accounts',return_value=[{'id':'different','name':'Other account'}]):mail.select_account(app,'different')
        with app.connect() as c:
            self.assertGreater(pipeline.revision(c),before)
            self.assertFalse(pipeline.pending_for_jobs(c,[{'id':self.a}])[0]['pending_positive'])
