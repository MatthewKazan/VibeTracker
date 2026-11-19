const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=name=>fs.readFileSync(require.resolve('../static/'+name),'utf8');
function assets(){const nodes=[],context={document:{createElement:tag=>({tag,remove(){this.removed=true}}),head:{append:node=>nodes.push(node)}}};vm.createContext(context);vm.runInContext(source('view-memory.js'),context);return {nodes,context}}
test('optional libraries are absent at startup and concurrent loads share one request',async()=>{
 const {nodes,context}=assets();assert.equal(nodes.length,0);
 const first=context.loadViewAsset('/optional.js'),second=context.loadViewAsset('/optional.js');assert.equal(first,second);assert.equal(nodes.length,1);nodes[0].onload();await first;
});
test('failed optional library loads can be retried',async()=>{
 const {nodes,context}=assets(),first=context.loadViewAsset('/optional.js');nodes[0].onerror();await assert.rejects(first,/retry/);assert(nodes[0].removed);
 const second=context.loadViewAsset('/optional.js');assert.equal(nodes.length,2);nodes[1].onload();await second;
});
test('chart dependencies load in order and map CSS precedes Leaflet',async()=>{
 const {nodes,context}=assets(),chart=context.ensureChartAssets();
 const expected=['/vendor/d3-array.min.js','/vendor/d3-path.min.js','/vendor/d3-shape.min.js','/vendor/d3-sankey.min.js','/sankey-data.js'];
 for(let i=0;i<expected.length;i++){assert.equal(nodes[i].src,expected[i]);nodes[i].onload();await new Promise(r=>setImmediate(r))}await chart;
 const map=context.ensureMapAssets();assert.equal(nodes[5].tag,'link');assert.equal(nodes[5].href,'/vendor/leaflet.css');nodes[5].onload();await new Promise(r=>setImmediate(r));assert.equal(nodes[6].src,'/vendor/leaflet.js');nodes[6].onload();await map;
});
test('email comparison catches changed bodies, review tokens and nested application links',()=>{
 const {context}=assets(),a={body:'large text',review_token:'first',links:[{id:1}]};assert(context.sameViewData(a,JSON.parse(JSON.stringify(a))));
 for(const b of [{...a,body:'changed'},{...a,review_token:'second'},{...a,links:[{id:2}]},{...a,extra:true}])assert(!context.sameViewData(a,b));
 assert(!context.sameViewData([],{}));
});
test('releasing hidden insights frees derived DOM and preserves chart display and scroll state',()=>{
 const cleared=[],context={activeView:'insights',viewScroll:new Map(),flowRenderRequest:0,flowDisplay:{},document:{scrollingElement:{scrollTop:570}},$:id=>({replaceChildren:()=>cleared.push(id),querySelector:selector=>selector==='svg'?{style:{minWidth:'0px'}}:selector==='.sankey-method'?{open:true}:{scrollLeft:75}})};
 vm.createContext(context);vm.runInContext(source('app.js').slice(source('app.js').indexOf('function restoreViewScroll(')),context);
 context.releaseHiddenView('applications');assert.equal(context.activeView,'applications');assert.equal(context.viewScroll.get('insights'),570);assert.equal(context.flowDisplay.minWidth,'0px');assert(context.flowDisplay.methodOpen);assert.equal(context.flowDisplay.scrollLeft,75);assert(cleared.includes('#applicationFlow'));assert(!cleared.includes('#resume'));
 context.restoreViewScroll('applications');context.document.scrollingElement.scrollTop=45;context.restoreViewScroll('applications');assert.equal(context.document.scrollingElement.scrollTop,45);context.releaseHiddenView('insights');context.restoreViewScroll('insights');assert.equal(context.document.scrollingElement.scrollTop,570);
});
test('clean email views release bodies while unsaved human review controls remain intact',()=>{
 const cache=new Map([['one',{body:'large body'}]]),host={},drafts=new WeakSet(),cleared=[],context={emailFetchRequest:0,emailState:{messages:[{}]},emailDetails:cache,emailRenderRecords:new WeakMap([[host,{}]]),emailDraftHosts:drafts,$:id=>id==='#emailDetail'?host:{replaceChildren:()=>cleared.push(id)}};
 host.replaceChildren=()=>cleared.push('detail');host.removeAttribute=()=>{};context.window=context;vm.createContext(context);vm.runInContext(source('emails.js').slice(source('emails.js').indexOf('window.releaseEmailView=function')),context);
 drafts.add(host);context.releaseEmailView();assert.equal(cache.size,1);assert(!cleared.includes('detail'));assert.equal(context.emailState.messages.length,0);
 drafts.delete(host);context.releaseEmailView();assert.equal(cache.size,0);assert(cleared.includes('detail'));assert(!context.emailRenderRecords.has(host));
});
test('a late email fetch cannot retain a full body after leaving the email view',async()=>{
 let finish;const cache=new Map(),context={emailSelected:'one',emailDetails:cache,api:()=>new Promise(r=>finish=r),$:()=>({hidden:true})};
 vm.createContext(context);const text=source('emails.js');vm.runInContext(text.slice(text.indexOf('async function ensureEmailBody('),text.indexOf('function emailJobs(')),context);
 const request=context.ensureEmailBody();finish({body:'large body'});await request;assert.equal(cache.size,0);
});

test('leaving a map removes its instance and keeps only the viewport for restoring',()=>{
 const cleared=[];let removed=0;const context={activeView:'map',viewScroll:new Map(),mapRenderRequest:0,mapPosition:null,map:{getCenter:()=>({lat:42,lon:-71}),getZoom:()=>8,remove:()=>removed++},markers:{},document:{scrollingElement:{scrollTop:150}},$:id=>({replaceChildren:()=>cleared.push(id)})};
 vm.createContext(context);const text=source('app.js');vm.runInContext(text.slice(text.indexOf('function restoreViewScroll(')),context);context.releaseHiddenView('applications');
 assert.equal(removed,1);assert.equal(context.map,null);assert.equal(context.markers,null);assert.equal(context.mapPosition.zoom,8);assert.deepEqual(cleared,['#mapCanvas','#mapList']);assert.equal(context.mapRenderRequest,1);
});
test('missing section scripts recover without duplicating initialized sections',async()=>{
 for(const [view,fn,file] of [['interviewPrep','loadPrep','interview-prep'],['questions','renderQuestions','questions'],['emails','loadEmails','emails']]){
  const {nodes,context}=assets();const failed=context.ensureSectionScript(view);nodes[0].onerror();await assert.rejects(failed,/retry/);
  const retry=context.ensureSectionScript(view);assert.equal(nodes[1].src,'/'+file+'.js');context[fn]=()=>{};nodes[1].onload();await retry;
  await context.ensureSectionScript(view);assert.equal(nodes.length,2);
 }
});
