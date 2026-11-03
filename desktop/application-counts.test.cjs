const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const tools=require('../static/table-tools.js');
test('rolling application counts include boundaries and exclude future/malformed dates',()=>{
 const jobs=['2026-11-02','2026-11-01','2026-10-27','2026-10-26','2026-10-04','2026-10-03','2026-11-03','bad','2026-02-30',null].map(date_applied=>({date_applied}));
 assert.deepEqual(tools.appliedCounts(jobs,new Date(2026,10,2,0,1)),{today:1,last7:3,last30:5});
 assert.deepEqual(tools.appliedCounts(jobs,new Date(2026,10,3,0,1)),{today:1,last7:3,last30:5});
});
test('leap day and year transitions use calendar windows',()=>{
 assert.deepEqual(tools.appliedCounts(['2024-02-29','2024-02-23','2024-02-22','2024-01-31','2024-01-30'].map(date_applied=>({date_applied})),new Date(2024,1,29)),{today:1,last7:2,last30:4});
 assert.deepEqual(tools.appliedCounts(['2026-01-01','2025-12-26','2025-12-03','2025-12-02'].map(date_applied=>({date_applied})),new Date(2026,0,1)),{today:1,last7:2,last30:3});
});
test('background option refresh preserves an open form status rather than selecting first option',()=>{
 const source=fs.readFileSync(require.resolve('../static/app.js'),'utf8'),fn=source.split('\n').find(line=>line.startsWith('function syncStatuses(){'));
 function select(value){return {value,items:[],set innerHTML(x){this.items=[];this.value=''},add(option){this.items.push(option);if(this.items.length===1)this.value=option.value}}}
 const fields={'#statusFilter':select('Rejected'),'#jobStatus':select('Rejected')};
 const context={$:key=>fields[key],state:{jobs:[{status:'Rejected'}],settings:{status_order:['Waiting','Rejected']}},statusDraftDirty:false,defaultStatusColors:{Waiting:'#aaa',Rejected:'#f00'},statusColor:()=> '#aaa',renderStatusColors:()=>{},Option:function(text,value){this.value=value}};
 vm.runInNewContext(fn+';syncStatuses()',context);assert.equal(fields['#jobStatus'].value,'Rejected');assert.equal(fields['#statusFilter'].value,'Rejected');
});
test('status draft colors and ordering survive unrelated email updates',()=>{
 const fn=fs.readFileSync(require.resolve('../static/app.js'),'utf8').split('\n').find(line=>line.startsWith('function syncStatuses(){'));
 function select(value){return {value,set innerHTML(x){this.value=''},add(option){if(!this.value)this.value=option.value}}}
 const fields={'#statusFilter':select(''),'#jobStatus':select('Rejected')},draft={Assessment:'#abcdef',Rejected:'#ff0000'};
 const context={$:key=>fields[key],state:{jobs:[],settings:{status_order:['Waiting','Rejected']}},statusDraftDirty:true,draftStatusColors:draft,defaultStatusColors:{Waiting:'#aaa',Rejected:'#f00'},statusColor:()=> '#aaa',renderStatusColors:()=>{throw Error('Must not redraw a dirty draft')},Option:function(text,value){this.value=value}};
 vm.runInNewContext(fn+';syncStatuses()',context);assert.equal(context.draftStatusColors,draft);assert.deepEqual(Object.keys(context.draftStatusColors),['Assessment','Rejected']);
});
