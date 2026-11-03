"""Bounded Apple Mail ingestion; raw reads and checkpoints commit atomically."""
import datetime as dt
import hashlib
import json
import time
import mail_integration as mail

MAX_BATCHES=2
MAX_SECONDS=12

def init(c):
    c.execute('CREATE TABLE IF NOT EXISTS mail_scan_seen(account_id TEXT NOT NULL,scope TEXT NOT NULL,message_id TEXT NOT NULL,received_at TEXT NOT NULL,body_complete INTEGER NOT NULL,checked_at TEXT NOT NULL,PRIMARY KEY(account_id,scope,message_id))')
    c.execute('CREATE INDEX IF NOT EXISTS mail_scan_seen_window ON mail_scan_seen(account_id,scope,received_at)')

def scan(app,account,jobs,profiles):
    import mail_pipeline as p
    fingerprint=hashlib.sha256(json.dumps(profiles,sort_keys=True).encode()).hexdigest()
    started=time.monotonic()
    aid=account['id'];until=p.now();end=dt.datetime.fromisoformat(until)
    with app.connect() as c:
        init(c);cursor=mail.checkpoint(c,aid)
    valid=cursor.get('collection_version')==p.VERSION and cursor.get('companies')==fingerprint
    oldest=cursor.get('history_oldest') if valid else None
    if not oldest:
        metadata=json.loads(cursor.get('bounds_progress','{}')) if valid else {}
        bounds=mail.read_bounds(aid,metadata)
        if bounds and bounds.get('deferred'):
            mail.SYNC['summary']='Mail is in use. Scanning waits until Apple Mail is in the background.';return
        if bounds is None:raise ValueError('Mail metadata scan did not finish within its time budget. No checkpoint advanced. Retry a small batch, or use a direct email connection.')
        dates=[v for v in (bounds.get('oldest'),metadata.get('oldest')) if v]
        oldest=min(dates,key=lambda v:dt.datetime.fromisoformat(v.replace('Z','+00:00'))) if dates else None
        if not bounds.get('complete',True):
            progress={'oldest':oldest,'folders':list(dict.fromkeys(metadata.get('folders',[])+bounds.get('folders',[])))}
            with app.LOCK,app.connect() as c:
                save_tasks(c,aid,[],fingerprint,'',p.VERSION)
                c.execute('INSERT OR REPLACE INTO mail_checkpoints VALUES (?,?,?)',(aid,'bounds_progress',json.dumps(progress)))
            mail.SYNC['summary']='Saved mailbox metadata progress. Continue with the next small batch; no email coverage advanced.'
            return
        oldest=oldest or until
    tasks=json.loads(cursor.get('scan_tasks','[]')) if valid else []
    if not tasks:
        right=dt.datetime.fromisoformat(cursor.get('history_before',until)) if valid else end
        left=dt.datetime.fromisoformat(oldest.replace('Z','+00:00'))
        while right>left:
            lower=max(left,right-dt.timedelta(days=7));tasks.append({'start':lower.isoformat(),'end':right.isoformat(),'history':True,'folders':[]});right=lower
    if valid and cursor.get('through') and not any(not t['history'] for t in tasks):
        tasks.insert(0,{'start':(dt.datetime.fromisoformat(cursor['through'])-dt.timedelta(days=2)).isoformat(),'end':until,'history':False,'folders':[]})
    with app.connect() as c:
        # Retry late downloads directly in their date window; do not rescan every
        # intervening month. Unrelated empty bodies also remain recoverable.
        missing=c.execute("SELECT min(received_at) FROM mail_scan_seen WHERE account_id=? AND scope=? AND body_complete=0 AND julianday(checked_at)<julianday(?)-1.0/24",(aid,fingerprint,until)).fetchone()[0]
        saved=c.execute("SELECT min(e.received_at) FROM emails e JOIN email_accounts a USING(message_id) WHERE a.account_id=? AND trim(e.body)='' AND e.review NOT IN ('approved','dismissed','ignored')",(aid,)).fetchone()[0]
    missing=min([v for v in (missing,saved) if v] or [''])
    if valid and missing and not any(t.get('recovery') for t in tasks):
        left=dt.datetime.fromisoformat(missing.replace('Z','+00:00')).replace(hour=0,minute=0,second=0,microsecond=0)
        tasks.insert(1 if tasks and not tasks[0]['history'] else 0,{'start':left.isoformat(),'end':(left+dt.timedelta(days=1)).isoformat(),'history':False,'recovery':True,'folders':[]})
    count=0;attempts=0
    while tasks and attempts<MAX_BATCHES and time.monotonic()-started<MAX_SECONDS:
        if mail.SCAN_CANCEL.is_set():break
        task=tasks[0];since,upper=task['start'],task['end']
        with app.connect() as c:
            seen=[r[0] for r in c.execute("SELECT message_id FROM mail_scan_seen WHERE account_id=? AND scope=? AND julianday(received_at)>=julianday(?)-1.0/86400 AND julianday(received_at)<julianday(?)+1.0/86400 AND (body_complete=1 OR julianday(checked_at)>julianday(?)-1.0/24)",(aid,fingerprint,since,upper,until))]
        remaining=MAX_SECONDS-(time.monotonic()-started)
        if remaining<=0:break
        options={'timeoutSeconds':min(10,remaining),'seen':seen,'folders':task.get('folders',[]),'maxBodies':8,'maxFolders':12,'budgetMs':min(4000,max(100,int(remaining*1000))),'pauseSeconds':0.15}
        mail.SYNC['summary']=f'Reading a small Mail batch: {since[:10]} through {upper[:10]}…'
        attempts+=1
        try:result=mail.read_mail(since,upper,aid,profiles,options)
        except Exception as exc:
            if mail.SCAN_CANCEL.is_set():break
            left,right=dt.datetime.fromisoformat(since),dt.datetime.fromisoformat(upper)
            if ('timed out' in str(exc).lower() or 'timeout' in str(exc).lower()) and right-left>dt.timedelta(days=1):
                mid=(left+(right-left)/2).isoformat()
                smaller=[{**task,'start':since,'end':mid,'folders':[]},{**task,'start':mid,'end':upper,'folders':[]}]
                tasks[0:1]=list(reversed(smaller)) if task['history'] else smaller
                # Persist the narrower unfinished window without advancing coverage.
                with app.connect() as c:save_tasks(c,aid,tasks,fingerprint,oldest,p.VERSION)
            raise
        if mail.SCAN_CANCEL.is_set():break
        if isinstance(result,dict) and result.get('deferred'):
            mail.SYNC['summary']='Mail is in use. Scanning waits until Apple Mail is in the background.';return
        if isinstance(result,list):messages=result;complete=True;scanned=[];folders=[]
        else:
            if not isinstance(result,dict) or type(result.get('complete')) is not bool or not isinstance(result.get('messages'),list) or not isinstance(result.get('scanned'),list) or not isinstance(result.get('folders'),list):raise ValueError('Invalid Mail batch; checkpoint unchanged.')
            messages=result['messages'];complete=result['complete'];scanned=result['scanned'];folders=result['folders']
            if len(scanned)>8 or any(not isinstance(x,dict) or not isinstance(x.get('message_id'),str) or not x['message_id'] or not isinstance(x.get('received_at'),str) or type(x.get('body_complete')) is not bool for x in scanned) or any(not isinstance(x,str) for x in folders):raise ValueError('Invalid Mail progress; checkpoint unchanged.')
            for x in scanned:
                stamp=dt.datetime.fromisoformat(x['received_at'].replace('Z','+00:00'))
                if stamp.tzinfo is None or not dt.datetime.fromisoformat(since)<=stamp<dt.datetime.fromisoformat(upper):raise ValueError('Mail progress outside the requested window; checkpoint unchanged.')
        next_tasks=[dict(t) for t in tasks]
        if complete:next_tasks.pop(0)
        else:
            next_tasks[0]={**task,'folders':list(dict.fromkeys(task.get('folders',[])+folders))}
            if not scanned and not folders:
                left,right=dt.datetime.fromisoformat(since),dt.datetime.fromisoformat(upper)
                if right-left<=dt.timedelta(hours=1):raise ValueError('Mail could not finish even a small metadata query within its budget. Scanning stopped; use a direct email connection or retry after Mail is idle.')
                mid=(left+(right-left)/2).isoformat()
                smaller=[{**task,'start':since,'end':mid,'folders':[]},{**task,'start':mid,'end':upper,'folders':[]}]
                next_tasks[0:1]=list(reversed(smaller)) if task['history'] else smaller
        with app.LOCK:
            app.backup()
            with app.connect() as c:
                count+=p.collect(c,messages,jobs,aid)
                for x in scanned:c.execute('INSERT OR REPLACE INTO mail_scan_seen VALUES (?,?,?,?,?,?)',(aid,fingerprint,x['message_id'],x['received_at'],int(x['body_complete']),until))
                previous=mail.checkpoint(c,aid)
                values={'history_before':since if complete and task['history'] else previous.get('history_before',upper)}
                if complete and not task.get('recovery'):values['through']=max(upper,previous.get('through',upper))
                if messages:
                    last=max(messages,key=lambda m:dt.datetime.fromisoformat(m['received_at'].replace('Z','+00:00')))
                    if not previous.get('last_received_at') or dt.datetime.fromisoformat(last['received_at'].replace('Z','+00:00'))>dt.datetime.fromisoformat(previous['last_received_at'].replace('Z','+00:00')):values.update(last_message_id=last['message_id'],last_received_at=last['received_at'])
                for k,v in values.items():c.execute('INSERT OR REPLACE INTO mail_checkpoints VALUES (?,?,?)',(aid,k,v))
                save_tasks(c,aid,next_tasks,fingerprint,oldest,p.VERSION);p.touch(c)
        tasks=next_tasks
        if not complete:break
    if mail.SCAN_CANCEL.is_set():mail.SYNC['summary']='Mail scan paused. Saved batches and checkpoint retained.'
    else:mail.SYNC['summary']=f'Saved {count} new company emails. '+('More mail remains; continue with the next small batch. Automatic batches run at most once every 5 minutes.' if tasks else 'Caught up. Automatic checks run at most once every 5 minutes.')

def save_tasks(c,aid,tasks,fingerprint,oldest,version):
    for k,v in {'scan_tasks':json.dumps(tasks),'companies':fingerprint,'history_oldest':oldest,'collection_version':version}.items():c.execute('INSERT OR REPLACE INTO mail_checkpoints VALUES (?,?,?)',(aid,k,v))
