"""Persistent email links and reviewable rejection proposals. No remote services."""
import datetime as dt
import json
import re
import subprocess
import sys
import threading
import unicodedata
from urllib.parse import quote
from pathlib import Path
from urllib.parse import urlparse

SYNC_LOCK = threading.Lock()
SYNC = {'running': False, 'error': '', 'summary': ''}

def init(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS emails (
      message_id TEXT PRIMARY KEY, sender TEXT NOT NULL, subject TEXT NOT NULL,
      body TEXT NOT NULL, received_at TEXT NOT NULL, company TEXT NOT NULL DEFAULT '',
      match_kind TEXT NOT NULL DEFAULT 'unlinked', evidence TEXT NOT NULL DEFAULT '',
      rejection INTEGER NOT NULL DEFAULT 0, review TEXT NOT NULL DEFAULT 'none');
    CREATE TABLE IF NOT EXISTS email_jobs (
      message_id TEXT NOT NULL, job_id INTEGER NOT NULL,
      PRIMARY KEY(message_id,job_id));
    CREATE TABLE IF NOT EXISTS email_feedback (message_id TEXT PRIMARY KEY,reason TEXT NOT NULL,base_prompt TEXT NOT NULL,proposal TEXT NOT NULL DEFAULT '',explanation TEXT NOT NULL DEFAULT '',state TEXT NOT NULL DEFAULT 'queued',error TEXT NOT NULL DEFAULT '');
    CREATE TABLE IF NOT EXISTS email_decisions (message_id TEXT NOT NULL,job_id INTEGER NOT NULL,status TEXT NOT NULL,PRIMARY KEY(message_id,job_id));
    CREATE TABLE IF NOT EXISTS email_accounts (message_id TEXT NOT NULL,account_id TEXT NOT NULL,PRIMARY KEY(message_id,account_id));
    CREATE TABLE IF NOT EXISTS mail_checkpoints (account_id TEXT NOT NULL,key TEXT NOT NULL,value TEXT NOT NULL,PRIMARY KEY(account_id,key));
    CREATE TABLE IF NOT EXISTS mail_sync (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    ''')
    if 'invitation' not in {r[1] for r in c.execute('PRAGMA table_info(emails)')}:
        c.execute('ALTER TABLE emails ADD COLUMN invitation INTEGER NOT NULL DEFAULT 0')
    columns={r[1] for r in c.execute('PRAGMA table_info(emails)')}
    for name in ('category','analysis_version','ignored_from'):
        if name not in columns:c.execute(f"ALTER TABLE emails ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
    for m in c.execute("SELECT * FROM emails WHERE category=''").fetchall():
        category='rejection' if m['rejection'] else 'interview' if m['invitation'] else 'confirmation' if confirmation_evidence(dict(m)) else 'other'
        c.execute('UPDATE emails SET category=? WHERE message_id=?',(category,m['message_id']))
    import mail_pipeline
    mail_pipeline.init(c)

def normalized(text):
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC',str(text)).casefold()))

def contains(text, phrase):
    return bool(phrase) and (' '+phrase+' ') in (' '+text+' ')

REJECTION = re.compile(r"(?:not (?:be )?(?:moving|move|proceeding|proceed|going|go) (?:forward|ahead)|(?:will|can|could|are|have) (?:not|no longer) (?:be )?(?:offer|proceed|consider|move|pursue)|decided (?:not to (?:move|proceed|continue|advance|pursue|offer|select|consider)|to (?:move|proceed|go) (?:forward|ahead) with other)|(?:position|role) (?:has been|is) (?:filled|closed)|(?:application|candidacy) (?:was|has been|is) (?:unsuccessful|rejected)|selected (?:another|other) candidate|(?:pursue|pursuing|chosen|choosing|selecting) (?:other|another) (?:candidate|applicant)|(?:unable|not able) to (?:offer|invite|proceed|move forward|advance)|(?:application|candidacy) (?:is )?no longer under consideration|(?:were|was|are) not selected|(?:not|won't) be taking (?:your|the) application (?:any )?further)", re.I)
RECRUITING = re.compile(r'\b(application|applied|applying|position|role|interview|candidate|recruit|careers|hiring|opportunity|submission|resume|résumé|assessment)\b', re.I)

ANALYSIS_VERSION='tracked-jobs-v2'
CONFIRMATION=re.compile(r"(?:thank(?:s| you) (?:for (?:applying|your (?:application|interest))|you for)|(?:received|submitted|reviewing) your application|your application (?:has been|was|is) (?:received|submitted)|application (?:received|submitted)|successfully (?:applied|submitted))",re.I)

def current_message(message):
    """Current authored text only; keep the complete original in storage/UI."""
    body=message.get('body','')
    lines=[]
    for line in body.splitlines():
        if re.match(r'^\s*(?:On .{3,300}wrote:|[-_]{2,}\s*(?:Original|Forwarded|Quoted) message|Begin forwarded message:|From:\s*.+(?:@|<))',line,re.I):break
        if re.match(r'^\s*>',line):continue
        lines.append(line)
    return {'subject':message.get('subject',''),'body':'\n'.join(lines),'sender':message.get('sender','')}

def message_text(message):
    current=current_message(message)
    return current['subject']+'\n'+current['body']

JOB_CONTEXT=re.compile(r'\b(?:job|application|applied|applying|candidate|candidacy|recruiting|recruiter|hiring|employment|resume|résumé|interview|phone screen|screening call|technical (?:test|assessment)|coding (?:test|assessment)|engineer|developer|scientist|analyst|designer|internship|position|role)\b',re.I)
CONSUMER_CONTEXT=re.compile(r'\b(?:boarding pass|flight (?:confirmation|itinerary|reservation)|mobile boarding|check[ -]?in (?:is|for|now)|your (?:flight|reservation|order|purchase|shipment)|order (?:confirmation|shipped)|shipping confirmation|payment (?:received|confirmation)|credit card application|loan application|visa application|rental application|apartment application)\b',re.I)
def employment_context(message):return bool(JOB_CONTEXT.search(message_text(message)))
def consumer_message(message):
    text=message_text(message)
    return bool(CONSUMER_CONTEXT.search(text)) and not bool(re.search(r'\b(?:interview|recruiting|recruiter|hiring|candidacy|employment|job application|applied for|applying for|technical (?:test|assessment))\b',text,re.I))

def confirmation_evidence(message):
    text=message_text(message)
    if consumer_message(message) or any(status_evidence(kind,message) for kind in ('rejection','interview','offer')):return ''
    found=CONFIRMATION.search(text)
    if not found:return ''
    # Interest, subscriptions and generic submissions are not job receipts.
    if not re.search(r'\b(?:application|applying|applied)\b',found.group(0),re.I) and not employment_context(message):return ''
    return found.group(0)

def invitation_evidence(message):
    # A condition and an action must not borrow context from different sentences.
    text=re.sub(r'\s+',' ',message_text(message))
    for sentence in re.split(r'[.!?]',text):
        if re.search(r"\b(if|should you|may|might|would be selected|if selected|potential candidates)\b",sentence,re.I):continue
        if re.search(r"\b(?:interview|technical (?:test|assessment|challenge)|coding (?:test|assessment|challenge)|take.home (?:test|assignment)|online assessment|phone screen|screening call)\b",sentence,re.I) and re.search(r"(?:please (?:complete|take|schedule|book|choose|select|submit|share|send|confirm)|(?:invite|inviting|invited) you|(?:like|love) to (?:invite|schedule|arrange|meet)|(?:schedule|book) (?:your|an|a|the)|(?:your|the) (?:interview|assessment|coding challenge) (?:is scheduled|is confirmed|has been scheduled)|(?:are you|you are|would you be) available|(?:complete|submit) (?:the|this|your|a|an) (?:technical|coding|online|take.home)|\bavailability\b)",sentence,re.I):return sentence.strip()[:600]
        if employment_context(message) and re.search(r"(?:like|love) to (?:speak|chat|meet) with you|(?:availability|available).{0,80}(?:conversation|call|meeting)|(?:phone screen|screening call).{0,60}(?:scheduled|confirmed)",sentence,re.I):return sentence.strip()[:600]
    return ''

def status_evidence(kind,message):
    if consumer_message(message) or not employment_context(message):return ''
    text=re.sub(r'\s+',' ',message_text(message))
    if kind=='interview':return invitation_evidence(message)
    if kind=='rejection':
        for sentence in re.split(r'[.!?]',text):
            if re.search(r'\b(?:if|may|might|could|in case)\b',sentence,re.I):continue
            found=REJECTION.search(sentence)
            if found:return sentence.strip()[:1000]
    if kind=='offer':
        for sentence in re.split(r'[.!?]',text):
            if re.search(r'\b(?:if|may|might|could|discount|coupon|sale|percent|% off)\b',sentence,re.I):continue
            if re.search(r'(?:offer (?:you|of|for) .{0,160}\b(?:position|role|job|employment)\b|(?:job|employment) offer|offer letter|(?:review|sign).{0,60}employment agreement|offering you .{0,160}\b(?:position|role|job)\b)',sentence,re.I):return sentence.strip()[:1000]
    return ''

def match(message, jobs):
    """Explainable lexical matches; ambiguity remains visible for human resolution."""
    head = normalized(message['sender']+' '+message['subject'])
    body = normalized(message['body'])
    companies = {}
    for job in jobs:
        if job.get('company', '').strip():
            companies.setdefault(normalized(job['company']), []).append(job)
    matched = []
    for name, group in companies.items():
        # A full company name, or its job-site hostname in the sender. Never infer
        # employer identity from shared applicant-tracking hosts.
        hosts = {urlparse(j.get('url') or '').hostname for j in group}
        host_match = any(h and not any(x in h for x in ('greenhouse','lever.co','workday','ashby','gem.com','linkedin','indeed')) and h.removeprefix('www.') in message['sender'].casefold() for h in hosts)
        alias=re.sub(r' (?:incorporated|inc|llc|ltd|limited|corp|corporation)$','',name)
        if contains(head, name) or (alias!=name and contains(head,alias)) or host_match or ((RECRUITING.search(message['subject']+' '+message['body']) or confirmation_evidence(message)) and (contains(body,name) or (alias!=name and contains(body,alias)))):
            matched.extend(group)
    specific = [j for j in matched if contains(normalized(message['subject']+' '+message['body']), normalized(j['title']))]
    linked = specific or matched
    company = ' / '.join(sorted({j['company'] for j in linked}))
    kind = 'role' if specific else 'company' if linked else 'unlinked'
    evidence = REJECTION.search(message['subject']+'\n'+message['body'])
    return linked, company, kind, evidence.group(0) if evidence else ''

def ingest(c, messages, save_job, classifications=None, account_id=None):
    jobs = [dict(r) for r in c.execute('SELECT * FROM jobs')]
    added = 0
    for m in sorted(messages,key=lambda m:m.get('received_at','') if isinstance(m,dict) else ''):
        if not isinstance(m, dict) or any(not isinstance(m.get(k), str) for k in ('message_id','sender','subject','body','received_at')):
            raise ValueError('Invalid email record. Sync checkpoint was not advanced.')
        if not m['message_id'] or len(m['body']) > 2_000_000:
            raise ValueError('Invalid email ID or email exceeds 2 MB.')
        stamp = dt.datetime.fromisoformat(m['received_at'].replace('Z','+00:00'))
        if stamp.tzinfo is None: raise ValueError('Email timestamp must include a timezone.')
        existing=c.execute('SELECT review,analysis_version,match_kind FROM emails WHERE message_id=?',(m['message_id'],)).fetchone()
        reanalyze=existing and existing['review']=='none' and existing['analysis_version']!=ANALYSIS_VERSION
        if existing and not reanalyze:
            if account_id:c.execute('INSERT OR IGNORE INTO email_accounts VALUES (?,?)',(m['message_id'],account_id))
            continue
        linked, company, kind, evidence = match(m, jobs)
        rejection = bool(evidence and RECRUITING.search(m['subject']+' '+m['body']))
        invitation = invitation_evidence(m) if not rejection else ''
        if classifications is not None and m['message_id'] in classifications:
            classified=classifications[m['message_id']]
            rejection=classified['kind']=='rejection'
            invitation=classified['evidence'] if classified['kind']=='interview' else ''
            evidence=classified['evidence'] if rejection else ''
        category='rejection' if rejection else 'interview' if invitation else 'confirmation' if confirmation_evidence(m) else 'other'
        if classifications is not None and m['message_id'] in classifications:
            classified=classifications[m['message_id']]
            category=classified['kind']
            if category=='other' and confirmation_evidence(m):category='confirmation'
            if 'job_ids' in classified:
                selected=set(classified['job_ids']);linked=[j for j in jobs if j['id'] in selected]
                if classified.get('match_kind')=='company':
                    companies={normalized(j['company']) for j in linked}
                    linked=[j for j in jobs if normalized(j['company']) in companies]
                company=' / '.join(sorted({j['company'] for j in linked}));kind=classified.get('match_kind','role') if linked else 'unlinked'
        if reanalyze and existing['match_kind']=='manual':
            manual_ids={r[0] for r in c.execute('SELECT job_id FROM email_jobs WHERE message_id=?',(m['message_id'],))}
            linked=[j for j in jobs if j['id'] in manual_ids];company=' / '.join(sorted({j['company'] for j in linked}));kind='manual'
        review = 'pending' if rejection or invitation else 'none'
        if not linked and category=='other' and not RECRUITING.search(m['subject']+' '+m['body']) and not (classifications or {}).get(m['message_id'],{}).get('related'): continue
        if reanalyze:
            c.execute('DELETE FROM email_jobs WHERE message_id=?',(m['message_id'],))
            c.execute('DELETE FROM emails WHERE message_id=?',(m['message_id'],))
        c.execute('INSERT INTO emails (message_id,sender,subject,body,received_at,company,match_kind,evidence,rejection,review) VALUES (?,?,?,?,?,?,?,?,?,?)', (m['message_id'],m['sender'],m['subject'],m['body'],m['received_at'],company,kind,evidence or invitation,int(rejection),review))
        c.execute('UPDATE emails SET invitation=?,category=?,analysis_version=? WHERE message_id=?',(int(bool(invitation)),category,ANALYSIS_VERSION,m['message_id']))
        for job in linked:
            c.execute('INSERT INTO email_jobs VALUES (?,?)', (m['message_id'],job['id']))
        if account_id:c.execute('INSERT OR IGNORE INTO email_accounts VALUES (?,?)',(m['message_id'],account_id))
        added += 1
    return added

def review(c, message_id, action, ids, save_job, expected_token=None):
    email = c.execute('SELECT * FROM emails WHERE message_id=?',(message_id,)).fetchone()
    if not email: raise ValueError('Email no longer exists.')
    account=get_setting(c,'mail_account')
    if account and not c.execute('SELECT 1 FROM email_accounts WHERE message_id=? AND account_id=?',(message_id,account['id'])).fetchone():raise ValueError('This email is not in the selected account.')
    if expected_token is not None:
        import mail_pipeline
        if expected_token!=mail_pipeline.review_token(c,dict(email)):raise ValueError('This email proposal changed. Review the refreshed email before confirming.')
    if action not in ('approve','dismiss','link','ignore','unignore'): raise ValueError('Unknown email action.')
    if action=='ignore':
        if email['review']!='ignored':c.execute("UPDATE emails SET ignored_from=review,review='ignored' WHERE message_id=?",(message_id,))
        import mail_pipeline;mail_pipeline.touch(c)
        return
    if action=='unignore':
        if email['review']!='ignored':raise ValueError('This email is not ignored.')
        c.execute("UPDATE emails SET review=?,ignored_from='',ignore_source='restored' WHERE message_id=?",(email['ignored_from'] or 'none',message_id))
        import mail_pipeline;mail_pipeline.touch(c);return
    if not isinstance(ids,list) or any(type(i) is not int for i in ids): raise ValueError('Select application IDs.')
    ids = list(set(ids))
    selected = [c.execute('SELECT * FROM jobs WHERE id=?',(i,)).fetchone() for i in ids]
    if any(j is None for j in selected): raise ValueError('One of these applications no longer exists.')
    if action != 'link' and email['review'] != 'pending': raise ValueError('This email has already been reviewed or has no proposed rejection.')
    if action == 'approve' and not ids: raise ValueError('Choose at least one affected application.')
    if action == 'approve':
        import mail_pipeline
        kind=email['category']
        if kind not in mail_pipeline.TARGETS or not email['evidence'].strip() or mail_pipeline.normalize_quote(email['evidence']) not in mail_pipeline.normalize_quote(message_text(dict(email))) or not status_evidence(kind,{'subject':email['subject'],'body':email['evidence']}) or not status_evidence(kind,dict(email)):
            raise ValueError('The current email does not support this status proposal. Reload this email and retry analysis before approving.')
        linked = {r[0] for r in c.execute('SELECT job_id FROM email_jobs WHERE message_id=?',(message_id,))}
        if not set(ids).issubset(linked): raise ValueError('Link this email to the application first.')
    if action == 'link':
        c.execute('DELETE FROM email_jobs WHERE message_id=?',(message_id,))
        for i in ids: c.execute('INSERT INTO email_jobs VALUES (?,?)',(message_id,i))
        c.execute('UPDATE emails SET company=?,match_kind=? WHERE message_id=?',(' / '.join(sorted({j['company'] for j in selected})), 'manual',message_id))
        import mail_pipeline;mail_pipeline.touch(c)
    else:
        if action == 'approve':
            for i in ids:
                target='Offer' if email['category']=='offer' else 'Interview pending' if email['invitation'] else 'Rejected'
                save_job(c,{'status':target,'_email_approval':True},i)
                c.execute('INSERT OR REPLACE INTO email_decisions VALUES (?,?,?)',(message_id,i,target))
        c.execute('UPDATE emails SET review=? WHERE message_id=?',('approved' if action=='approve' else 'dismissed',message_id))
        import mail_pipeline
        if action=='approve':mail_pipeline.record_approval(c,message_id,ids)
        else:mail_pipeline.touch(c)

def export(c):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='emails'").fetchone():return {'messages':[],'links':[],'feedback':[],'decisions':[],'sync':{}}
    return {**__import__('mail_sources').export(c),'messages':[dict(r) for r in c.execute('SELECT * FROM emails')],
            'links':[dict(r) for r in c.execute('SELECT * FROM email_jobs')],
            'feedback':[dict(r) for r in c.execute('SELECT * FROM email_feedback')],
            'decisions':[dict(r) for r in c.execute('SELECT * FROM email_decisions')],
            'accounts':table_rows(c,'email_accounts'),'checkpoints':table_rows(c,'mail_checkpoints'),
            'events':table_rows(c,'email_events'),'approvals':table_rows(c,'job_status_approvals'),'missing':table_rows(c,'email_missing'),'missing_sources':table_rows(c,'email_missing_messages'),
            'sync':dict(c.execute('SELECT key,value FROM mail_sync'))}

def inbox(c,include_body=True,query="",options=None):
    options=options or {}
    account=get_setting(c,'mail_account',None)
    fields='e.*' if include_body else ','.join('substr(e.body,1,800) AS body' if r[1]=='body' else 'e.'+r[1] for r in c.execute('PRAGMA table_info(emails)'))
    fields+=',length(e.body) AS body_length'
    sql='SELECT '+fields+' FROM emails e';params=[];conditions=[]
    if account:sql+=' JOIN email_accounts a USING(message_id)';conditions.append('a.account_id=?');params.append(account['id'])
    if query:
        c.create_function('casefold',1,lambda value:str(value or '').casefold())
        escaped=query.casefold().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        conditions.append("casefold(e.sender||' '||e.subject||' '||e.company||' '||e.body) LIKE ? ESCAPE '\\'");params.append('%'+escaped+'%')
    if options.get('job_id'):
        conditions.append('EXISTS(SELECT 1 FROM email_jobs l WHERE l.message_id=e.message_id AND l.job_id=?)');params.append(int(options['job_id']))
    if options.get('pending')=='1':conditions.append("e.review='pending'")
    if options.get('show_ignored')=='0':conditions.append("e.review!='ignored'")
    category="CASE WHEN e.analysis_state='queued' AND e.review='none' THEN 'unclassified' ELSE e.category END"
    if options.get('type'):conditions.append(category+'=?');params.append(options['type'])
    if options.get('exclude_confirmations')=='1':conditions.append("e.category!='confirmation'")
    def localday(value):
        try:return dt.datetime.fromisoformat(value.replace('Z','+00:00')).astimezone().date().isoformat()
        except (ValueError,AttributeError):return ''
    c.create_function('localday',1,localday)
    for key,comparison in [('from','>='),('to','<=')]:
        if options.get(key):
            dt.date.fromisoformat(options[key]);conditions.append('localday(e.received_at)'+comparison+'?');params.append(options[key])
    if conditions:sql+=' WHERE '+' AND '.join(conditions)
    matching=c.execute('SELECT count(*) FROM ('+sql+')',params).fetchone()[0]
    sort=options.get('sort','newest')
    order={'oldest':'julianday(e.received_at) ASC', 'type':category+' ASC,julianday(e.received_at) DESC', 'status':"CASE e.review WHEN 'pending' THEN 0 WHEN 'none' THEN 1 WHEN 'approved' THEN 2 WHEN 'dismissed' THEN 3 ELSE 4 END,julianday(e.received_at) DESC",'company':'e.company COLLATE NOCASE,julianday(e.received_at) DESC'}.get(sort,'julianday(e.received_at) DESC')
    sql+=' ORDER BY '+order+',e.message_id'
    offset=max(0,int(options.get('offset',0)));limit=None
    if 'limit' in options:
        limit=max(1,min(1000,int(options['limit'])));sql+=' LIMIT ? OFFSET ?';params.extend([limit,offset])
    messages=[dict(r) for r in c.execute(sql,params)]
    if query:
        for message in messages:message['search_query']=query.lower()
    decorate_messages(c,messages)
    import mail_pipeline
    return mail_pipeline.attach(c,{'messages':messages,'matching':matching,'offset':offset,'has_more':limit is not None and offset+len(messages)<matching,'account':account,'sync':checkpoint(c,account['id']) if account else {}, 'worker':dict(SYNC), 'available':__import__('mail_sources').available(account),'prompt':get_prompt(c),'shortcut':get_setting(c,'mail_shortcut','JobTracker Email Review'),'use_shortcut':get_setting(c,'mail_use_shortcut',True)})

def decorate_messages(c,messages):
    for start in range(0,len(messages),200):
        batch=messages[start:start+200];by_id={m['message_id']:m for m in batch};ids=list(by_id);marks=','.join('?' for _ in ids)
        for m in batch:m.update(job_ids=[],feedback=None,decisions=[])
        for row in c.execute('SELECT l.message_id,l.job_id FROM email_jobs l JOIN jobs j ON j.id=l.job_id WHERE message_id IN ('+marks+') ORDER BY l.job_id',ids):by_id[row[0]]['job_ids'].append(row[1])
        for row in c.execute('SELECT * FROM email_feedback WHERE message_id IN ('+marks+')',ids):by_id[row['message_id']]['feedback']=dict(row)
        for row in c.execute('SELECT message_id,job_id,status FROM email_decisions WHERE message_id IN ('+marks+')',ids):by_id[row['message_id']]['decisions'].append({'job_id':row['job_id'],'status':row['status']})
        for m in batch:m['mail_url']='message://%3C'+quote(m['message_id'].strip('<>'),safe='')+'%3E'

def read_mail(since, until, account_id, profiles=None):
    if sys.platform != 'darwin': raise ValueError('Apple Mail sync is available on macOS only.')
    try:
        result = subprocess.run(['/usr/bin/osascript','-l','JavaScript',str(Path(__file__).with_name('mail_reader.js')),since,until,account_id,json.dumps(profiles or [])],capture_output=True,text=True,timeout=180)
    except subprocess.TimeoutExpired:
        raise ValueError('Apple Mail timed out. Open Mail, let it finish downloading, then retry. The checkpoint is unchanged.') from None
    if result.returncode:
        raise ValueError('Could not read Apple Mail. Allow automation of Mail in System Settings → Privacy & Security → Automation, then retry. The checkpoint is unchanged. '+result.stderr.strip()[:350])
    return json.loads(result.stdout)

def sync(app):
    import mail_pipeline
    return mail_pipeline.sync(app)

def start_sync(app):
    threading.Thread(target=sync,args=(app,),daemon=True).start()
    return {'ok':True}

def worker(app):
    import time,mail_pipeline
    threading.Thread(target=mail_pipeline.analysis_worker,args=(app,),daemon=True).start()
    threading.Thread(target=mail_pipeline.lookup_worker,args=(app,),daemon=True).start()
    with app.connect() as c:
        interrupted=[r[0] for r in c.execute("SELECT message_id FROM email_feedback WHERE state IN ('queued','running')")]
    for message_id in interrupted:start_feedback(app,message_id)
    while True:
        try:
            if app.settings().get('mail_enabled') is True: sync(app)
        except Exception as exc: SYNC['error']=str(exc)
        time.sleep(60)

def restore(c, data, job_map):
    if not isinstance(data,dict) or any(not isinstance(data.get(k,[]),list) for k in ('messages','links','proposals','decisions','feedback','accounts')):
        raise ValueError('Invalid email backup.')
    restored = set()
    for m in data.get('messages',[]):
        if not isinstance(m,dict) or any(not isinstance(m.get(k),str) for k in ('message_id','sender','subject','body','received_at','company','match_kind','evidence','review')):
            raise ValueError('Invalid email in backup.')
        if m['review'] not in ('none','pending','approved','dismissed','ignored'): raise ValueError('Invalid email review state.')
        if c.execute('SELECT 1 FROM emails WHERE message_id=?',(m['message_id'],)).fetchone(): continue
        c.execute('INSERT INTO emails (message_id,sender,subject,body,received_at,company,match_kind,evidence,rejection,review) VALUES (?,?,?,?,?,?,?,?,?,?)',tuple(m[k] for k in ('message_id','sender','subject','body','received_at','company','match_kind','evidence'))+(int(bool(m.get('rejection'))),m['review']))
        if m.get('invitation'):c.execute('UPDATE emails SET invitation=1 WHERE message_id=?',(m['message_id'],))
        category=m.get('category') or ('rejection' if m.get('rejection') else 'interview' if m.get('invitation') else 'confirmation' if confirmation_evidence(m) else 'other')
        if category not in ('rejection','interview','offer','confirmation','other'):raise ValueError('Invalid email category in backup.')
        c.execute('UPDATE emails SET category=?,analysis_version=?,ignored_from=? WHERE message_id=?',(category,m.get('analysis_version',''),m.get('ignored_from',''),m['message_id']))
        c.execute('UPDATE emails SET analysis_state=?,analysis_error=?,ignore_source=?,body_version=?,analysis_revision=? WHERE message_id=?',(m.get('analysis_state','done') if m.get('analysis_state')!='running' else 'queued',m.get('analysis_error',''),m.get('ignore_source',''),m.get('body_version',0),m.get('analysis_revision',0),m['message_id']))
        restored.add(m['message_id'])
    for link in data.get('links',[]):
        if link['message_id'] in restored and link['job_id'] in job_map:
            c.execute('INSERT OR IGNORE INTO email_jobs VALUES (?,?)',(link['message_id'],job_map[link['job_id']]))
    for a in data.get('accounts',[]):
        if c.execute('SELECT 1 FROM emails WHERE message_id=?',(a['message_id'],)).fetchone():c.execute('INSERT OR IGNORE INTO email_accounts VALUES (?,?)',(a['message_id'],a['account_id']))
    restore_feedback(c,data)
    # Keep the existing checkpoint on merge. A fresh restore rechecks from the
    # earliest application, deduplicating restored messages by Message-ID.

    for d in data.get('decisions',[]):
        if d['message_id'] in restored and d['job_id'] in job_map:
            c.execute('INSERT OR IGNORE INTO email_decisions VALUES (?,?,?)',(d['message_id'],job_map[d['job_id']],d['status']))
    import mail_pipeline
    mail_pipeline.restore(c,data,job_map)
    __import__('mail_sources').restore(c,data)

DEFAULT_PROMPT = '''Retain every application-received confirmation and all correspondence about the supplied tracked companies/jobs, including shortened company names and applicant-tracking senders. Use the supplied job IDs to identify links; company-only messages must link to all roles at that company. Confirmations do not propose status changes. Identify explicit job-application rejections and actual interview or technical-test requests. Return other for generic hiring-process descriptions, and conditional promises such as "if selected we will invite you to interview". Use only the current message, ignoring quoted historical correspondence. Support each proposal with an exact quote. Never change a job status: all proposals require manual approval. Link company-only correspondence to all applications from that company and ask the user to choose the affected application when multiple roles match. Never infer which job was rejected from a company-only message.'''

def get_setting(c,key,default=None):
    r=c.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
    return json.loads(r[0]) if r else default

def get_prompt(c):
    return get_setting(c,'mail_prompt',DEFAULT_PROMPT)

def run_shortcut(name,payload):
    import tempfile
    if name in ('','JobTracker Email Review'):
        helper=Path(__file__).with_name('mail_shortcut.py')
        try:result=subprocess.run([sys.executable,'-B',str(helper)],input=json.dumps(payload),capture_output=True,text=True,timeout=240)
        except subprocess.TimeoutExpired:raise ValueError('The local email classifier timed out. Retry this email.') from None
        if result.returncode:raise ValueError('The local email classifier failed. '+result.stderr.strip()[:500])
        data=json.loads(result.stdout)
        if not isinstance(data,dict):raise ValueError('The local email classifier must return a JSON object.')
        return data
    if sys.platform!='darwin':raise ValueError('Custom Apple Shortcuts require macOS. Clear the custom name to use the bundled classifier.')
    with tempfile.TemporaryDirectory(prefix='jobtracker-feedback-') as folder:
        source=Path(folder)/'input.json';target=Path(folder)/'output.json'
        source.write_text(json.dumps(payload),encoding='utf-8')
        try:
            result=subprocess.run(['/usr/bin/shortcuts','run',name,'--input-path',str(source),'--output-path',str(target)],capture_output=True,text=True,timeout=240)
        except subprocess.TimeoutExpired:raise ValueError('The email review Shortcut timed out. Retry from the email review panel.') from None
        if result.returncode:raise ValueError('The email review Shortcut could not run. Open it in Shortcuts and check its permissions. '+result.stderr.strip()[:500])
        if not target.exists():raise ValueError('The email review Shortcut returned no JSON output.')
        data=json.loads(target.read_text())
        if not isinstance(data,dict):raise ValueError('The email review Shortcut must return a JSON object.')
        return data

def analyze_feedback(app,message_id):
    try:
        with app.connect() as c:
            f=dict(c.execute('SELECT * FROM email_feedback WHERE message_id=?',(message_id,)).fetchone())
            m=dict(c.execute('SELECT * FROM emails WHERE message_id=?',(message_id,)).fetchone())
            name=get_setting(c,'mail_shortcut','JobTracker Email Review')
            model=get_setting(c,'model','')
            jobs=[dict(r) for r in c.execute('SELECT id,company,title,url,date_applied FROM jobs')]
            c.execute("UPDATE email_feedback SET state='running',error='' WHERE message_id=?",(message_id,))
        with app.priority():output=run_shortcut(name,{'mode':'feedback','model':model,'classifier_prompt':f['base_prompt'],'email':m,'jobs':jobs,'disapproval_reason':f['reason']})
        proposal=output.get('proposed_prompt');explanation=output.get('explanation')
        if not isinstance(proposal,str) or not proposal.strip() or len(proposal)>16000 or not isinstance(explanation,str):raise ValueError('Shortcut returned an invalid prompt proposal.')
        with app.LOCK,app.connect() as c:c.execute("UPDATE email_feedback SET state='ready',proposal=?,explanation=?,error='' WHERE message_id=?",(proposal,explanation,message_id));__import__('mail_pipeline').touch(c)
    except Exception as exc:
        with app.connect() as c:c.execute("UPDATE email_feedback SET state='failed',error=? WHERE message_id=?",(str(exc),message_id));__import__('mail_pipeline').touch(c)

def start_feedback(app,message_id):
    threading.Thread(target=analyze_feedback,args=(app,message_id),daemon=True).start()

def apply_feedback(c,message_id):
    f=c.execute('SELECT * FROM email_feedback WHERE message_id=?',(message_id,)).fetchone()
    if not f or f['state']!='ready':raise ValueError('No prompt proposal is ready.')
    if f['base_prompt']!=get_prompt(c):raise ValueError('The prompt changed since this proposal was generated. Analyze again before applying.')
    c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('mail_prompt',json.dumps(f['proposal'])))
    c.execute("UPDATE email_feedback SET state='applied' WHERE message_id=?",(message_id,));__import__('mail_pipeline').touch(c)


def restore_feedback(c,data):
    for f in data.get('feedback',[]):
        if not isinstance(f,dict) or any(not isinstance(f.get(k),str) for k in ('message_id','reason','base_prompt','proposal','explanation','state','error')):raise ValueError('Invalid feedback backup.')
        state=f['state'] if f['state'] in ('ready','applied','failed') else 'failed'
        c.execute('INSERT OR IGNORE INTO email_feedback VALUES (?,?,?,?,?,?,?)',(f['message_id'],f['reason'],f['base_prompt'],f['proposal'],f['explanation'],state,f['error']))


def checkpoint(c,account_id):
    return dict(c.execute('SELECT key,value FROM mail_checkpoints WHERE account_id=?',(account_id,)))

def list_accounts():
    if sys.platform!='darwin':raise ValueError('Apple Mail accounts are available on macOS only.')
    result=subprocess.run(['/usr/bin/osascript','-l','JavaScript',str(Path(__file__).with_name('mail_reader.js')),'accounts'],capture_output=True,text=True,timeout=30)
    if result.returncode:raise ValueError('Could not list Mail accounts. Open Apple Mail and allow automation access, then retry. '+result.stderr.strip()[:300])
    accounts=json.loads(result.stdout)
    if not isinstance(accounts,list):raise ValueError('Mail returned an invalid account list.')
    return accounts

def select_account(app,account_id):
    if isinstance(account_id,str) and account_id.startswith(('gmail:','graph:','imap:')):return __import__('mail_sources').select_account(app,account_id)
    if not isinstance(account_id,str) or not account_id.strip():raise ValueError('Choose an email account.')
    if not SYNC_LOCK.acquire(blocking=False):raise ValueError('Wait for the current Mail sync to finish before changing accounts.')
    try:
        matches=[a for a in list_accounts() if a['id']==account_id]
        if len(matches)!=1:raise ValueError('That Mail account is unavailable. Refresh the account list.')
        with app.LOCK:
            app.backup()
            with app.connect() as c:
                c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('mail_account',json.dumps(matches[0])))
                __import__('mail_pipeline').touch(c)
        SYNC.update(error='',summary='Account saved. Check emails to sync this account.')
        return {'account':matches[0]}
    finally:SYNC_LOCK.release()


def table_rows(c,name):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone():return []
    return [dict(r) for r in c.execute('SELECT * FROM '+name)]


def read_bounds(account_id):
    try:
        result=subprocess.run(['/usr/bin/osascript','-l','JavaScript',str(Path(__file__).with_name('mail_reader.js')),'bounds','',account_id],capture_output=True,text=True,timeout=45)
        if result.returncode:return None
        data=json.loads(result.stdout)
        return data if isinstance(data,dict) and 'oldest' in data else None
    except Exception:return None


def message_detail(c,message_id):
    account=get_setting(c,'mail_account')
    if account:
        row=c.execute('SELECT e.* FROM emails e JOIN email_accounts a USING(message_id) WHERE e.message_id=? AND a.account_id=?',(message_id,account['id'])).fetchone()
    else:row=c.execute('SELECT * FROM emails WHERE message_id=?',(message_id,)).fetchone()
    if not row:raise ValueError('This email is not in the selected account.')
    m=dict(row);m['job_ids']=[r[0] for r in c.execute('SELECT l.job_id FROM email_jobs l JOIN jobs j ON j.id=l.job_id WHERE message_id=?',(message_id,))]
    feedback=c.execute('SELECT * FROM email_feedback WHERE message_id=?',(message_id,)).fetchone();m['feedback']=dict(feedback) if feedback else None
    m['decisions']=[dict(r) for r in c.execute('SELECT job_id,status FROM email_decisions WHERE message_id=?',(message_id,))]
    ref=c.execute('SELECT web_url,internet_id,provider,body_complete FROM email_source_refs WHERE message_id=? AND account_id=? LIMIT 1',(message_id,account['id'] if account else '')).fetchone()
    m['body_complete']=bool(ref['body_complete']) if ref else True
    m['source_provider']=ref['provider'] if ref else 'apple_mail';m['source_url']=__import__('mail_sources').valid_link(ref['web_url'],ref['provider']) if ref else '';m['internet_id']=ref['internet_id'] if ref else message_id
    m['newer']=None
    if m['job_ids']:
        marks=','.join('?' for _ in m['job_ids'])
        row=c.execute("SELECT e.message_id,e.subject,e.received_at FROM emails e WHERE e.review IN ('pending','approved') AND e.category IN ('rejection','interview','offer') AND julianday(e.received_at)>julianday(?) AND e.message_id IN (SELECT message_id FROM email_jobs WHERE job_id IN ("+marks+")) AND e.message_id IN (SELECT message_id FROM email_accounts WHERE account_id=?) ORDER BY julianday(e.received_at) DESC LIMIT 1",[m['received_at'],*m['job_ids'],account['id'] if account else '']).fetchone()
        if row:m['newer']=dict(row)
    import mail_pipeline
    return mail_pipeline.attach(c,{'messages':[m]})['messages'][0]
