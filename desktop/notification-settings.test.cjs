const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
test('loading example phrases does not enable alerts, change modes, or save preferences',()=>{
 const elements=new Map(),calls=[];
 const $=selector=>{if(!elements.has(selector))elements.set(selector,{value:'',checked:false,disabled:false});return elements.get(selector)};
 $('#notifyEnabled').checked=false;$('#notifyMode').value='custom';$('#notifyAds').value='never';$('#notifyAdKeywords').value='My own phrase';
 const context={$,api:route=>{calls.push(route);return new Promise(()=>{})},state:{settings:{}},toast(){},loadActivity(){}};
 vm.createContext(context);vm.runInContext(fs.readFileSync(require.resolve('../static/notification-settings.js'),'utf8'),context);
 $('#notifyAdExample').onclick();
 assert.equal($('#notifyEnabled').checked,false);assert.equal($('#notifyMode').value,'custom');assert.equal($('#notifyAds').value,'never');
 assert.equal($('#notifyAdKeywords').value,'Boston Dynamics\nhumanoid');assert.equal($('#notifyAdKeywords').disabled,true);
 assert.equal(vm.runInContext('notificationFormDirty',context),true);assert.deepEqual(calls,['notification-preferences']);assert.equal(context.state.settings.notification_preferences,undefined);
 assert.match($('#notifyStatus').textContent,/loaded into this form/);
});
