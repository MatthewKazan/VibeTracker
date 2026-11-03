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
