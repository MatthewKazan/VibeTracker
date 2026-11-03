import base64
import copy
import json
import time
import unittest
from unittest.mock import patch
import app
import mail_sources as s
import mail_pipeline as pipeline
import mail_integration as mail
import test_mail as base

CONFIG={'provider':'gmail','client_id':'public-id','access_token':'private-token','refresh_token':'private-refresh','expires_at':9999999999,'email':'jobs@example.test'}
def gmail_message(ident='one',body='Acme has received your application for Backend Engineer.'):
    return {'id':ident,'internalDate':'1793534400000','labelIds':['SPAM'],'payload':{'mimeType':'text/plain','headers':[{'name':'From','value':'Acme <jobs@acme.com>'},{'name':'Subject','value':'Backend Engineer application'},{'name':'Message-ID','value':'<'+ident+'@test>'}],'body':{'data':base64.urlsafe_b64encode(body.encode()).decode(),'size':len(body)}}}

class AdapterTests(unittest.TestCase):
    def test_api_continuation_rejects_foreign_host_before_credentials(self):
        calls=[];adapter=s.Gmail(CONFIG,transport=lambda *a,**k:calls.append((a,k)))
        for url in ('https://evil.test/steal','https://gmail.googleapis.com@evil.test/','https://gmail.googleapis.com:444/'):
            with self.assertRaises(s.SourceError):adapter.get(url)
        self.assertFalse(calls)
    def test_refresh_rotation_and_auth_retry(self):
        calls=[];updated=[]
        def transport(url,**kw):
            calls.append((url,kw))
            if url.endswith('/token'):return {'access_token':'new','refresh_token':'rotated','expires_in':3600}
            if len(calls)==1:raise s.SourceError('expired',401)
            return {'emailAddress':'jobs@example.test'}
        a=s.Gmail(CONFIG,update=updated.append,transport=transport);self.assertEqual(a.profile()['addresses'],['jobs@example.test']);self.assertEqual(updated[0]['refresh_token'],'rotated');self.assertEqual(calls[-1][1]['headers']['Authorization'],'Bearer new')
    def test_gmail_spam_pages_baseline_history_dedup_and_expiry(self):
        a=s.Gmail(CONFIG);calls=[]
        def get(path):
            calls.append(path)
            if path=='/profile':return {'historyId':'100'}
            if path.startswith('/messages?'):
                self.assertIn('includeSpamTrash=true',path)
                return {'messages':[{'id':'one'}],'nextPageToken':'next'} if 'pageToken' not in path else {'messages':[{'id':'two'}]}
            if path.startswith('/messages/'):return gmail_message(path.split('/')[2].split('?')[0])
            return {'history':[{'messages':[{'id':'one'}],'messagesAdded':[{'message':{'id':'one'}}]}],'historyId':'120'}
        a.get=get
        first,cursor,done=a.page({});self.assertFalse(done);self.assertEqual(cursor['historyId'],'100');self.assertEqual(first[0]['folder_id'],'SPAM')
        second,cursor,done=a.page(cursor);self.assertTrue(done);self.assertEqual(cursor['historyId'],'100')
        changed,cursor,done=a.page(cursor);self.assertEqual(len(changed),1);self.assertEqual(cursor['historyId'],'120')
        a.get=lambda _:(_ for _ in ()).throw(s.SourceError('expired',404));self.assertEqual(a.page(cursor),([],{},False))
    def test_gmail_text_attachment_fetch_and_binary_attachment_skip(self):
        data=gmail_message();data['payload']['mimeType']='multipart/mixed';data['payload']['parts']=[{'mimeType':'text/plain','body':{'attachmentId':'text','size':5}},{'mimeType':'text/plain','filename':'secret.txt','body':{'attachmentId':'secret'}}];data['payload']['body']={}
        calls=[]
        def get(path):
            calls.append(path);return {'data':base64.urlsafe_b64encode(b'hello').decode()} if '/attachments/' in path else data
        a=s.Gmail(CONFIG);a.get=get;self.assertEqual(a.message('one')['body'],'hello');self.assertEqual(len(calls),2)
    def test_empty_or_oversized_gmail_body_not_classifiable(self):
        for data in (gmail_message(body=''),gmail_message()):
            if data['payload']['body']['size']:data['payload']['body']['size']=3000000
            a=s.Gmail(CONFIG);a.get=lambda _:data;m=a.message('one');self.assertFalse(m['body_complete']);self.assertIn('source_warning',m)
    def test_gmail_drafts_trash_deleted_are_skipped(self):
        a=s.Gmail(CONFIG)
        for label in ('DRAFT','TRASH'):
            data=gmail_message();data['labelIds']=[label];a.get=lambda _:data;self.assertIsNone(a.message('one'))
        a.get=lambda _:(_ for _ in ()).throw(s.SourceError('gone',404));self.assertIsNone(a.message('one'))
    def test_graph_folders_include_junk_archive_and_paginate(self):
        a=s.Graph({**CONFIG,'provider':'graph'})
        pages={'/me/mailFolders/deleteditems?$select=id':{'id':'trash'},'/me/mailFolders/drafts?$select=id':{'id':'draft'},'/me/mailFolders?includeHiddenFolders=true&$top=100&$select=id,childFolderCount':{'value':[{'id':'trash','childFolderCount':2},{'id':'junk'},{'id':'archive','childFolderCount':1}],'@odata.nextLink':'https://graph.microsoft.com/next'},'https://graph.microsoft.com/next':{'value':[{'id':'inbox'},{'id':'draft'}]},'/me/mailFolders/archive/childFolders?includeHiddenFolders=true&$top=100&$select=id,childFolderCount':{'value':[{'id':'old'}]}}
        a.get=pages.__getitem__;self.assertEqual(set(a.folders()),{'junk','archive','old','inbox'})
    def test_graph_delta_deleted_cursor_and_removed_items(self):
        a=s.Graph({**CONFIG,'provider':'graph'});a.folders=lambda:['junk'];data={'value':[{'id':'one','internetMessageId':'<one@test>','receivedDateTime':'2026-11-01T12:00:00Z','body':{'contentType':'html','content':'<p>Hello Acme</p><script>bad</script>'}},{'id':'gone','@removed':{}},{'id':'draft','isDraft':True}],'@odata.deltaLink':'https://graph.microsoft.com/delta'};a.get=lambda _:data
        messages,cursor,done=a.page({});self.assertTrue(done);self.assertEqual(len(messages),1);self.assertEqual(messages[0]['body'],'Hello Acme');self.assertEqual(cursor['deltas']['junk'],'https://graph.microsoft.com/delta')
        a.get=lambda _:(_ for _ in ()).throw(s.SourceError('gone',404));_,cursor,done=a.page(cursor);self.assertEqual(cursor['index'],0);_,cursor,done=a.page(cursor);self.assertEqual(cursor['index'],1);self.assertTrue(a.page(cursor)[2])
    def test_graph_immutable_text_header_on_each_request(self):
        calls=[];a=s.Graph({**CONFIG,'provider':'graph'},transport=lambda u,**kw:calls.append(kw) or {})
        a.get('/me');a.get('https://graph.microsoft.com/v1.0/next');self.assertTrue(all('ImmutableId' in v['headers']['Prefer'] and 'text' in v['headers']['Prefer'] for v in calls))
    def test_imap_folder_parser_localized_flags_literals_and_escaping(self):
        for row in (b'(\\Trash) "/" "Papierkorb"',b'(\\Drafts) "/" "Entwuerfe"',b'(\\Noselect) "/" "Root"'):
            self.assertIsNone(s.imap_folder(row))
        self.assertEqual(s.imap_folder(b'(\\Junk) "/" "Spam"'),b'Spam');self.assertEqual(s.imap_folder((b'() "/" {4}',b'Test')),b'Test');self.assertEqual(s.imap_folder(b'() "/" "a\\"b"'),b'a"b')
    def test_imap_fetch_only_text_readonly_uid_reset(self):
        class Connection:
            queries=[]
            def login(self,*a):pass
            def list(self):return 'OK',[b'(\\Junk) "/" "Spam"']
            def select(self,name,readonly):self.readonly=readonly;return 'OK',[]
            def response(self,_):return 'UIDVALIDITY',[b'99']
            def uid(self,command,*args):
                self.queries.append((command,args))
                if command=='search':return 'OK',[b'1']
                if 'HEADER' in args[-1]:return 'OK',[(b'1 (UID 1 INTERNALDATE "01-Nov-2026 12:00:00 +0000" BODYSTRUCTURE (("TEXT" "PLAIN" ("CHARSET" "UTF-8") NIL NIL "BASE64" 8 1)("APPLICATION" "PDF" NIL NIL NIL "BASE64" 99999999) "MIXED") BODY[HEADER] {100}',b'From: Acme <jobs@acme.com>\r\nSubject: Test\r\nMessage-ID: <one@test>\r\n\r\n'),b')']
                return 'OK',[(b'1 (BODY[1] {8}',b'aGVsbG8='),b')']
            def logout(self):pass
        connection=Connection();a=s.IMAP({'provider':'imap','email':'jobs@example.test','host':'imap.test','password':'secret'},factory=lambda *a,**kw:connection)
        messages,cursor,done=a.page({});self.assertTrue(connection.readonly);self.assertEqual(messages[0]['body'],'hello');self.assertTrue(messages[0]['remote_id'].endswith(':99:1'));self.assertFalse(any('BODY[]' in str(q) for q in connection.queries))
        connection.queries=[];cursor['positions'][cursor['folders'][0]]={'validity':'old','uid':500};a.page(cursor);self.assertEqual(connection.queries[0],('search',(None,'UID','1:*')))
    def test_imap_missing_uidvalidity_never_checkpoints(self):
        class Connection:
            def login(self,*a):pass
            def list(self):return 'OK',[b'() "/" "INBOX"']
            def select(self,*a,**k):return 'OK',[]
            def response(self,*a):return None,[None]
            def logout(self):pass
        a=s.IMAP({'host':'imap.test','email':'a@test','password':'secret'},factory=lambda *a,**k:Connection())
        with self.assertRaisesRegex(s.SourceError,'UIDVALIDITY'):a.page({})
    def test_validation_rejects_newlines_and_unsafe_links(self):
        for config in ({**CONFIG,'access_token':'a\nb'},{'provider':'imap','host':'http://evil','password':'a','email':'a@test'},{**CONFIG,'expires_at':float('nan')}):
            with self.assertRaises(ValueError):s.validate_config(config)
        for link in ('javascript:alert(1)','https://mail.google.com:bad/','https://evil.test/','https://u:p@mail.google.com/'):
            self.assertEqual(s.valid_link(link,'gmail'),'')

class SourceStorageTests(unittest.TestCase):
    setUp=base.MailTests.setUp
    def tearDown(self):s.CREDENTIALS.clear();s.UPDATES.clear();base.MailTests.tearDown(self)
    def source(self):
        account={'id':'gmail:test','provider':'gmail','addresses':['jobs@example.test'],'name':'Test Gmail'}
        with app.connect() as c:c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('mail_account',json.dumps(account)));c.execute('INSERT OR REPLACE INTO mail_source_accounts VALUES (?,?)',(account['id'],json.dumps(account)))
        s.CREDENTIALS[account['id']]=CONFIG.copy();return account
    def test_partial_failure_commits_prior_page_only_and_preserves_status(self):
        account=self.source();m={'remote_id':'one','internet_id':'one@test','sender':'Acme <jobs@acme.com>','subject':'Backend Engineer application','body':'Acme has received your application for Backend Engineer.','received_at':'2026-11-01T12:00:00+00:00'}
        class Adapter:
            def __init__(self,*a,**kw):pass
            def page(self,cursor):
                if cursor:raise s.SourceError('offline')
                return [m],{'page':2},False
        with patch.dict(s.ADAPTERS,gmail=Adapter):
            with self.assertRaisesRegex(s.SourceError,'offline'):s.sync_locked(app,account,app.current_jobs())
        with app.connect() as c:self.assertEqual(json.loads(c.execute('SELECT cursor FROM mail_provider_cursors').fetchone()[0]),{'page':2});self.assertEqual(c.execute('SELECT count(*) FROM emails').fetchone()[0],1)
        self.assertEqual(next(j['status'] for j in app.current_jobs() if j['id']==self.a),'Interview 2')
    def test_canonical_account_isolation_folder_move_and_manual_links(self):
        account=self.source();m={'remote_id':'one','internet_id':'one@test','sender':'Acme <jobs@acme.com>','subject':'Acme Backend Engineer','body':'Acme application received','received_at':'2026-11-01T12:00:00+00:00'}
        with app.connect() as c:
            ident=s.canonical(c,account,m);pipeline.collect(c,[{**m,'message_id':ident}],app.current_jobs(),account['id']);c.execute('INSERT INTO email_source_refs VALUES (?,?,?,?,?,?,?,?)',(account['id'],'one',ident,'gmail',m['internet_id'],'inbox','',1));mail.review(c,ident,'link',[self.b],app.save_job)
            self.assertEqual(s.canonical(c,account,{**m,'remote_id':'moved'}),ident)
            other={**account,'id':'gmail:other','addresses':['other@test']};self.assertNotEqual(s.canonical(c,other,m),ident)
            self.assertEqual(mail.message_detail(c,ident)['job_ids'],[self.b])
    def test_preprovider_snapshot_can_still_be_exported(self):
        with app.connect() as c:
            for table in ('email_source_refs','mail_provider_cursors','mail_source_accounts'):c.execute('DROP TABLE '+table)
            data=mail.export(c)
            self.assertEqual(data['source_accounts'],[]);self.assertEqual(data['source_refs'],[]);self.assertEqual(data['provider_cursors'],[])
    def test_export_has_metadata_not_credentials_and_restore_does_not_trust_cursor(self):
        account=self.source()
        with app.connect() as c:
            c.execute('INSERT INTO mail_provider_cursors VALUES (?,?,?)',(account['id'],'{"privateCursor":"value"}','fingerprint'));data=mail.export(c)
            self.assertNotIn('private-token',json.dumps(data));self.assertNotIn('private-refresh',json.dumps(data));self.assertIn('source_accounts',data)
            c.execute('DELETE FROM mail_provider_cursors');s.restore(c,data);self.assertEqual(c.execute('SELECT count(*) FROM mail_provider_cursors').fetchone()[0],0)
    def test_rotated_credentials_revision_and_disconnect_preserve_emails(self):
        account=self.source();s.rotated(account['id'],{**CONFIG,'access_token':'new'});s.rotated(account['id'],{**CONFIG,'access_token':'newer'});self.assertEqual(s.UPDATES[account['id']]['revision'],2)
        s.disconnect(app,account['id']);self.assertNotIn(account['id'],s.CREDENTIALS)
        with app.connect() as c:self.assertIsNone(mail.get_setting(c,'mail_account'));self.assertEqual(len(s.accounts(c)),1)
    def test_incomplete_source_never_enters_classifier_queue(self):
        account=self.source();m={'remote_id':'one','internet_id':'one@test','sender':'Acme <jobs@acme.com>','subject':'Acme Backend Engineer','body':'Acme partial body','received_at':'2026-11-01T12:00:00+00:00','body_complete':False,'source_warning':'incomplete'}
        class Adapter:
            def __init__(self,*a,**kw):pass
            def page(self,cursor):return [m],{'done':True},True
        with patch.dict(s.ADAPTERS,gmail=Adapter):s.sync_locked(app,account,app.current_jobs())
        with app.connect() as c:self.assertEqual(c.execute('SELECT analysis_state FROM emails').fetchone()[0],'warning')
    def test_late_empty_source_body_recovers_without_advancing_over_failure(self):
        account=self.source();m={'remote_id':'one','internet_id':'one@test','sender':'Acme <jobs@acme.com>','subject':'Acme Backend Engineer','body':'','received_at':'2026-11-01T12:00:00+00:00','body_complete':False,'source_warning':'waiting for body'}
        class Adapter:
            def __init__(self,*a,**kw):pass
            def page(self,cursor):return ([m] if not cursor else []),{'done':True},True
            def message(self,ident):return {**m,'body':'Acme has received your application for Backend Engineer.','body_complete':True,'source_warning':''}
        with patch.dict(s.ADAPTERS,gmail=Adapter):
            s.sync_locked(app,account,app.current_jobs());s.sync_locked(app,account,app.current_jobs())
        with app.connect() as c:
            row=c.execute('SELECT * FROM emails').fetchone();self.assertEqual(row['analysis_state'],'queued');self.assertIn('received your application',row['body']);self.assertEqual(c.execute('SELECT body_complete FROM email_source_refs').fetchone()[0],1)
    def test_main_only_http_routes_do_not_expose_credentials_to_renderer(self):
        import threading,urllib.request,urllib.error
        account=self.source();s.rotated(account['id'],CONFIG)
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(secret=None,data=None):
            headers={'X-Token':app.TOKEN}
            if secret:headers['X-Waypoint-Main']=secret
            req=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+'/api/mail/source/'+('ack' if data is not None else 'updates'),headers=headers,data=json.dumps(data).encode() if data is not None else None)
            try:
                with urllib.request.urlopen(req) as r:return r.status,json.load(r)
            except urllib.error.HTTPError as e:return e.code,json.load(e)
        try:
            with patch.object(app,'MAIN_TOKEN','main-secret'):
                self.assertEqual(request()[0],403);self.assertEqual(request('wrong')[0],403);self.assertEqual(request('main-secret')[1]['updates'][account['id']]['config']['access_token'],'private-token')
                request('main-secret',{'account_id':account['id'],'revision':0});self.assertIn(account['id'],s.UPDATES)
                request('main-secret',{'account_id':account['id'],'revision':1});self.assertNotIn(account['id'],s.UPDATES)
        finally:server.shutdown();server.server_close();thread.join()
    def test_resync_does_not_reopen_approved_decisions_or_duplicate_notifications(self):
        account=self.source();m={'remote_id':'one','internet_id':'one@test','sender':'Acme <jobs@acme.com>','subject':'Acme Backend Engineer','body':'We are not moving forward with your application for Backend Engineer at Acme.','received_at':'2026-11-01T12:00:00+00:00','body_complete':True}
        class Adapter:
            def __init__(self,*a,**kw):pass
            def page(self,cursor):return [m],{'done':True},True
        with patch.dict(s.ADAPTERS,gmail=Adapter):
            s.sync_locked(app,account,app.current_jobs())
            with app.connect() as c:
                row=dict(c.execute('SELECT * FROM emails').fetchone());pipeline.classify_one(c,row,{'kind':'rejection','evidence':m['body']});mail.review(c,row['message_id'],'approve',[self.a],app.save_job,mail.message_detail(c,row['message_id'])['review_token']);before=c.execute('SELECT count(*) FROM email_events').fetchone()[0]
            s.sync_locked(app,account,app.current_jobs())
        with app.connect() as c:self.assertEqual(c.execute('SELECT review FROM emails').fetchone()[0],'approved');self.assertEqual(c.execute('SELECT count(*) FROM email_events').fetchone()[0],before)

class RateLimitTests(unittest.TestCase):
    def test_retry_after_stops_repeated_requests_until_window_expires(self):
        calls=[]
        def transport(*a,**k):calls.append(1);raise s.SourceError('wait',429,time.time()+90)
        a=s.Gmail(CONFIG,transport=transport)
        try:
            with self.assertRaises(s.SourceError):a.get('/profile')
            with self.assertRaisesRegex(s.SourceError,'retry window'):s.Gmail(CONFIG,transport=transport).get('/profile')
            self.assertEqual(len(calls),1)
        finally:s.RETRY_AT.clear()
    def test_http_retry_after_is_parsed_without_reading_sensitive_error_body(self):
        import urllib.error
        from email.message import Message
        headers=Message();headers['Retry-After']='120'
        class Opener:
            def open(self,*a,**k):raise urllib.error.HTTPError('https://gmail.googleapis.com',429,'limited',headers,None)
        with patch.object(s.urllib.request,'build_opener',return_value=Opener()):
            with self.assertRaises(s.SourceError) as caught:s.request_json('https://gmail.googleapis.com')
            self.assertGreater(caught.exception.retry_at,time.time()+110)
