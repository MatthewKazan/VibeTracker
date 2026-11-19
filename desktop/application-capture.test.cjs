const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require.resolve('../static/app.js'),'utf8');
function harness(){
 const nodes=new Map(),calls=[];const $=id=>{if(!nodes.has(id))nodes.set(id,{hidden:true,textContent:'',innerHTML:'',open:true,setAttribute(k,v){this[k]=v},removeAttribute(k){delete this[k]}});return nodes.get(id)};
 $('#jobForm').elements=Object.fromEntries(['url','title','company','location','description','fit','date_applied'].map(k=>[k,{value:''}]));$('#paste').value='';
 const context={window:{},crypto:{randomUUID:()=>"test-progress-id"},setTimeout,clearTimeout,$,draftRequest:0,editing:null,backgroundPaused:()=>false,esc:String,api:(route,body)=>new Promise((resolve,reject)=>calls.push({route,body,resolve,reject})),renderAnalysis:a=>{$('#draftAnalysis').innerHTML=a.summary}};
 vm.createContext(context);vm.runInContext(source.slice(source.indexOf('async function extract(){'),source.indexOf("$('#jobForm').onsubmit")),context);
 return {context,$,calls};
}
const tick=()=>new Promise(r=>setImmediate(r));
test('Autofill immediately announces analysis and shows keywords before model completion',async()=>{
 const {context,$,calls}=harness(),pending=context.extract();assert.equal($('#draftReview').hidden,false);assert.match($('#draftStatus').textContent,/Starting analysis/);
 calls[0].resolve({description:'Python and SQL',source:'Posting'});await tick();assert.equal(calls[1].route,'fit/draft');assert.equal(calls[1].body.description,'Python and SQL');
 calls[1].resolve({can_analyze:true,matched:['Python'],missing:[],message:'Keyword comparison'});await tick();assert.match($('#draftKeywords').innerHTML,/Python/);assert.equal(calls[2].body.analyze,true);
 calls[2].resolve({analysis:{summary:'Review ready',score:75}});await tick();await pending;assert.equal($('#jobForm').elements.fit.value,75);assert.equal($('#draftReview')['aria-busy'],'false');
});
test('closing or replacing a draft ignores late extraction results',async()=>{
 const {context,$,calls}=harness(),pending=context.extract();context.draftRequest++;calls[0].resolve({title:'Old draft',description:'Old posting'});await pending;
 assert.equal($('#jobForm').elements.title.value,'');assert.equal(calls.length,1);
});
test('missing résumé skips AI and model failure retains keywords and form fields',async()=>{
 for(const can_analyze of [false,true]){const {context,$,calls}=harness(),pending=context.extract();calls[0].resolve({title:'Engineer',description:'SQL',source:'Posting'});await tick();calls[1].resolve({can_analyze,matched:[],missing:[{term:'SQL',job_evidence:'SQL',advice:'Only if true'}],message:'Add résumé'});await tick();if(can_analyze)calls[2].reject(Error('Model unavailable'));await tick();await pending;assert.equal(calls.length,can_analyze?3:2);assert.equal($('#jobForm').elements.title.value,'Engineer');assert.match($('#draftKeywords').innerHTML,/SQL/);assert.equal($('#extract').disabled,false);}
});
test('changed description cannot receive a stale model score',async()=>{
 const {context,$,calls}=harness(),pending=context.extract();calls[0].resolve({description:'SQL',source:'Posting'});await tick();calls[1].resolve({can_analyze:true,matched:[],missing:[],message:''});await tick();$('#jobForm').elements.description.value='Python';calls[2].resolve({analysis:{score:99}});await tick();await pending;assert.notEqual($('#jobForm').elements.fit.value,99);assert.match($('#draftStatus').textContent,/description changed/);
});

test('Autofill returns and allows another click while both keyword and AI suggestions remain pending',async()=>{
 const {context,$,calls}=harness();let finished=false;
 const pending=context.extract().then(()=>finished=true);
 calls[0].resolve({title:'Engineer',description:'SQL',source:'Posting'});await tick();
 assert.equal(finished,true);assert.equal($('#extract').disabled,false);assert.equal($('#extract').textContent,'Autofill ↗');assert.equal($('#draftSuggestions').open,false);assert.match($('#draftStatus').textContent,/save now/);
 calls[1].resolve({can_analyze:true,matched:[],missing:[],message:''});await tick();
 assert.equal($('#extract').disabled,false);assert.equal($('#draftSuggestions').open,false);
 // Saving/closing invalidates the draft; the ongoing review must not change the next form.
 context.draftRequest++;$('#jobDialog').open=false;calls[2].resolve({analysis:{score:99}});await tick();assert.equal($('#jobForm').elements.fit.value,'');await pending;
});

test('review progress uses actual completed requirements and remains indeterminate before extraction',()=>{
 const {context,$}=harness();context.renderDraftProgress({stage:'extracting'});assert.equal($('#draftProgress').value,undefined);assert.match($('#draftWork').textContent,/Finding requirements/);
 context.renderDraftProgress({stage:'reviewing',completed:6,total:18,requirement:'Python'});assert.equal($('#draftProgress').max,18);assert.equal($('#draftProgress').value,6);assert.match($('#draftWork').textContent,/6 of 18.*33%.*Python/);
});
test('low-resource mode allows Autofill and keyword comparison without starting AI',async()=>{
 const {context,$,calls}=harness();context.backgroundPaused=()=>true;const pending=context.extract();calls[0].resolve({title:'Engineer',description:'Python',source:'Posting'});await pending;
 assert.equal($('#extract').disabled,false);calls[1].resolve({can_analyze:true,matched:['Python'],missing:[],message:''});await tick();assert.equal(calls.length,2);assert.match($('#draftStatus').textContent,/AI is paused/);
});
