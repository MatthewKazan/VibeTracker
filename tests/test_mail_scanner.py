import datetime as dt
import json
import unittest
from unittest.mock import patch,Mock
import app
import mail_integration as mail
import mail_scanner as scanner
import test_mail as base

class ScannerTests(unittest.TestCase):
    setUp=base.MailTests.setUp
    tearDown=base.MailTests.tearDown
    message=base.MailTests.message
    def page(self,m=None,complete=False,folders=None,scanned=None):
        m=m or self.message();m['received_at']=dt.datetime.now(dt.timezone.utc).isoformat()
        return dict(messages=[m],complete=complete,folders=folders or [],scanned=scanned or [dict(message_id=m['message_id'],received_at=m['received_at'],body_complete=True)])
    def test_partial_page_persists_data_but_does_not_advance_coverage(self):
        page=self.page()
        with patch.object(mail,'read_mail',return_value=page):mail.sync(app)
        with app.connect() as c:
            cp=mail.checkpoint(c,'test-account');self.assertNotIn('through',cp);task=json.loads(cp['scan_tasks'])[0]
            self.assertEqual(c.execute('SELECT count(*) FROM emails').fetchone()[0],1)
        with patch.object(mail,'read_mail',return_value={'messages':[],'scanned':[],'folders':[],'complete':True}) as read:mail.sync(app)
        self.assertEqual(read.call_args.args[0],task['start']);self.assertEqual(read.call_args.args[4]['seen'],['one'])
        with app.connect() as c:self.assertEqual(mail.checkpoint(c,'test-account')['through'],task['end'])
    def test_completed_folder_and_nonmatching_read_cache_survive_restart(self):
        page=self.page();page['messages']=[];page['folders']=['["Inbox"]']
        with patch.object(mail,'read_mail',return_value=page):mail.sync(app)
        with patch.object(mail,'read_mail',return_value={**page,'scanned':[],'complete':True}) as read:mail.sync(app)
        self.assertEqual(read.call_args.args[4]['seen'],['one']);self.assertEqual(read.call_args.args[4]['folders'],['["Inbox"]'])
        with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM emails').fetchone()[0],0)
    def test_failed_or_invalid_page_leaves_cache_records_and_checkpoint_atomic(self):
        page=self.page();page['messages'].append({'bad':'record'})
        with patch.object(mail,'read_mail',return_value=page):mail.sync(app)
        with app.connect() as c:
            self.assertFalse(mail.checkpoint(c,'test-account'));self.assertEqual(c.execute('SELECT count(*) FROM emails').fetchone()[0],0);self.assertEqual(c.execute('SELECT count(*) FROM mail_scan_seen').fetchone()[0],0)
    def test_no_immediate_retry_storm_on_timeout(self):
        with patch.object(mail,'read_mail',side_effect=ValueError('Mail timed out')) as read:mail.sync(app)
        self.assertEqual(read.call_count,1);self.assertIn('timed out',mail.SYNC['error'])
        with app.connect() as c:self.assertEqual(len(json.loads(mail.checkpoint(c,'test-account')['scan_tasks'])),2)
    def test_large_history_has_strict_per_invocation_batch_limit(self):
        with patch.object(mail,'read_bounds',return_value={'oldest':'2000-01-01T00:00:00Z'}),patch.object(mail,'read_mail',return_value=[]) as read:mail.sync(app)
        self.assertEqual(read.call_count,2)
        with app.connect() as c:self.assertGreater(len(json.loads(mail.checkpoint(c,'test-account')['scan_tasks'])),100)
    def test_wall_clock_budget_stops_before_starting_more_work(self):
        clock=Mock(side_effect=[0,0,20,20])
        with patch.object(scanner.time,'monotonic',clock),patch.object(mail,'read_bounds',return_value={'oldest':'2000-01-01T00:00:00Z'}),patch.object(mail,'read_mail',return_value=[]) as read:mail.sync(app)
        self.assertEqual(read.call_count,1)
    def test_cancelled_page_does_not_commit_and_next_scan_resumes(self):
        page=self.page()
        def cancel(*args):mail.pause_sync();return page
        with patch.object(mail,'read_mail',side_effect=cancel):mail.sync(app)
        with app.connect() as c:self.assertFalse(mail.checkpoint(c,'test-account'));self.assertEqual(c.execute('SELECT count(*) FROM emails').fetchone()[0],0)
        with patch.object(mail,'read_mail',return_value=page):mail.sync(app)
        with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM emails').fetchone()[0],1)
    def test_pause_before_queued_worker_starts_prevents_any_mail_access(self):
        generation=mail.SCAN_GENERATION;mail.pause_sync()
        with patch.object(mail,'read_mail') as read:mail.sync(app,generation)
        read.assert_not_called()
    def test_cache_is_account_and_company_scope_isolated(self):
        page=self.page()
        with patch.object(mail,'read_mail',return_value=page):mail.sync(app)
        with app.connect() as c:app.save_job(c,{'title':'Scientist','company':'New Company'})
        with patch.object(mail,'read_mail',return_value={**page,'scanned':[]}) as read:mail.sync(app)
        self.assertEqual(read.call_args.args[4]['seen'],[])
        with app.connect() as c:c.execute("UPDATE settings SET value=? WHERE key='mail_account'",(json.dumps({'id':'different'}),))
        with patch.object(mail,'read_mail',return_value={**page,'scanned':[]}) as read:mail.sync(app)
        self.assertEqual(read.call_args.args[4]['seen'],[])
    def test_empty_unrelated_body_is_retried_after_download_grace_period(self):
        page=self.page();page['messages']=[];page['scanned'][0]['body_complete']=False
        with patch.object(mail,'read_mail',return_value=page):mail.sync(app)
        with app.connect() as c:c.execute("UPDATE mail_scan_seen SET checked_at='2000-01-01T00:00:00Z'")
        with patch.object(mail,'read_mail',return_value={**page,'scanned':[]}) as read:mail.sync(app)
        self.assertEqual(read.call_args.args[4]['seen'],[])
    def test_busy_scan_never_starts_another_reader(self):
        mail.SYNC_LOCK.acquire()
        try:
            with patch.object(mail,'read_mail') as read:mail.sync(app)
            read.assert_not_called()
        finally:mail.SYNC_LOCK.release()
    def test_auto_scan_cooldown_and_manual_minimum_rest(self):
        with patch.object(app,'settings',return_value={'mail_enabled':True}),patch.object(mail,'LAST_SCAN_FINISHED',100),patch.object(mail.time,'monotonic',return_value=399):self.assertFalse(mail.automatic_due(app))
        with patch.object(app,'settings',return_value={'mail_enabled':True}),patch.object(mail,'LAST_SCAN_FINISHED',100),patch.object(mail.time,'monotonic',return_value=400):self.assertTrue(mail.automatic_due(app))
        with patch.object(mail,'LAST_SCAN_FINISHED',100),patch.object(mail.time,'monotonic',return_value=101):
            with self.assertRaisesRegex(ValueError,'resting'):mail.start_sync(app)
    def test_cancel_terminates_only_owned_reader_process(self):
        process=Mock();process.poll.return_value=None;mail.SCAN_CANCEL.set()
        try:
            with patch.object(mail.subprocess,'Popen',return_value=process):
                with self.assertRaisesRegex(ValueError,'paused'):mail.mail_script(['bounds','','test-account'])
            process.terminate.assert_called_once();process.communicate.assert_called_once()
        finally:mail.SCAN_CANCEL.clear()
    def test_inaccessible_bounds_never_start_a_fallback_full_mailbox_scan(self):
        with patch.object(mail,'read_bounds',return_value=None),patch.object(mail,'read_mail') as read:mail.sync(app)
        read.assert_not_called()
        with app.connect() as c:self.assertFalse(mail.checkpoint(c,'test-account'))
    def test_out_of_window_progress_is_rejected(self):
        page=self.page();page['scanned'][0]['received_at']='1990-01-01T00:00:00Z'
        with patch.object(mail,'read_mail',return_value=page):mail.sync(app)
        with app.connect() as c:self.assertFalse(mail.checkpoint(c,'test-account'))
    def test_large_folder_metadata_inventory_resumes_without_reading_bodies(self):
        first={'oldest':'2024-01-01T00:00:00Z','folders':['["Inbox"]'],'complete':False}
        with patch.object(mail,'read_bounds',return_value=first),patch.object(mail,'read_mail') as reader:mail.sync(app)
        reader.assert_not_called()
        with app.connect() as c:self.assertNotIn('through',mail.checkpoint(c,'test-account'))
        final={'oldest':'2020-01-01T00:00:00Z','folders':['["Spam"]'],'complete':True}
        with patch.object(mail,'read_bounds',return_value=final) as bounds,patch.object(mail,'read_mail',return_value=[]):mail.sync(app)
        self.assertEqual(bounds.call_args.args[1]['folders'],['["Inbox"]'])
        with app.connect() as c:self.assertEqual(mail.checkpoint(c,'test-account')['history_oldest'],'2020-01-01T00:00:00Z')
    def test_metadata_only_stall_narrows_window_for_next_batch_without_retrying_now(self):
        result={'messages':[],'scanned':[],'folders':[],'complete':False}
        with patch.object(mail,'read_mail',return_value=result) as reader:mail.sync(app)
        self.assertEqual(reader.call_count,1)
        with app.connect() as c:
            cp=mail.checkpoint(c,'test-account');tasks=json.loads(cp['scan_tasks']);self.assertNotIn('through',cp);self.assertEqual(len(tasks),2)
    def test_mail_foreground_defers_without_changing_coverage(self):
        with patch.object(mail,'read_mail',return_value={'deferred':True}):mail.sync(app)
        with app.connect() as c:self.assertFalse(mail.checkpoint(c,'test-account'))
        self.assertIn('Mail is in use',mail.SYNC['summary'])
