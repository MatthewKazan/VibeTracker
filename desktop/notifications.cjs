const groupEvents=events=>{
 const urgentMessages=new Set(events.filter(e=>e.kind.startsWith('status:')).map(e=>e.message_id));
 const urgent=events.filter(e=>urgentMessages.has(e.message_id)),normal=events.filter(e=>!urgentMessages.has(e.message_id));
 return [urgent.length?{urgent:true,events:urgent}:null,normal.length?{urgent:false,events:normal}:null].filter(Boolean);
};
function startNotifications({Notification,request,app,win,openEmail,interval=5000}){
 let busy=false,stopped=false,lastAttempt=0;
 const retained=new Set();
 async function poll(){
  if(busy||stopped)return;busy=true;
  try{
   const summary=await request('emails/summary');app.setBadgeCount?.(summary.notification_badge===false?0:summary.pending||0);
   const response=await request('emails/notifications'),events=response.events||[],presentation={sound:true,previews:true,attention:true,...response.presentation};
   if(!events.length||!Notification?.isSupported?.()||Date.now()-lastAttempt<30000)return;
   lastAttempt=Date.now();
   for(const group of groupEvents(events)){
    const unique=[...new Map(group.events.map(e=>[e.message_id,e])).values()],first=unique[0];
    const title=group.urgent?'Urgent: application status needs review':'JobTracker: new company email'+(unique.length>1?'s':'');
    const body=!presentation.previews?(group.urgent?'An application status needs your review. Open JobTracker.':unique.length+' new job-related email'+(unique.length===1?'':'s')+'. Open JobTracker.'):unique.length===1?(first.company||'Application correspondence')+' · '+first.subject:unique.length+' emails '+(group.urgent?'may change application statuses. Review in JobTracker.':'added to your email inbox.');
    const n=new Notification({title,body,urgency:group.urgent?'critical':'normal',timeoutType:group.urgent?'never':'default',silent:!presentation.sound});retained.add(n);
    n.once('show',()=>{request('emails/notifications/ack',{ids:group.events.map(e=>e.id)}).catch(()=>{});if(group.urgent&&presentation.attention){win.flashFrame?.(true);const bounce=app.dock?.bounce?.('critical');win.once?.('focus',()=>{win.flashFrame?.(false);if(bounce!==undefined)app.dock?.cancelBounce?.(bounce)});}});
    n.once('click',()=>{win.show();win.focus();openEmail(first.message_id)});
    n.once('close',()=>retained.delete(n));n.once('failed',()=>retained.delete(n));n.show();
   }
  }catch{}finally{busy=false}
 }
 const timer=setInterval(poll,interval);timer.unref?.();poll();
 return ()=>{stopped=true;clearInterval(timer);for(const n of retained)n.close?.();retained.clear()};
}
module.exports={startNotifications,groupEvents};
