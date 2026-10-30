const path = require('node:path');
function pythonExecutable(root, platform=process.platform){return path.join(root,platform==='win32'?'python.exe':'bin/python3');}
function safeExternal(value){try{const u=new URL(value);return u.protocol==='https:';}catch{return false;}}
function backendEnvironment(data, token){return {...process.env,JOB_MANAGER_DATA:data,JOB_MANAGER_TOKEN:token,PORT:'0',PYTHONDONTWRITEBYTECODE:'1',PYTHONNOUSERSITE:'1',PYTHONPYCACHEPREFIX:path.join(data,'cache')};}
// "Delete all data" removes a whole folder, so refuse anything that is not the app's own profile directory.
function wipeTarget(userData){return path.basename(userData)==='Waypoint'&&path.dirname(userData)!==userData?userData:null;}
module.exports={pythonExecutable,safeExternal,backendEnvironment,wipeTarget};
