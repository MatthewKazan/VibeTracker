const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
async function run(policy,answer,fail=false){
 const handlers={},calls=[],dialogs=[];let quits=0;
 const app={setPath(){},getPath(){return '/tmp'},requestSingleInstanceLock(){return true},on(n,f){handlers[n]=f},whenReady(){return {then(){return {catch(){}}}}},quit(){quits++}};
 const context={require:n=>n==='electron'?{app,dialog:{async showMessageBox(_win,options){dialogs.push(options);return answer}},BrowserWindow(){},Menu:{},shell:{},session:{}}:n==='./runtime.cjs'?require('./runtime.cjs'):require(n),__dirname:__dirname,process:{platform:'darwin',env:{}},setTimeout,clearTimeout,AbortSignal,URL,fetch:async(url,options)=>{const route=url.split('/api/')[1];calls.push([route,options.body&&JSON.parse(options.body)]);if(route==='ai/unload'&&fail)throw Error('Ollama unavailable');return {ok:true,json:async()=>route==='state'?{token:'token',settings:{model:'local:test',quit_model_policy:policy}}:{ok:true}}}};
 vm.createContext(context);vm.runInContext(fs.readFileSync(__dirname+'/main.cjs','utf8'),context);vm.runInContext("origin='http://127.0.0.1:1';secret='secret';server={exitCode:null};",context);
 let prevented=false;handlers['before-quit']({preventDefault(){prevented=true}});
 for(let i=0;i<8;i++)await new Promise(r=>setImmediate(r));
 return {calls,dialogs,quits,prevented};
}
test('quit asks and persists unload preference before unloading selected model',async()=>{const r=await run('ask',{response:0,checkboxChecked:true});assert(r.prevented);assert.equal(r.quits,1);assert(r.calls.some(([n,b])=>n==='settings'&&b.quit_model_policy==='unload'));assert(r.calls.some(([n])=>n==='ai/unload'));});
test('cancel does not quit or unload',async()=>{const r=await run('ask',{response:2});assert.equal(r.quits,0);assert(!r.calls.some(([n])=>n==='ai/unload'));});
test('remembered keep preference skips prompt and unload',async()=>{const r=await run('keep',{});assert.equal(r.quits,1);assert.equal(r.dialogs.length,0);assert(!r.calls.some(([n])=>n==='ai/unload'));});
test('unload failure offers cancel and leaves app open',async()=>{const r=await run('unload',{response:1},true);assert.equal(r.quits,0);assert.equal(r.dialogs[0].title,'Could not finish model cleanup');});
