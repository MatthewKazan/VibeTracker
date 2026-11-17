/* Plain Markdown is the interchange format; the server owns revisions. */
let prepMenuTarget=null,prepDrag=null,prepCardTarget=null;
const prep={sheets:[],selected:null,drafts:new Map(),editing:false,tab:'both',loading:false,saving:false};
function prepCurrent(){return prep.sheets.find(s=>s.id===prep.selected)}
function prepDraft(){const s=prepCurrent();return s&&(prep.drafts.get(s.id)||s)}
function prepExtraSections(d=prepDraft()){return d?.sections||[]}
function prepField(d,field){return field.startsWith('extra:')?prepExtraSections(d).find(s=>s.id===field.slice(6))?.content??'':d[field]}
function prepSetField(d,field,text){return field.startsWith('extra:')?{...d,sections:prepExtraSections(d).map(s=>s.id===field.slice(6)?{...s,content:text}:s)}:{...d,[field]:text}}
function prepSectionList(d=prepDraft()){return [{field:'about',title:'About me'},{field:'technical',title:'Technical reference'},...prepExtraSections(d).map(s=>({field:'extra:'+s.id,title:s.title}))]}
function prepRenderExtraSections(d,query){
 if(prep.tab!=='both'&&!prepSectionList(d).some(s=>s.field===prep.tab))prep.tab='both';
 document.querySelectorAll('.prep-extra-column').forEach(n=>n.remove());
 for(const section of prepExtraSections(d)){
  const field='extra:'+section.id,node=document.createElement('section');node.className='prep-column prep-extra-column';node.dataset.prepColumn=field;node.hidden=prep.tab!=='both'&&prep.tab!==field;
  node.innerHTML=`<div class="prep-section-heading"><h2>${esc(section.title)}</h2><button type="button" class="prep-manage-section" data-prep-manage="${esc(section.id)}" data-prep-section-actions="${esc(field)}" aria-label="Manage ${esc(section.title)} section">•••</button></div><div class="prep-extra-read" ${prep.editing?'hidden':''}>${prepMarkdown(section.content,query,field)}</div><textarea data-prep-editor="${esc(section.id)}" aria-label="${esc(section.title)} Markdown" ${prep.editing?'':'hidden'} spellcheck="true"></textarea><button type="button" class="prep-add-card" data-prep-add="${esc(field)}" ${prep.editing?'hidden':''}>+ Add card</button>`;
  node.querySelector('textarea').value=section.content;$('#prepColumns').append(node);
 }
 const valid=prepSectionList(d).some(s=>s.field===prep.tab);if(prep.tab!=='both'&&!valid)prep.tab='both';
 $('.prep-tabs').innerHTML=`<button data-prep-tab="both">${prepExtraSections(d).length?'All sections':'Both'}</button>`+prepSectionList(d).map(s=>`<button data-prep-tab="${esc(s.field)}">${esc(s.field==='technical'?'Technical':s.title)}</button>`).join('');
}
function prepLayoutEntries(d=prepDraft()){
 const fields=prepSectionList(d).map(s=>s.field),seen=new Set(),entries=[];
 for(const e of Array.isArray(d?.section_layout)?d.section_layout:[])if(e&&fields.includes(e.field)&&!seen.has(e.field)&&['left','right','both'].includes(e.column)){entries.push({field:e.field,column:e.column});seen.add(e.field)}
 fields.forEach((field,i)=>{if(!seen.has(field))entries.push({field,column:i%2?'right':'left'})});return entries;
}
function prepCardPositions(d,field){const entry=prepLayoutEntries(d).find(e=>e.field===field),saved=d.card_columns?.[field];return prepSections(prepField(d,field)).map((_,i)=>entry?.column!=='both'?entry?.column||'left':Array.isArray(saved)&&['left','right'].includes(saved[i])?saved[i]:(i%2?'right':'left'))}
function prepArrangeCards(node,field,d,span){
 const read=node.querySelector(field==='about'?'#prepAboutRead':field==='technical'?'#prepTechnicalRead':'.prep-extra-read');if(!read)return;
 const cards=[...read.querySelectorAll('.prep-card')];if(!cards.length)return;
 if(!span){read.replaceChildren(...cards);return;}
 const grid=document.createElement('div');grid.className='prep-card-lanes';
 for(const side of ['left','right']){const lane=document.createElement('div');lane.className='prep-card-lane';lane.dataset.prepCardLane=side;lane.dataset.prepField=field;grid.append(lane)}
 const positions=prepCardPositions(d,field);cards.forEach(card=>grid.children[positions[Number(card.dataset.prepIndex)]==='right'?1:0].append(card));read.replaceChildren(grid);
}
function prepLayoutColumns(){
 const host=$('#prepColumns'),d=prepDraft(),nodes=new Map([['about',$('#prepAbout')],['technical',$('#prepTechnical')],...prepExtraSections(d).map(s=>['extra:'+s.id,host.querySelector(`[data-prep-column="extra:${s.id}"]`)])]);
 host.replaceChildren();let row=null,lanes=null;
 const flush=()=>{if(row){lanes.forEach(l=>l.hidden=![...l.children].some(n=>!n.hidden));row.hidden=lanes.every(l=>l.hidden);row=null;lanes=null}};
 for(const [sectionIndex,entry] of prepLayoutEntries(d).entries()){
  const node=nodes.get(entry.field);if(!node)continue;node.style.order=sectionIndex;node.dataset.prepSection=entry.field;node.classList.toggle('prep-spanning',entry.column==='both');prepArrangeCards(node,entry.field,d,entry.column==='both');
  if(entry.column==='both'){flush();host.append(node);continue;}
  if(!row){row=document.createElement('div');row.className='prep-row';row.style.order=sectionIndex;lanes=['left','right'].map(side=>{const lane=document.createElement('div');lane.className='prep-lane';lane.dataset.prepLane=side;row.append(lane);return lane});host.append(row)}
  lanes[entry.column==='right'?1:0].append(node);
 }
 flush();
}
function prepDirty(){return prep.drafts.size>0}
function prepRemember(key,value){try{localStorage.setItem('interview-prep-'+key,value)}catch{}}
function prepRecall(key,fallback){try{return localStorage.getItem('interview-prep-'+key)||fallback}catch{return fallback}}
function prepInline(text){
 const tokens=text.split(/(\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$\$[\s\S]*?\$\$|\$[^$\n]+\$)/g);
 return tokens.map((part,i)=>{
  if(i%2&&typeof katex!=='undefined'){
   const display=part.startsWith('\\[')||part.startsWith('$$'),size=part.startsWith('$')&&!display?1:2;
   return katex.renderToString(part.slice(size,-size),{displayMode:display,throwOnError:false,trust:false,maxSize:10,maxExpand:1000,strict:'ignore'});
  }
  return esc(part).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/\n/g,'<br>');
 }).join('');
}
function prepSections(markdown){return markdown.trim()?markdown.trim().split(/\n(?=## )/).map(s=>s.trim()):[]}
function prepBlocks(markdown){return prepSections(markdown).map((raw,index)=>{const lines=raw.split('\n'),heading=lines[0].startsWith('## ')?lines.shift().slice(3):'';return {heading,text:lines.join('\n'),raw,index}})}
function prepMoveMarkdown(markdown,from,to){
 const blocks=prepSections(markdown);if(!Number.isInteger(from)||!Number.isInteger(to)||from<0||to<0||from>=blocks.length||to>=blocks.length||from===to)return markdown;
 // Give an unheaded preamble a boundary if moved behind another section.
 const items=blocks.map(b=>b.startsWith('## ')?b:'## Notes\n'+b),[item]=items.splice(from,1);items.splice(to,0,item);return items.join('\n\n')+'\n';
}
function prepMarkdown(markdown,query='',field='about'){
 return prepBlocks(markdown).filter(b=>!query||`${b.heading} ${b.text}`.toLowerCase().includes(query)).map(b=>{
  const content=b.text.trim().split(/\n\s*\n/).filter(Boolean).map(paragraph=>{
   const lines=paragraph.split('\n');return lines.every(line=>/^[-*] /.test(line))?'<ul>'+lines.map(line=>'<li>'+prepInline(line.slice(2))+'</li>').join('')+'</ul>':'<p>'+prepInline(paragraph)+'</p>';
  }).join('');return `<article class="prep-card" tabindex="0" aria-haspopup="menu" data-prep-field="${field}" data-prep-index="${b.index}"><div class="prep-card-head"><h3>${esc(b.heading||'Notes')}</h3><button type="button" class="prep-drag" draggable="true" aria-label="Reorder ${esc(b.heading||'Notes')}" title="Drag to reorder · right-click for edit and move" ${prep.saving?'disabled':''}>⠿</button></div>${content}</article>`;
 }).join('')||'<p class="prep-empty">No matching notes.</p>';
}
function prepStatus(text){$('#prepStatus').textContent=text}
function renderPrep(){
 prepCloseMenu();
 const s=prepCurrent();if(!s)return;const d=prepDraft(),query=$('#prepSearch').value.trim().toLowerCase();
 $('#prepVersion').innerHTML=prep.sheets.map(v=>`<option value="${esc(v.id)}">${esc((prep.drafts.has(v.id)?'• ':'')+v.title)}</option>`).join('');$('#prepVersion').value=s.id;
 $('#prepRoleBrief').hidden=!s.role_description;$('#prepRoleDescription').textContent=s.role_description||'';$('#prepRoleUrl').textContent=s.role_url||'';
 $('#prepTitle').value=d.title;$('#prepAboutEdit').value=d.about;$('#prepTechnicalEdit').value=d.technical;
 $('#prepAboutRead').innerHTML=prepMarkdown(d.about,query,'about');$('#prepTechnicalRead').innerHTML=prepMarkdown(d.technical,query,'technical');
 prepRenderExtraSections(d,query);
 $('#prepAbout').hidden=prep.tab!=='both'&&prep.tab!=='about';$('#prepTechnical').hidden=prep.tab!=='both'&&prep.tab!=='technical';
 $('#prepColumns').classList.toggle('prep-single',prep.tab!=='both');prepLayoutColumns();
 for(const key of ['About','Technical']){$('#prep'+key+'Edit').hidden=!prep.editing;$('#prep'+key+'Read').hidden=prep.editing}
 document.querySelectorAll('.prep-add-card').forEach(b=>b.hidden=prep.editing);
 $('#prepTitleLabel').hidden=!prep.editing;$('#prepEdit').textContent=prep.editing?'Read notes':'Edit notes';$('#prepEdit').setAttribute('aria-pressed',String(prep.editing));
 $('#prepSearch').hidden=prep.editing;$('#prepSave').hidden=!prep.editing&&!prep.drafts.has(s.id);$('#prepSave').disabled=!prep.drafts.has(s.id)||prep.saving;
 $('#prepDelete').disabled=s.id==='general';$('#prepMeta').textContent=(s.id==='general'?'Reusable base':s.parent_id?'Independent copy':'Interview sheet')+' · revision '+s.revision;
 document.querySelectorAll('[data-prep-tab]').forEach(b=>{b.classList.toggle('active',b.dataset.prepTab===prep.tab);b.setAttribute('aria-pressed',String(b.dataset.prepTab===prep.tab))});
 prepStatus(prep.drafts.has(s.id)?'Unsaved draft · Save or press ⌘/Ctrl+S':s.updated_at?'Saved locally · '+new Date(s.updated_at).toLocaleString():'Ready · included in full backups');
}
async function loadPrep(){
 if(prep.loading)return;prep.loading=true;prepStatus('Loading notes…');
 try{await loadViewAsset('/vendor/katex/katex.min.css',true);await loadViewAsset('/vendor/katex/katex.min.js');const r=await api('interview-prep');prep.sheets=r.sheets;prep.selected=prep.sheets.some(s=>s.id===prep.selected)?prep.selected:prepRecall('selected','crabi');if(!prepCurrent())prep.selected='general';renderPrep()}
 catch(e){prepStatus(e.message)}finally{prep.loading=false}
}
function prepCapture(){const s=prepCurrent();if(!s)return;const old=prepDraft(),sections=prepExtraSections(old).map(section=>({...section,content:document.querySelector(`[data-prep-editor="${section.id}"]`)?.value??section.content})),d={...old,title:$('#prepTitle').value,about:$('#prepAboutEdit').value,technical:$('#prepTechnicalEdit').value,sections};if(['title','about','technical'].every(k=>d[k]===s[k])&&JSON.stringify(sections)===JSON.stringify(prepExtraSections(s)))prep.drafts.delete(s.id);else prep.drafts.set(s.id,d);$('#prepSave').disabled=!prep.drafts.has(s.id)||prep.saving;prepStatus(prep.drafts.has(s.id)?'Unsaved draft · Save or press ⌘/Ctrl+S':'Saved locally')}
async function prepSave(){
 const s=prepCurrent(),draft=s&&prep.drafts.get(s.id);if(!draft)return true;if(prep.saving)return false;
 prep.saving=true;$('#prepSave').disabled=true;prepStatus('Saving…');
 try{const r=await api('interview-prep',{action:'save',id:s.id,expected_revision:draft.revision,title:draft.title,about:draft.about,technical:draft.technical,sections:prepExtraSections(draft),section_layout:prepLayoutEntries(draft),card_columns:Object.fromEntries(prepSectionList(draft).filter(s=>Array.isArray(draft.card_columns?.[s.field])).map(s=>[s.field,prepCardPositions(draft,s.field)]))});prep.sheets=r.sheets;if(prep.drafts.get(s.id)===draft)prep.drafts.delete(s.id);else{const newer=prep.drafts.get(s.id);if(newer)newer.revision=r.sheets.find(v=>v.id===s.id).revision}renderPrep();return true}
 catch(e){prepStatus(e.message);return false}finally{prep.saving=false;$('#prepSave').disabled=!prep.drafts.has(prep.selected);document.querySelectorAll('.prep-drag').forEach(button=>button.disabled=false)}
}
function prepSource(d=prepDraft()){return `# ${d.title}\n\n<!-- about -->\n${d.about.trim()}\n\n<!-- technical -->\n${d.technical.trim()}\n`+prepExtraSections(d).map(s=>`\n<!-- section:${s.id} -->\n# ${s.title}\n\n${s.content.trim()}\n`).join('')+(d.section_layout||d.card_columns?`\n<!-- interview-layout:${JSON.stringify({section_layout:d.section_layout||[],card_columns:d.card_columns||{}})} -->\n`:'')}
function prepParse(source){
 let metadata={};const layout=/\n<!-- interview-layout:([^\n]+) -->\s*$/.exec(source);if(layout){if(layout[1].length>1000000)throw Error('Layout metadata is too large.');const parsed=JSON.parse(layout[1]);if(!parsed||!Array.isArray(parsed.section_layout)||!parsed.card_columns||typeof parsed.card_columns!=='object'||Array.isArray(parsed.card_columns))throw Error('Invalid interview layout metadata.');metadata={section_layout:parsed.section_layout,card_columns:parsed.card_columns};source=source.slice(0,layout.index)}
 const markers=[...source.matchAll(/<!-- (about|technical|section:[a-z][a-z0-9_-]{0,63}) -->/g)],ids=markers.map(m=>m[1]);
 if(ids[0]!=='about'||ids[1]!=='technical'||new Set(ids).size!==ids.length||ids.slice(2).some(id=>!id.startsWith('section:')))throw Error('Keep one <!-- about --> then one <!-- technical --> marker; extra sections use unique <!-- section:id --> markers.');
 const title=source.slice(0,markers[0].index).trim();if(!/^# [^\n]+$/.test(title))throw Error('Start with one # Sheet name line before the section markers.');
 const parts=markers.map((m,i)=>source.slice(m.index+m[0].length,markers[i+1]?.index??source.length).trim()),sections=parts.slice(2).map((part,i)=>{const newline=part.indexOf('\n'),heading=(newline<0?part:part.slice(0,newline)).trim();if(!/^# [^\n]+$/.test(heading))throw Error('Each extra section starts with # Section name after its marker.');return {id:ids[i+2].slice(8),title:heading.slice(2).trim(),content:newline<0?'':part.slice(newline+1).trim()}});
 if(sections.length>20||sections.some(s=>['about','technical','both'].includes(s.id)||s.title.length>80||s.content.length>100000))throw Error('Use up to 20 extra sections, names up to 80 characters, and notes up to 100,000 characters.');
 return {title:title.slice(2).trim(),about:parts[0],technical:parts[1],sections,...metadata};
}
async function prepCopy(text){try{await navigator.clipboard.writeText(text);prepStatus('Copied to clipboard')}catch{prepStatus('Clipboard unavailable. Use Export .md instead.')}}
function prepExport(){const d=prepDraft();if(!d)return;const url=URL.createObjectURL(new Blob([prepSource(d)],{type:'text/markdown;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=d.title.replace(/[^a-z0-9]+/gi,'-').replace(/^-|-$/g,'')+'.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
$('#prepVersion').onchange=e=>{prep.selected=e.target.value;prepRemember('selected',prep.selected);renderPrep()};
$('#prepEdit').onclick=async()=>{if(prep.editing){prepCapture();if(!await prepSave())return;}prep.editing=!prep.editing;renderPrep()};
for(const id of ['prepTitle','prepAboutEdit','prepTechnicalEdit'])$('#'+id).addEventListener('input',prepCapture);
$('#prepSave').onclick=prepSave;
$('#prepSearch').oninput=()=>{const d=prepDraft();if(!d)return;const q=$('#prepSearch').value.trim().toLowerCase();$('#prepAboutRead').innerHTML=prepMarkdown(d.about,q,'about');$('#prepTechnicalRead').innerHTML=prepMarkdown(d.technical,q,'technical');document.querySelectorAll('.prep-extra-column').forEach(n=>n.querySelector('.prep-extra-read').innerHTML=prepMarkdown(prepField(d,n.dataset.prepColumn),q,n.dataset.prepColumn));prepLayoutColumns()};
$('.prep-tabs').onclick=e=>{const b=e.target.closest('[data-prep-tab]');if(!b)return;prep.tab=b.dataset.prepTab;prepRemember('tab',prep.tab);renderPrep()};
$('#prepFork').onclick=()=>{
 const d=prepDraft();if(!d)return;$('#prepForkName').value=d.title==='General cheat sheet'?'New interview':d.title+' · copy';$('#prepForkJob').innerHTML='<option value="">No linked application</option>'+state.jobs.map(j=>`<option value="${j.id}">${esc(j.company+' · '+j.title)}</option>`).join('');$('#prepForkUrl').value='';$('#prepForkDescription').value='';$('#prepForkStatus').textContent='A description adds relevant focus prompts and stays attached to this copy. AI tailoring is optional.';prepClearTailored();$('#prepForkDialog').showModal();$('#prepForkName').focus();$('#prepForkName').select();
};
function prepClearTailored(){$('#prepTailoredPreview').hidden=true;$('#prepTailoredPreview').open=false;$('#prepTailoredAbout').value='';$('#prepTailoredTechnical').value=''}
$('#prepForkJob').onchange=e=>{const j=state.jobs.find(j=>String(j.id)===e.target.value);prepClearTailored();$('#prepForkDescription').value=j?.description||'';$('#prepForkUrl').value=j?.url||'';if(j){$('#prepForkName').value=`${j.company} · ${j.title}`;$('#prepForkStatus').textContent=(j.description||'').trim().length<80?'This saved description is short. Read its URL or paste the full description before tailoring.':'Saved description loaded. Create a copy or optionally tailor with local AI.'}};
$('#prepForkDescription').oninput=$('#prepForkUrl').oninput=prepClearTailored;
$('#prepDiscardTailored').onclick=prepClearTailored;
$('#prepReadUrl').onclick=async()=>{const b=$('#prepReadUrl');b.disabled=true;$('#prepForkCreate').disabled=true;$('#prepForkStatus').textContent='Reading posting…';try{const r=await api('extract',{url:$('#prepForkUrl').value.trim(),text:''});prepClearTailored();$('#prepForkDescription').value=r.description||'';if(r.title)$('#prepForkName').value=(r.company?r.company+' · ':'')+r.title;$('#prepForkStatus').textContent=(r.warning?r.warning+' ':'')+'Review the description below. If the site blocks access, paste the posting text.'}catch(e){$('#prepForkStatus').textContent=e.message+' You can paste the job description instead.'}finally{b.disabled=false;$('#prepForkCreate').disabled=false}};
$('#prepTailor').onclick=async()=>{const b=$('#prepTailor');b.disabled=true;$('#prepForkCreate').disabled=true;$('#prepForkStatus').textContent='Drafting with local AI…';try{if(!await prepSave()){throw Error('Save the source sheet before generating the draft.')}const s=prepCurrent(),description=$('#prepForkDescription').value,r=await api('interview-prep/draft',{id:s.id,expected_revision:s.revision,role_description:description});if($('#prepForkDescription').value!==description)throw Error('The job description changed during generation. Generate again for the updated description.');$('#prepTailoredAbout').value=r.about;$('#prepTailoredTechnical').value=r.technical;$('#prepTailoredPreview').hidden=false;$('#prepTailoredPreview').open=true;$('#prepForkStatus').textContent='AI draft ready. Check facts, metrics, and scope in the preview before creating the copy.'}catch(e){$('#prepForkStatus').textContent=e.message+' You can still create a copy without AI.'}finally{b.disabled=false;$('#prepForkCreate').disabled=false}};
$('#prepForkForm').onsubmit=async e=>{e.preventDefault();const b=$('#prepForkCreate');b.disabled=true;try{if(!await prepSave())return;const s=prepCurrent(),r=await api('interview-prep',{action:'fork',id:s.id,expected_revision:s.revision,title:$('#prepForkName').value.trim(),job_id:$('#prepForkJob').value||null,role_description:$('#prepForkDescription').value,role_url:$('#prepForkUrl').value,...($('#prepTailoredPreview').hidden?{}:{about:$('#prepTailoredAbout').value,technical:$('#prepTailoredTechnical').value})});prep.sheets=r.sheets;prep.selected=r.selected_id;prepRemember('selected',prep.selected);$('#prepForkDialog').close();renderPrep()}catch(e){$('#prepForkStatus').textContent=e.message}finally{b.disabled=false}};
$('#prepDelete').onclick=async()=>{const s=prepCurrent();if(!s||s.id==='general'||!confirm(`Delete “${s.title}” and its draft? A recovery snapshot is kept.`))return;try{const r=await api('interview-prep',{action:'delete',id:s.id,expected_revision:s.revision});prep.drafts.delete(s.id);prep.sheets=r.sheets;prep.selected=r.selected_id;prepRemember('selected',prep.selected);renderPrep()}catch(e){prepStatus(e.message)}};
$('#prepReload').onclick=async()=>{const s=prepCurrent();if(s&&prep.drafts.has(s.id)&&!confirm('Discard this draft and load the saved sheet? Export it first if you want to merge it.'))return;if(s)prep.drafts.delete(s.id);await loadPrep()};
$('#prepExport').onclick=prepExport;
$('#prepAI').onclick=()=>{const d=prepDraft();if(d)prepCopy('Edit this interview cheat sheet. Preserve the # title, every HTML section marker, and the interview-layout comment, including all extra sections. Return the complete Markdown only. Keep it compact, specific, and accurate; do not invent achievements or turn research goals into completed results.\n\n'+prepSource(d))};
$('#prepImport').onclick=()=>{if(!prepCurrent())return;$('#prepSource').value=prepSource();$('#prepImportStatus').textContent='Paste an AI-edited version, or choose a Markdown file. This becomes a draft; review and Save.';$('#prepImportDialog').showModal()};
$('#prepImportFile').onchange=async e=>{try{const f=e.target.files[0];if(!f)return;if(f.size>1000000)throw Error('Choose a Markdown file smaller than 1 MB.');$('#prepSource').value=await f.text()}catch(e){$('#prepImportStatus').textContent=e.message}finally{e.target.value=''}};
$('#prepImportForm').onsubmit=e=>{e.preventDefault();try{const parsed=prepParse($('#prepSource').value);if(parsed.title.length>160||parsed.about.length>100000||parsed.technical.length>100000)throw Error('Name or section is too long.');const s=prepCurrent();prep.drafts.set(s.id,{...prepDraft(),...parsed,sections:parsed.sections.length?parsed.sections:prepExtraSections(prepDraft())});prep.editing=true;$('#prepImportDialog').close();renderPrep()}catch(e){$('#prepImportStatus').textContent=e.message}};
$('#prepFocus').onclick=()=>{const enabled=document.body.classList.toggle('prep-focus');$('#prepFocus').textContent=enabled?'Exit interview view':'Interview view';$('#prepFocus').setAttribute('aria-pressed',String(enabled))};
$('#prepFont').oninput=e=>{const value=Number(e.target.value);$('#interviewPrep').style.setProperty('--prep-font',value+'px');prepRemember('font',String(value))};
prep.tab=prepRecall('tab','both');if(!['both','about','technical'].includes(prep.tab)&&!/^extra:[a-z][a-z0-9_-]{0,63}$/.test(prep.tab))prep.tab='both';
$('#prepFont').value=Math.min(20,Math.max(12,Number(prepRecall('font','14'))||14));$('#prepFont').oninput({target:$('#prepFont')});
window.addEventListener('keydown',e=>{if(e.key==='Escape'&&document.body.classList.contains('prep-focus'))$('#prepFocus').click();if(activeView==='interviewPrep'&&(e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='s'){e.preventDefault();prepSave()}});
window.addEventListener('beforeunload',e=>{if(prepDirty()){e.preventDefault();e.returnValue=''}});

// Card commands live in one context menu; Markdown order remains the source of truth.

function prepCloseMenu(){const m=$('#prepCardMenu');if(m)m.hidden=true;const section=$('#prepSectionMenu');if(section)section.hidden=true;prepMenuTarget=null}
function prepCardData(card){const field=card.dataset.prepField,index=Number(card.dataset.prepIndex),d=prepDraft();return {id:prep.selected,field,index,markdown:prepField(d,field),raw:prepSections(prepField(d,field))[index]}}
function prepTargetValid(t){return t&&t.id===prep.selected&&prepDraft()&&prepField(prepDraft(),t.field)===t.markdown}
function prepCardNeighbor(d,field,index,direction){const positions=prepCardPositions(d,field),side=positions[index];let next=index+direction;while(next>=0&&next<positions.length&&positions[next]!==side)next+=direction;return next>=0&&next<positions.length?next:null}
function prepOpenMenu(card,x,y){
 if(prep.editing||prep.saving)return;prepMenuTarget=prepCardData(card);const m=$('#prepCardMenu');m.hidden=false;
 $('#prepCardUp').disabled=prepCardNeighbor(prepDraft(),prepMenuTarget.field,prepMenuTarget.index,-1)===null;$('#prepCardDown').disabled=prepCardNeighbor(prepDraft(),prepMenuTarget.field,prepMenuTarget.index,1)===null;for(const side of ['left','right'])$('#prepCardMenu').querySelector(`[data-card-column="${side}"]`).disabled=prepCardPositions(prepDraft(),prepMenuTarget.field)[prepMenuTarget.index]===side;
 m.style.left=Math.max(8,Math.min(x,innerWidth-m.offsetWidth-8))+'px';m.style.top=Math.max(8,Math.min(y,innerHeight-m.offsetHeight-8))+'px';$('#prepCardEdit').focus();
}
async function prepCommitCards(target,markdown){
 if(prep.saving||!prepTargetValid(target)){prepStatus('The notes changed. Try the card action again.');return false;}
 prep.drafts.set(prep.selected,prepSetField(prepDraft(),target.field,markdown));renderPrep();return prepSave();
}
async function prepMoveCard(target,to){if(!prepTargetValid(target))return;const next=prepMoveMarkdown(target.markdown,target.index,to);if(next===target.markdown)return;const d=prepDraft(),positions=prepCardPositions(d,target.field),[position]=positions.splice(target.index,1);positions.splice(to,0,position);prep.drafts.set(prep.selected,{...d,card_columns:{...d.card_columns,[target.field]:positions}});await prepCommitCards(target,next)}
$('#prepColumns').addEventListener('contextmenu',e=>{const card=e.target.closest('.prep-card');if(!card||prep.editing)return;e.preventDefault();prepOpenMenu(card,e.clientX,e.clientY)});
$('#prepColumns').addEventListener('keydown',e=>{if(e.key==='ContextMenu'||(e.shiftKey&&e.key==='F10')){const card=e.target.closest('.prep-card');if(card){e.preventDefault();const r=card.getBoundingClientRect();prepOpenMenu(card,r.x+20,r.y+25)}}});
$('#prepCardUp').onclick=()=>{const t=prepMenuTarget;prepCloseMenu();if(t){const next=prepCardNeighbor(prepDraft(),t.field,t.index,-1);if(next!==null)prepMoveCard(t,next)}};
$('#prepCardDown').onclick=()=>{const t=prepMenuTarget;prepCloseMenu();if(t){const next=prepCardNeighbor(prepDraft(),t.field,t.index,1);if(next!==null)prepMoveCard(t,next)}};
$('#prepCardEdit').onclick=()=>{
 const t=prepMenuTarget;prepCloseMenu();if(!prepTargetValid(t))return;prepCardTarget=t;
 const block=prepBlocks(t.markdown)[t.index];$('#prepCardHeading').value=block.heading;$('#prepCardBody').value=block.text.trim();$('#prepCardError').textContent='';$('#prepCardDialog').showModal();$('#prepCardBody').focus();
};
$('#prepCardForm').onsubmit=async e=>{e.preventDefault();const t=prepCardTarget,b=$('#prepCardSave');b.disabled=true;try{
 if(!prepTargetValid(t))throw Error('The notes changed. Close this editor and reopen the card.');
 const heading=$('#prepCardHeading').value.trim(),body=$('#prepCardBody').value.trim();if(!heading&&!body)throw Error('Keep a heading or some text in the card.');
 const sections=prepSections(t.markdown);sections[t.index]='## '+(heading||'Notes')+'\n'+body;
 const markdown=sections.join('\n\n')+'\n';if(markdown.length>100000)throw Error('This section is too long (100,000 characters maximum).');
 if(await prepCommitCards(t,markdown))$('#prepCardDialog').close();else $('#prepCardError').textContent=$('#prepStatus').textContent;
 }catch(e){$('#prepCardError').textContent=e.message}finally{b.disabled=false}};
$('#prepCardMenu').addEventListener('keydown',e=>{const buttons=[...$('#prepCardMenu').querySelectorAll('button:not(:disabled)')],i=buttons.indexOf(document.activeElement);if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();buttons[(i+(e.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length].focus()}});
document.addEventListener('pointerdown',e=>{if(!e.target.closest('#prepCardMenu,#prepSectionMenu'))prepCloseMenu()});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('#prepCardMenu').hidden){e.stopImmediatePropagation();prepCloseMenu()}},true);
window.addEventListener('scroll',prepCloseMenu,true);window.addEventListener('resize',prepCloseMenu);
function prepClearDrop(){document.querySelectorAll('.prep-drop-before,.prep-drop-after,.prep-dragging').forEach(e=>e.classList.remove('prep-drop-before','prep-drop-after','prep-dragging'))}
$('#prepColumns').addEventListener('dragstart',e=>{const handle=e.target.closest('.prep-drag');if(!handle||prep.saving||prep.editing){e.preventDefault();return;}const card=handle.closest('.prep-card');prepDrag=prepCardData(card);prepCloseMenu();prepTrackAutoScroll(e);card.classList.add('prep-dragging');e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain','Reorder interview card');e.dataTransfer.setDragImage(card,20,20)});
function prepDropLocation(e,target=prepDrag){
 if(!target||!prepTargetValid(target))return null;const card=e.target.closest?.('.prep-card'),lane=e.target.closest?.('[data-prep-card-lane]');
 const host=$('#prepColumns').getBoundingClientRect(),wide=innerWidth>850,side=lane?.dataset.prepCardLane||(wide?(e.clientX>=host.x+host.width/2?'right':'left'):prepLayoutEntries().find(s=>s.field===target.field)?.column||'left');
 // A horizontal move retains section membership, expanding its section as needed.
 const matches=card?.dataset.prepField===target.field,index=matches?Number(card.dataset.prepIndex):null;
 const positions=prepCardPositions(prepDraft(),target.field),candidates=positions.map((p,i)=>p===side?i:-1).filter(i=>i>=0);
 if(matches){const r=card.getBoundingClientRect(),after=e.clientY>=r.y+r.height/2,slot=index+(after?1:0);return {side,to:slot>target.index?slot-1:slot,after,card}}
 if(lane&&lane.dataset.prepField===target.field)return {side,to:candidates.length?candidates[candidates.length-1]+1-(candidates[candidates.length-1]>target.index?1:0):positions.length-1};
 if(wide&&side!==positions[target.index]&&host.left<=e.clientX&&e.clientX<=host.right)return {side,to:target.index};
 return null;
}
async function prepDropCard(target,location){
 if(!prepTargetValid(target)||!location)return;const d=prepDraft(),positions=prepCardPositions(d,target.field),from=target.index,to=Math.max(0,Math.min(positions.length-1,location.to));
 const oldSide=positions[from];if(oldSide===location.side&&from===to)return;positions[from]=location.side;const [position]=positions.splice(from,1);positions.splice(to,0,position);
 const layout=prepLayoutEntries(d).map(e=>e.field===target.field&&oldSide!==location.side?{...e,column:'both'}:e);
 const text=prepMoveMarkdown(target.markdown,from,to);prep.drafts.set(prep.selected,{...d,section_layout:layout,card_columns:{...d.card_columns,[target.field]:positions}});await prepCommitCards(target,text);
}
$('#prepColumns').addEventListener('dragover',e=>{const location=prepDropLocation(e);if(!location)return;e.preventDefault();e.dataTransfer.dropEffect='move';document.querySelectorAll('.prep-drop-before,.prep-drop-after').forEach(c=>c.classList.remove('prep-drop-before','prep-drop-after'));location.card?.classList.add(location.after?'prep-drop-after':'prep-drop-before')});
$('#prepColumns').addEventListener('drop',async e=>{const t=prepDrag,location=prepDropLocation(e,t);prepStopAutoScroll();prepDrag=null;prepClearDrop();if(!location)return;e.preventDefault();await prepDropCard(t,location)});
$('#prepColumns').addEventListener('dragend',()=>{prepStopAutoScroll();prepDrag=null;prepClearDrop()});

// Extra sections use stable IDs so forks, card actions, and Markdown exchange agree.
let prepSectionEditing=null;
function prepOpenSection(id=null){prepSectionEditing=id;const section=prepExtraSections().find(s=>s.id===id);$('#prepSectionDialogTitle').textContent=id?'Manage section':'Add section';$('#prepSectionName').value=section?.title||'';$('#prepSectionNotes').value=section?.content||'';$('#prepSectionNotesLabel').hidden=!!id;$('#prepSectionDelete').hidden=!id;$('#prepSectionError').textContent='';$('#prepSectionDialog').showModal();$('#prepSectionName').focus()}
$('#prepAddSection').onclick=()=>{if(prepCurrent())prepOpenSection()};
$('#prepColumns').addEventListener('input',e=>{if(e.target.matches('[data-prep-editor]'))prepCapture()});
$('#prepColumns').addEventListener('click',e=>{
 const manage=e.target.closest('[data-prep-section-actions]');if(manage){const r=manage.getBoundingClientRect();prepOpenSectionMenu(manage.dataset.prepSectionActions,r.right,r.bottom);return;}
 const add=e.target.closest('[data-prep-add]');if(!add||prep.saving)return;const field=add.dataset.prepAdd,markdown=prepField(prepDraft(),field);prepCardTarget={id:prep.selected,field,markdown,index:prepSections(markdown).length};$('#prepCardHeading').value='';$('#prepCardBody').value='';$('#prepCardError').textContent='';$('#prepCardDialog').showModal();$('#prepCardHeading').focus();
});
$('#prepSectionForm').onsubmit=async e=>{e.preventDefault();const b=$('#prepSectionSave');b.disabled=true;try{
 if(prep.editing)prepCapture();if(prep.saving)throw Error('Wait for the current save to finish.');
 const name=$('#prepSectionName').value.trim();if(!name)throw Error('Give this section a name.');const d=prepDraft(),sections=prepExtraSections(d);
 if(!prepSectionEditing&&sections.length>=20)throw Error('Maximum 20 additional sections per sheet.');
 const next=prepSectionEditing?sections.map(s=>s.id===prepSectionEditing?{...s,title:name}:s):[...sections,{id:'section-'+crypto.randomUUID(),title:name,content:$('#prepSectionNotes').value}];
 prep.drafts.set(prep.selected,{...d,sections:next});renderPrep();if(await prepSave())$('#prepSectionDialog').close();else $('#prepSectionError').textContent=$('#prepStatus').textContent;
 }catch(e){$('#prepSectionError').textContent=e.message}finally{b.disabled=false}};
$('#prepSectionDelete').onclick=async()=>{
 const section=prepExtraSections().find(s=>s.id===prepSectionEditing);if(!section||!confirm(`Delete the “${section.title}” section and its cards? A recovery snapshot is kept.`))return;if(prep.saving)return;if(prep.editing)prepCapture();
 prep.drafts.set(prep.selected,{...prepDraft(),sections:prepExtraSections().filter(s=>s.id!==section.id)});if(prep.tab==='extra:'+section.id)prep.tab='both';renderPrep();if(await prepSave())$('#prepSectionDialog').close();else $('#prepSectionError').textContent=$('#prepStatus').textContent;
};

// Speed benchmark: Atlassian's standard auto-scroll is 900px/s with 400ms dampening.
// https://github.com/atlassian/pragmatic-drag-and-drop/blob/main/packages/auto-scroll/src/shared/configuration.ts
let prepAutoScroll={frame:null,x:0,y:0,last:0,entered:null,direction:0,remainder:0};
function prepScrollVelocity(y,top,bottom,elapsed){
 const zone=Math.min(180,(bottom-top)*.25);if(zone<=0||y<0||y>innerHeight)return 0;
 const upper=(top+zone-y)/zone,lower=(y-(bottom-zone))/zone;
 const penetration=upper>0?-Math.min(1,upper*2):lower>0?Math.min(1,lower*2):0;
 const ramp=Math.min(1,Math.max(0,elapsed)/400);
 return 900*Math.sign(penetration)*Math.abs(penetration)**2*ramp**2;
}
function prepStopAutoScroll(){if(prepAutoScroll.frame!==null)cancelAnimationFrame(prepAutoScroll.frame);prepAutoScroll={frame:null,x:0,y:0,last:0,entered:null,direction:0,remainder:0}}
function prepTrackAutoScroll(e){
 if(!prepDrag)return;const rect=$('#interviewPrep').getBoundingClientRect();
 if(e.clientX<rect.left||e.clientX>rect.right||e.clientY<0||e.clientY>innerHeight){prepStopAutoScroll();return;}
 prepAutoScroll.x=e.clientX;prepAutoScroll.y=e.clientY;
 if(prepAutoScroll.frame===null)prepAutoScroll.frame=requestAnimationFrame(prepAutoScrollStep);
}
function prepAutoScrollStep(now){
 prepAutoScroll.frame=null;
 if(!prepDrag||activeView!=='interviewPrep'||prep.editing||document.hidden){prepStopAutoScroll();return;}
 const toolbar=$('.prep-toolbar').getBoundingClientRect(),top=Math.max(0,toolbar.bottom),bottom=innerHeight;
 const direction=Math.sign(prepScrollVelocity(prepAutoScroll.y,top,bottom,400));
 if(direction!==prepAutoScroll.direction){prepAutoScroll.entered=now;prepAutoScroll.direction=direction;prepAutoScroll.remainder=0}
 const elapsed=now-(prepAutoScroll.entered??now),dt=prepAutoScroll.last?Math.min(50,now-prepAutoScroll.last)/1000:0;
 prepAutoScroll.last=now;const velocity=prepScrollVelocity(prepAutoScroll.y,top,bottom,elapsed);
 prepAutoScroll.remainder+=velocity*dt;const pixels=Math.trunc(prepAutoScroll.remainder);prepAutoScroll.remainder-=pixels;
 if(pixels){
  document.scrollingElement.scrollTop+=pixels;
  const card=document.elementFromPoint(prepAutoScroll.x,prepAutoScroll.y)?.closest('.prep-card');
  document.querySelectorAll('.prep-drop-before,.prep-drop-after').forEach(c=>c.classList.remove('prep-drop-before','prep-drop-after'));
  if(card&&card.dataset.prepField===prepDrag.field){const r=card.getBoundingClientRect();card.classList.add(prepAutoScroll.y<r.y+r.height/2?'prep-drop-before':'prep-drop-after')}
 }
 prepAutoScroll.frame=requestAnimationFrame(prepAutoScrollStep);
}
document.addEventListener('dragover',prepTrackAutoScroll);
document.addEventListener('drop',()=>{prepStopAutoScroll();prepDrag=null;prepClearDrop()});
document.addEventListener('dragend',()=>{prepStopAutoScroll();prepDrag=null;prepClearDrop()});
document.addEventListener('dragleave',e=>{if(e.clientX<=0||e.clientX>=innerWidth||e.clientY<=0||e.clientY>=innerHeight)prepStopAutoScroll()});
window.addEventListener('blur',prepStopAutoScroll);window.addEventListener('pagehide',prepStopAutoScroll);
document.addEventListener('visibilitychange',()=>{if(document.hidden)prepStopAutoScroll()});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){prepStopAutoScroll();prepDrag=null;prepClearDrop()}});

let prepSectionMenuField=null;
function prepOpenSectionMenu(field,x,y){
 if(prep.saving)return;prepCloseMenu();prepSectionMenuField=field;const m=$('#prepSectionMenu');m.hidden=false;
 const layout=prepLayoutEntries(),entry=layout.find(e=>e.field===field),i=layout.findIndex(e=>e.field===field);
 $('#prepSectionMoveUp').disabled=!layout.slice(0,i).some(e=>entry.column==='both'||e.column===entry.column||e.column==='both');
 $('#prepSectionMoveDown').disabled=!layout.slice(i+1).some(e=>entry.column==='both'||e.column===entry.column||e.column==='both');
 for(const column of ['left','right','both'])m.querySelector(`[data-section-column="${column}"]`).disabled=entry.column===column;
 $('#prepSectionRename').hidden=!field.startsWith('extra:');m.style.left=Math.max(8,Math.min(x,innerWidth-m.offsetWidth-8))+'px';m.style.top=Math.max(8,Math.min(y,innerHeight-m.offsetHeight-8))+'px';m.querySelector('button:not(:disabled)').focus();
}
async function prepChangeSection(field,{column,direction}={}){
 if(prep.saving)return;if(prep.editing)prepCapture();const d=prepDraft(),layout=prepLayoutEntries(d),i=layout.findIndex(e=>e.field===field);if(i<0)return;const entry=layout[i];
 if(direction){let j=i+direction;while(j>=0&&j<layout.length&&entry.column!=='both'&&layout[j].column!==entry.column&&layout[j].column!=='both')j+=direction;if(j<0||j>=layout.length)return;layout.splice(i,1);layout.splice(j,0,entry)}
 let columns=d.card_columns;
 if(column){layout[i]={...entry,column};if(column==='both'&&entry.column!=='both')columns={...columns,[field]:prepSections(prepField(d,field)).map((_,n)=>n%2?'right':'left')}}
 prep.drafts.set(prep.selected,{...d,section_layout:layout,...(columns?{card_columns:columns}:{})});renderPrep();await prepSave();
}
$('#prepSectionMenu').onclick=e=>{const button=e.target.closest('button');if(!button||button.disabled)return;const field=prepSectionMenuField;prepCloseMenu();if(button.id==='prepSectionRename')return prepOpenSection(field.slice(6));if(button.dataset.sectionColumn)return prepChangeSection(field,{column:button.dataset.sectionColumn});prepChangeSection(field,{direction:button.id==='prepSectionMoveUp'?-1:1})};
$('#prepColumns').addEventListener('contextmenu',e=>{if(e.target.closest('.prep-card'))return;const heading=e.target.closest('.prep-section-heading');if(heading){e.preventDefault();prepOpenSectionMenu(heading.closest('[data-prep-section]').dataset.prepSection,e.clientX,e.clientY)}});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('#prepSectionMenu').hidden){e.stopImmediatePropagation();prepCloseMenu()}},true);

for(const side of ['left','right'])$('#prepCardMenu').querySelector(`[data-card-column="${side}"]`).onclick=()=>{const target=prepMenuTarget;prepCloseMenu();if(target)prepDropCard(target,{side,to:target.index})};
