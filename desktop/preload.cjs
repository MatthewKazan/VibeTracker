const {contextBridge,ipcRenderer}=require('electron');
const invoke=(channel,...args)=>ipcRenderer.invoke(channel,...args).catch(error=>{throw Error(String(error.message||'Mail connection failed.').replace(/^Error invoking remote method '[^']+': (?:Error: )?/,''))});
contextBridge.exposeInMainWorld('jobtrackerMail',Object.freeze({
 status:()=>invoke('mail:status'),
 connect:config=>invoke('mail:connect',config),
 cancel:()=>invoke('mail:cancel'),
 disconnect:id=>invoke('mail:disconnect',id)
}));
