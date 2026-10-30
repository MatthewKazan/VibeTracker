const path = require('node:path');
function pythonExecutable(root, platform=process.platform){return platform==='win32'?path.win32.join(root,'python.exe'):path.posix.join(root,'bin/python3');}
function safeExternal(value){try{const u=new URL(value);return u.protocol==='https:';}catch{return false;}}
function backendEnvironment(data, token){return {...process.env,JOB_MANAGER_DATA:data,JOB_MANAGER_TOKEN:token,PORT:'0',PYTHONDONTWRITEBYTECODE:'1',PYTHONNOUSERSITE:'1',PYTHONUTF8:'1',PYTHONPYCACHEPREFIX:path.join(data,'cache')};}
// "Delete all data" removes a whole folder, so refuse anything that is not the app's own profile directory.
function wipeTarget(userData){return path.basename(userData)==='Waypoint'&&path.dirname(userData)!==userData?userData:null;}
// Fully drain each response before resolving; no pooled Undici parser survives backend shutdown.
function localRequest(value,{method='GET',headers={},body,timeout=10000}={}){
 return new Promise((resolve,reject)=>{
  const url=new URL(value);
  if(url.protocol!=='http:'||url.hostname!=='127.0.0.1'){reject(Error('Only the local backend is supported.'));return;}
  const req=require('node:http').request(url,{method,headers,agent:false},res=>{
   const chunks=[];let size=0;
   res.on('data',chunk=>{size+=chunk.length;if(size>100_000_000){res.destroy(Error('Local response exceeds 100 MB.'));return;}chunks.push(chunk);});
   res.on('error',reject);
   res.on('aborted',()=>reject(Error('The local engine closed an incomplete response.')));
   res.on('end',()=>{clearTimeout(timer);const text=Buffer.concat(chunks).toString('utf8');resolve({ok:res.statusCode>=200&&res.statusCode<300,status:res.statusCode,json:async()=>JSON.parse(text)});});
  });
  const timer=setTimeout(()=>req.destroy(Error('The local engine request timed out.')),timeout);
  req.on('error',reject);req.on('close',()=>clearTimeout(timer));
  req.end(body);
 });
}
module.exports={pythonExecutable,safeExternal,backendEnvironment,wipeTarget,localRequest};
