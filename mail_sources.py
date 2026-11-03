"""Read-only provider adapters, account-scoped source identity and durable page cursors.

Credentials live in memory only. The Electron main process owns encrypted persistence.
Provider response URLs are validated before bearer credentials are attached.
"""
import base64
import datetime as dt
import email.policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime, parseaddr
import hashlib
from html.parser import HTMLParser
import imaplib
import json
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse as urlparse
import urllib.request

CREDENTIALS={}
UPDATES={}
RETRY_AT={}
CREDENTIAL_LOCK=threading.RLock()
PROVIDERS={'gmail','graph','imap'}
MAX_RAW=8_000_000

class SourceError(ValueError):
    def __init__(self,message,status=None,retry_at=None):super().__init__(message);self.status=status;self.retry_at=retry_at

class TextHTML(HTMLParser):
    def __init__(self,text):super().__init__();self.parts=[];self.skip=0;self.feed(text)
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.skip+=1
        if tag=='blockquote':self.parts.append('\n----- Quoted message -----\n')
        if tag in ('p','div','br','li','tr'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style') and self.skip:self.skip-=1
    def handle_data(self,data):
        if not self.skip:self.parts.append(data)
def plain_html(text):return ''.join(TextHTML(text).parts).strip()
def utc(value):
    try:
        stamp=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    except (ValueError,AttributeError):stamp=parsedate_to_datetime(value)
    if not stamp:raise SourceError('The provider returned a message without a valid receipt date.')
    if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=dt.timezone.utc)
    return stamp.astimezone(dt.timezone.utc).isoformat()
def identity(provider,address,host=''):
    return provider+':'+hashlib.sha256((address.strip().casefold()+'\0'+host.casefold()).encode()).hexdigest()[:24]
def message_key(account,remote):return 'source:'+account['provider']+':'+hashlib.sha256((account['id']+'\0'+remote).encode()).hexdigest()
def valid_link(link,provider):
    try:p=urlparse.urlparse(link or '');port=p.port
    except ValueError:return ''
    hosts={'gmail':{'mail.google.com'},'graph':{'outlook.live.com','outlook.office.com','outlook.office365.com'}}
    return link if p.scheme=='https' and not p.username and not p.password and p.hostname in hosts.get(provider,set()) and port in (None,443) else ''

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def request_json(url,headers=None,form=None):
    data=urlparse.urlencode(form).encode() if form is not None else None
    req=urllib.request.Request(url,data=data,headers=headers or {})
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=30) as response:
            raw=response.read(12_000_001)
            if len(raw)>12_000_000:raise SourceError('The mail provider response is too large. Retry with a smaller page.')
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        if exc.code in (401,403):raise SourceError('Mail access was denied. Reconnect this account and check its read permission.',exc.code) from None
        if exc.code in (429,503):
            delay=exc.headers.get('Retry-After','60')
            try:retry_at=time.time()+max(1,min(float(delay),86400))
            except ValueError:
                try:retry_at=parsedate_to_datetime(delay).timestamp()
                except (TypeError,ValueError):retry_at=time.time()+60
            raise SourceError('The mail provider is temporarily limiting requests. Saved progress is unchanged; retry after '+dt.datetime.fromtimestamp(retry_at).strftime('%H:%M:%S')+'.',exc.code,retry_at) from None
        if exc.code in (404,410):raise SourceError('The saved mail cursor or message is no longer available.',exc.code) from None
        raise SourceError('The mail provider request failed (HTTP '+str(exc.code)+'). Saved progress is unchanged.',exc.code) from None
    except (OSError,ValueError) as exc:
        if isinstance(exc,SourceError):raise
        raise SourceError('The mail provider could not be reached or returned an invalid response. Retry later.') from None

class API:
    def __init__(self,config,update=lambda value:None,transport=request_json):self.config=dict(config);self.update=update;self.transport=transport
    def refresh(self):
        c=self.config
        if not c.get('refresh_token'):raise SourceError('Reconnect this mail account to renew access.')
        endpoint='https://oauth2.googleapis.com/token' if c['provider']=='gmail' else 'https://login.microsoftonline.com/common/oauth2/v2.0/token'
        form={'client_id':c['client_id'],'refresh_token':c['refresh_token'],'grant_type':'refresh_token'}
        if c['provider']=='gmail' and c.get('client_secret'):form['client_secret']=c['client_secret']
        result=self.transport(endpoint,form=form)
        if not isinstance(result.get('access_token'),str):raise SourceError('The mail authorization could not be renewed. Reconnect this account.')
        c.update(access_token=result['access_token'],expires_at=time.time()+int(result.get('expires_in',3600)))
        if result.get('refresh_token'):c['refresh_token']=result['refresh_token']
        self.update(dict(c))
    def get(self,path):
        provider=self.config['provider'];throttle_key=(provider,self.config.get('email') or self.config.get('client_id'))
        if RETRY_AT.get(throttle_key,0)>time.time():raise SourceError('Waiting for the mail provider retry window. Saved progress is unchanged; try again later.',429)
        host='gmail.googleapis.com' if provider=='gmail' else 'graph.microsoft.com'
        root='https://'+host+('/gmail/v1/users/me' if provider=='gmail' else '/v1.0')
        url=path if path.startswith('https:') else root+path
        parsed=urlparse.urlparse(url)
        if parsed.scheme!='https' or parsed.hostname!=host or parsed.port not in (None,443) or parsed.username or parsed.password:raise SourceError('The mail provider returned an unsafe continuation link.')
        if self.config.get('expires_at',0)<time.time()+60:self.refresh()
        for attempt in range(2):
            headers={'Authorization':'Bearer '+self.config['access_token']}
            if provider=='graph':headers['Prefer']='IdType="ImmutableId", outlook.body-content-type="text"'
            try:return self.transport(url,headers=headers)
            except SourceError as exc:
                if exc.retry_at:RETRY_AT[throttle_key]=exc.retry_at
                if exc.status==401 and attempt==0:self.refresh();continue
                raise

class Gmail(API):
    def profile(self):
        data=self.get('/profile');address=data.get('emailAddress','')
        if not address:raise SourceError('Gmail did not return an account address.')
        return {'id':identity('gmail',address),'provider':'gmail','name':address+' · Gmail','addresses':[address]}
    def message(self,ident):
        try:data=self.get('/messages/'+urlparse.quote(ident,safe='')+'?format=full')
        except SourceError as exc:
            if exc.status==404:return None
            raise
        if set(data.get('labelIds',[]))&{'TRASH','DRAFT'}:return None
        headers={h['name'].casefold():h.get('value','') for h in data.get('payload',{}).get('headers',[])}
        texts=[];html=[];limited=False
        def walk(part):
            nonlocal limited
            if part.get('filename'):return
            payload=part.get('body',{});value=payload.get('data')
            is_text=part.get('mimeType') in ('text/plain','text/html')
            if is_text and payload.get('size',0)>2_000_000:limited=True;return
            if is_text and not value and payload.get('attachmentId'):
                value=self.get('/messages/'+urlparse.quote(ident,safe='')+'/attachments/'+urlparse.quote(payload['attachmentId'],safe='')).get('data')
            if value:
                try:text=base64.urlsafe_b64decode(value+'='*(-len(value)%4)).decode('utf-8','replace')
                except (ValueError,TypeError):raise SourceError('Gmail returned invalid message content.') from None
                if part.get('mimeType')=='text/plain':texts.append(text)
                elif part.get('mimeType')=='text/html':html.append(plain_html(text))
            for child in part.get('parts',[]):walk(child)
        walk(data.get('payload',{}))
        body='\n'.join(texts or html)
        limited|=len(body)>2_000_000;body=body[:2_000_000]
        received=dt.datetime.fromtimestamp(int(data['internalDate'])/1000,dt.timezone.utc).isoformat()
        return {'remote_id':str(data['id']),'internet_id':headers.get('message-id','').strip('<> '),'folder_id':','.join(sorted(data.get('labelIds',[]))),'sender':headers.get('from',''),'subject':headers.get('subject',''),'body':body,'received_at':received,'web_url':'https://mail.google.com/mail/?authuser='+urlparse.quote(self.config.get('email',''),safe='')+'#all/'+str(data['id']),'body_complete':bool(body.strip()) and not limited,**({'source_warning':'Email body is empty or exceeds the safe download limit. Rescan after downloading the complete message, or review the original.'} if limited or not body.strip() else {})}
    def page(self,cursor):
        state=dict(cursor or {})
        if not state:
            start=self.get('/profile')['historyId'];state={'mode':'initial','historyId':str(start)}
        initial=state['mode']=='initial'
        query={'maxResults':100}
        if state.get('pageToken'):query['pageToken']=state['pageToken']
        if initial:query.update(includeSpamTrash='true',q='-in:trash -in:drafts');path='/messages'
        else:query['startHistoryId']=state['historyId'];path='/history'
        try:data=self.get(path+'?'+urlparse.urlencode(query))
        except SourceError as exc:
            if not initial and exc.status==404:return [],{},False
            raise
        if initial:ids=[m['id'] for m in data.get('messages',[])]
        else:
            ids=[]
            for change in data.get('history',[]):
                for key in ('messages','messagesAdded','labelsAdded','labelsRemoved'):
                    for item in change.get(key,[]):
                        value=item.get('message',item)
                        if value.get('id'):ids.append(value['id'])
        messages=[m for ident in dict.fromkeys(ids) if (m:=self.message(ident)) is not None]
        if data.get('nextPageToken'):state['pageToken']=data['nextPageToken'];done=False
        else:state={'mode':'history','historyId':str(data.get('historyId',state['historyId']))};done=True
        return messages,state,done

class Graph(API):
    def profile(self):
        data=self.get('/me?$select=id,mail,userPrincipalName');address=data.get('mail') or data.get('userPrincipalName')
        if not address or not data.get('id'):raise SourceError('Outlook did not return a usable account identity.')
        return {'id':identity('graph',data['id']),'provider':'graph','name':address+' · Outlook','addresses':[address]}
    def folders(self):
        excluded=set()
        for name in ('deleteditems','drafts'):
            try:excluded.add(self.get('/me/mailFolders/'+name+'?$select=id')['id'])
            except SourceError as exc:
                if exc.status!=404:raise
        found=[];pending=['/me/mailFolders?includeHiddenFolders=true&$top=100&$select=id,childFolderCount']
        while pending:
            data=self.get(pending.pop(0))
            for folder in data.get('value',[]):
                if folder['id'] in excluded:continue
                found.append(folder['id'])
                if folder.get('childFolderCount'):pending.append('/me/mailFolders/'+urlparse.quote(folder['id'],safe='')+'/childFolders?includeHiddenFolders=true&$top=100&$select=id,childFolderCount')
            if data.get('@odata.nextLink'):pending.append(data['@odata.nextLink'])
        return list(dict.fromkeys(found))
    def page(self,cursor):
        state=json.loads(json.dumps(cursor or {}))
        if not state or state.get('complete'):
            state={'folders':self.folders(),'index':0,'deltas':state.get('deltas',{})}
        if state['index']>=len(state['folders']):state['complete']=True;return [],state,True
        folder=state['folders'][state['index']]
        url=state.get('next') or state['deltas'].get(folder) or '/me/mailFolders/'+urlparse.quote(folder,safe='')+'/messages/delta?$top=100&$select=id,internetMessageId,subject,from,receivedDateTime,body,webLink,isDraft,parentFolderId'
        try:data=self.get(url)
        except SourceError as exc:
            if exc.status in (404,410):
                had_cursor=bool(state.get('next') or state['deltas'].get(folder));state.pop('next',None);state['deltas'].pop(folder,None)
                if not had_cursor:state['index']+=1
                return [],state,False
            raise
        messages=[self.normalize(item,folder) for item in data.get('value',[]) if '@removed' not in item and not item.get('isDraft')]
        if data.get('@odata.nextLink'):state['next']=data['@odata.nextLink']
        else:
            state['deltas'][folder]=data.get('@odata.deltaLink',url);state.pop('next',None);state['index']+=1
        state['complete']=state['index']>=len(state['folders'])
        return messages,state,state['complete']

    def normalize(self,item,folder=''):
        address=item.get('from',{}).get('emailAddress',{});body=item.get('body',{});content=body.get('content','')
        return {'remote_id':item['id'],'internet_id':item.get('internetMessageId','').strip('<> '),'folder_id':folder,'sender':((address.get('name','')+' <'+address.get('address','')+'>').strip()),'subject':item.get('subject',''),'body':(plain_html(content) if body.get('contentType','').casefold()=='html' else content)[:2_000_000],'received_at':utc(item['receivedDateTime']),'web_url':valid_link(item.get('webLink'),'graph'),'body_complete':bool(content.strip()) and len(content)<=2_000_000,**({'source_warning':'Email text is empty or exceeds the safe download limit. Rescan or review the original.'} if not content.strip() or len(content)>2_000_000 else {})}
    def message(self,ident):
        try:item=self.get('/me/messages/'+urlparse.quote(ident,safe='')+'?$select=id,internetMessageId,subject,from,receivedDateTime,body,webLink,isDraft,parentFolderId')
        except SourceError as exc:
            if exc.status==404:return None
            raise
        return None if item.get('isDraft') else self.normalize(item,item.get('parentFolderId',''))

LIST_PATTERN=re.compile(rb'^\((.*?)\)\s+(?:"[^"]*"|NIL)\s+(.+)$')
def imap_folder(row):
    literal=None
    if isinstance(row,tuple):row,literal=row
    if not isinstance(row,bytes):return None
    match=LIST_PATTERN.match(row)
    if not match:return None
    flags=match[1].lower();name=literal or match[2]
    if b'\\noselect' in flags or b'\\trash' in flags or b'\\drafts' in flags:return None
    if name.startswith(b'"') and name.endswith(b'"'):name=name[1:-1].replace(b'\\"',b'"').replace(b'\\\\',b'\\')
    if name.lower() in (b'trash',b'deleted messages',b'drafts'):return None
    return name

def mime_message(raw,metadata):
    message=BytesParser(policy=email.policy.default).parsebytes(raw)
    text=message.get_body(preferencelist=('plain','html')) if message.is_multipart() else message
    body=''
    if text and text.get_content_maintype()=='text':
        try:body=text.get_content()
        except (LookupError,ValueError):body=text.get_payload(decode=True).decode('utf-8','replace')
        if text.get_content_subtype()=='html':body=plain_html(body)
    date=re.search(rb'INTERNALDATE "([^"]+)"',metadata)
    received=utc(date[1].decode()) if date else utc(str(message.get('Date','')))
    return {'internet_id':str(message.get('Message-ID','')).strip('<> '),'sender':str(message.get('From','')),'subject':str(message.get('Subject','')),'body':str(body)[:2_000_000],'received_at':received,'web_url':'','body_complete':True}

def body_structure(metadata):
    found=re.search(rb'BODYSTRUCTURE\s+(\()',metadata,re.I)
    if len(metadata)>1_000_000:raise SourceError('The IMAP body structure exceeds the safe limit.')
    if not found:raise SourceError('The IMAP server did not return a body structure.')
    tokens=re.findall(rb'\(|\)|"(?:\\.|[^"\\])*"|[^\s()]+',metadata[found.start(1):])
    index=0
    def value():
        nonlocal index
        if index>=len(tokens):raise SourceError('The IMAP body structure is incomplete.')
        token=tokens[index];index+=1
        if token==b'(':
            result=[]
            while index<len(tokens) and tokens[index]!=b')':result.append(value())
            if index>=len(tokens):raise SourceError('The IMAP body structure is incomplete.')
            index+=1;return result
        if token.startswith(b'"'):return re.sub(rb'\\(.)',rb'\1',token[1:-1]).decode('ascii','replace')
        return None if token.upper()==b'NIL' else token.decode('ascii','replace')
    return value()

def text_parts(structure,prefix=''):
    if len(prefix)>200:raise SourceError('The IMAP message is nested too deeply.')
    if not isinstance(structure,list) or not structure:return []
    if isinstance(structure[0],list):
        result=[]
        for index,child in enumerate(structure,1):
            if not isinstance(child,list):break
            result.extend(text_parts(child,(prefix+'.' if prefix else '')+str(index)))
        return result
    if len(structure)<7 or str(structure[0]).upper()!='TEXT' or str(structure[1]).upper() not in ('PLAIN','HTML'):return []
    params=structure[2] if isinstance(structure[2],list) else []
    parameters={str(params[i]).casefold():str(params[i+1]) for i in range(0,len(params)-1,2)}
    if parameters.get('name') or any(isinstance(v,list) and v and str(v[0]).upper()=='ATTACHMENT' for v in structure[7:]):return []
    return [{'part':prefix or 'TEXT','subtype':str(structure[1]).casefold(),'charset':parameters.get('charset','utf-8'),'encoding':str(structure[5]),'size':max(0,int(structure[6]))}]

def read_imap_message(connection,ident):
    status,parts=connection.uid('fetch',str(ident),'(UID INTERNALDATE BODYSTRUCTURE BODY.PEEK[HEADER])')
    if status!='OK':raise SourceError('An IMAP message could not be read. Saved progress is unchanged.')
    chunks=[p for p in parts if isinstance(p,tuple) and len(p)==2]
    if not chunks:raise SourceError('IMAP did not return this email header. Retry the page.')
    metadata,header=chunks[0];message=mime_message(header,metadata)
    selected=text_parts(body_structure(metadata));selected=[p for p in selected if p['subtype']=='plain'] or selected
    content=[];remaining=2_000_000;limited=False
    for part in selected:
        if remaining<=0:limited=True;break
        cap=min(part['size'],remaining)
        if cap==0:continue
        query='(BODY.PEEK['+part['part']+']'+('<0.'+str(cap)+'>' if part['size']>cap else '')+')'
        status,data=connection.uid('fetch',str(ident),query)
        chunks=[p for p in data if isinstance(p,tuple) and len(p)==2] if status=='OK' else []
        if not chunks:raise SourceError('An IMAP text part could not be downloaded. Retry the page.')
        raw=chunks[0][1]
        from email.message import EmailMessage
        section=EmailMessage(policy=email.policy.default);section.set_type('text/'+part['subtype']);section.set_param('charset',part['charset']);section['Content-Transfer-Encoding']=part['encoding'];section.set_payload(raw)
        try:text=section.get_content(errors='replace')
        except (LookupError,ValueError):text=raw.decode('utf-8','replace')
        content.append(plain_html(text) if part['subtype']=='html' else text);remaining-=len(raw);limited|=part['size']>cap
    message['body']='\n'.join(content)[:2_000_000];message['body_complete']=not limited and bool(message['body'].strip())
    if limited or not message['body'].strip():message['source_warning']='This email text exceeds the safe download limit. Review the complete original in your mail app; no automatic status suggestion was generated.'
    return message

class IMAP:
    def __init__(self,config,update=lambda value:None,factory=imaplib.IMAP4_SSL,**kwargs):self.config=dict(config);self.factory=factory
    def connect(self):
        c=self.config
        try:
            connection=self.factory(c['host'],int(c.get('port',993)),ssl_context=ssl.create_default_context(),timeout=30)
            connection.login(c.get('username') or c['email'],c['password']);return connection
        except (imaplib.IMAP4.error,OSError):raise SourceError('Could not connect or authenticate to IMAP. Check the server, username and app password.') from None
    def profile(self):
        connection=self.connect()
        try:
            status,_=connection.list()
            if status!='OK':raise SourceError('The IMAP account could not list its folders.')
        finally:
            try:connection.logout()
            except Exception:pass
        c=self.config;address=c['email']
        return {'id':identity('imap',c.get('username') or address,c['host']+':'+str(c.get('port',993))),'provider':'imap','name':address+' · IMAP','addresses':[address]}
    def page(self,cursor):
        state=json.loads(json.dumps(cursor or {}));connection=self.connect()
        try:
            if not state or state.get('complete'):
                status,rows=connection.list()
                if status!='OK':raise SourceError('Could not enumerate IMAP folders. Saved progress is unchanged.')
                folders=[base64.b64encode(name).decode() for row in rows if (name:=imap_folder(row)) is not None]
                state={'folders':folders,'index':0,'positions':state.get('positions',{})}
            if state['index']>=len(state['folders']):state['complete']=True;return [],state,True
            folder=state['folders'][state['index']];name=base64.b64decode(folder)
            quoted=b'"'+name.replace(b'\\',b'\\\\').replace(b'"',b'\\"')+b'"'
            status,_=connection.select(quoted,readonly=True)
            if status!='OK':raise SourceError('An IMAP folder is unavailable. Saved progress is unchanged.')
            _,validity=connection.response('UIDVALIDITY')
            if not validity or not validity[0]:raise SourceError('The IMAP server did not provide UIDVALIDITY; a safe checkpoint cannot be saved.')
            validity=validity[0].decode() if isinstance(validity[0],bytes) else str(validity[0])
            previous=state['positions'].get(folder,{})
            last=previous.get('uid',0) if previous.get('validity')==validity else 0
            status,data=connection.uid('search',None,'UID',str(last+1)+':*')
            if status!='OK':raise SourceError('The IMAP message search failed. Saved progress is unchanged.')
            ids=sorted(int(v) for v in (data[0] or b'').split() if int(v)>last);batch=ids[:20];messages=[]
            for ident in batch:
                message=read_imap_message(connection,ident);message.update(remote_id=folder+':'+validity+':'+str(ident),folder_id=folder);messages.append(message)
            state['positions'][folder]={'validity':validity,'uid':batch[-1] if batch else last}
            if len(ids)<=len(batch):state['index']+=1
            state['complete']=state['index']>=len(state['folders'])
            return messages,state,state['complete']
        except (imaplib.IMAP4.error,OSError):raise SourceError('IMAP was interrupted. Saved progress is unchanged; retry the connection.') from None
        finally:
            try:connection.logout()
            except Exception:pass

    def message(self,remote):
        folder,validity,ident=remote.rsplit(':',2);connection=self.connect()
        try:
            name=base64.b64decode(folder);quoted=b'"'+name.replace(b'\\',b'\\\\').replace(b'"',b'\\"')+b'"'
            status,_=connection.select(quoted,readonly=True)
            if status!='OK':return None
            _,current=connection.response('UIDVALIDITY')
            if not current or not current[0] or current[0].decode()!=validity:return None
            message=read_imap_message(connection,int(ident));message.update(remote_id=remote,folder_id=folder);return message
        finally:
            try:connection.logout()
            except Exception:pass

ADAPTERS={'gmail':Gmail,'graph':Graph,'imap':IMAP}
def init(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS mail_source_accounts(id TEXT PRIMARY KEY,metadata TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS mail_provider_cursors(account_id TEXT PRIMARY KEY,cursor TEXT NOT NULL,fingerprint TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS email_source_refs(account_id TEXT NOT NULL,remote_id TEXT NOT NULL,message_id TEXT NOT NULL,provider TEXT NOT NULL,internet_id TEXT NOT NULL DEFAULT '',folder_id TEXT NOT NULL DEFAULT '',web_url TEXT NOT NULL DEFAULT '',body_complete INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(account_id,remote_id));
    CREATE INDEX IF NOT EXISTS source_rfc_id ON email_source_refs(account_id,internet_id);
    CREATE INDEX IF NOT EXISTS source_message ON email_source_refs(message_id);
    ''')

def validate_config(config):
    if not isinstance(config,dict) or config.get('provider') not in PROVIDERS:raise SourceError('Choose Gmail, Outlook or IMAP.')
    c={k:v for k,v in config.items() if k in ('provider','client_id','client_secret','access_token','refresh_token','expires_at','email','username','host','port')}
    if c['provider']=='imap':
        # Passwords are intentionally accepted only in the main-process credential route.
        c['password']=config.get('password','')
        if not all(isinstance(c.get(k),str) and c[k].strip() for k in ('host','email','password')):raise SourceError('Enter the IMAP server, email address and app password.')
        if any(ch in c['host'] for ch in ('/',':','\\','\n','\r',' ')):raise SourceError('Enter an IMAP hostname without a URL or port.')
        try:port=int(c.get('port',993))
        except (ValueError,TypeError):raise SourceError('The IMAP port is invalid.') from None
        if not 1<=port<=65535:raise SourceError('The IMAP port is invalid.')
        c['port']=port
    elif not all(isinstance(c.get(k),str) and c[k] for k in ('client_id','access_token')):raise SourceError('Complete the provider sign-in before connecting.')
    if any(not isinstance(v,(str,int,float)) for v in c.values()):raise SourceError('Invalid mail connection configuration.')
    if any(isinstance(v,str) and ('\r' in v or '\n' in v or len(v)>10000) for v in c.values()):raise SourceError('Mail connection fields must be single-line values.')
    if 'expires_at' in c:
        import math
        c['expires_at']=float(c['expires_at'])
        if not math.isfinite(c['expires_at']):raise SourceError('Invalid token expiry.')
    return c

def rotated(account_id,config):
    with CREDENTIAL_LOCK:
        if account_id in CREDENTIALS:
            CREDENTIALS[account_id]=dict(config)
            UPDATES[account_id]={'config':dict(config),'revision':UPDATES.get(account_id,{}).get('revision',0)+1}

def install(app,config,activate=False):
    import mail_integration as mail,mail_pipeline as pipeline
    cfg=validate_config(config);adapter=ADAPTERS[cfg['provider']](cfg);account=adapter.profile()
    with app.LOCK,app.connect() as c:
        if activate and mail.SYNC_LOCK.locked():raise SourceError('Wait for the current email sync to finish before switching accounts.')
        old=mail.get_setting(c,'mail_account')
        if old:c.execute('INSERT OR REPLACE INTO mail_source_accounts VALUES (?,?)',(old['id'],json.dumps(old)))
        c.execute('INSERT OR REPLACE INTO mail_source_accounts VALUES (?,?)',(account['id'],json.dumps(account)))
        if activate:c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('mail_account',json.dumps(account)))
        pipeline.touch(c)
    with CREDENTIAL_LOCK:
        CREDENTIALS[account['id']]=dict(adapter.config)
        if adapter.config!=cfg:rotated(account['id'],adapter.config)
        CREDENTIALS[account['id']]['email']=account['addresses'][0]
    return account

def disconnect(app,account_id):
    import mail_integration as mail,mail_pipeline as pipeline
    with app.LOCK,app.connect() as c:
        selected=mail.get_setting(c,'mail_account') or {}
        if selected.get('id')==account_id and mail.SYNC_LOCK.locked():raise SourceError('Wait for the current sync to finish before disconnecting.')
        if selected.get('id')==account_id:
            c.execute("DELETE FROM settings WHERE key='mail_account'")
            c.execute("INSERT OR REPLACE INTO settings VALUES ('mail_enabled','false')")
        pipeline.touch(c)
    with CREDENTIAL_LOCK:CREDENTIALS.pop(account_id,None);UPDATES.pop(account_id,None)

def accounts(c):return [json.loads(r[0]) for r in c.execute('SELECT metadata FROM mail_source_accounts ORDER BY id')]
def available(account):
    if not account:return False
    if account.get('provider') in PROVIDERS:
        with CREDENTIAL_LOCK:return account['id'] in CREDENTIALS
    import sys
    return sys.platform=='darwin'

def canonical(c,account,message):
    ident=c.execute('SELECT message_id FROM email_source_refs WHERE account_id=? AND remote_id=?',(account['id'],message['remote_id'])).fetchone()
    if ident:return ident[0]
    internet=message.get('internet_id','').strip('<> ')
    # Reconcile a folder move or an Apple Mail -> direct-provider migration only
    # within a proven shared account address and matching sender/subject/date.
    related={account['id']}
    addresses={v.casefold() for v in account.get('addresses',[])}
    for other in accounts(c):
        if addresses & {v.casefold() for v in other.get('addresses',[])}:related.add(other['id'])
    candidates=[]
    if internet:
        candidates=[r[0] for r in c.execute('SELECT DISTINCT message_id FROM email_source_refs WHERE internet_id=? AND account_id IN ('+','.join('?' for _ in related)+')',[internet,*sorted(related)])]
        candidates+=[internet,'<'+internet+'>']
    for candidate in candidates:
        row=c.execute('SELECT e.* FROM emails e JOIN email_accounts a USING(message_id) WHERE e.message_id=? AND a.account_id IN ('+','.join('?' for _ in related)+')',[candidate,*sorted(related)]).fetchone()
        if row and (not row['body'].strip() or not message['body'].strip() or re.sub(r'\s+',' ',row['body']).strip()[:80]==re.sub(r'\s+',' ',message['body']).strip()[:80]) and row['subject']==message['subject'] and parseaddr(row['sender'])[1].casefold()==parseaddr(message['sender'])[1].casefold():
            try:
                if abs((dt.datetime.fromisoformat(utc(row['received_at']))-dt.datetime.fromisoformat(utc(message['received_at']))).total_seconds())<=300:return candidate
            except ValueError:pass
    return message_key(account,message['remote_id'])

def sync_locked(app,account,jobs):
    import mail_integration as mail,mail_pipeline as pipeline
    with CREDENTIAL_LOCK:config=dict(CREDENTIALS.get(account['id'],{}))
    if not config:raise SourceError('Reconnect the selected email account to unlock its credentials.')
    adapter=ADAPTERS[account['provider']](config,update=lambda value:rotated(account['id'],value))
    profiles=pipeline.company_profiles(jobs)
    if not profiles:raise SourceError('Add a company name to an application before syncing mail.')
    fingerprint=hashlib.sha256(json.dumps(profiles,sort_keys=True).encode()).hexdigest()
    with app.connect() as c:
        saved=c.execute('SELECT cursor,fingerprint FROM mail_provider_cursors WHERE account_id=?',(account['id'],)).fetchone()
        cursor=json.loads(saved['cursor']) if saved and saved['fingerprint']==fingerprint else {}
    recovery=[]
    with app.connect() as c:
        empty=[r[0] for r in c.execute("SELECT r.remote_id FROM email_source_refs r JOIN emails e USING(message_id) WHERE r.account_id=? AND r.body_complete=0 AND length(trim(e.body))=0 AND e.review NOT IN ('approved','dismissed','ignored') LIMIT 20",(account['id'],))]
    for ident in empty:
        message=adapter.message(ident)
        if message is not None:recovery.append(message)
    count=0
    while True:
        mail.SYNC['summary']='Collecting '+account['provider']+' messages; each completed page is saved before AI analysis.'
        messages,next_cursor,done=adapter.page(cursor)
        messages=recovery+messages;recovery=[]
        with app.LOCK,app.connect() as c:
            selected=mail.get_setting(c,'mail_account') or {}
            if selected.get('id')!=account['id']:raise SourceError('The selected account changed. This page was not committed.')
            converted=[]
            for message in messages:
                converted.append({**message,'message_id':canonical(c,account,message)})
            count+=pipeline.collect(c,converted,jobs,account['id'])
            for message in converted:
                if c.execute('SELECT 1 FROM emails WHERE message_id=?',(message['message_id'],)).fetchone():
                    previous=c.execute('SELECT body_complete FROM email_source_refs WHERE account_id=? AND remote_id=?',(account['id'],message['remote_id'])).fetchone()
                    if previous and not previous[0] and message.get('body_complete',True):c.execute("UPDATE emails SET analysis_state='queued',analysis_error='' WHERE message_id=? AND review='none'",(message['message_id'],))
                    if message.get('source_warning'):c.execute("UPDATE emails SET analysis_state='warning',analysis_error=? WHERE message_id=? AND review='none'",(message['source_warning'],message['message_id']))
                    c.execute('INSERT OR REPLACE INTO email_source_refs VALUES (?,?,?,?,?,?,?,?)',(account['id'],message['remote_id'],message['message_id'],account['provider'],message.get('internet_id',''),message.get('folder_id',''),valid_link(message.get('web_url'),account['provider']),int(message.get('body_complete',True))))
            c.execute('INSERT OR REPLACE INTO mail_provider_cursors VALUES (?,?,?)',(account['id'],json.dumps(next_cursor),fingerprint))
            stamp=pipeline.now()
            retained=[m for m in converted if c.execute('SELECT 1 FROM emails WHERE message_id=?',(m['message_id'],)).fetchone()]
            latest=max(retained,key=lambda m:utc(m['received_at'])) if retained else None
            previous=mail.checkpoint(c,account['id']).get('last_received_at')
            if latest and (not previous or utc(latest['received_at'])>utc(previous)):
                for k,v in [('last_received_at',latest['received_at']),('last_message_id',latest['message_id'])]:c.execute('INSERT OR REPLACE INTO mail_checkpoints VALUES (?,?,?)',(account['id'],k,v))
            c.execute('INSERT OR REPLACE INTO mail_checkpoints VALUES (?,?,?)',(account['id'],'through',stamp))
        cursor=next_cursor
        if done:break
    mail.SYNC['summary']='Collected '+str(count)+' new company emails from '+account['provider']+'. Classification continues separately.'

def select_account(app,account_id):
    import mail_integration as mail,mail_pipeline as pipeline
    if not mail.SYNC_LOCK.acquire(blocking=False):raise SourceError('Wait for the current email sync to finish before changing accounts.')
    try:
        with CREDENTIAL_LOCK:
            if account_id not in CREDENTIALS:raise SourceError('Reconnect this account to unlock its credentials.')
        with app.LOCK,app.connect() as c:
            row=c.execute('SELECT metadata FROM mail_source_accounts WHERE id=?',(account_id,)).fetchone()
            if not row:raise SourceError('This connection no longer exists.')
            account=json.loads(row[0]);c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('mail_account',json.dumps(account)));pipeline.touch(c)
        return {'account':account}
    finally:mail.SYNC_LOCK.release()

def export(c):
    return {name:([dict(r) for r in c.execute('SELECT * FROM '+table)] if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone() else []) for name,table in [('source_accounts','mail_source_accounts'),('source_refs','email_source_refs'),('provider_cursors','mail_provider_cursors')]}

def restore(c,data):
    for row in data.get('source_accounts',[]):
        account=json.loads(row['metadata'])
        # Only whitelisted public metadata can enter the source account table.
        safe={k:account[k] for k in ('id','name','provider','addresses') if k in account}
        c.execute('INSERT OR IGNORE INTO mail_source_accounts VALUES (?,?)',(row['id'],json.dumps(safe)))
        c.execute('DELETE FROM mail_provider_cursors WHERE account_id=?',(row['id'],))
    for row in data.get('source_refs',[]):
        if c.execute('SELECT 1 FROM emails WHERE message_id=?',(row['message_id'],)).fetchone():
            keys=('account_id','remote_id','message_id','provider','internet_id','folder_id','web_url','body_complete')
            c.execute('INSERT OR IGNORE INTO email_source_refs VALUES (?,?,?,?,?,?,?,?)',tuple(row.get(k,'') for k in keys))
    # A restore deliberately starts a fresh provider pass, preserving all source
    # identities/decisions. It must not trust a cursor from an unrelated device.
