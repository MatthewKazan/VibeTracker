let activityChanging=false,startupTimer,startupDeadline=0,startupScheduled=false;
function startupWaiting(){return Date.now()<startupDeadline}
window.startActivityAfterGrace=function(){
 if(startupScheduled)return;startupScheduled=true;
 startupDeadline=Date.now()+Math.max(0,state.activity?.startup_remaining??30)*1000;
 window.syncActivityUI();
 startupTimer=setTimeout(async()=>{window.syncActivityUI();if(!backgroundPaused())await discoverAI(true)},Math.max(0,startupDeadline-Date.now()));
};
window.syncActivityUI=function(){
 const paused=backgroundPaused(),button=$('#activityToggle');
 for(const id of ['extract','geocode','qaAISearch','startAI','connectAI','checkAI','analyzeFit','sendFitMessage','aiMapping']){
  const control=$('#'+id);if(!control)continue;
  if(paused){if(!control.hasAttribute('data-before-pause')){control.setAttribute('data-before-pause',String(control.disabled));control.setAttribute('data-before-pause-title',control.title||'')}control.disabled=true;control.title='Resume background activity to use this feature.'}
  else if(control.hasAttribute('data-before-pause')){control.disabled=control.getAttribute('data-before-pause')==='true';control.title=control.getAttribute('data-before-pause-title');control.removeAttribute('data-before-pause');control.removeAttribute('data-before-pause-title')}
 }

 button.disabled=activityChanging;button.setAttribute('aria-pressed',String(paused));button.setAttribute('aria-label',paused?'Resume background activity':'Pause background activity');
 button.title=paused?'Low-resource mode: resume background activity using your saved settings':'Pause AI, email sync, web lookups, notifications and polling; unload JobTracker’s model';
 button.innerHTML=paused?'<svg class="sidebar-icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" aria-hidden="true"><path d="m8 5 11 7-11 7Z"/></svg>':'<svg class="sidebar-icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M8 5v14M16 5v14"/></svg>';
 document.body.classList.toggle('low-resource',paused);$('#activityStatus').hidden=!paused&&!startupWaiting();$('#activityStatus').textContent=paused?'Low-resource mode · saved views available':startupWaiting()?'Background activity starts 30 seconds after launch. Pause here to prevent it.':'';
 if(paused){$('#aiSetupLabel').textContent='Local AI · paused';$('#queueStatus').textContent='';clearTimeout(appliedBoundaryTimer);if(map){mapPosition={center:map.getCenter(),zoom:map.getZoom()};map.remove();map=null;markers=null;$('#mapCanvas').textContent='Map tiles paused in low-resource mode.'}}
 if(!paused&&$('#aiSetupLabel').textContent==='Local AI · paused')$('#aiSetupLabel').textContent='Local AI';
 setQueuePolling(paused||startupWaiting()||!startupScheduled);if(typeof setEmailPolling==='function')setEmailPolling(paused||startupWaiting()||!startupScheduled);if(!paused)scheduleAppliedBoundary();
};
async function changeActivity(paused){
 if(activityChanging)return;activityChanging=true;
 // Stop renderer polling immediately while the backend cancels work and unloads.
 if(paused){state.settings.low_resource_mode=true;window.syncActivityUI();$('#activityStatus').textContent='Stopping background work and unloading the model…'}
 try{
  const result=window.jobtrackerActivity?await window.jobtrackerActivity.setPaused(paused):await api('activity',{paused});
  state.settings.low_resource_mode=result.paused;window.syncActivityUI();
  $('#activityRetry').hidden=!result.unload_error;
  if(result.unload_error)$('#activityStatus').textContent='Background work paused. Model unload needs retry: '+result.unload_error;
  if(!result.paused&&!startupWaiting()){if(state.settings.auto_start!==false)await discoverAI(true);else $('#aiSetupLabel').textContent='Local AI';}
  toast(result.paused?'Low-resource mode on. Saved data stays available.':'Background activity resumed using your saved settings.');
 }catch(e){try{const actual=await api('activity');state.settings.low_resource_mode=actual.paused}catch{}window.syncActivityUI();toast(e.message)}
 finally{activityChanging=false;$('#activityToggle').disabled=false;}
}
$('#activityToggle').onclick=()=>changeActivity(!backgroundPaused());
$('#activityRetry').onclick=()=>changeActivity(true);
window.syncActivityUI();
