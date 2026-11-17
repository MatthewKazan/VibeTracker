const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function fixture(paused=false){
 const elements=new Map(),timers=[],polls=[],calls=[];let now=1000;
 const $=id=>{if(!elements.has(id))elements.set(id,{hidden:false,value:'unsaved text',attributes:new Map(),setAttribute(k,v){this.attributes.set(k,v)},hasAttribute(k){return this.attributes.has(k)},getAttribute(k){return this.attributes.get(k)},removeAttribute(k){this.attributes.delete(k)}});return elements.get(id)};
 const context={$,state:{settings:{low_resource_mode:paused,auto_start:true},activity:{startup_remaining:30}},Date:{now:()=>now},setTimeout:(fn,delay)=>{const timer={fn,delay};timers.push(timer);return timer},clearTimeout(){},appliedBoundaryTimer:null,map:null,markers:null,document:{body:{classList:{toggle(){}}}},setQueuePolling:p=>polls.push(['queue',p]),setEmailPolling:p=>polls.push(['email',p]),scheduleAppliedBoundary(){},toast(){},discoverAI:async()=>calls.push('AI'),api:async(route,body)=>{calls.push([route,body]);return {paused:body.paused}},backgroundPaused:()=>context.state.settings.low_resource_mode===true};
 context.window=context;vm.createContext(context);vm.runInContext(fs.readFileSync(require.resolve('../static/low-resource.js'),'utf8'),context);
 return {context,$,timers,polls,calls,advance:n=>now+=n};
}
test('startup grace prevents automatic AI and polling; pausing during it preserves unsaved fields',async()=>{
 const f=fixture();f.context.startActivityAfterGrace();assert.equal(f.timers[0].delay,30000);assert(!f.calls.length);assert(f.polls.every(([,p])=>p));
 await f.$('#activityToggle').onclick();assert.equal(f.context.state.settings.low_resource_mode,true);assert.equal(f.$('#resume').value,'unsaved text');
 f.advance(30000);await f.timers[0].fn();assert(!f.calls.includes('AI'));assert(f.polls.every(([,p])=>p));
 await f.$('#activityToggle').onclick();assert.equal(f.context.state.settings.auto_start,true);assert(f.calls.includes('AI'));assert.equal(f.context.state.settings.low_resource_mode,false);assert(f.polls.some(([,p])=>!p));
});
test('startup starts background activity only when grace expires',async()=>{
 const f=fixture();f.context.startActivityAfterGrace();f.advance(30000);await f.timers[0].fn();assert.equal(f.calls.filter(c=>c==='AI').length,1);assert(f.polls.some(([,p])=>!p));
});
test('a persisted pause survives startup grace and never starts AI',async()=>{
 const f=fixture(true);f.context.startActivityAfterGrace();f.advance(30000);await f.timers[0].fn();assert.equal(f.calls.length,0);assert(f.polls.every(([,p])=>p));assert.match(f.$('#activityStatus').textContent,/Low-resource/);
});
