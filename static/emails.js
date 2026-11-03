/* Application correspondence, review queue, and durable email catch-up. */
let emailState={messages:[],sync:{},worker:{}},emailSelected=null,emailBusy=false,emailDetailKey='',mailAccounts=[],mailSettingsInitialized=false,emailFetchRequest=0,emailVisibleLimit=200;
const emailBodies=new Map();
function emailQuery(offset=0,extra={}){return new URLSearchParams({query:$('#mailSearch').value,type:$('#mailType').value,pending:$('#mailPending').checked?'1':'0',exclude_confirmations:$('#mailExcludeConfirmations').checked?'1':'0',show_ignored:$('#mailShowIgnored').checked?'1':'0',from:$('#mailFrom').value,to:$('#mailTo').value,sort:$('#mailSort').value,limit:'200',offset:String(offset),...extra})}
let emailNextOffset=0;
const emailDetails=new Map();
async function loadEmails(append=false){
 const request=++emailFetchRequest,target=append?200:emailVisibleLimit;let offset=append?emailNextOffset:0,received=[],fresh;
 try{
  do{fresh=await api('emails?'+emailQuery(offset));if(request!==emailFetchRequest)return;received.push(...fresh.messages);offset+=fresh.messages.length;}while(fresh.has_more&&received.length<target);
  emailNextOffset=offset;emailVisibleLimit=append?emailVisibleLimit+received.length:Math.max(200,received.length);
  emailState={...fresh,messages:append?[...emailState.messages,...received]:received};
  await ensureEmailBody();if(request!==emailFetchRequest)return;renderEmails();
 }catch(e){toast(e.message)}
}
async function ensureEmailBody(){
 if(!emailSelected)return;
 const id=emailSelected,full=await api('emails/message?message_id='+encodeURIComponent(id));
 emailDetails.set(id,full);if(emailDetails.size>30)emailDetails.delete(emailDetails.keys().next().value);
}

function emailJobs(m){return state.jobs.filter(j=>m.job_ids.includes(j.id))}
function renderEmails(){
 const sync=emailState.sync,w=emailState.worker;
 if(!$('#mailPromptSettings').contains(document.activeElement)){$('#mailPrompt').value=emailState.prompt;$('#mailShortcutName').value=emailState.shortcut;$('#mailUseShortcut').checked=emailState.use_shortcut}
 renderMailAccount();
 if(!mailSettingsInitialized){$('#mailSettings').open=!emailState.account;mailSettingsInitialized=true}
 $('#mailEnabled').checked=state.settings.mail_enabled===true;
 $('#mailEnabled').disabled=!emailState.available||!emailState.account;
 $('#mailSync').disabled=w.running||!emailState.available||!emailState.account;$('#mailRescan').disabled=w.running||!emailState.available||!emailState.account;
 $('#mailSync').textContent=w.running?'Checking Mail…':'Check emails since last sync';
 $('#mailSyncStatus').textContent=w.error||w.summary||(sync.through?'Checked through '+new Date(sync.through).toLocaleString():'Collection searches company mentions across the selected account’s history.');
 $('#mailSyncStatus').classList.toggle('mail-error',Boolean(w.error));
 if(emailState.queued||emailState.failed)$('#mailSyncStatus').textContent+=` · ${emailState.queued||0} saved emails awaiting classification${emailState.failed?' · '+emailState.failed+' analyses need retry':''}`;
 $('#mailProgress').textContent=$('#mailSyncStatus').textContent;$('#mailProgress').classList.toggle('mail-error',Boolean(w.error));
 $('#mailCheckpoint').textContent=sync.last_received_at?'Last collected email: '+new Date(sync.last_received_at).toLocaleString()+' · '+sync.last_message_id:'';
 const messages=emailState.messages;
 const visible=messages,groups=emailTools.groups(visible,$('#mailGroup').value);
 $('#emailCount').textContent=`${emailState.total??messages.length} total · ${visible.length} shown · ${emailState.matching??messages.length} match · ${emailState.pending??0} to review · ${emailState.queued??0} awaiting classification`;
 $('#mailRetryAll').disabled=!(emailState.failed>0);
 $('#emailList').innerHTML=groups.map(([group,list])=>{
  const content=$('#mailGroup').value==='company'?(()=>{const roles=new Map();for(const m of list){const role=m.match_kind==='company'?'Company correspondence':emailJobs(m).map(j=>j.title).join(' / ')||'Unlinked';if(!roles.has(role))roles.set(role,[]);roles.get(role).push(m)}return [...roles].map(([role,emails])=>`<details class="mail-role" open><summary>${esc(role)} <span class="sub">${emails.length}</span></summary>${emails.map(mailRow).join('')}</details>`).join('')})():list.map(mailRow).join('');
  return $('#mailGroup').value==='none'?content:`<details class="mail-company" open><summary>${esc(group)} <span class="sub">${list.length}</span></summary>${content}</details>`;
 }).join('')||'<p class="empty">No emails match these filters. Collected company emails appear here before classification finishes.</p>';
 const selected=emailDetails.get(emailSelected)||messages.find(m=>m.message_id===emailSelected);
 $('#mailShowMore').hidden=!emailState.has_more;
 renderEmailDetail(selected||null);
}
function renderEmailDetail(m,host=$('#emailDetail')){
 const prefix=host.id==='emailPreviewDetail'?'preview-':'',q=s=>host.querySelector(s.replace(/^#/, '#'+prefix)),key=JSON.stringify([m,state.jobs.map(j=>[j.id,j.status])]);if(key===host.dataset.renderKey)return;host.dataset.renderKey=key;if(!m){host.innerHTML='<p>Select an email to read its content and review its application links.</p>';return}
 const jobs=emailJobs(m),ambiguous=jobs.length!==1,newer=m.newer||emailTools.newer(m,emailState.messages);
 const ignoreControls=`<button id="mailIgnore">${m.review==='ignored'?'Restore ignored email':'Ignore email'}</button>`;
 const newerNotice=newer?`<div class="mail-review"><strong>A newer status email may supersede this one</strong><p>${esc(newer.subject)} · ${esc(new Date(newer.received_at).toLocaleString())}</p><button id="mailViewNewer">Read newer email</button><p>You can ignore this older message to keep it out of the review queue.</p></div>`:'';
 host.innerHTML=`<h2>${esc(m.subject||'(No subject)')}</h2><p>${esc(m.sender)}<br>${esc(new Date(m.received_at).toLocaleString())}</p><button id="mailOpen">Open original email ↗</button> ${ignoreControls}${newerNotice}<p>${esc(m.match_kind==='company'?'No exact role identified. Linked to every tracked application at this company.':m.match_kind==='role'?'Matched a company and job title.':m.match_kind==='manual'?'Links selected by you.':m.match_kind==='missing'?'This email names a role that may be missing from your application list. Existing roles are not assumed to match.':'No company or role match. Choose application links below.')}</p>${m.review==='pending'?`<div class="mail-review"><strong>${m.category==='offer'?'Possible job offer':m.invitation?'Interview or technical test request':'Possible rejection'} — review the email before approving</strong>${m.evidence?`<p>Detected wording: “${esc(m.evidence)}”</p>`:''}${ambiguous?'<p>Select the affected application(s) before approving.</p>':''}${jobs.map(j=>`<label class="check-label"><input type="checkbox" name="rejectJob" value="${j.id}" ${!ambiguous?'checked':''}>${esc(j.title)} · ${esc(j.company)} <span class="sub">${esc(j.status)}</span></label>`).join('')}<button class="primary" id="mailApprove" ${!jobs.length?'disabled':''}>${m.category==='offer'?'Approve offer status':m.invitation?'Confirm interview pending':'Approve rejection'}</button> <button id="mailDismiss">Disapprove &amp; analyze</button><label>What was wrong? (optional)<textarea id="mailFeedbackReason" rows="2" maxlength="4000" placeholder="e.g. This describes a possible future interview, not an invitation."></textarea></label></div>`:`<p>Review: ${esc(m.review==='none'?'No status change suggested':emailTools.label(m))}</p>${(m.decisions||[]).map(d=>`<p>${esc(state.jobs.find(j=>j.id===d.job_id)?.title||'Removed application')} → ${esc(d.status)}</p>`).join('')}`}<details><summary>Change application links</summary><p>Company correspondence can be linked to several applications.</p><input id="mailLinkSearch" placeholder="Filter companies or roles" aria-label="Filter application links"><div id="mailLinkChoices">${state.jobs.map(j=>`<label class="check-label" data-link-label="${esc((j.company+' '+j.title).toLowerCase())}"><input type="checkbox" name="linkJob" value="${j.id}" ${m.job_ids.includes(j.id)?'checked':''}>${esc(j.company)} · ${esc(j.title)}</label>`).join('')}</div><button id="mailSaveLinks">Save links</button></details>${analysisPanel(m)}${missingPanel(m)}${feedbackPanel(m.feedback)}<h3>Email content</h3><pre class="mail-body">${esc(m.body)}</pre>`;
 if(prefix)host.querySelectorAll('[id]').forEach(node=>node.id=prefix+node.id);
 q('#mailOpen').onclick=async()=>{try{const result=await api('emails/open',{message_id:m.message_id});if(result.url)window.open(result.url,'_blank','noopener,noreferrer')}catch(e){toast(e.message)}};
 const act=async(action,selector)=>{if(emailBusy)return;emailBusy=true;try{await api('emails/review',{message_id:m.message_id,action,expected_token:m.review_token,reason:q('#mailFeedbackReason')?.value||'',job_ids:[...host.querySelectorAll(selector+':checked')].map(e=>Number(e.value))});await refreshEmailSurfaces();toast(action==='approve'?'Application status confirmed and saved':action==='dismiss'?'Disapproved. Local analysis queued.':action==='ignore'?'Email ignored. Application status unchanged.':action==='unignore'?'Email restored.':'Email links saved')}catch(e){toast(e.message);if(/proposal changed|Reload this email/.test(e.message))await refreshEmailSurfaces()}finally{emailBusy=false}};
 q('#mailIgnore').onclick=()=>act(m.review==='ignored'?'unignore':'ignore','[name="rejectJob"]');
 if(q('#mailViewNewer'))q('#mailViewNewer').onclick=()=>{if(host.id==='emailPreviewDetail'){openEmailPreview(newer.message_id);return}emailSelected=newer.message_id;$('#mailFrom').value='';$('#mailTo').value='';$('#mailType').value='';$('#mailExcludeConfirmations').checked=false;$('#mailPending').checked=false;$('#mailShowIgnored').checked=false;$('#mailSearch').value='';loadEmails()};
 if(q('#mailApprove'))q('#mailApprove').onclick=()=>act('approve','[name="rejectJob"]');
 if(q('#mailDismiss'))q('#mailDismiss').onclick=()=>act('dismiss','[name="rejectJob"]');
 if(q('#mailFeedbackRetry'))q('#mailFeedbackRetry').onclick=()=>feedbackAction('retry',m.message_id);
 if(q('#mailFeedbackApply'))q('#mailFeedbackApply').onclick=()=>feedbackAction('apply',m.message_id);
 if(q('#mailAnalysisRetry'))q('#mailAnalysisRetry').onclick=async()=>{try{await api('emails/retry',{message_id:m.message_id});await refreshEmailSurfaces()}catch(e){toast(e.message)}};
 bindMissingActions(host,m);
 q('#mailSaveLinks').onclick=()=>act('link','[name="linkJob"]');
 q('#mailLinkSearch').oninput=e=>host.querySelectorAll('[data-link-label]').forEach(x=>x.hidden=!x.dataset.linkLabel.includes(e.target.value.toLowerCase()));
}
$('#emailList').onclick=async e=>{const b=e.target.closest('[data-email]');if(b){emailSelected=b.dataset.email;try{await ensureEmailBody();await markEmailRead(emailSelected);renderEmails()}catch(err){toast(err.message)}}};
let emailSearchTimer;$('#mailSearch').oninput=()=>{emailSelected=null;emailVisibleLimit=200;clearTimeout(emailSearchTimer);emailSearchTimer=setTimeout(loadEmails,200)};for(const id of ['mailPending','mailType','mailExcludeConfirmations','mailShowIgnored','mailFrom','mailTo','mailSort'])$('#'+id).onchange=()=>{emailSelected=null;emailVisibleLimit=200;loadEmails()};$('#mailGroup').onchange=()=>renderEmails();
$('#mailClearFilters').onclick=()=>{for(const id of ['mailSearch','mailType','mailFrom','mailTo'])$('#'+id).value='';for(const id of ['mailPending','mailExcludeConfirmations','mailShowIgnored'])$('#'+id).checked=false;emailVisibleLimit=200;loadEmails()};
$('#mailSync').onclick=async()=>{try{await api('emails/sync',{});emailState.worker.running=true;renderEmails()}catch(e){toast(e.message)}};
$('#mailEnabled').onchange=async e=>{try{await api('emails/settings',{enabled:e.target.checked});state.settings.mail_enabled=e.target.checked;await loadEmails()}catch(err){toast(err.message);e.target.checked=!e.target.checked}};
let emailRevision=-1,emailPollBusy=false;
setInterval(async()=>{
 if(emailPollBusy)return;emailPollBusy=true;
 try{const meta=await api('emails/summary'),changed=meta.revision!==emailRevision;emailState.worker=meta.worker;if(changed){emailRevision=($('#emailDetail').contains(document.activeElement)&&!$('#emails').hidden)?-1:meta.revision;const fresh=await api('state');acceptJobUpdates(fresh.jobs);syncStatuses();render()}if(changed&&!$('#emails').hidden&&!$('#emailDetail').contains(document.activeElement))await loadEmails();await loadActivity();if($('#emailPreview').open&&previewMessage&&!$('#emailPreviewDetail').contains(document.activeElement))await openEmailPreview(previewMessage.message_id,false)}catch{}finally{emailPollBusy=false}
},4000);
window.renderJobEmails=async function(id){
 const box=$('#jobEmails');box.innerHTML='';if(!id)return;
 try{const data=await api('emails?job_id='+id+'&limit=1000');if(editing!==id)return;const linked=data.messages;box.innerHTML='<h3>Related emails ('+data.matching+')</h3>'+linked.map(m=>`<button type="button" class="job-email" data-job-email="${esc(m.message_id)}">${esc(m.subject)} <span class="sub">${esc(new Date(m.received_at).toLocaleDateString())}${m.match_kind==='company'?' · Company correspondence':''}</span></button>`).join('');box.onclick=e=>{const b=e.target.closest('[data-job-email]');if(b)openEmailPreview(b.dataset.jobEmail)}}catch(e){box.textContent=e.message}
};

function feedbackPanel(f){
 if(!f)return '';return `<section class="mail-review"><h3>Disapproval analysis</h3><p>${esc(f.state==='queued'||f.state==='running'?'Analyzing disapproval with local AI…':f.state==='failed'?f.error:f.explanation)}</p>${f.proposal?`<details open><summary>Proposed prompt correction</summary><pre class="mail-body">${esc(f.proposal)}</pre></details>`:''}${f.state==='ready'?'<button class="primary" id="mailFeedbackApply">Approve prompt correction</button>':''}${f.state==='applied'?'<p>Prompt correction approved and saved.</p>':'<button id="mailFeedbackRetry">Analyze again</button>'}</section>`;
}
async function feedbackAction(action,id){try{await api('emails/feedback/'+action,{message_id:id});await refreshEmailSurfaces();toast(action==='apply'?'Prompt correction approved. Future shortcut runs use this prompt.':'Feedback analysis queued.')}catch(e){toast(e.message)}}
$('#mailSavePrompt').onclick=async()=>{try{await api('emails/prompt',{prompt:$('#mailPrompt').value,shortcut:$('#mailShortcutName').value,use_shortcut:$('#mailUseShortcut').checked});await loadEmails();toast('Classification prompt and settings saved')}catch(e){toast(e.message)}};

function mailRow(m){const jobs=emailJobs(m);return `<button class="mail-row ${m.message_id===emailSelected?'selected':''}" data-email="${esc(m.message_id)}"><span><strong>${esc(m.subject||'(No subject)')}</strong>${(m.missing||[]).filter(s=>s.state==='suggested').map(s=>`<span class="missing-role">${esc(s.title)} may be missing from list</span>`).join('')}<span class="sub">${esc(m.match_kind==='company'?'Company correspondence · all '+jobs.length+' applications':jobs.map(j=>j.title).join(' · ')||'Link to an application')}</span><span class="sub">${esc(m.sender)} · ${esc(new Date(m.received_at).toLocaleDateString())}</span></span><span class="badge">${esc(emailTools.label(m))}</span></button>`}

$('#mailRescan').onclick=async()=>{try{await api('emails/rescan',{});emailState.worker.running=true;renderEmails()}catch(e){toast(e.message)}};

function renderMailAccount(){
 const selected=emailState.account,select=$('#mailAccount');
 if(document.activeElement!==select){
  const choices=[...mailAccounts];if(selected&&!choices.some(a=>a.id===selected.id))choices.push(selected);
  const value=selected?.id||select.value||'';
  select.innerHTML='<option value="">Choose your email account…</option>'+choices.map(a=>`<option value="${esc(a.id)}">${esc(a.name)}${a.addresses?.length?' · '+esc(a.addresses.join(', ')):''}</option>`).join('');select.value=value;
 }
 $('#mailSaveAccount').disabled=emailState.worker.running;
 $('#mailAccount').disabled=emailState.worker.running;
 $('#mailLoadAccounts').disabled=emailState.worker.running;
 $('#mailDisconnect').disabled=!window.jobtrackerMail||!selected||emailState.worker.running;
 $('#mailAccountStatus').textContent=selected?'Syncing only: '+selected.name+(selected.addresses?.length?' · '+selected.addresses.join(', '):''):'Choose one account before syncing. Other accounts are excluded.';
}
$('#mailLoadAccounts').onclick=async()=>{const button=$('#mailLoadAccounts');button.disabled=true;try{const data=await api('emails/accounts',{include_apple:true});mailAccounts=data.accounts;renderMailAccount();if(data.warning)toast(data.warning);if(!mailAccounts.length)toast('No accounts found. Connect a provider above, or add an account in Apple Mail on macOS.')}catch(e){toast(e.message)}finally{button.disabled=false}};
$('#mailSaveAccount').onclick=async()=>{try{const result=await api('emails/account',{account_id:$('#mailAccount').value});emailSelected=null;previewMessage=null;$('#emailPreview').close();emailDetails.clear();emailBodies.clear();emailVisibleLimit=200;emailDetailKey='';emailState.account=result.account;await refreshEmailSurfaces();toast('Job-search account saved. Sync reads only this account.')}catch(e){toast(e.message)}};

function analysisPanel(m){return m.analysis_state==='queued'?'<p class="mail-analysis">Saved · awaiting AI classification. This email is already linked and viewable.</p>':m.analysis_error?`<div class="mail-review"><strong>${m.analysis_state==='failed'?'Analysis needs retry':'Review the original email'}</strong><p>${esc(m.analysis_error)}</p>${!['approved','dismissed','ignored'].includes(m.review)&&m.body_complete!==false?'<button id="mailAnalysisRetry">Retry this email</button>':''}</div>`:m.ignore_source==='unrelated'?'<p>Excluded from job correspondence because this is a travel, purchase or other personal transaction. The original is retained. Restore it and manually link it if needed.</p>':m.ignore_source==='superseded'?'<p>Automatically ignored because every application at this company has an approved, later status. Restore it to review it again.</p>':''}
function missingPanel(m){return (m.missing||[]).map(s=>`<section class="mail-review"><h3>${esc(s.title)} ${s.state==='added'?'added to applications':'may be missing from list'}</h3><p>${esc(s.company)} · ${s.state==='added'?'Added to your applications':s.lookup_state==='found'?'A matching public posting was found':s.lookup_state==='searching'?'Searching for the public posting…':s.lookup_state==='queued'?'Posting lookup queued':esc(s.error||'No verified public posting found.')}</p>${s.url?`<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">View verified posting ↗</a>`:''}${s.state!=='added'?`<div class="data-actions"><button data-missing-add="${s.id}" class="primary">Review &amp; add application</button><button data-missing-search="${s.id}" ${['queued','searching'].includes(s.lookup_state)?'disabled':''}>Search posting again</button><button data-missing-dismiss="${s.id}">Dismiss suggestion</button><a href="https://www.google.com/search?q=${encodeURIComponent(s.company+' '+s.title+' jobs')}" target="_blank" rel="noopener noreferrer">Search web ↗</a></div>`:''}</section>`).join('')}
function bindMissingActions(host,m){
 host.querySelectorAll('[data-missing-add]').forEach(button=>button.onclick=()=>{const suggestion=m.missing.find(s=>s.id===Number(button.dataset.missingAdd));if($('#jobDialog').open&&window.jobFormBaseline!==new URLSearchParams(new FormData($('#jobForm'))).toString()&&!confirm('Adding this application closes the current form. Discard its unsaved changes?'))return;$('#emailPreview').close();$('#jobDialog').close();openJob();window.emailDraftSuggestion=suggestion.id;const form=$('#jobForm'),date=new Date(m.received_at);for(const [key,value] of Object.entries({title:suggestion.title,company:suggestion.company,url:suggestion.url,description:suggestion.description,date_applied:`${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`,notes:'Application confirmation received '+date.toLocaleDateString()+'. Review the application date and posting details before saving.'}))if(form.elements[key])form.elements[key].value=value||'';$('#dialogTitle').textContent='Review application found in email'});
 for(const [attribute,action] of [['data-missing-search','search'],['data-missing-dismiss','dismiss']])host.querySelectorAll('['+attribute+']').forEach(button=>button.onclick=async()=>{try{await api('emails/missing/'+action,{id:Number(button.getAttribute(attribute))});await refreshEmailSurfaces()}catch(e){toast(e.message)}});
}
$('#mailRetryAll').onclick=async()=>{try{await api('emails/retry',{});await loadEmails();toast('Failed email analyses queued for retry. Collection is unaffected.')}catch(e){toast(e.message)}};
window.openEmailFull=async function(id){emailSelected=id;for(const name of ['mailSearch','mailType','mailFrom','mailTo'])$('#'+name).value='';$('#mailPending').checked=false;$('#mailExcludeConfirmations').checked=false;$('#mailShowIgnored').checked=true;document.querySelector('nav [data-view="emails"]').click();await loadEmails();await markEmailRead(id);renderEmails()};

$('#mailShowMore').onclick=()=>loadEmails(true);

let previewMessage=null,previewRequest=0,activityState={items:[]},activityBusy=false,activityLimit=200;
async function refreshEmailSurfaces(){
 const fresh=await api('state');acceptJobUpdates(fresh.jobs);syncStatuses();render();
 await loadActivity();
 if(!$('#emails').hidden)await loadEmails();
 if($('#emailPreview').open&&previewMessage)await openEmailPreview(previewMessage.message_id,false);
}

async function openEmailPreview(id,show=true){
 const request=++previewRequest,dialog=$('#emailPreview'),host=$('#emailPreviewDetail');
 if(show){previewMessage=null;host.dataset.renderKey='';host.textContent='Loading email…';if(!dialog.open)dialog.showModal()}
 try{
  const message=await api('emails/message?message_id='+encodeURIComponent(id));
  if(request!==previewRequest||!dialog.open)return;
  previewMessage=message;renderEmailDetail(message,host);
  const item=activityState.items.find(x=>x.message_id===id);
  if(item&&!item.seen){await api('emails/activity/seen',{through:item.event_id,message_id:id});await loadActivity()}
 }catch(e){if(request===previewRequest){host.textContent=e.message;toast(e.message)}}
}
window.openEmailReview=openEmailPreview;
$('#emailPreview').addEventListener('close',()=>{previewMessage=null;previewRequest++});
$('#previewFullEmail').onclick=()=>{
 if(!previewMessage)return;const id=previewMessage.message_id;
 if($('#jobDialog').open&&window.jobFormBaseline!==new URLSearchParams(new FormData($('#jobForm'))).toString()&&!confirm('Opening the Emails tab closes this application form. Discard its unsaved changes?'))return;
 $('#emailPreview').close();$('#jobDialog').close();$('#notificationCenter').close();openEmailFull(id);
};
function activityDescription(item){
 if(item.urgent)return 'Status change awaiting your approval: '+item.proposed_status;
 if(item.review==='approved')return 'Status change reviewed and saved';
 if(item.review==='dismissed')return 'Status suggestion disapproved';
 if(item.review==='ignored')return 'Email ignored · no review needed';
 return item.analysis_state==='queued'||item.analysis_state==='running'?'New company email · awaiting classification':'New company email · '+emailTools.label(item);
}
async function loadActivity(){
 if(activityBusy)return;activityBusy=true;
 try{activityState=await api('emails/activity?limit='+activityLimit);renderActivity()}catch(e){if($('#notificationCenter').open)toast(e.message)}finally{activityBusy=false}
}
function renderActivity(){
 const pending=activityState.pending||0,unread=activityState.unread||0;
 $('#notificationCount').textContent=pending||unread||'';
 $('#notificationsButton').title='Notifications · '+pending+' status changes to review · '+unread+' unread emails';
 $('#notificationSummary').textContent=pending+' status changes awaiting approval · '+unread+' unread email notifications';
 $('#notificationList').innerHTML=activityState.items.map(item=>`<button class="activity-item ${item.urgent?'urgent':''} ${!item.seen?'unread':''}" data-notification-email="${esc(item.message_id)}"><span class="activity-reason">${esc(activityDescription(item))}</span><strong>${esc(item.company||'Application correspondence')}</strong><span>${esc(item.subject)}</span><span class="sub">${esc(new Date(item.at).toLocaleString())}${item.seen?' · Read':' · Unread'}</span></button>`).join('')||'<p>No email notifications yet. New company emails and suggested status changes will appear here.</p>';
 $('#notificationsRead').disabled=!unread;$('#notificationsMore').hidden=activityState.items.length>=activityState.total;
}
$('#notificationsButton').onclick=()=>{$('#notificationCenter').showModal();loadActivity()};
$('#notificationList').onclick=e=>{const item=e.target.closest('[data-notification-email]');if(item)openEmailPreview(item.dataset.notificationEmail)};
$('#notificationsRead').onclick=async()=>{try{await api('emails/activity/seen',{through:activityState.through||0});await loadActivity()}catch(e){toast(e.message)}};

$('#notificationsMore').onclick=()=>{activityLimit+=200;loadActivity()};

async function markEmailRead(id){const item=activityState.items.find(x=>x.message_id===id);if(item&&!item.seen){await api('emails/activity/seen',{through:item.event_id,message_id:id});await loadActivity()}};

// Only the isolated preload bridge passes credentials to the desktop main process.
const mailBridge=window.jobtrackerMail;
function mailProviderFields(){const provider=$('#mailProvider').value;$('#mailOAuthFields').hidden=provider==='imap';$('#mailIMAPFields').hidden=provider!=='imap';$('#mailClientSecretLabel').hidden=provider!=='gmail'}
$('#mailProvider').onchange=mailProviderFields;mailProviderFields();
async function mailConnectionStatus(){if(!mailBridge){$('#mailConnectionStatus').textContent='Direct provider connections require the desktop app.';$('#mailConnect').disabled=true;$('#mailDisconnect').disabled=true;return}try{const info=await mailBridge.status();$('#mailConnectionStatus').textContent=info.warning||(info.secureStorage===false?'Secure storage unavailable. Uncheck Remember to connect for this session.':info.secureStorage===null?'System credential storage is checked when you connect. Credentials are excluded from exports.':'Credentials are encrypted by your system and excluded from exports.');}catch(e){$('#mailConnectionStatus').textContent=e.message}}
mailConnectionStatus();
$('#mailConnect').onclick=async()=>{const config={provider:$('#mailProvider').value,client_id:$('#mailClientId').value.trim(),client_secret:$('#mailClientSecret').value,email:$('#mailAddress').value.trim(),host:$('#mailHost').value.trim(),port:Number($('#mailPort').value),username:$('#mailUsername').value.trim(),password:$('#mailPassword').value,remember:$('#mailRemember').checked};$('#mailConnect').disabled=true;$('#mailConnectCancel').disabled=false;$('#mailConnectionStatus').textContent=config.provider==='imap'?'Checking read-only connection…':'Complete sign-in in your browser…';try{const result=await mailBridge.connect(config);$('#mailPassword').value='';$('#mailClientSecret').value='';emailDetails.clear();emailBodies.clear();emailSelected=null;previewMessage=null;$('#emailPreview').close();const data=await api('emails/accounts',{});mailAccounts=data.accounts;await refreshEmailSurfaces();$('#mailConnectionStatus').textContent=result.warning||'Connected. Check emails to collect company correspondence.';toast('Email account connected.')}catch(e){$('#mailConnectionStatus').textContent=e.message}finally{config.password='';config.client_secret='';$('#mailConnect').disabled=false;$('#mailConnectCancel').disabled=true}};
$('#mailConnectCancel').onclick=async()=>{try{await mailBridge.cancel()}catch(e){toast(e.message)}};
$('#mailDisconnect').onclick=async()=>{if(!emailState.account)return;try{await mailBridge.disconnect(emailState.account.id);await refreshEmailSurfaces();await mailConnectionStatus();toast('Disconnected. Saved emails and decisions are preserved.')}catch(e){toast(e.message)}};
