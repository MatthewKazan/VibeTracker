// Credentials never cross the renderer bridge on reads or enter application backups.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),http=require('node:http');
class Vault{
 constructor(file,safeStorage){this.file=file;this.safe=safeStorage;this.records={};this.error='';try{if(fs.existsSync(file)){if(!this.available())throw Error('Unlock your system credential store to restore saved mail connections.');this.records=JSON.parse(this.safe.decryptString(Buffer.from(JSON.parse(fs.readFileSync(file,'utf8')).encrypted,'base64')));}}catch{this.error='Saved mail credentials could not be unlocked. Existing encrypted data has been preserved.';}}
 available(){return !!this.safe?.isEncryptionAvailable?.()&&this.safe.getSelectedStorageBackend?.()!=='basic_text';}
 save(){if(this.error)throw Error(this.error);if(!this.available())throw Error('Secure credential storage is unavailable. Connect for this session without remembering credentials.');fs.mkdirSync(path.dirname(this.file),{recursive:true});const temporary=this.file+'.'+crypto.randomBytes(6).toString('hex');try{fs.writeFileSync(temporary,JSON.stringify({version:1,encrypted:this.safe.encryptString(JSON.stringify(this.records)).toString('base64')}),{mode:0o600,flag:'wx'});fs.renameSync(temporary,this.file);}finally{if(fs.existsSync(temporary))fs.unlinkSync(temporary);}}
 put(id,config){const previous=this.records[id];this.records[id]=config;try{this.save()}catch(e){if(previous)this.records[id]=previous;else delete this.records[id];throw e;}}
 remove(id){const previous=this.records[id];delete this.records[id];try{this.save()}catch(e){if(previous)this.records[id]=previous;throw e;}}
}
const DEFINITIONS={gmail:{authorize:'https://accounts.google.com/o/oauth2/v2/auth',token:'https://oauth2.googleapis.com/token',scope:'https://www.googleapis.com/auth/gmail.readonly'},graph:{authorize:'https://login.microsoftonline.com/common/oauth2/v2.0/authorize',token:'https://login.microsoftonline.com/common/oauth2/v2.0/token',scope:'offline_access User.Read Mail.Read'}};
const b64=buffer=>buffer.toString('base64url');
function pkce(){const verifier=b64(crypto.randomBytes(48));return {verifier,challenge:b64(crypto.createHash('sha256').update(verifier).digest()),state:b64(crypto.randomBytes(32))};}
function equal(a,b){return typeof a==='string'&&typeof b==='string'&&Buffer.byteLength(a)===Buffer.byteLength(b)&&crypto.timingSafeEqual(Buffer.from(a),Buffer.from(b));}
async function oauth(config,{openExternal,fetcher=fetch,signal,timeout=300000}){
 const definition=DEFINITIONS[config.provider];if(!definition||typeof config.client_id!=='string'||!config.client_id.trim())throw Error('Enter the OAuth application client ID from your provider registration.');
 const proof=pkce();let server,timer,abort;let redirect,finished=false;
 const code=await new Promise((resolve,reject)=>{
  const finish=(error,value)=>{if(finished)return;finished=true;clearTimeout(timer);signal?.removeEventListener('abort',abort);server?.close();error?reject(error):resolve(value)};
  abort=()=>finish(Error('Mail sign-in was cancelled.'));
  server=http.createServer((req,res)=>{
   const parsed=new URL(req.url,'http://127.0.0.1');
   if(req.method!=='GET'||parsed.pathname!=='/oauth/callback'||req.headers.host!==new URL(redirect).host||!equal(parsed.searchParams.get('state'),proof.state)){res.writeHead(400,{'Content-Type':'text/plain'});res.end('Invalid sign-in response.');return;}
   const value=parsed.searchParams.get('code'),error=parsed.searchParams.get('error');res.writeHead(200,{'Content-Type':'text/plain','Cache-Control':'no-store','Content-Security-Policy':"default-src 'none'"});res.end(error?'Sign-in was not completed. Return to JobTracker.':'Sign-in received. You can close this page and return to JobTracker.');
   finish(error||!value?Error('Provider sign-in was cancelled or denied.'):null,value);
  });
  server.once('error',()=>finish(Error('Could not open the local sign-in callback. Retry connection.')));
  server.listen(0,'127.0.0.1',()=>{
   if(finished){server.close();return}
   redirect='http://'+(config.provider==='graph'?'localhost':'127.0.0.1')+':'+server.address().port+'/oauth/callback';
   const parameters=new URLSearchParams({client_id:config.client_id,redirect_uri:redirect,response_type:'code',scope:definition.scope,state:proof.state,code_challenge:proof.challenge,code_challenge_method:'S256'});
   if(config.provider==='gmail'){parameters.set('access_type','offline');parameters.set('prompt','consent')}
   Promise.resolve().then(()=>openExternal(definition.authorize+'?'+parameters)).catch(()=>finish(Error('Could not open the browser for sign-in.')));
  });
  timer=setTimeout(()=>finish(Error('Mail sign-in timed out. Try connecting again.')),timeout);timer.unref?.();signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
 });
 const body=new URLSearchParams({client_id:config.client_id,code,code_verifier:proof.verifier,redirect_uri:redirect,grant_type:'authorization_code'});
 if(config.provider==='gmail'&&config.client_secret)body.set('client_secret',config.client_secret);
 let response,data;try{response=await fetcher(definition.token,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:body.toString(),redirect:'error',signal:signal?AbortSignal.any([signal,AbortSignal.timeout(30000)]):AbortSignal.timeout(30000)});data=await response.json()}catch{if(signal?.aborted)throw Error('Mail sign-in was cancelled.');throw Error('Could not exchange the sign-in code. Check your network and retry.');}
 if(!response.ok||typeof data.access_token!=='string')throw Error('Mail sign-in failed. Verify the client registration, redirect URI and read-only permissions.');
 if(!data.refresh_token)throw Error('The provider did not grant offline access. Reconnect and approve the requested read permission.');
 return {provider:config.provider,client_id:config.client_id,...(config.provider==='gmail'&&config.client_secret?{client_secret:config.client_secret}:{}),access_token:data.access_token,refresh_token:data.refresh_token,expires_at:Date.now()/1000+Number(data.expires_in||3600)};
}
function startMailAccounts({ipcMain,safeStorage,userData,win,origin,request,openExternal,interval=15000}){
 const vault=new Vault(path.join(userData,'mail-credentials.enc.json'),safeStorage);let stopped=false,busy=false,auth,warning=vault.error,updatesBusy=false;const restores=new Map();
 const authorized=event=>{if(event.sender!==win.webContents||new URL(event.senderFrame?.url||'about:blank').origin!==origin)throw Error('Mail connection requests must come from JobTracker.');};
 const handles=[];const handle=(name,callback)=>{handles.push(name);ipcMain.handle(name,async(event,...args)=>{authorized(event);try{return await callback(...args)}catch(e){throw Error(e.message||'Mail connection failed.')}})};
 handle('mail:status',()=>({secureStorage:vault.available(),warning,busy}));
 handle('mail:connect',async config=>{
  if(busy)throw Error('Finish or cancel the current mail connection first.');if(!config||JSON.stringify(config).length>20000||!['gmail','graph','imap'].includes(config.provider))throw Error('Choose a mail provider.');
  if(config.remember!==false&&(!vault.available()||vault.error))throw Error(vault.error||'Secure storage is unavailable. Uncheck Remember to connect for this session.');
  busy=true;auth=new AbortController();try{
   const credentials=config.provider==='imap'?{provider:'imap',host:config.host,port:config.port||993,email:config.email,username:config.username||config.email,password:config.password}:await oauth(config,{openExternal,signal:auth.signal});
   const installed=await request('mail/source/install',{config:credentials,activate:true});const {account}=installed;let stored=false;
   if(config.remember!==false){try{vault.put(account.id,{...(installed.credentials||credentials),email:account.addresses[0]});stored=true}catch(e){warning=e.message+' This connection is available for this session only.';}}
   if(config.remember===false&&vault.records[account.id]){try{vault.remove(account.id)}catch{warning='Connected for this session, but previous remembered credentials could not be removed. Unlock your credential store and disconnect to forget them.'}}
   return {account,stored,warning:stored?'':warning||'Connected for this session. Reconnect after closing the app.'};
  }finally{busy=false;auth=null}
 });
 handle('mail:cancel',()=>{auth?.abort();return {ok:true}});
 handle('mail:disconnect',async id=>{if(vault.error)throw Error('Unlock your system credential store before forgetting a saved account.');if(typeof id!=='string')throw Error('Choose an account.');await restores.get(id);await request('mail/source/disconnect',{account_id:id});if(vault.records[id])vault.remove(id);return {ok:true}});
 // Restore asynchronously so an offline provider never delays app startup.
 (async()=>{for(const [id,config] of Object.entries(vault.records)){if(stopped)break;if(!vault.records[id])continue;let finished;const pending=new Promise(resolve=>finished=resolve);restores.set(id,pending);try{await request('mail/source/install',{config,activate:false})}catch{warning='A saved mail account could not reconnect. Open email settings to reconnect when online.';}finally{restores.delete(id);finished()}}})().catch(()=>{});
 const timer=setInterval(async()=>{if(stopped||updatesBusy)return;updatesBusy=true;try{const {updates}=await request('mail/source/updates');for(const [id,item] of Object.entries(updates)){if(vault.records[id])vault.put(id,item.config);await request('mail/source/ack',{account_id:id,revision:item.revision})}}catch{warning='Refreshed credentials could not be saved. Reconnect this account if access expires.';}finally{updatesBusy=false}},interval);timer.unref?.();
 return ()=>{stopped=true;auth?.abort();clearInterval(timer);for(const name of handles)ipcMain.removeHandler(name)};
}
module.exports={Vault,pkce,equal,oauth,startMailAccounts,DEFINITIONS};
