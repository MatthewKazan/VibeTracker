// Reproducible Electron measurement using only a disposable synthetic profile.
// Run with an Electron executable: electron scripts/memory-profile.cjs /tmp/result.json
const {app,BrowserWindow}=require('electron');
const {spawn,execFileSync}=require('node:child_process');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const root=path.resolve(__dirname,'..'),dir=fs.mkdtempSync(path.join(os.tmpdir(),'jobtracker-memory-'));
app.setPath('userData',path.join(dir,'electron'));
const env={...process.env,JOB_MANAGER_DATA:path.join(dir,'data'),PORT:'0',PYTHONDONTWRITEBYTECODE:'1'};
delete env.JOB_MANAGER_TOKEN;delete env.JOB_MANAGER_MAIN_TOKEN;
const python=path.join(root,'build/runtime/bin/python3');let backend;
app.whenReady().then(async()=>{
 execFileSync(python,['-B','-c',`
import app,json
app.init()
with app.connect() as c:
 for k,v in {'low_resource_mode':True,'auto_start':False,'auto_analyze':False,'mail_enabled':False,'questions':[{'question':'Synthetic question '+str(i),'answer':('Synthetic answer '+str(i)+' ')*180,'group':'QA'} for i in range(100)]}.items():c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(k,json.dumps(v)))
 for i in range(120):app.save_job(c,{'title':'Synthetic Engineer '+str(i),'company':'Synthetic QA '+str(i),'status':'Waiting','description':('Synthetic job description '+str(i)+' ')*100})
 for i in range(45):
  c.execute('INSERT INTO emails(message_id,sender,subject,body,received_at,company,match_kind,evidence,rejection,review,category,analysis_state) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',('synthetic-'+str(i),'qa@example.test','Synthetic message '+str(i),('Synthetic email body '+str(i)+' ')*4000,'2026-11-01T12:00:00+00:00','Synthetic QA 0','company','',0,'none','other','done'))
  c.execute('INSERT INTO email_jobs VALUES (?,?)',('synthetic-'+str(i),1))
`],{cwd:root,env});
 backend=spawn(python,['-u','-B','app.py'],{cwd:root,env,stdio:['ignore','pipe','pipe']});let errors='';backend.stderr.on('data',d=>errors+=d);
 const origin=await new Promise((resolve,reject)=>{let output='';backend.stdout.on('data',d=>{output+=d;const m=output.match(/WAYPOINT_READY (http:\/\/127\.0\.0\.1:\d+)/);if(m)resolve(m[1])});backend.once('exit',()=>reject(Error(errors)))});
 const win=new BrowserWindow({width:1280,height:860,show:false,webPreferences:{contextIsolation:true,nodeIntegration:false,sandbox:true}});
 await win.loadURL(origin);win.webContents.debugger.attach('1.3');
 await win.webContents.executeJavaScript("new Promise((resolve,reject)=>{const deadline=Date.now()+10000;function check(){if(state.token)resolve();else if(Date.now()>deadline)reject(Error('State did not load'));else setTimeout(check,25)}check()})");
 const measure=async()=>{await win.webContents.debugger.sendCommand('HeapProfiler.collectGarbage');return {heap:await win.webContents.debugger.sendCommand('Runtime.getHeapUsage'),dom:await win.webContents.debugger.sendCommand('Memory.getDOMCounters'),processes:app.getAppMetrics().map(p=>({type:p.type,memory:p.memory}))}};
 const startup=await measure();
 await win.webContents.executeJavaScript(`(async()=>{
  document.querySelector('#resume').value='UNSAVED SYNTHETIC PROFILE';
  document.querySelector('nav [data-view="insights"]').click();
  if(typeof ensureChartAssets==='function')await ensureChartAssets();
  document.querySelector('nav [data-view="questions"]').click();document.querySelector('#qaSearch').value='Synthetic question 7';renderQuestions();
  document.querySelector('nav [data-view="emails"]').click();await loadEmails();
  for(let i=0;i<40;i++){emailSelected='synthetic-'+i;await ensureEmailBody();renderEmails()}
  await openEmailPreview('synthetic-44');document.querySelector('#emailPreview').close();
  document.querySelector('nav [data-view="applications"]').click();
  if(document.querySelector('#resume').value!=='UNSAVED SYNTHETIC PROFILE')throw Error('Unsaved profile changed');
 })()`);
 const afterBrowsing=await measure();
 const retained=await win.webContents.executeJavaScript("({fullEmails:emailDetails.size,chartNodes:document.querySelector('#applicationFlow').childElementCount,qaNodes:document.querySelector('#qaList').childElementCount,previewText:document.querySelector('#emailPreviewDetail').textContent.length,loadedScripts:[...document.scripts].map(s=>s.getAttribute('src')).filter(Boolean)})");
 const checks=await win.webContents.executeJavaScript(`(async()=>{
  const nav=view=>document.querySelector('nav [data-view="'+view+'"]').click();
  nav('emails');await loadEmails();emailSelected='synthetic-0';await ensureEmailBody();renderEmails();
  const input=document.querySelector('#mailLinkSearch');input.closest('details').open=true;input.value='UNSAVED LINK FILTER';input.dispatchEvent(new Event('input',{bubbles:true}));
  nav('questions');nav('emails');await loadEmails();
  if(document.querySelector('#mailLinkSearch')!==input||input.value!=='UNSAVED LINK FILTER'||!input.closest('details').open)throw Error('Email draft changed across navigation');
  if(emailDetails.size>1||document.querySelector('#emailDetail .mail-body').textContent.length<80000)throw Error('Email body caching regression');
  nav('insights');await renderFlow();const svg=document.querySelector('#applicationFlow svg');svg.style.minWidth='0px';document.querySelector('.sankey-method').open=true;
  nav('applications');nav('insights');await renderFlow();
  if(document.querySelector('#applicationFlow svg').style.minWidth!=='0px'||!document.querySelector('.sankey-method').open)throw Error('Chart settings changed');
  nav('questions');if(document.querySelector('#qaSearch').value!=='Synthetic question 7'||!document.querySelector('#qaList').textContent.includes('Synthetic question 7'))throw Error('Question filter changed');
  if(document.querySelector('#resume').value!=='UNSAVED SYNTHETIC PROFILE')throw Error('Unsaved profile changed');
  nav('applications');return {emailDraft:true,fullBody:true,chartSettings:true,questionFilter:true,unsavedProfile:true};
 })()`);
 fs.writeFileSync(process.argv[2]||path.join(dir,'measurement.json'),JSON.stringify({startup,afterBrowsing,retained,checks},null,2));
 backend.kill();app.exit(0);
}).catch(error=>{console.error(error);backend?.kill();app.exit(1)});
setTimeout(()=>{console.error('Memory profile timed out');backend?.kill();app.exit(1)},60000).unref();
