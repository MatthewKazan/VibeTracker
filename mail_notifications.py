"""Notification selection is separate from durable email storage and review state."""
import datetime as dt
import json
import re
from email.utils import parseaddr
import mail_integration as mail

DEFAULTS={'enabled':True,'mode':'custom','rejection':True,'interview':True,'offer':True,'confirmation':True,'other':True,'ad_mode':'never','ad_keywords':['Boston Dynamics','humanoid'],'include_keywords':[],'exclude_keywords':[],'muted_senders':[],'muted_companies':[],'filter_reviews':False,'sound':True,'previews':True,'attention':True,'badge':True,'quiet_enabled':False,'quiet_start':'22:00','quiet_end':'08:00','reviews_bypass_quiet':False,'analysis_failures':False}
LISTS=('ad_keywords','include_keywords','exclude_keywords','muted_senders','muted_companies')
BOOLS=set(DEFAULTS)-set(LISTS)-{'mode','ad_mode','quiet_start','quiet_end'}
def validate(value):
    if not isinstance(value,dict) or set(value)-set(DEFAULTS):raise ValueError('Invalid notification preferences.')
    result={**DEFAULTS,**value}
    if any(type(result[k]) is not bool for k in BOOLS):raise ValueError('Notification switches must be on or off.')
    if result['mode'] not in ('custom','reviews_only') or result['ad_mode'] not in ('never','keywords','all'):raise ValueError('Choose a valid notification mode.')
    for key in LISTS:
        if not isinstance(result[key],list) or len(result[key])>50 or any(not isinstance(v,str) or not v.strip() or len(v)>200 or '\n' in v or '\r' in v for v in result[key]):raise ValueError('Use up to 50 nonempty phrases per notification filter, each at most 200 characters.')
        result[key]=list(dict.fromkeys(v.strip() for v in result[key]))
    for key in ('quiet_start','quiet_end'):
        if not isinstance(result[key],str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',result[key]):raise ValueError('Quiet hours need valid local times.')
    if result['quiet_enabled'] and result['quiet_start']==result['quiet_end']:raise ValueError('Quiet-hour start and end must differ. Use Enable notifications to turn all alerts off.')
    if result['ad_mode']=='keywords' and not result['ad_keywords']:raise ValueError('Add at least one ad phrase, or choose Never notify for job ads.')
    for sender in result['muted_senders']:
        if not re.fullmatch(r'(?:[^@\s]+)?@(?:[a-zA-Z0-9-]+\.)+[a-zA-Z0-9-]+',sender):raise ValueError('Sender mutes need an email address or @domain, one per line.')
    return result

def preferences(c):
    try:return validate(mail.get_setting(c,'notification_preferences',{}))
    except ValueError:return validate({})
def quiet(p,now=None):
    if not p['quiet_enabled']:return False
    clock=(now or dt.datetime.now().astimezone()).strftime('%H:%M');start,end=p['quiet_start'],p['quiet_end']
    if start==end:return False
    return start<=clock<end if start<end else clock>=start or clock<end

def phrases(text,values):
    normalized=mail.normalized(text)
    return any(bool(term:=mail.normalized(v)) and (mail.contains(normalized,term) or mail.contains(normalized,term+'s')) for v in values)
def allows(message,p):
    if not p['enabled'] or message.get('review')=='ignored':return False
    review=message.get('review')=='pending' and message.get('category') in ('rejection','interview','offer')
    category=message.get('category') or 'other'
    if p['mode']=='reviews_only' and not review:return False
    if review:
        if not p.get(category,False):return False
    elif category=='job_ad':
        if p['ad_mode']=='never':return False
    elif message.get('analysis_state')=='failed':
        if not p['analysis_failures']:return False
    elif not p.get(category,False):return False
    text='\n'.join(str(message.get(k) or '') for k in ('company','subject','sender','body'))
    if category=='job_ad' and p['ad_mode']=='keywords' and not phrases(text,p['ad_keywords']):return False
    if not review or p['filter_reviews']:
        sender=parseaddr(message.get('sender',''))[1].casefold();domain=sender.rsplit('@',1)[-1] if '@' in sender else ''
        for value in p['muted_senders']:
            value=value.casefold()
            if value.startswith('@') and (domain==value[1:] or domain.endswith('.'+value[1:])):return False
            if sender==value:return False
        companies=message.get('company','').split(' / ')
        if any(__import__('mail_pipeline').company_key(v)==__import__('mail_pipeline').company_key(co) for v in p['muted_companies'] for co in companies):return False
        if p['include_keywords'] and not phrases(text,p['include_keywords']):return False
        if phrases(text,p['exclude_keywords']):return False
    return True

def pending(c,now=None):
    p=preferences(c);account=mail.get_setting(c,'mail_account') or {};aid=account.get('id','')
    rows=[dict(r) for r in c.execute("SELECT n.id,n.kind,e.* FROM email_events n JOIN emails e USING(message_id) JOIN email_accounts a USING(message_id) WHERE a.account_id=? AND n.delivered=0 ORDER BY CASE WHEN n.kind LIKE 'status:%' THEN 0 ELSE 1 END,n.id LIMIT 1000",(aid,))]
    events=[];suppressed=[];is_quiet=quiet(p,now)
    for row in rows:
        if row['analysis_state'] in ('queued','running') and row['review']!='pending':continue
        if row['kind']!='added' and row['review']!='pending':suppressed.append((row['id'],));continue
        if not allows(row,p):suppressed.append((row['id'],));continue
        if is_quiet and not (row['review']=='pending' and p['reviews_bypass_quiet']):continue
        if len(events)<100:events.append({k:row[k] for k in ('id','message_id','kind','company','subject','category')})
    c.executemany('UPDATE email_events SET delivered=1,suppressed=1 WHERE id=?',suppressed)
    return {'events':events,'presentation':{k:p[k] for k in ('sound','previews','attention','badge')},'quiet':is_quiet}
