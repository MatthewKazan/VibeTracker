const test=require('node:test'),assert=require('node:assert/strict');
const {pythonExecutable,safeExternal,backendEnvironment}=require('./runtime.cjs');
test('Windows uses bundled interpreter, never a system Python',()=>assert.equal(pythonExecutable('C:\\bundle','win32'),'C:\\bundle\\python.exe'));
test('Linux uses bundled interpreter',()=>assert.equal(pythonExecutable('/bundle','linux'),'/bundle/bin/python3'));
test('External links cannot launch arbitrary protocols',()=>{assert.equal(safeExternal('https://ollama.com'),true);for(const v of ['file:///etc/passwd','javascript:alert(1)','cmd:foo','http://example.com'])assert.equal(safeExternal(v),false);});
test('Backend gets a per-launch secret and persistent data directory',()=>{const env=backendEnvironment('/profile/data','secret');assert.equal(env.JOB_MANAGER_DATA,'/profile/data');assert.equal(env.JOB_MANAGER_TOKEN,'secret');assert.equal(env.PORT,'0');assert.equal(env.PYTHONUTF8,'1');});
test('Wipe only ever targets the app profile folder',()=>{
 const {wipeTarget}=require('./runtime.cjs');
 assert.equal(wipeTarget('/Users/a/Library/Application Support/Waypoint'),'/Users/a/Library/Application Support/Waypoint');
 for(const v of ['/','/Users/a','/Users/a/Library/Application Support','/Users/a/Documents/Waypoint2'])assert.equal(wipeTarget(v),null);
});
test('Desktop request header matches backend authentication contract',()=>{
 const fs=require('node:fs'),path=require('node:path');
 const main=fs.readFileSync(path.join(__dirname,'main.cjs'),'utf8');
 const backend=fs.readFileSync(path.join(__dirname,'../app.py'),'utf8');
 const sent=main.match(/'([^']+-Session)':secret/)[1];
 const required=[...backend.matchAll(/headers\.get\('([^']+-Session)'\)/g)].map(m=>m[1]);
 assert.equal(required.length,2);for(const name of required)assert.equal(sent,name);
});
