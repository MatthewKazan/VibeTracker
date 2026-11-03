const test=require('node:test'),assert=require('node:assert/strict'),{EventEmitter}=require('node:events');
const {groupEvents,startNotifications}=require('./notifications.cjs');
test('status events are urgent and coalesce the same email added event',()=>{
 const grouped=groupEvents([{id:1,message_id:'a',kind:'added'},{id:2,message_id:'a',kind:'status:interview'},{id:3,message_id:'b',kind:'added'}]);
 assert.equal(grouped.length,2);assert.equal(grouped[0].urgent,true);assert.deepEqual(grouped[0].events.map(e=>e.id),[1,2]);assert.equal(grouped[1].urgent,false);
});
test('desktop notifications acknowledge only after display and open the review on click',async()=>{
 const shown=[],calls=[],opened=[];let badge;
 class Notification extends EventEmitter {static isSupported(){return true}constructor(options){super();this.options=options;shown.push(this)}show(){this.emit('show')}close(){}}
 const stop=startNotifications({Notification,request:async(route,body)=>{calls.push([route,body]);return route==='emails/summary'?{pending:1}:route==='emails/notifications'?{events:[{id:9,message_id:'x',kind:'status:rejection',company:'Acme',subject:'Update'}]}:{}},app:{setBadgeCount:n=>badge=n},win:{show(){},focus(){},flashFrame(){},once(){}},openEmail:id=>opened.push(id),interval:999999});
 for(let i=0;i<4;i++)await new Promise(r=>setImmediate(r));
 assert.equal(badge,1);assert.equal(shown[0].options.urgency,'critical');assert(calls.some(([r,b])=>r==='emails/notifications/ack'&&b.ids[0]===9));shown[0].emit('click');assert.deepEqual(opened,['x']);stop();
});
