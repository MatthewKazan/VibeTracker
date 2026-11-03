const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require.resolve('../mail_reader.js'),'utf8');
function fixture(){
 const touched=[];
 const account=id=>({id:()=>id,name:()=>id, emailAddresses:()=>[id+'@example.test'],mailboxes:()=>{touched.push(id);return [{name:()=> 'Inbox',mailboxes:()=>[],messages:{whose:()=>()=>[{messageId:()=>id+'-message',content:()=>id+' body',sender:()=> 'Recruiter',subject:()=> 'Job application',dateReceived:()=>new Date('2026-11-02T12:00:00Z')}]}}]}});
 const context={Application:()=>({accounts:()=>[account('jobs'),account('personal')]})};vm.createContext(context);vm.runInContext(source,context);return {context,touched};
}
test('Mail reader reads folders only for the explicitly selected account',()=>{
 const {context,touched}=fixture();const messages=JSON.parse(context.run(['2026-11-01','2026-11-03','jobs']));
 assert.deepEqual(touched,['jobs']);assert.equal(messages[0].message_id,'jobs-message');
});
test('account discovery returns names and addresses without opening mailboxes',()=>{
 const {context,touched}=fixture();const accounts=JSON.parse(context.run(['accounts']));
 assert.equal(accounts.length,2);assert.deepEqual(accounts[0].addresses,['jobs@example.test']);assert.deepEqual(touched,[]);
});
test('missing or removed account never falls back to all accounts',()=>{
 for(const id of [undefined,'removed']){const {context,touched}=fixture();assert.throws(()=>context.run(['2026-11-01','2026-11-03',id]),/account/);assert.deepEqual(touched,[])}
});
test('selected account includes Spam and Junk while excluding Trash and Drafts',()=>{
 const touched=[];
 const box=name=>({name:()=>name,mailboxes:()=>[],messages:{whose:()=>{touched.push(name);return ()=>[{messageId:()=>name+'-message',content:()=> 'Job application',sender:()=> 'Recruiter',subject:()=> 'Application update',dateReceived:()=>new Date('2026-11-02T12:00:00Z')}]}}});
 const context={Application:()=>({accounts:()=>[{id:()=> 'jobs',mailboxes:()=>['Inbox','Spam','Junk','Trash','Drafts','Deleted Messages'].map(box)}]})};
 vm.createContext(context);vm.runInContext(source,context);
 const messages=JSON.parse(context.run(['2026-11-01','2026-11-03','jobs']));
 assert.deepEqual(touched,['Inbox','Spam','Junk']);assert.equal(messages.length,3);
});
test('company mention in a non-recruiting body is collected while unrelated mail is excluded',()=>{
 let bodyReads=0;
 const message=(id,body)=>({messageId:()=>id,content:()=>{bodyReads++;return body},sender:()=> 'News',subject:()=> 'Weekly update',dateReceived:()=>new Date('2026-11-02T12:00:00Z')});
 const context={Application:()=>({accounts:()=>[{id:()=> 'jobs',mailboxes:()=>[{name:()=> 'Inbox',mailboxes:()=>[],messages:{whose:()=>()=>[message('company','New research from Acme Robotics.'),message('personal','Dinner on Friday?')]}}]}]})};
 vm.createContext(context);vm.runInContext(source,context);const result=JSON.parse(context.run(['2026-11-01','2026-11-03','jobs',JSON.stringify([{terms:['Acme Robotics'],domains:[]}])]));assert.deepEqual(result.map(m=>m.message_id),['company']);assert.equal(bodyReads,2);
});
test('date bounds only read metadata for the selected account',()=>{
 let bodies=0;const context={Application:()=>({accounts:()=>[{id:()=> 'jobs',mailboxes:()=>[{name:()=> 'Inbox',mailboxes:()=>[],messages:{dateReceived:()=>[new Date('2020-01-01'),new Date('2026-01-01')],content:()=>{bodies++}}}]}]})};
 vm.createContext(context);vm.runInContext(source,context);assert.equal(JSON.parse(context.run(['bounds','','jobs'])).oldest,'2020-01-01T00:00:00.000Z');assert.equal(bodies,0);
});
function batchFixture(count=40){
 let clock=0,reads=0,metadata=0;
 const records=Array.from({length:count},(_,i)=>({id:'id-'+i,body:i%2?'Dinner plans':'New work at Acme Robotics.'}));
 const wrap=m=>({messageId:()=>m.id,content:()=>{reads++;return m.body},sender:()=> 'Sender',subject:()=> 'Update',dateReceived:()=>new Date('2026-11-02T12:00:00Z')});
 const selection=()=>records.map(wrap);for(let i=0;i<count;i++)Object.defineProperty(selection,i,{get:()=>wrap(records[i])});selection.messageId=()=>{metadata++;return records.map(m=>m.id)};selection.id=()=>records.map(m=>m.id);
 class Clock extends Date {static now(){return clock}}
 const context={Date:Clock,delay:seconds=>clock+=seconds*1000,Application:()=>({accounts:()=>[{id:()=> 'jobs',mailboxes:()=>[{name:()=> 'Inbox',mailboxes:()=>[],messages:{whose:()=>selection,byId:id=>wrap(records.find(m=>m.id===id))}}]}]})};
 vm.createContext(context);vm.runInContext(source,context);
 return {records,read:options=>{clock=0;return JSON.parse(context.run(['2026-11-01','2026-11-03','jobs',JSON.stringify([{terms:['Acme Robotics']}]),JSON.stringify(options)]))},counts:()=>({reads,metadata})};
}
test('a large inbox is resumable with no more than eight bodies per page, including unrelated mail',()=>{
 const fixture=batchFixture(300),seen=[],folders=[];let complete=false,total=0,pages=0;
 while(!complete&&pages++<100){const page=fixture.read({seen,folders,maxBodies:8});assert(page.scanned.length<=8);seen.push(...page.scanned.map(m=>m.message_id));folders.push(...page.folders);total+=page.messages.length;complete=page.complete}
 assert(complete);assert.equal(total,150);assert.equal(seen.length,300);assert.equal(fixture.counts().reads,300);assert(pages>30);
});
test('previously scanned unrelated bodies are skipped and folder completion survives another invocation',()=>{
 const f=batchFixture(3),page=f.read({});assert(page.complete);const next=f.read({seen:page.scanned.map(m=>m.message_id),folders:page.folders});assert(next.complete);assert.equal(next.scanned.length,0);assert.equal(f.counts().reads,3);assert.equal(f.counts().metadata,1);
});
test('deletion and reordering between pages cannot skip unseen messages',()=>{
 const f=batchFixture(20),page=f.read({maxBodies:8}),seen=page.scanned.map(m=>m.message_id);f.records.splice(0,2);f.records.reverse();
 const second=f.read({seen,maxBodies:8});seen.push(...second.scanned.map(m=>m.message_id));const third=f.read({seen,maxBodies:8});seen.push(...third.scanned.map(m=>m.message_id));assert(third.complete);assert.equal(new Set(seen).size,20);assert.equal(f.counts().reads,20);
});
test('wall-clock budget ends a page before its body limit without losing progress',()=>{
 const f=batchFixture(20),page=f.read({budgetMs:200,maxBodies:8});assert.equal(page.complete,false);assert.equal(page.scanned.length,2);const next=f.read({seen:page.scanned.map(m=>m.message_id),budgetMs:200,maxBodies:8});assert.equal(next.scanned[0].message_id,'id-2');
});
test('Mail in the foreground defers before touching any mailbox or body',()=>{
 let touched=0;const context={Application:()=>({frontmost:()=>true,accounts:()=>[{id:()=> 'jobs',mailboxes:()=>{touched++;return []}}]})};vm.createContext(context);vm.runInContext(source,context);
 const page=JSON.parse(context.run(['2026-11-01','2026-11-03','jobs','[]','{}']));assert.equal(page.deferred,true);assert.equal(touched,0);
 const bounds=JSON.parse(context.run(['bounds','','jobs','','{}']));assert.equal(bounds.deferred,true);assert.equal(touched,0);
});
test('switching to Mail mid-batch stops further body reads',()=>{
 let reads=0;const selection=()=>[0,1,2].map(i=>({messageId:()=>''+i,content:()=>{reads++;return 'Application'},sender:()=> 'Acme',subject:()=> 'Update',dateReceived:()=>new Date('2026-11-02T12:00:00Z')}));
 const context={Application:()=>({frontmost:()=>reads>0,accounts:()=>[{id:()=> 'jobs',mailboxes:()=>[{name:()=> 'Inbox',mailboxes:()=>[],messages:{whose:()=>selection}}]}]})};vm.createContext(context);vm.runInContext(source,context);
 const page=JSON.parse(context.run(['2026-11-01','2026-11-03','jobs','[]','{}']));assert.equal(page.deferred,true);assert.equal(reads,1);assert.equal(page.complete,false);
});
