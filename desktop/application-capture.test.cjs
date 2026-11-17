const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require.resolve('../static/app.js'),'utf8');
function harness(){
 const nodes=new Map(),calls=[];const $=id=>{if(!nodes.has(id))nodes.set(id,{hidden:true,textContent:'',innerHTML:'',open:true,setAttribute(k,v){this[k]=v}});return nodes.get(id)};
 $('#jobForm').elements=Object.fromEntries(['url','title','company','location','description','fit','date_applied'].map(k=>[k,{value:''}]));$('#paste').value='';
 const context={$,draftRequest:0,editing:null,backgroundPaused:()=>false,esc:String,api:(route,body)=>new Promise((resolve,reject)=>calls.push({route,body,resolve,reject})),renderAnalysis:a=>{$('#draftAnalysis').innerHTML=a.summary}};
 vm.createContext(context);vm.runInContext(source.slice(source.indexOf('async function extract(){'),source.indexOf("$('#jobForm').onsubmit")),context);
 return {context,$,calls};
}
const tick=()=>new Promise(r=>setImmediate(r));
test('Autofill immediately announces analysis and shows keywords before model completion',async()=>{
 const {context,$,calls}=harness(),pending=context.extract();assert.equal($('#draftReview').hidden,false);assert.match($('#draftStatus').textContent,/Starting analysis/);
 calls[0].resolve({description:'Python and SQL',source:'Posting'});await tick();assert.equal(calls[1].route,'fit/draft');assert.equal(calls[1].body.description,'Python and SQL');
 calls[1].resolve({can_analyze:true,matched:['Python'],missing:[],message:'Keyword comparison'});await tick();assert.match($('#draftKeywords').innerHTML,/Python/);assert.equal(calls[2].body.analyze,true);
 calls[2].resolve({analysis:{summary:'Review ready',score:75}});await pending;assert.equal($('#jobForm').elements.fit.value,75);assert.equal($('#draftReview')['aria-busy'],'false');
});
test('closing or replacing a draft ignores late extraction results',async()=>{
 const {context,$,calls}=harness(),pending=context.extract();context.draftRequest++;calls[0].resolve({title:'Old draft',description:'Old posting'});await pending;
 assert.equal($('#jobForm').elements.title.value,'');assert.equal(calls.length,1);
});
test('missing résumé skips AI and model failure retains keywords and form fields',async()=>{
 for(const can_analyze of [false,true]){const {context,$,calls}=harness(),pending=context.extract();calls[0].resolve({title:'Engineer',description:'SQL',source:'Posting'});await tick();calls[1].resolve({can_analyze,matched:[],missing:[{term:'SQL',job_evidence:'SQL',advice:'Only if true'}],message:'Add résumé'});await tick();if(can_analyze)calls[2].reject(Error('Model unavailable'));await pending;assert.equal(calls.length,can_analyze?3:2);assert.equal($('#jobForm').elements.title.value,'Engineer');assert.match($('#draftKeywords').innerHTML,/SQL/);assert.equal($('#extract').disabled,false);}
});
test('changed description cannot receive a stale model score',async()=>{
 const {context,$,calls}=harness(),pending=context.extract();calls[0].resolve({description:'SQL',source:'Posting'});await tick();calls[1].resolve({can_analyze:true,matched:[],missing:[],message:''});await tick();$('#jobForm').elements.description.value='Python';calls[2].resolve({analysis:{score:99}});await pending;assert.notEqual($('#jobForm').elements.fit.value,99);assert.match($('#draftStatus').textContent,/description changed/);
});
