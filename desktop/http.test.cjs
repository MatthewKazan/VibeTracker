const test=require('node:test'),assert=require('node:assert/strict'),http=require('node:http');
const {localRequest}=require('./runtime.cjs');
async function serve(t,handler){const server=http.createServer(handler);await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(()=>new Promise(r=>server.close(r)));return `http://127.0.0.1:${server.address().port}`;}
test('large backend response is fully consumed before immediate shutdown',async t=>{const data={text:'a'.repeat(1024*1024)};const url=await serve(t,(req,res)=>{assert.equal(req.headers['x-waypoint-session'],'secret');res.end(JSON.stringify(data));});for(let i=0;i<5;i++){const r=await localRequest(url,{headers:{'X-Waypoint-Session':'secret'}});assert(r.ok);assert.deepEqual(await r.json(),data);}});
test('partial backend response rejects without uncaught parser exception',async t=>{const url=await serve(t,(req,res)=>{res.writeHead(200,{'Content-Length':100000});res.write('{');setImmediate(()=>res.destroy());});await assert.rejects(localRequest(url),/incomplete|aborted|reset/i);});
test('stalled backend times out and closes its connection',async t=>{const url=await serve(t,()=>{});await assert.rejects(localRequest(url,{timeout:30}),/timed out/);});
test('backend transport refuses external destinations',async()=>{await assert.rejects(localRequest('https://example.com'),/local backend/);});
