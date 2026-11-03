import json
import unittest
from unittest.mock import patch
import app
import mail_integration as mail
import mail_pipeline as pipeline
import mail_sources
import test_mail as base

class PrecisionTests(unittest.TestCase):
    setUp=base.MailTests.setUp
    tearDown=base.MailTests.tearDown
    status=base.MailTests.status
    def message(self,body,subject='Acme Backend Engineer application',sender='Acme Recruiting <jobs@acme.test>',id='precision'):
        return dict(message_id=id,subject=subject,sender=sender,body=body,received_at='2026-11-01T12:00:00+00:00')
    def collect(self,m):
        with app.connect() as c:return pipeline.collect(c,[m],[dict(r) for r in c.execute('SELECT * FROM jobs')],'test-account')
    def classify(self,m,kind,evidence=None):
        self.collect(m)
        with app.connect() as c:
            stored=c.execute('SELECT * FROM emails WHERE message_id=?',(m['message_id'],)).fetchone()
            self.assertIsNotNone(stored)
            pipeline.classify_one(c,dict(stored),{'kind':kind,'evidence':evidence if evidence is not None else m['body']})
            return mail.message_detail(c,m['message_id'])
    def apple(self):
        with app.connect() as c:return app.save_job(c,{'title':'Machine Learning Engineer','company':'Apple','url':'https://jobs.apple.com/en-us/details/123'})
    def test_airline_boarding_pass_wallet_badge_is_not_an_apple_application(self):
        self.apple();m=self.message('Your flight is ready. Add your mobile boarding pass to Apple Wallet.','American Airlines mobile boarding pass','American Airlines <no-reply@info.email.aa.com>')
        self.assertEqual(self.collect(m),0)
        with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM emails').fetchone()[0],0)
    def test_consumer_messages_even_from_a_tracked_employer_do_not_enter_job_mail(self):
        self.apple()
        for index,body in enumerate(['Your order has shipped. Thank you for your interest. Apple Wallet.', 'Your flight reservation is confirmed. Add to Apple Wallet.', 'We received your credit card application. Thank you for your application.']):
            m=self.message(body,'Your order confirmation','Apple <store@apple.com>',str(index));self.assertEqual(self.collect(m),0)
    def test_unrelated_personal_receipt_does_not_pass_the_unlinked_confirmation_escape_hatch(self):
        m=self.message('Thank you for your interest. We received your rental application.','Application received','Property office <leasing@example.test>')
        self.assertEqual(self.collect(m),0)
    def test_real_application_receipts_remain_collectable_without_a_tracked_company(self):
        m=self.message('We received your application for Platform Engineer.','Application received','New Employer Recruiting <no-reply@hire.lever.co>')
        self.assertEqual(self.collect(m),1)
    def test_apple_ats_receipt_and_real_employer_newsletters_are_kept(self):
        self.apple()
        for index,m in enumerate([self.message('We received your application for Machine Learning Engineer at Apple.','Your Apple application','Apple Recruiting <no-reply@myworkday.com>'),self.message('New engineering research this month.','Apple engineering newsletter','Apple <research@apple.com>')]):
            m['message_id']=str(index);self.assertEqual(self.collect(m),1)
    def test_actual_interview_travel_message_is_kept(self):
        m=self.message('Your flight reservation for the onsite interview at Acme is confirmed.','Your onsite interview travel')
        self.assertEqual(self.collect(m),1)
    def test_domain_lookalikes_and_incidental_footer_urls_do_not_link(self):
        self.apple()
        for i,m in enumerate([self.message('Hello there. https://jobs.apple.com.evil.test/privacy','A greeting','Hello <hello@apple.com.evil.test>'),self.message('Read this on Apple devices.','A greeting','Hello <hello@elsewhere.test>')]):
            m['message_id']=str(i);self.assertEqual(self.collect(m),0)
    def test_company_in_quoted_thread_does_not_match_current_personal_mail(self):
        self.apple();m=self.message('Thanks, see you Friday.\nOn Monday someone wrote:\nApple received your application for Machine Learning Engineer.','Weekend','Friend <friend@example.test>')
        self.assertEqual(self.collect(m),0)
    def test_missing_title_company_prefix_matches_existing_merlin_role(self):
        with app.connect() as c:ident=app.save_job(c,{'title':'Autonomy Software Engineer','company':'Merlin Labs'})
        m=self.message('We received your application for the Autonomy Software Engineer role.','Thank you for your interest in Merlin | Autonomy Software Engineer','Merlin Labs <no-reply@hire.lever.co>')
        result=self.classify(m,'confirmation')
        self.assertEqual(result['job_ids'],[ident]);self.assertEqual(result['missing'],[])
    def test_merlin_rejection_does_not_create_a_missing_application(self):
        with app.connect() as c:ident=app.save_job(c,{'title':'Autonomy Software Engineer','company':'Merlin Labs'})
        body="Thank you for your interest. We've made the decision to not move forward at this time for the Autonomy Software Engineer opportunity."
        m=self.message(body,'Thank you for your interest in Merlin | Autonomy Software Engineer','Merlin Labs <no-reply@hire.lever.co>')
        result=self.classify(m,'rejection',"We've made the decision to not move forward at this time for the Autonomy Software Engineer opportunity")
        self.assertEqual(result['review'],'pending');self.assertEqual(result['job_ids'],[ident]);self.assertEqual(result['missing'],[])
    def test_genuinely_new_merlin_role_still_suggests_addition(self):
        with app.connect() as c:app.save_job(c,{'title':'Autonomy Software Engineer','company':'Merlin Labs'})
        m=self.message('We received your application for the Platform Engineer role.','Application received: Platform Engineer','Merlin Labs <no-reply@hire.lever.co>')
        result=self.classify(m,'confirmation');self.assertEqual(result['job_ids'],[]);self.assertEqual(len(result['missing']),1)
    def test_invented_evidence_creates_no_status_proposal_or_urgent_notification(self):
        m=self.message('We are not moving forward with your application.');result=self.classify(m,'rejection','Invented rejection quotation')
        self.assertEqual(result['review'],'none');self.assertEqual(result['analysis_state'],'warning');self.assertEqual(result['evidence'],'')
        with app.connect() as c:
            self.assertFalse(any(e['kind'].startswith('status:') for e in pipeline.notifications(c)))
            with self.assertRaises(ValueError):mail.review(c,m['message_id'],'approve',[self.a],app.save_job,result['review_token'])
    def test_model_cannot_call_a_greeting_an_interview(self):
        m=self.message('Thank you for applying. We received your application for Backend Engineer.');result=self.classify(m,'interview','Thank you for applying.')
        self.assertEqual(result['review'],'none');self.assertEqual(result['invitation'],0)
    def test_conditional_interviews_and_hypothetical_rejections_are_not_proposals(self):
        for i,(kind,body) in enumerate([('interview','If selected, please book an interview for Backend Engineer.'),('rejection','If we are not moving forward with your application, we will let you know.'),('offer','If selected, we will offer you the Backend Engineer role.')]):
            result=self.classify(self.message(body,id=str(i)),kind);self.assertEqual(result['review'],'none')
    def test_quoted_old_interview_and_rejection_cannot_supply_model_evidence(self):
        for i,(kind,old) in enumerate([('interview','Please book an interview for Backend Engineer.'),('rejection','We are not moving forward with your application.')]):
            m=self.message('Acme team newsletter.\nOn Monday recruiter wrote:\n'+old,id=str(i));result=self.classify(m,kind,old);self.assertEqual(result['review'],'none')
    def test_html_quote_boundaries_survive_ingestion(self):
        body=mail_sources.plain_html('<p>Acme engineering update.</p><blockquote>Please book an interview for Backend Engineer.</blockquote>')
        result=self.classify(self.message(body),'interview','Please book an interview for Backend Engineer.');self.assertEqual(result['review'],'none')
    def test_current_rejection_after_an_old_invitation_is_still_a_rejection(self):
        quote='We are not moving forward with your application for Backend Engineer.'
        m=self.message(quote+'\nOn Monday recruiter wrote:\nPlease book your interview.')
        result=self.classify(m,'rejection',quote);self.assertEqual(result['review'],'pending');self.assertEqual(result['category'],'rejection')
    def test_true_positive_interview_test_offer_and_rejection_need_approval(self):
        cases=[('interview','Please share your availability for an interview for Backend Engineer.'),('interview','Please complete the technical assessment for Backend Engineer by Friday.'),('offer','We are pleased to offer you the Backend Engineer position.'),('rejection','We decided not to proceed with your application for Backend Engineer.')]
        for i,(kind,body) in enumerate(cases):
            result=self.classify(self.message(body,id=str(i)),kind);self.assertEqual(result['review'],'pending');self.assertEqual(result['category'],kind)
        self.assertEqual(self.status(self.a),'Interview 2')
    def test_discount_offer_from_employer_is_not_an_employment_offer(self):
        result=self.classify(self.message('We offer you 20 percent off your next purchase.','Acme offers'),'offer');self.assertEqual(result['review'],'none')
    def test_precision_repair_is_reversible_and_preserves_manual_links_and_decisions(self):
        apple=self.apple()
        with app.connect() as c:
            for ident,scope,review in [('boarding','company','none'),('manual','manual','none'),('approved','company','approved')]:
                c.execute("INSERT INTO emails(message_id,sender,subject,body,received_at,company,match_kind,category,review,analysis_state) VALUES (?,'American Airlines <no-reply@aa.com>','Mobile boarding pass','Your flight is ready. Add to Apple Wallet.','2026-11-01T12:00:00+00:00','Apple',?,'other',?,'done')",(ident,scope,review));c.execute('INSERT INTO email_jobs VALUES (?,?)',(ident,apple));c.execute('INSERT INTO email_accounts VALUES (?,?)',(ident,'test-account'))
            c.execute("DELETE FROM mail_meta WHERE key='precision_repair_v1'");pipeline.repair_precision(c)
            row=c.execute("SELECT * FROM emails WHERE message_id='boarding'").fetchone();self.assertEqual(row['review'],'ignored');self.assertEqual(row['ignore_source'],'unrelated');self.assertIn('Apple Wallet',row['body'])
            self.assertEqual(c.execute("SELECT count(*) FROM email_jobs WHERE message_id='boarding'").fetchone()[0],0)
            self.assertEqual(c.execute("SELECT match_kind FROM emails WHERE message_id='manual'").fetchone()[0],'manual');self.assertEqual(c.execute("SELECT review FROM emails WHERE message_id='approved'").fetchone()[0],'approved')
            mail.review(c,'boarding','unignore',[],app.save_job);mail.review(c,'boarding','link',[apple],app.save_job);pipeline.repair_precision(c)
            self.assertEqual(c.execute("SELECT review FROM emails WHERE message_id='boarding'").fetchone()[0],'none')
    def test_existing_merlin_hint_is_reconciled_even_after_manual_approval(self):
        with app.connect() as c:
            ident=app.save_job(c,{'title':'Autonomy Software Engineer','company':'Merlin Labs','status':'Rejected'})
            c.execute("INSERT INTO emails(message_id,sender,subject,body,received_at,company,match_kind,category,review) VALUES ('merlin','Merlin Labs <no-reply@hire.lever.co>','Thank you for your interest in Merlin | Autonomy Software Engineer','We decided not to move forward with your application.','2026-11-01T12:00:00+00:00','Merlin Labs','manual','rejection','approved')")
            c.execute("INSERT INTO email_missing(message_id,company,title) VALUES ('merlin','Merlin Labs','Merlin | Autonomy Software Engineer')");pipeline.reconcile_missing(c)
            self.assertEqual(c.execute('SELECT state FROM email_missing').fetchone()[0],'dismissed');self.assertEqual(c.execute("SELECT review FROM emails WHERE message_id='merlin'").fetchone()[0],'approved')
            self.assertEqual(c.execute('SELECT status FROM jobs WHERE id=?',(ident,)).fetchone()[0],'Rejected')
    def test_regret_about_rescheduling_is_not_a_rejection(self):
        m=self.message('We regret to inform you that your interview is rescheduled for Friday.')
        result=self.classify(m,'rejection');self.assertEqual(result['review'],'none')
    def test_alternate_explicit_declines_are_supported(self):
        for i,body in enumerate(['We are pursuing other candidates for the Backend Engineer position.','We are unable to offer you an interview for Backend Engineer.','Your application is no longer under consideration.','You were not selected for the Backend Engineer role.']):
            result=self.classify(self.message(body,id=str(i)),'rejection');self.assertEqual(result['review'],'pending',body)
    def test_candidate_declining_an_offer_is_not_an_employer_rejection(self):
        m=self.message('I decided not to accept your job offer for Backend Engineer.','Re: Acme employment offer','Candidate <candidate@example.test>')
        result=self.classify(m,'rejection');self.assertEqual(result['review'],'none')
    def test_legacy_unsupported_proposal_cannot_bypass_checks_at_approval(self):
        self.collect(self.message('Thank you for applying. We received your application for Backend Engineer.'))
        with app.connect() as c:
            c.execute("UPDATE emails SET review='pending',category='interview',invitation=1,evidence='Thank you for applying.' WHERE message_id='precision'")
            with self.assertRaisesRegex(ValueError,'does not support'):mail.review(c,'precision','approve',[self.a],app.save_job,mail.message_detail(c,'precision')['review_token'])
        self.assertEqual(self.status(self.a),'Interview 2')
    def test_repair_withdraws_invalid_manual_proposal_but_keeps_manual_links(self):
        self.collect(self.message('Thank you for applying.'))
        with app.connect() as c:
            mail.review(c,'precision','link',[self.b],app.save_job)
            c.execute("UPDATE emails SET review='pending',category='interview',invitation=1,evidence='Thank you for applying.' WHERE message_id='precision'");c.execute("DELETE FROM mail_meta WHERE key='precision_repair_v1'")
            pipeline.repair_precision(c);result=mail.message_detail(c,'precision');self.assertEqual(result['review'],'none');self.assertEqual(result['job_ids'],[self.b]);self.assertEqual(result['match_kind'],'manual')
    def test_common_conversation_and_offer_wording_remains_reviewable(self):
        cases=[('interview',"We would like to speak with you about the Backend Engineer position."),('interview','Please send your availability for an initial conversation about the Backend Engineer role.'),('interview','Your phone screen for Backend Engineer is scheduled for Friday.'),('offer','Attached is your offer for the Backend Engineer position.'),('offer','Please review and sign the attached employment agreement for Backend Engineer.'),('rejection',"We won't be taking your application any further for Backend Engineer.")]
        for i,(kind,body) in enumerate(cases):
            result=self.classify(self.message(body,id=str(i)),kind);self.assertEqual(result['review'],'pending',body)
