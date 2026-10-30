const {app,BrowserWindow,dialog,Menu,shell,session,screen}=require('electron');
const {spawn}=require('node:child_process');
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const {pythonExecutable,safeExternal,backendEnvironment,wipeTarget}=require('./runtime.cjs');
// Smoke mode (CI launch test) uses a throwaway profile so it never touches real data or collides with a running copy.
const smoke=process.env.WAYPOINT_SMOKE==='1';
app.setPath('userData',smoke?path.join(require('node:os').tmpdir(),'jobtracker-smoke-'+process.pid,'Waypoint'):path.join(app.getPath('appData'),'Waypoint'));
// GUI apps have no visible console on Windows, so smoke results go to a file.
function smokeResult(text){if(process.env.WAYPOINT_SMOKE_RESULT)fs.writeFileSync(process.env.WAYPOINT_SMOKE_RESULT,text);}
let server,win,origin,quitting=false,quitPending=false,wipeOnQuit=false,secret,logStream;
const gotLock=app.requestSingleInstanceLock();
if(!gotLock){app.quit();}else{
app.on('second-instance',()=>{if(win){if(win.isMinimized())win.restore();win.show();win.focus();}});
app.whenReady().then(start).catch(e=>{if(smoke){smokeResult('fail: '+e.message);if(server)server.kill();app.exit(1);return;}dialog.showErrorBox('JobTracker could not start',e.message+'\nYour saved data has not been removed.');app.quit();});
}
async function start(){
 const root=app.isPackaged?process.resourcesPath:path.resolve(__dirname,'..');
 const backend=app.isPackaged?path.join(root,'backend'):root;
 const runtime=app.isPackaged?path.join(root,'python'):path.join(root,'build/runtime');
 const data=path.join(app.getPath('userData'),'data');fs.mkdirSync(data,{recursive:true});
 logStream=fs.createWriteStream(path.join(data,'desktop.log'),{flags:'a'});
 secret=crypto.randomBytes(32).toString('hex');
 server=spawn(pythonExecutable(runtime),['-u','-B',path.join(backend,'app.py')],{cwd:backend,env:backendEnvironment(data,secret),stdio:['ignore','pipe','pipe'],windowsHide:true});
 server.stderr.on('data',d=>logStream.write(d));
 origin=await new Promise((resolve,reject)=>{
  let output='';const timer=setTimeout(()=>reject(Error('The local data engine did not start. Check '+path.join(data,'desktop.log'))),30000);
  server.once('error',e=>{clearTimeout(timer);reject(e);});
  server.once('exit',code=>{clearTimeout(timer);reject(Error('The data engine exited with code '+code));});
  server.stdout.on('data',d=>{logStream.write(d);output+=d;const match=output.match(/WAYPOINT_READY (http:\/\/127\.0\.0\.1:\d+)/);if(match){clearTimeout(timer);resolve(match[1]);}});
 });
 const health=await fetch(origin+'/api/state',{headers:{'X-Waypoint-Session':secret},signal:AbortSignal.timeout(10000)});
 if(!health.ok)throw Error('The app and data engine could not authenticate (HTTP '+health.status+'). Install the latest JobTracker build. Your data is unchanged.');
 session.defaultSession.setPermissionRequestHandler((_wc,permission,callback)=>callback(permission==='clipboard-sanitized-write'));
 session.defaultSession.webRequest.onBeforeSendHeaders({urls:[origin+'/*']},(details,callback)=>callback({requestHeaders:{...details.requestHeaders,'X-Waypoint-Session':secret}}));
 const bounds=savedBounds();
 const area=screen.getPrimaryDisplay().workArea,width=Math.min(1628,area.width),height=Math.min(869,area.height);
 win=new BrowserWindow({x:area.x+Math.round((area.width-width)/2),y:area.y+Math.round((area.height-height)/2),width,height,minWidth:640,minHeight:480,backgroundColor:'#171717',title:'JobTracker',icon:path.join(__dirname,'../build/icon.png'),show:false,webPreferences:{contextIsolation:true,nodeIntegration:false,sandbox:true,webSecurity:true}});
 win.webContents.setWindowOpenHandler(({url})=>{if(safeExternal(url))shell.openExternal(url);return {action:'deny'};});
 win.webContents.on('will-navigate',(event,url)=>{if(new URL(url).origin!==origin){event.preventDefault();if(safeExternal(url))shell.openExternal(url);}});
 win.webContents.on('will-attach-webview',e=>e.preventDefault());
 server.on('exit',code=>{if(!quitting){dialog.showErrorBox('JobTracker data engine stopped','Please restart JobTracker. Saved applications remain on disk. Exit code: '+code);app.quit();}});
 const template=[...(process.platform==='darwin'?[{role:'appMenu'}]:[]),{label:'File',submenu:[{label:'Open data folder',click:()=>shell.openPath(data)},{label:'Delete all JobTracker data…',click:wipeData},{type:'separator'},{role:'quit'}]},{role:'editMenu'},{label:'View',submenu:[{role:'reload'},{role:'resetZoom'},{role:'zoomIn'},{role:'zoomOut'},{role:'togglefullscreen'}]},{label:'Help',submenu:[{label:'About JobTracker',click:()=>dialog.showMessageBox(win,{type:'info',title:'JobTracker',message:'JobTracker '+app.getVersion(),detail:'Local job application management. Your data stays in your user profile. Local AI is optional.'})}]}];
 Menu.setApplicationMenu(Menu.buildFromTemplate(template));
 win.on('close',event=>{if(!quitting){event.preventDefault();app.quit();}});
 // Saved bounds are applied after creation: setBounds handles monitors with different scale factors more reliably than constructor options on Windows.
 if(bounds.width){const {maximized,...rect}=bounds;win.setBounds(rect);if(maximized)win.maximize();}
 let saveTimer;const writeBounds=()=>{clearTimeout(saveTimer);try{fs.writeFileSync(windowStateFile(),JSON.stringify({...win.getNormalBounds(),maximized:win.isMaximized()}));}catch{}};
 for(const e of ['resize','move','maximize','unmaximize'])win.on(e,()=>{clearTimeout(saveTimer);saveTimer=setTimeout(writeBounds,400);});
 win.on('close',writeBounds);
 await win.loadURL(origin);win.show();
 if(smoke){
  // Pass only if the backend answered and the interface actually rendered the application list.
  const rendered=await win.webContents.executeJavaScript("new Promise(r=>setTimeout(()=>r(!!document.querySelector('#navcount')&&document.querySelector('#rows')!==null),3000))");
  if(!rendered)throw Error('The interface did not render.');
  smokeResult('ok '+app.getVersion());setTimeout(()=>app.quit(),1000);
 }
}
app.on('window-all-closed',()=>app.quit());
// First launch opens centered at 1628x869, shrunk to fit smaller screens. Later launches reopen at the last size and position, as long as it is still on a connected display.
function windowStateFile(){return path.join(app.getPath('userData'),'window-state.json');}
function savedBounds(){
 try{const b=JSON.parse(fs.readFileSync(windowStateFile(),'utf8'));if(![b.x,b.y,b.width,b.height].every(Number.isFinite))return {};
  const area=screen.getDisplayMatching(b).workArea,visible=b.x<area.x+area.width-80&&b.x+b.width>area.x+80&&b.y>=area.y-10&&b.y<area.y+area.height-80;
  return visible?{x:b.x,y:b.y,width:Math.min(b.width,area.width),height:Math.min(b.height,area.height),maximized:!!b.maximized}:{};
 }catch{return {};}
}
async function wipeData(){
 const dir=wipeTarget(app.getPath('userData'));if(!dir)return;
 const answer=await dialog.showMessageBox(win,{type:'warning',title:'Delete all JobTracker data',message:'Permanently delete all JobTracker data?',detail:'This removes your applications, résumé, saved analyses and recovery snapshots from '+dir+'. It cannot be undone, so export a backup first if you may want it. JobTracker will close afterwards. Removing the app itself does not delete this data.',buttons:['Cancel','Delete everything & quit'],defaultId:0,cancelId:0});
 if(answer.response!==1)return;
 quitting=wipeOnQuit=true;
 if(server&&server.exitCode===null){server.kill();await new Promise(resolve=>server.once('exit',resolve));}
 app.quit();
}
app.on('quit',()=>{
 const dir=wipeOnQuit&&wipeTarget(app.getPath('userData'));if(!dir)return;
 try{fs.rmSync(path.join(dir,'data'),{recursive:true,force:true});}catch{}
 // Chromium can recreate cache files while shutting down (and Windows may still hold the log open), so finish from a detached process.
 spawn(process.execPath,['-e',`setTimeout(()=>require('fs').rmSync(${JSON.stringify(dir)},{recursive:true,force:true}),2000)`],{detached:true,stdio:'ignore',env:{...process.env,ELECTRON_RUN_AS_NODE:'1'}}).unref();
});
async function backendRequest(route,body){
 const headers={'X-Waypoint-Session':secret};
 if(body){const state=await backendRequest('state');headers['X-Token']=state.token;headers['Content-Type']='application/json';}
 const r=await fetch(origin+'/api/'+route,{method:body?'POST':'GET',headers,body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(35000)});
 const result=await r.json();if(!r.ok)throw Error(result.error||'The local engine did not respond.');return result;
}
app.on('before-quit',event=>{
 if(quitting){if(server&&!server.killed)server.kill();if(logStream)logStream.end();return;}
 event.preventDefault();if(quitPending)return;quitPending=true;
 (async()=>{
  try{
   if(origin&&server&&server.exitCode===null){
    const state=await backendRequest('state');let policy=state.settings.quit_model_policy||'ask';
    if(state.settings.model){
     if(policy==='ask'){
      const answer=await dialog.showMessageBox(win,{type:'question',title:'Quit JobTracker',message:'Unload your selected Ollama model?',detail:'Unload '+state.settings.model+' to release its memory. Ollama and other models keep running. Another app using this same model may need to reload it.',buttons:['Unload model & quit','Keep loaded & quit','Cancel'],defaultId:0,cancelId:2,checkboxLabel:'Remember my answer (change in Profile & data)',checkboxChecked:false});
      if(answer.response===2)return;
      policy=answer.response===0?'unload':'keep';
      if(answer.checkboxChecked)await backendRequest('settings',{quit_model_policy:policy});
     }
     if(policy==='unload')await backendRequest('ai/unload',{});
    }
   }
  }catch(e){const answer=await dialog.showMessageBox(win,{type:'warning',title:'Could not finish model cleanup',message:e.message,detail:'You can quit now and unload the model later with Ollama, or cancel and retry. Saved applications remain on disk.',buttons:['Quit anyway','Cancel'],defaultId:1,cancelId:1});if(answer.response===1)return;}
  quitting=true;app.quit();
 })().finally(()=>{quitPending=false;});
});
