import datetime as dt
import json
import unittest
from unittest.mock import patch
import app
import mail_pipeline as p
import mail_integration as mail
import mail_notifications as notifications
import test_mail as base

class AdNotificationTests(unittest.TestCase):
    setUp=base.MailTests.setUp
    tearDown=base.MailTests.tearDown
    def message(self,id='one',subject='Acme is hiring a Backend Engineer',body='You may be a fit for this open role. View jobs and apply.',sender='LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>'):
        return dict(message_id=id,sender=sender,subject=subject,body=body,received_at='2026-11-03T14:00:00+00:00')
    def collect(self,m):
        with app.connect() as c:p.collect(c,[m],app.current_jobs(),'test-account')
    def prefs(self,**values):
        config=notifications.validate(values)
        with app.connect() as c:c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('notification_preferences',json.dumps(config)))
        return config
    def classify(self,m,kind):
        self.collect(m)
        with app.connect() as c:
            row=dict(c.execute('SELECT * FROM emails WHERE message_id=?',(m['message_id'],)).fetchone());p.classify_one(c,row,{'kind':kind,'evidence':m['body']})
    def test_bulk_job_ads_hidden_by_default_but_retained_and_explicitly_viewable(self):
        self.collect(self.message())
        with app.connect() as c:
            self.assertEqual(mail.inbox(c)['messages'],[])
            ads=mail.inbox(c,options={'include_ads':'1'})['messages'];self.assertEqual(len(ads),1);self.assertEqual(ads[0]['category'],'job_ad')
            self.assertEqual(len(mail.inbox(c,options={'type':'job_ad'})['messages']),1)
            self.assertEqual(p.summary(c)['ads'],1);self.assertEqual(c.execute('SELECT count(*) FROM emails').fetchone()[0],1)
    def test_recruiter_ad_is_hidden_but_personal_reply_is_not(self):
        ad=self.message(subject='Great Job Opportunity at Acme',body='Our client is seeking a Backend Engineer. Are you open to new opportunities?',sender='Recruiter <recruiter@example.test>');self.collect(ad)
        reply=self.message('reply','Re: Your Acme application','Thanks for sending your resume. I will check with the hiring manager.','Recruiter <recruiter@acme.test>');self.collect(reply)
        self.classify(reply,'job_ad')
        with app.connect() as c:self.assertEqual([m['message_id'] for m in mail.inbox(c)['messages']],['reply'])
    def test_application_receipt_with_other_job_recommendations_is_not_an_ad(self):
        m=self.message(subject='Acme application received',body='We received your application for Backend Engineer. Other jobs you may like are below.');self.collect(m)
        with app.connect() as c:self.assertNotEqual(mail.inbox(c)['messages'][0]['category'],'job_ad')
    def test_real_invitation_is_not_hidden_even_if_an_ad_label_is_returned(self):
        m=self.message(subject='Acme Backend Engineer interview',body='Please share your availability for an interview for Backend Engineer.');self.classify(m,'job_ad')
        with app.connect() as c:
            message=mail.inbox(c)['messages'][0];self.assertNotEqual(message['category'],'job_ad');self.assertIn('Kept visible',message['analysis_error'])
    def test_default_never_notifies_job_ads_and_never_replays_them_after_enabling(self):
        self.collect(self.message())
        with app.connect() as c:
            self.assertEqual(notifications.pending(c)['events'],[]);self.assertEqual(c.execute('SELECT suppressed FROM email_events').fetchone()[0],1)
        self.prefs(ad_mode='all')
        with app.connect() as c:self.assertEqual(notifications.pending(c)['events'],[]);self.assertEqual(p.activity(c)['unread'],0);self.assertTrue(p.activity(c)['items'][0]['muted'])
    def test_ad_keywords_match_body_case_and_whole_phrases_with_plural_support(self):
        self.prefs(ad_mode='keywords',ad_keywords=['Boston Dynamics','humanoid'])
        for id,body in [('match','Acme has a humanoid robotics opening.'),('plural','Acme works on Humanoids.'),('company','Acme is recruiting with Boston Dynamics.'),('no','Acme has a backend opening.')]:self.collect(self.message(id,body=body))
        with app.connect() as c:
            events=notifications.pending(c)['events'];self.assertEqual({e['message_id'] for e in events},{'match','plural','company'})
            activity=p.activity(c);self.assertFalse(next(m for m in activity['items'] if m['message_id']=='match')['muted']);self.assertTrue(next(m for m in activity['items'] if m['message_id']=='no')['muted'])
    def test_ordinary_alert_waits_for_classification_and_cannot_notify_a_job_ad_early(self):
        self.collect(self.message(subject='Acme opportunities for your consideration',body='Acme has a new Backend Engineer opportunity.'))
        with app.connect() as c:self.assertEqual(notifications.pending(c)['events'],[])
        self.classify(self.message(subject='Acme opportunities for your consideration',body='Acme has a new Backend Engineer opportunity.'),'job_ad')
        with app.connect() as c:self.assertEqual(notifications.pending(c)['events'],[])
    def test_only_reviews_mode_excludes_receipts_and_ads_but_preserves_review(self):
        self.prefs(mode='reviews_only',ad_mode='all')
        self.collect(self.message('ad'));receipt=self.message('receipt','Acme receipt','We received your application for Backend Engineer.');self.classify(receipt,'confirmation')
        rejection=self.message('reject','Acme application update','We are not moving forward with your application for Backend Engineer.');self.classify(rejection,'rejection')
        with app.connect() as c:
            events=notifications.pending(c)['events'];self.assertEqual({e['message_id'] for e in events},{'reject'});self.assertEqual(c.execute('SELECT status FROM jobs WHERE id=?',(self.a,)).fetchone()[0],'Interview 2')
    def test_categories_and_sender_company_mutes_are_account_scoped(self):
        self.prefs(ad_mode='all',muted_senders=['@linkedin.com'])
        self.collect(self.message('muted'));self.collect(self.message('other-account'))
        with app.connect() as c:
            c.execute("UPDATE email_accounts SET account_id='other' WHERE message_id='other-account'")
            self.assertEqual(notifications.pending(c)['events'],[])
            self.assertEqual(c.execute("SELECT delivered FROM email_events WHERE message_id='other-account'").fetchone()[0],0)
        cfg=notifications.validate({'ad_mode':'all','muted_companies':['Acme Inc.']})
        self.assertFalse(notifications.allows({'category':'job_ad','company':'Acme','review':'none'},cfg))
    def test_review_filters_are_explicit_and_master_off_disables_badge(self):
        m={'category':'interview','review':'pending','company':'Acme','sender':'jobs@acme.test','subject':'Interview','body':'Please book your interview.'}
        cfg=notifications.validate({'exclude_keywords':['interview'],'muted_senders':['@acme.test']});self.assertTrue(notifications.allows(m,cfg))
        cfg['filter_reviews']=True;self.assertFalse(notifications.allows(m,cfg))
        self.prefs(enabled=False)
        with app.connect() as c:self.assertFalse(p.summary(c)['notification_badge'])
    def test_quiet_hours_defer_instead_of_acknowledging_and_reviews_can_bypass(self):
        self.prefs(quiet_enabled=True,quiet_start='22:00',quiet_end='08:00')
        m=self.message('reject','Acme decision','We are not moving forward with your application for Backend Engineer.');self.classify(m,'rejection')
        with app.connect() as c:
            self.assertEqual(notifications.pending(c,dt.datetime(2026,11,3,23,0))['events'],[])
            self.assertEqual(c.execute("SELECT delivered FROM email_events WHERE kind LIKE 'status:%'").fetchone()[0],0)
            self.assertTrue(notifications.pending(c,dt.datetime(2026,11,4,8,0))['events'])
        self.prefs(quiet_enabled=True,reviews_bypass_quiet=True)
        with app.connect() as c:self.assertTrue(notifications.pending(c,dt.datetime(2026,11,3,23,0))['events'])
    def test_quiet_hour_boundaries_and_same_day_windows(self):
        cfg=notifications.validate({'quiet_enabled':True,'quiet_start':'09:00','quiet_end':'17:00'})
        for hour,expected in [(8,False),(9,True),(16,True),(17,False)]:self.assertEqual(notifications.quiet(cfg,dt.datetime(2026,11,3,hour)),expected)
    def test_invalid_preferences_are_rejected(self):
        for value in [{'enabled':'yes'},{'mode':'bad'},{'ad_mode':'keywords','ad_keywords':[]},{'muted_senders':['linkedin.com']},{'quiet_enabled':True,'quiet_start':'22:00','quiet_end':'22:00'},{'quiet_start':'24:00'},{'include_keywords':[3]},{'unknown':True}]:
            with self.assertRaises(ValueError):notifications.validate(value)
    def test_preferences_and_suppressed_history_survive_export_restore(self):
        self.prefs(ad_mode='never',previews=False,sound=False);self.collect(self.message())
        with app.connect() as c:
            notifications.pending(c);data=mail.export(c)
            c.execute('DELETE FROM email_events');mail.restore(c,data,{self.a:self.a,self.b:self.b})
            self.assertEqual(c.execute('SELECT suppressed FROM email_events').fetchone()[0],1)
            self.assertFalse(notifications.preferences(c)['previews']);self.assertEqual(p.activity(c)['unread'],0)
    def test_existing_ads_are_reclassified_without_changing_links_or_human_approvals(self):
        self.collect(self.message())
        with app.connect() as c:
            before=[tuple(r) for r in c.execute('SELECT * FROM email_jobs')]
            c.execute("UPDATE emails SET category='other',analysis_state='done'");c.execute("DELETE FROM mail_meta WHERE key='job_ads_v1'")
            p.repair_ads(c);self.assertEqual(c.execute('SELECT category FROM emails').fetchone()[0],'job_ad');self.assertEqual(before,[tuple(r) for r in c.execute('SELECT * FROM email_jobs')])
