"""Company-indexed collection, independent classification, and durable email review state."""
import datetime as dt
import hashlib
import html
import json
import re
import threading
import time
import unicodedata
from urllib.parse import urlparse, parse_qs, unquote, quote, urlunparse, urlencode
from html.parser import HTMLParser
import mail_integration as mail

VERSION='company-index-v5-precision'
ANALYSIS={'running':False,'error':'','current':''}
CLASSIFY_LOCK=threading.Lock()
TARGETS={'rejection':'Rejected','interview':'Interview pending','offer':'Offer'}

def init(c):
    columns={r[1] for r in c.execute('PRAGMA table_info(emails)')}
    migrating_analysis='analysis_state' not in columns
    for name,default in [('analysis_state','queued'),('analysis_error',''),('ignore_source','')]:
        if name not in columns:c.execute(f"ALTER TABLE emails ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}'")
    for name in ('body_version','analysis_revision'):
        if name not in columns:c.execute(f'ALTER TABLE emails ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0')
    c.executescript('''
    CREATE TABLE IF NOT EXISTS mail_meta(key TEXT PRIMARY KEY,value INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS email_events(id INTEGER PRIMARY KEY AUTOINCREMENT,message_id TEXT NOT NULL,kind TEXT NOT NULL,at TEXT NOT NULL,delivered INTEGER NOT NULL DEFAULT 0,UNIQUE(message_id,kind));
    CREATE TABLE IF NOT EXISTS job_status_approvals(job_id INTEGER PRIMARY KEY,message_id TEXT NOT NULL,status TEXT NOT NULL,effective_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS email_missing_messages(suggestion_id INTEGER NOT NULL,message_id TEXT NOT NULL,PRIMARY KEY(suggestion_id,message_id));
    CREATE TABLE IF NOT EXISTS email_missing(id INTEGER PRIMARY KEY,message_id TEXT NOT NULL,company TEXT NOT NULL,title TEXT NOT NULL,url TEXT NOT NULL DEFAULT '',description TEXT NOT NULL DEFAULT '',state TEXT NOT NULL DEFAULT 'suggested',lookup_state TEXT NOT NULL DEFAULT 'queued',error TEXT NOT NULL DEFAULT '',job_id INTEGER,UNIQUE(company,title));
    ''')
    if 'seen' not in {r[1] for r in c.execute('PRAGMA table_info(email_events)')}:
        c.execute('ALTER TABLE email_events ADD COLUMN seen INTEGER NOT NULL DEFAULT 0')
    c.execute("UPDATE emails SET analysis_state='done' WHERE review IN ('approved','dismissed','ignored') AND analysis_state='queued'")
    if migrating_analysis:c.execute("UPDATE emails SET analysis_state='done' WHERE review='pending' AND analysis_state='queued'")
    c.execute("UPDATE emails SET analysis_state='queued' WHERE analysis_state='running'")
    c.execute('INSERT OR IGNORE INTO email_missing_messages SELECT id,message_id FROM email_missing')
    c.execute('CREATE INDEX IF NOT EXISTS email_missing_message ON email_missing(message_id)')
    c.execute('CREATE INDEX IF NOT EXISTS email_accounts_account ON email_accounts(account_id)')
    c.execute('CREATE INDEX IF NOT EXISTS email_jobs_job ON email_jobs(job_id)')
    for row in c.execute("SELECT message_id,category FROM emails WHERE review='pending'").fetchall():event(c,row['message_id'],'status:'+row['category'])
    # Prior versions recorded decisions but no company cutoff; preserve their effective date.
    c.execute("INSERT OR IGNORE INTO job_status_approvals SELECT d.job_id,d.message_id,d.status,e.received_at FROM email_decisions d JOIN emails e USING(message_id) WHERE e.review='approved' ORDER BY e.received_at DESC")
    c.execute('CREATE INDEX IF NOT EXISTS email_review_date ON emails(review,received_at)')
    c.execute('CREATE INDEX IF NOT EXISTS email_analysis_date ON emails(analysis_state,received_at)')
    c.execute('CREATE INDEX IF NOT EXISTS email_events_message ON email_events(message_id)')
    __import__('mail_sources').init(c)
    reconcile_missing(c);repair_precision(c);bootstrap_manual_approvals(c);auto_ignore(c)

def repair_precision(c):
    marker='precision_repair_v2'
    if c.execute('SELECT 1 FROM mail_meta WHERE key=?',(marker,)).fetchone():return
    jobs=[dict(r) for r in c.execute('SELECT * FROM jobs')]
    for row in c.execute("SELECT * FROM emails WHERE review IN ('none','pending')").fetchall():
        message=dict(row);linked,company,scope=match(message,jobs)
        if not linked and (mail.consumer_message(message) or (not mail.confirmation_evidence(message) and not mail.employment_context(message))) and message['match_kind']!='manual' and message['ignore_source']!='restored':
            c.execute("UPDATE emails SET review='ignored',ignored_from='none',ignore_source='unrelated',company='',match_kind='unlinked',category='other',rejection=0,invitation=0,evidence='',analysis_state='done',analysis_error='',analysis_revision=analysis_revision+1 WHERE message_id=?",(message['message_id'],))
            c.execute('DELETE FROM email_jobs WHERE message_id=?',(message['message_id'],))
            c.execute('UPDATE email_events SET delivered=1 WHERE message_id=?',(message['message_id'],))
        elif not linked and message['review']=='none' and message['match_kind'] not in ('manual','missing') and message['ignore_source']!='restored':
            c.execute("UPDATE emails SET company='',match_kind='unlinked',analysis_revision=analysis_revision+1 WHERE message_id=?",(message['message_id'],))
            c.execute('DELETE FROM email_jobs WHERE message_id=?',(message['message_id'],))
        elif message['review']=='pending':
            # Recheck queued proposals with the new evidence contract, preserving
            # valid proposals and all resolved/manual decisions.
            classify_one(c,message,{'kind':message['category'],'evidence':message['evidence']})
    c.execute('INSERT OR REPLACE INTO mail_meta VALUES (?,1)',(marker,));touch(c)

def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def touch(c):c.execute("INSERT INTO mail_meta VALUES ('revision',1) ON CONFLICT(key) DO UPDATE SET value=value+1")
def revision(c):
    r=c.execute("SELECT value FROM mail_meta WHERE key='revision'").fetchone();return r[0] if r else 0

def company_key(name):
    return re.sub(r' (?:incorporated|inc|llc|ltd|limited|corp|corporation)$','',mail.normalized(name))

def company_profiles(jobs):
    groups={}
    for job in jobs:
        name=(job.get('company') or '').strip()
        if not name:continue
        key=company_key(name);profile=groups.setdefault(key,{'key':key,'name':name,'terms':set(),'domains':set()})
        aliases=[name,key,*re.split(r'\s*[|/]\s*',name)]
        aliases += [re.sub(r'(?<=[a-z])(?=[A-Z])',' ',a) for a in aliases]
        aliases += [re.sub(r'^(?:through|via)\s+','',a,flags=re.I) for a in aliases]
        if re.fullmatch(r'[\w-]+\.(?:ai|com|io)',name,re.I):aliases.append(name.split('.')[0])
        profile['terms'].update(a.strip() for a in aliases if len(a.strip())>=2)
        host=urlparse(job.get('url') or '').hostname
        if host and not any(x in host for x in ('greenhouse','lever.co','workday','ashby','gem.com','linkedin','indeed')):profile['domains'].add(host.removeprefix('www.'))
    return [{**p,'terms':sorted(p['terms']),'domains':sorted(p['domains'])} for p in groups.values()]

def match(message,jobs):
    current=mail.current_message(message)
    if mail.consumer_message(current):return [],'','unlinked'
    body=re.sub(r'https?://\S+|www\.\S+',' ',current['body'],flags=re.I)
    body=re.sub(r'(?im)^\s*(?:copyright|©|unsubscribe\b|all rights reserved\b)[^\n]*',' ',body)
    body=re.sub(r'\b(?:Apple (?:Wallet|App\s*Store|devices)|Google Play|Microsoft Outlook|(?:sign|log) in with Apple)\b',' ',body,flags=re.I)
    text=mail.normalized(current['subject']+' '+body);head=mail.normalized(current['subject'])
    from email.utils import parseaddr
    display,address=parseaddr(current['sender']);sender=mail.normalized(display or (current['sender'] if '@' not in current['sender'] else ''))
    domain=address.rsplit('@',1)[-1].casefold() if '@' in address else ''
    found=[]
    for profile in company_profiles(jobs):
        terms=[mail.normalized(t) for t in profile['terms']]
        trusted=[]
        for host in profile['domains']:
            trusted.append(host)
            trusted.append(re.sub(r'^(?:jobs|careers|apply|recruitment)\.', '',host))
        direct=any(domain==host or domain.endswith('.'+host) for host in trusted if host)
        named=any(mail.contains(sender,t) or mail.contains(head,t) for t in terms)
        # Body-only brand mentions need job context. A Wallet badge, disclaimer,
        # tracking URL or quoted thread is not evidence of an employer conversation.
        body_text=mail.normalized(body)
        hiring=r'\b(?:applied|applying|your application|job application|application for|application to|interview|recruiting|recruiter|hiring|candidacy|employment|resume)\b'
        roles=[mail.normalized(j['title']) for j in jobs if company_key(j.get('company') or '')==profile['key']]
        body_match=False
        for term in terms:
            for occurrence in re.finditer(r'(?<!\w)'+re.escape(term)+r'(?!\w)',body_text):
                nearby=body_text[max(0,occurrence.start()-200):occurrence.end()+200]
                if len(term.split())>=2 or re.search(hiring,nearby) or any(len(role.split())>=2 and mail.contains(nearby,role) for role in roles):body_match=True;break
            if body_match:break
        if direct or named or body_match:found.append(profile['key'])
    linked=[j for j in jobs if company_key(j.get('company') or '') in found]
    specific=[j for j in linked if mail.contains(text,mail.normalized(j['title']))]
    linked=specific or linked
    names=[]
    for j in linked:
        if not any(company_key(n)==company_key(j['company']) for n in names):names.append(j['company'])
    return linked,' / '.join(sorted(names)),'role' if specific else 'company' if linked else 'unlinked'

def event(c,message_id,kind):
    c.execute('INSERT OR IGNORE INTO email_events(message_id,kind,at) VALUES (?,?,?)',(message_id,kind,now()))

def extract_missing_title(message):
    # Specific role labels and application-receipt sentences, not AI guesses.
    patterns=[r'(?:job title|position title|position|role applied for|position applied for|application(?: received| submitted)?)\s*[:,–—-]\s*([^\n.!]{4,180})',r'(?:application (?:for|to)|appl(?:ying|ied) (?:for|to)|interest in)\s+(?:the\s+)?([^\n.!]{4,180}?)(?:\s+(?:position|role|at|with)\b|[.!\n]|$)',r'(?:position|role) of\s+([^\n.!]{4,180})']
    text=mail.message_text(message)
    for pattern in patterns:
        m=re.search(pattern,text,re.I)
        if not m:continue
        title=m.group(1).strip(' \t\r,:;"“”')
        title=re.split(r'\s+(?:has been|was|is)\s+(?:received|submitted)|(?<=[a-z])at\s+[A-Z]',title,maxsplit=1)[0].strip()
        if len(title.split())<2 or len(title)>160 or re.match(r'(your |our |a |an |this |you |us\b|employment\b|joining\b|working\b)',title,re.I):continue
        if not re.search(r'\b(engineer|developer|scientist|researcher|analyst|designer|manager|architect|specialist|intern|director|officer|consultant|technician|coordinator|associate|lead)\b',title,re.I):continue
        return title
    return ''

def role_key(title,company):
    parts=re.split(r'\s*[|:–—]\s*|\s+-\s+',title,maxsplit=1)
    variants={company_key(company),re.sub(r' (?:labs?|robotics|technologies|technology)$','',company_key(company))}
    if len(parts)==2 and company_key(parts[0]) in variants:title=parts[1]
    suffix=re.split(r'\s+(?:at|with)\s+',title,flags=re.I)
    if len(suffix)==2 and company_key(suffix[1]) in variants:title=suffix[0]
    return mail.normalized(title)

def reconcile_missing(c):
    # Older extraction could include receipt boilerplate or a missing space before "at".
    jobs=[dict(r) for r in c.execute('SELECT * FROM jobs')]
    for suggestion in c.execute("SELECT * FROM email_missing WHERE state='suggested'").fetchall():
        for source in (c.execute('SELECT message_id FROM email_missing_messages WHERE suggestion_id=?',(suggestion['id'],)).fetchall() or [(suggestion['message_id'],)]):
            row=c.execute('SELECT * FROM emails WHERE message_id=?',(source[0],)).fetchone()
            if not row:continue
            message=dict(row);title=extract_missing_title(message)
            if not any(company_key(j['company'])==company_key(suggestion['company']) and role_key(j['title'],suggestion['company'])==role_key(title,suggestion['company']) for j in jobs):continue
            c.execute("UPDATE email_missing SET state='dismissed' WHERE id=?",(suggestion['id'],))
            if message['match_kind']!='missing' or message['review'] in ('approved','dismissed','ignored'):continue
            linked,company,scope=match(message,jobs)
            c.execute('UPDATE emails SET company=?,match_kind=? WHERE message_id=?',(company,scope,source[0]))
            for job in linked:c.execute('INSERT OR IGNORE INTO email_jobs VALUES (?,?)',(source[0],job['id']))

def detect_missing(c,message):
    if message.get('category')!='confirmation' or message.get('review') in ('approved','dismissed','ignored'):return
    if any(mail.status_evidence(kind,message) for kind in TARGETS):return
    title=extract_missing_title(message)
    if not title:return
    company=message.get('company','').split(' / ')[0]
    if not company:return
    if mail.normalized(title) in {mail.normalized(company),company_key(company)}:return
    jobs=[dict(r) for r in c.execute('SELECT id,title,company FROM jobs')]
    if any(company_key(j['company'])==company_key(company) and role_key(j['title'],company)==role_key(title,company) for j in jobs):return
    c.execute('INSERT OR IGNORE INTO email_missing(message_id,company,title) VALUES (?,?,?)',(message['message_id'],company,title))
    suggestion=c.execute('SELECT id,state FROM email_missing WHERE company=? AND title=?',(company,title)).fetchone()
    c.execute('INSERT OR IGNORE INTO email_missing_messages VALUES (?,?)',(suggestion['id'],message['message_id']))
    if suggestion['state']=='suggested' and message.get('match_kind') in ('company','role','missing'):
        c.execute("UPDATE emails SET match_kind='missing' WHERE message_id=?",(message['message_id'],))
        c.execute('DELETE FROM email_jobs WHERE message_id=?',(message['message_id'],))

def collect(c,messages,jobs,account_id):
    added=0
    for m in messages:
        if not isinstance(m,dict) or any(not isinstance(m.get(k),str) for k in ('message_id','sender','subject','body','received_at')):raise ValueError('Mail returned an invalid message; collection checkpoint is unchanged.')
        if not m['message_id']:raise ValueError('Mail returned an empty Message-ID.')
        stamp=dt.datetime.fromisoformat(m['received_at'].replace('Z','+00:00'))
        if stamp.tzinfo is None:raise ValueError('Email date needs a timezone.')
        linked,company,scope=match(m,jobs)
        existing=c.execute('SELECT * FROM emails WHERE message_id=?',(m['message_id'],)).fetchone()
        if not existing and not linked and not (mail.confirmation_evidence(m) and mail.employment_context(m)):continue
        if existing and m['body'].strip() and (not existing['body'].strip() or len(m['body'])>=len(existing['body'])) and m['body'][:2_000_000]!=existing['body']:
            # A later Mail download may hydrate an already collected message. Never
            # downgrade a complete body to a shorter/empty transient Mail response.
            c.execute('UPDATE emails SET body=?,body_version=body_version+1 WHERE message_id=?',(m['body'][:2_000_000],m['message_id']))
            if existing['review'] not in ('approved','dismissed','ignored'):
                c.execute("UPDATE emails SET analysis_state='queued',analysis_error='',review='none',evidence='',analysis_revision=analysis_revision+1 WHERE message_id=?",(m['message_id'],))
        if not existing:
            c.execute("INSERT INTO emails(message_id,sender,subject,body,received_at,company,match_kind,category,review,analysis_state) VALUES (?,?,?,?,?,?,?,'other','none','queued')",(m['message_id'],m['sender'],m['subject'],m['body'][:2_000_000],m['received_at'],company,scope))
            event(c,m['message_id'],'added');added+=1
        if not existing or (existing['match_kind']!='manual' and existing['review'] not in ('approved','ignored','dismissed')):
            c.execute('UPDATE emails SET company=?,match_kind=? WHERE message_id=?',(company,scope,m['message_id']))
            c.execute('DELETE FROM email_jobs WHERE message_id=?',(m['message_id'],))
            for j in linked:c.execute('INSERT OR IGNORE INTO email_jobs VALUES (?,?)',(m['message_id'],j['id']))
        c.execute('INSERT OR IGNORE INTO email_accounts VALUES (?,?)',(m['message_id'],account_id))
        if mail.confirmation_evidence(m):
            saved=dict(c.execute('SELECT * FROM emails WHERE message_id=?',(m['message_id'],)).fetchone());saved['category']='confirmation';detect_missing(c,saved)
    auto_ignore(c)
    if messages:touch(c)
    return added

def sync(app):
    if not mail.SYNC_LOCK.acquire(blocking=False):return
    mail.SYNC.update(running=True,error='',summary='Collecting company emails…')
    try:
        with app.connect() as c:
            account=mail.get_setting(c,'mail_account')
            if not account:raise ValueError('Choose your job-search email account before syncing.')
            jobs=[dict(r) for r in c.execute('SELECT * FROM jobs')]
            if not jobs:raise ValueError('Add an application before syncing Mail.')
            if account.get('provider') in ('gmail','graph','imap'):return __import__('mail_sources').sync_locked(app,account,jobs)
            profiles=company_profiles(jobs)
            if not profiles:raise ValueError('Add a company name to an application before syncing Mail.')
            cursor=mail.checkpoint(c,account['id'])
        fingerprint=hashlib.sha256(json.dumps(profiles,sort_keys=True).encode()).hexdigest()
        until=now();end=dt.datetime.fromisoformat(until)
        valid=cursor.get('collection_version')==VERSION and cursor.get('companies')==fingerprint
        bounds=None if valid and cursor.get('history_oldest') else mail.read_bounds(account['id'])
        oldest_text=cursor.get('history_oldest') if valid else None
        if bounds is not None:oldest_text=bounds.get('oldest')
        elif not oldest_text:oldest_text='1970-01-01T00:00:00+00:00'
        tasks=[]
        if valid and cursor.get('through'):
            tasks.append(((dt.datetime.fromisoformat(cursor['through'])-dt.timedelta(days=2)).isoformat(),until,False))
        with app.connect() as c:
            incomplete=c.execute("SELECT min(e.received_at) FROM emails e JOIN email_accounts a USING(message_id) WHERE a.account_id=? AND trim(e.body)='' AND e.review NOT IN ('approved','dismissed','ignored')",(account['id'],)).fetchone()[0]
        if valid and incomplete and cursor.get('through') and incomplete<cursor['through']:
            # Recover old headers-only messages without moving the history cursor.
            left=dt.datetime.fromisoformat(incomplete.replace('Z','+00:00'));right=end
            while right>left:
                lower=max(left,right-dt.timedelta(days=31));tasks.append((lower.isoformat(),right.isoformat(),False));right=lower
        if oldest_text:
            oldest=dt.datetime.fromisoformat(oldest_text.replace('Z','+00:00'))
            right=dt.datetime.fromisoformat(cursor.get('history_before',until)) if valid else end
            # Collect newest history first: relevant recent statuses arrive promptly,
            # and approvals can suppress obsolete older mail before AI sees it.
            while right>oldest:
                lower=max(oldest,right-dt.timedelta(days=31))
                tasks.append((lower.isoformat(),right.isoformat(),True));right=lower
        elif not valid and bounds is None:
            tasks.append(('1970-01-01T00:00:00+00:00',until,True))
        if not tasks:tasks=[(until,until,False)]
        total=0
        while tasks:
            since,window_end,history=tasks.pop(0)
            mail.SYNC['summary']=f'Collecting company matches: {since[:10]} through {window_end[:10]}…'
            try:messages=mail.read_mail(since,window_end,account['id'],profiles) if since!=window_end else []
            except Exception as exc:
                left=dt.datetime.fromisoformat(since);right=dt.datetime.fromisoformat(window_end)
                if ('timed out' in str(exc).lower() or 'timeout' in str(exc).lower()) and right-left>dt.timedelta(days=1):
                    mid=(left+(right-left)/2).isoformat()
                    smaller=[(since,mid,history),(mid,window_end,history)]
                    tasks[0:0]=list(reversed(smaller)) if history else smaller
                    continue
                raise
            with app.LOCK:
                app.backup()
                with app.connect() as c:
                    total+=collect(c,messages,jobs,account['id'])
                    previous=mail.checkpoint(c,account['id'])
                    last=max(messages,key=lambda m:dt.datetime.fromisoformat(m['received_at'].replace('Z','+00:00'))) if messages else None
                    highwater=until if history else max(window_end,previous.get('through',window_end))
                    values={'through':highwater,'collection_version':VERSION,'companies':fingerprint,'history_oldest':oldest_text or '','history_before':since if history else previous.get('history_before',oldest_text or until),'last_message_id':previous.get('last_message_id',''),'last_received_at':previous.get('last_received_at','')}
                    if last and (not values['last_received_at'] or dt.datetime.fromisoformat(last['received_at'].replace('Z','+00:00'))>dt.datetime.fromisoformat(values['last_received_at'].replace('Z','+00:00'))):
                        values.update(last_message_id=last['message_id'],last_received_at=last['received_at'])
                    for k,v in values.items():c.execute('INSERT OR REPLACE INTO mail_checkpoints VALUES (?,?,?)',(account['id'],k,v))
                try:app.backup()
                except Exception:pass
            mail.SYNC['summary']=f'Collected {total} new company emails. Saved history through {since[:10]}. AI classifies the saved queue separately.'
    except Exception as exc:mail.SYNC['error']=str(exc)
    finally:mail.SYNC['running']=False;mail.SYNC_LOCK.release()

def normalize_quote(text):
    text=unicodedata.normalize('NFKC',html.unescape(text)).translate(str.maketrans({'“':'"','”':'"','‘':"'",'’':"'",'–':'-','—':'-'}))
    return re.sub(r'\s+',' ',text).strip().casefold()

def classify_one(c,message,result):
    incomplete=c.execute('SELECT min(body_complete),max(body_complete) FROM email_source_refs WHERE message_id=?',(message['message_id'],)).fetchone()
    if incomplete[0]==0 and incomplete[1]==0:return
    kind=result.get('kind')
    if kind=='other' and mail.confirmation_evidence(message):kind='confirmation'
    if kind not in ('rejection','interview','offer','confirmation','other'):raise ValueError('The classifier did not return a recognized email type.')
    evidence=result.get('evidence','')
    if not isinstance(evidence,str):evidence=''
    source=mail.message_text(message)
    warning=''
    if kind in TARGETS:
        supported=mail.status_evidence(kind,message)
        if not evidence.strip() or normalize_quote(evidence) not in normalize_quote(source):
            kind='other';evidence='';warning='No status proposal: the model quote could not be verified in the current message.'
        elif not supported or not mail.status_evidence(kind,{'subject':message['subject'],'body':evidence}):
            kind='other';evidence='';warning='No status proposal: the quoted text does not establish this hiring outcome. Conditional wording and quoted earlier replies do not count.'
    current=c.execute('SELECT * FROM emails WHERE message_id=?',(message['message_id'],)).fetchone()
    if not current or current['review'] in ('approved','dismissed','ignored'):return
    if current['body_version']!=message.get('body_version',0):return
    review='pending' if kind in TARGETS else 'none'
    c.execute('UPDATE emails SET category=?,rejection=?,invitation=?,evidence=?,review=?,analysis_state=?,analysis_error=?,analysis_version=?,analysis_revision=analysis_revision+1 WHERE message_id=?',(kind,int(kind=='rejection'),int(kind=='interview'),evidence,review,'warning' if warning else 'done',warning,VERSION,message['message_id']))
    if kind in TARGETS:
        event(c,message['message_id'],'status:'+kind)
        # The urgent alert covers this message; do not replay its older normal
        # alert after a large historical ingestion backlog drains.
        c.execute("UPDATE email_events SET delivered=1 WHERE message_id=? AND kind='added'",(message['message_id'],))
    updated=dict(current);updated['category']=kind
    detect_missing(c,updated);reconcile_missing(c)
    auto_ignore(c);touch(c)

def analyze_pending(app,limit=3):
    if not CLASSIFY_LOCK.acquire(blocking=False):return 0
    completed=0
    try:
        with app.connect() as c:
            account=mail.get_setting(c,'mail_account')
            if not account:return 0
            messages=[dict(r) for r in c.execute("SELECT e.* FROM emails e JOIN email_accounts a USING(message_id) WHERE a.account_id=? AND e.analysis_state='queued' AND e.review NOT IN ('approved','dismissed','ignored') ORDER BY e.received_at DESC LIMIT ?",(account['id'],limit))]
            config=app.settings();prompt=mail.get_prompt(c)
        if not messages:return 0
        ANALYSIS.update(running=True,error='',current=messages[0]['message_id'])
        # Independently commit each result: one failed message never blocks another.
        for message in messages:
            try:
                if config.get('mail_use_shortcut',True):
                    with app.priority():result=mail.run_shortcut(config.get('mail_shortcut','JobTracker Email Review'),{'mode':'classify','type_only':True,'model':config.get('model',''),'classifier_prompt':prompt,'email':{k:message[k] for k in ('message_id','sender','subject','body','company','received_at')}})
                else:
                    rejection=mail.REJECTION.search(message['subject']+'\n'+message['body']);invite=mail.invitation_evidence(message)
                    result={'kind':'rejection' if rejection else 'interview' if invite else 'confirmation' if mail.confirmation_evidence(message) else 'other','evidence':rejection.group(0) if rejection else invite}
                if not isinstance(result,dict):raise ValueError('The classifier returned an unreadable result.')
                with app.LOCK,app.connect() as c:classify_one(c,message,result)
                completed+=1
            except Exception as exc:
                with app.LOCK,app.connect() as c:
                    c.execute("UPDATE emails SET analysis_state='failed',analysis_error=? WHERE message_id=? AND body_version=? AND review NOT IN ('approved','dismissed','ignored')",(str(exc),message['message_id'],message.get('body_version',0)));touch(c)
                ANALYSIS['error']=str(exc)
        return completed
    finally:ANALYSIS.update(running=False,current='');CLASSIFY_LOCK.release()

def analysis_worker(app):
    while True:
        try:count=analyze_pending(app)
        except Exception as exc:ANALYSIS['error']=str(exc);count=0
        time.sleep(1 if count else 3)

def record_approval(c,message_id,ids):
    email=c.execute('SELECT * FROM emails WHERE message_id=?',(message_id,)).fetchone()
    target=TARGETS.get(email['category'],'Interview pending' if email['invitation'] else 'Rejected')
    for ident in ids:c.execute('INSERT OR REPLACE INTO job_status_approvals VALUES (?,?,?,?)',(ident,message_id,target,email['received_at']))
    auto_ignore(c);touch(c)

def auto_ignore(c):
    groups={}
    for row in c.execute('SELECT id,company,status FROM jobs'):
        if row['company']:groups.setdefault(company_key(row['company']),[]).append(dict(row))
    approvals={r['job_id']:dict(r) for r in c.execute('SELECT * FROM job_status_approvals')}
    cutoffs={}
    for jobs in groups.values():
        if all(j['id'] in approvals and approvals[j['id']]['status']==j['status'] for j in jobs):
            cutoff=min(timestamp(approvals[j['id']]['effective_at']) for j in jobs)
            for j in jobs:cutoffs[j['id']]=(company_key(j['company']),cutoff)
    if not cutoffs:return
    rows=c.execute("SELECT e.message_id,e.received_at,l.job_id FROM emails e JOIN email_jobs l USING(message_id) JOIN jobs j ON j.id=l.job_id WHERE e.review NOT IN ('approved','dismissed','ignored') AND e.ignore_source!='restored'")
    candidates={}
    for row in rows:
        entry=candidates.setdefault(row['message_id'],[row['received_at'],[]]);entry[1].append(row['job_id'])
    ignored=[]
    for ident,(received,ids) in candidates.items():
        if not all(i in cutoffs for i in ids):continue
        if len({cutoffs[i][0] for i in ids})!=1:continue
        if timestamp(received)<min(cutoffs[i][1] for i in ids):ignored.append((ident,))
    c.executemany("UPDATE emails SET ignored_from=review,review='ignored',ignore_source='superseded' WHERE message_id=?",ignored)

def pending_for_jobs(c,jobs):
    account=mail.get_setting(c,'mail_account') or {}
    for j in jobs:
        pending=[dict(r) for r in c.execute("SELECT e.message_id,e.subject,e.category,e.analysis_error FROM emails e JOIN email_jobs l USING(message_id) WHERE l.job_id=? AND e.review='pending' AND e.message_id IN (SELECT message_id FROM email_accounts WHERE account_id=?) ORDER BY e.received_at DESC",(j['id'],account.get('id','')))]
        for p in pending:p['proposed_status']=TARGETS.get(p['category'],'Rejected')
        j['pending_changes']=pending;j['pending_positive']=any(p['category'] in ('interview','offer') for p in pending)
    return jobs

def summary(c):
    account=mail.get_setting(c,'mail_account');aid=account['id'] if account else ''
    counts=dict(c.execute("SELECT count(*) AS total,coalesce(sum(e.review='pending'),0) AS pending,coalesce(sum(e.analysis_state='queued' AND e.review NOT IN ('ignored','approved','dismissed')),0) AS queued,coalesce(sum(e.analysis_state='failed' AND e.review NOT IN ('ignored','approved','dismissed')),0) AS failed FROM emails e JOIN email_accounts a USING(message_id) WHERE a.account_id=?",(aid,)).fetchone())
    return {**counts,'revision':revision(c),'analysis':dict(ANALYSIS),'worker':dict(mail.SYNC)}

def notifications(c):
    account=mail.get_setting(c,'mail_account');aid=account['id'] if account else ''
    return [dict(r) for r in c.execute("SELECT n.id,n.message_id,n.kind,e.company,e.subject FROM email_events n JOIN emails e USING(message_id) JOIN email_accounts a USING(message_id) WHERE a.account_id=? AND n.delivered=0 AND (n.kind='added' OR e.review='pending') ORDER BY CASE WHEN n.kind LIKE 'status:%' THEN 0 ELSE 1 END,n.id LIMIT 100",(aid,))]

def activity(c,limit=200):
    limit=max(1,min(10000,int(limit)))
    account=mail.get_setting(c,'mail_account');aid=account['id'] if account else ''
    rows=[dict(r) for r in c.execute("""SELECT e.message_id,e.company,e.subject,e.category,e.review,e.analysis_state,
        max(n.id) AS event_id,max(n.at) AS at,min(n.seen) AS seen
        FROM email_events n JOIN emails e USING(message_id) JOIN email_accounts a USING(message_id)
        WHERE a.account_id=? GROUP BY e.message_id ORDER BY (e.review='pending') DESC,max(n.id) DESC""",(aid,))]
    for row in rows:
        row['urgent']=row['review']=='pending'
        row['proposed_status']=TARGETS.get(row['category'],'') if row['urgent'] else ''
    return {'items':rows[:limit],'through':max([r['event_id'] for r in rows] or [0]),'unread':sum(not r['seen'] for r in rows),'pending':sum(r['urgent'] for r in rows),'total':len(rows)}

def mark_activity_seen(c,through,message_id=None):
    if type(through) is not int or through<0:raise ValueError('Invalid notification checkpoint.')
    account=mail.get_setting(c,'mail_account');aid=account['id'] if account else ''
    c.execute('UPDATE email_events SET seen=1 WHERE id<=? AND (? IS NULL OR message_id=?) AND message_id IN (SELECT message_id FROM email_accounts WHERE account_id=?)',(through,message_id,message_id,aid))
    touch(c)

def review_token(c,message,jobs=None):
    if jobs is None:jobs=[tuple(r) for r in c.execute('SELECT j.id,j.status,j.updated_at FROM email_jobs l JOIN jobs j ON j.id=l.job_id WHERE message_id=? ORDER BY j.id',(message['message_id'],))]
    payload=[message.get(k) for k in ('message_id','category','review','invitation','evidence','body_version','analysis_revision')]+[jobs]
    return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()

def attach(c,data):
    messages=data['messages']
    for start in range(0,len(messages),200):
        batch=messages[start:start+200];by_id={m['message_id']:m for m in batch};ids=list(by_id);marks=','.join('?' for _ in ids)
        jobs={ident:[] for ident in ids}
        for row in c.execute('SELECT l.message_id,j.id,j.status,j.updated_at FROM email_jobs l JOIN jobs j ON j.id=l.job_id WHERE message_id IN ('+marks+') ORDER BY j.id',ids):jobs[row[0]].append(tuple(row)[1:])
        for m in batch:m['missing']=[];m['review_token']=review_token(c,m,jobs[m['message_id']])
        for row in c.execute("SELECT l.message_id AS source_id,s.* FROM email_missing_messages l JOIN email_missing s ON s.id=l.suggestion_id WHERE l.message_id IN ("+marks+") AND s.state!='dismissed'",ids):
            suggestion=dict(row);ident=suggestion.pop('source_id');by_id[ident]['missing'].append(suggestion)
    data.update(summary(c));return data

class Links(HTMLParser):
    def __init__(self,text):super().__init__();self.urls=[];self.feed(text)
    def handle_starttag(self,tag,attrs):
        if tag=='a':
            href=dict(attrs).get('href','')
            if 'uddg=' in href:href=parse_qs(urlparse(href).query).get('uddg',[''])[0]
            if href.startswith('https://'):self.urls.append(html.unescape(href))

def lookup_missing(app,ident):
    with app.connect() as c:
        row=c.execute('SELECT * FROM email_missing WHERE id=?',(ident,)).fetchone()
        if not row:return
        suggestion=dict(row);email=c.execute('SELECT body FROM emails WHERE message_id=?',(row['message_id'],)).fetchone()
        c.execute("UPDATE email_missing SET lookup_state='searching',error='' WHERE id=?",(ident,));touch(c)
    query=suggestion['company']+' '+suggestion['title']+' job careers'
    try:
        urls=re.findall(r'https://[^\s<>"\)]+',email['body']) if email else []
        try:urls+=Links(app.fetch('https://html.duckduckgo.com/html/?q='+quote(query))).urls
        except Exception:pass
        tried=set()
        for url in urls:
            if len(tried)>=4:break
            url=public_posting_url(url)
            if not url:continue
            if not re.search(r'(jobs|careers|positions|greenhouse|lever\.co|ashby)',url,re.I) or url in tried:continue
            tried.add(url)
            try:
                posting=posting_details(app,app.fetch(url),url,suggestion['title'])
                if not posting.get('title') or mail.normalized(suggestion['title']) not in mail.normalized(posting['title']):continue
                company=posting.get('company','')
                if not company or company_key(company)!=company_key(suggestion['company']):continue
                with app.LOCK,app.connect() as c:
                    c.execute("UPDATE email_missing SET url=?,description=?,lookup_state='found',error='' WHERE id=?",(url,posting.get('description',''),ident));touch(c)
                return
            except Exception:continue
        with app.connect() as c:c.execute("UPDATE email_missing SET url='',description='',lookup_state='not_found',error='No verified public posting found. You can still review and add the role from the email.' WHERE id=?",(ident,));touch(c)
    except Exception as exc:
        with app.connect() as c:c.execute("UPDATE email_missing SET lookup_state='failed',error=? WHERE id=?",(str(exc),ident));touch(c)

def lookup_worker(app):
    with app.connect() as c:c.execute("UPDATE email_missing SET lookup_state='queued' WHERE lookup_state='searching'")
    while True:
        try:
            with app.connect() as c:
                account=mail.get_setting(c,'mail_account') or {}
                row=c.execute("SELECT DISTINCT s.id FROM email_missing s JOIN email_missing_messages m ON m.suggestion_id=s.id JOIN email_accounts a ON a.message_id=m.message_id WHERE a.account_id=? AND s.lookup_state='queued' AND s.state='suggested' ORDER BY s.id LIMIT 1",(account.get('id',''),)).fetchone()
            if row:lookup_missing(app,row['id'])
        except Exception:pass
        time.sleep(3)

def restore(c,data,job_map):
    for a in data.get('approvals',[]):
        if a['job_id'] in job_map:c.execute('INSERT OR IGNORE INTO job_status_approvals VALUES (?,?,?,?)',(job_map[a['job_id']],a['message_id'],a['status'],a['effective_at']))
    suggestion_ids={}
    for s in data.get('missing',[]):
        if not c.execute('SELECT 1 FROM emails WHERE message_id=?',(s['message_id'],)).fetchone():continue
        c.execute('INSERT OR IGNORE INTO email_missing(message_id,company,title,url,description,state,lookup_state,error,job_id) VALUES (?,?,?,?,?,?,?,?,?)',(s['message_id'],s['company'],s['title'],s.get('url',''),s.get('description',''),s.get('state','suggested'),s.get('lookup_state','queued') if s.get('lookup_state')!='searching' else 'queued',s.get('error',''),job_map.get(s.get('job_id'))))
        restored=c.execute('SELECT id FROM email_missing WHERE company=? AND title=?',(s['company'],s['title'])).fetchone()
        if restored and s.get('id') is not None:suggestion_ids[s['id']]=restored[0]
    for source in data.get('missing_sources',[]):
        if source['suggestion_id'] in suggestion_ids:c.execute('INSERT OR IGNORE INTO email_missing_messages VALUES (?,?)',(suggestion_ids[source['suggestion_id']],source['message_id']))
    for event_row in data.get('events',[]):
        if not isinstance(event_row,dict) or not all(isinstance(event_row.get(k),str) for k in ('message_id','kind','at')):raise ValueError('Invalid notification backup.')
        if not c.execute('SELECT 1 FROM emails WHERE message_id=?',(event_row['message_id'],)).fetchone():continue
        c.execute('INSERT INTO email_events(message_id,kind,at,delivered,seen) VALUES (?,?,?,?,?) ON CONFLICT(message_id,kind) DO UPDATE SET delivered=max(email_events.delivered,excluded.delivered),seen=max(email_events.seen,excluded.seen)',(event_row['message_id'],event_row['kind'],event_row['at'],int(bool(event_row.get('delivered'))),int(bool(event_row.get('seen')))))
    if 'events' not in data:
        # Old backups contain no alert delivery state. Reconstruct archival entries
        # quietly; pending proposals still get an undelivered status alert.
        for row in c.execute('SELECT message_id,received_at,review,category FROM emails').fetchall():
            c.execute("INSERT OR IGNORE INTO email_events(message_id,kind,at,delivered,seen) VALUES (?,'added',?,1,1)",(row['message_id'],row['received_at']))
            if row['review']=='pending':event(c,row['message_id'],'status:'+row['category'])
    c.execute('INSERT OR IGNORE INTO email_missing_messages SELECT id,message_id FROM email_missing')
    c.execute("INSERT OR IGNORE INTO job_status_approvals SELECT d.job_id,d.message_id,d.status,e.received_at FROM email_decisions d JOIN emails e USING(message_id) WHERE e.review='approved' ORDER BY e.received_at DESC")
    bootstrap_manual_approvals(c);auto_ignore(c);touch(c)

def on_job_saved(c):
    jobs=[dict(r) for r in c.execute('SELECT * FROM jobs')]
    for row in c.execute("SELECT * FROM emails WHERE review NOT IN ('approved','ignored','dismissed') AND match_kind!='manual'").fetchall():
        message=dict(row);linked,company,scope=match(message,jobs)
        if row['match_kind']=='missing':
            title=extract_missing_title(message)
            linked=[j for j in linked if mail.normalized(j['title'])==mail.normalized(title)];scope='role' if linked else 'missing'
        c.execute('UPDATE emails SET company=?,match_kind=? WHERE message_id=?',(company,scope,message['message_id']))
        c.execute('DELETE FROM email_jobs WHERE message_id=?',(message['message_id'],))
        for j in linked:c.execute('INSERT OR IGNORE INTO email_jobs VALUES (?,?)',(message['message_id'],j['id']))
    for s in c.execute("SELECT * FROM email_missing WHERE state='suggested'").fetchall():
        job=next((j for j in jobs if company_key(j['company'])==company_key(s['company']) and mail.normalized(j['title'])==mail.normalized(s['title'])),None)
        if job:
            c.execute("UPDATE email_missing SET state='added',job_id=? WHERE id=?",(job['id'],s['id']))
            c.execute('INSERT OR IGNORE INTO email_jobs VALUES (?,?)',(s['message_id'],job['id']))
    touch(c)


def posting_details(app,raw,url,title):
    found=[]
    def walk(value):
        if isinstance(value,dict):
            typ=value.get('@type',[])
            if typ=='JobPosting' or isinstance(typ,list) and 'JobPosting' in typ:found.append(value)
            for child in value.values():walk(child)
        elif isinstance(value,list):
            for child in value:walk(child)
    for chunk in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',raw,re.I|re.S):
        try:walk(json.loads(chunk))
        except ValueError:continue
    for job in found:
        if mail.normalized(title) not in mail.normalized(job.get('title','')):continue
        org=job.get('hiringOrganization',{})
        return {'title':job.get('title',''),'company':org.get('name','') if isinstance(org,dict) else str(org),'description':app.clean(job.get('description',''))}
    return app.source_posting(raw,url)


def public_posting_url(url):
    p=urlparse(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password:return ''
    if re.search(r'/(?:candidates?|applications?|assessments?|interviews?|unsubscribe|login|signin|auth|tokens?)(?:/|$)',p.path,re.I):return ''
    if not re.search(r'/(?:jobs?|positions?|careers|openings)(?:/|$)',p.path,re.I):return ''
    # Public posting identifiers are useful; applicant tokens and tracking data
    # are never sent as part of an automatic public-posting lookup.
    ids={key:value for key,value in parse_qs(p.query).items() if key.lower() in ('gh_jid','jobid','job_id','reqid','postingid','posting_id')}
    return urlunparse((p.scheme,p.netloc,p.path,'',urlencode(ids,doseq=True),''))


TERMINAL_APPROVALS={'Rejected','Accepted','Withdrawn','Offer declined'}

def timestamp(value):
    stamp=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    return stamp if stamp.tzinfo else stamp.astimezone()

def record_manual_approval(c,ident,status,at,status_changed=True):
    if status not in TERMINAL_APPROVALS:return
    previous=c.execute('SELECT status FROM job_status_approvals WHERE job_id=?',(ident,)).fetchone()
    if previous and previous['status']==status and not status_changed:return
    c.execute('INSERT OR REPLACE INTO job_status_approvals VALUES (?,?,?,?)',(ident,'manual:'+str(ident),status,at))
    auto_ignore(c);touch(c)

def bootstrap_manual_approvals(c):
    for job in c.execute('SELECT id,status FROM jobs').fetchall():
        if job['status'] not in TERMINAL_APPROVALS:continue
        previous=c.execute('SELECT status FROM job_status_approvals WHERE job_id=?',(job['id'],)).fetchone()
        if previous and previous['status']==job['status']:continue
        tail=[]
        for row in c.execute('SELECT status,at FROM history WHERE job_id=? ORDER BY id DESC',(job['id'],)):
            if row['status']!=job['status']:break
            tail.append(row['at'])
        if tail:c.execute('INSERT OR REPLACE INTO job_status_approvals VALUES (?,?,?,?)',(job['id'],'manual:'+str(job['id']),job['status'],tail[-1]))
