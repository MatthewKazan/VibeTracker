let learningGeneration=0,autofillBaseline=null,lastAutofillImprovement=null;
const learningFields=['title','company','location'],learningLabels={title:'job title',company:'company',location:'location'};
function learningValues(){const f=$('#jobForm');return Object.fromEntries(['url',...learningFields].map(k=>[k,f.elements[k].value.trim()]))}
window.resetAutofillLearning=function(){learningGeneration++;autofillBaseline=null;lastAutofillImprovement=null;$('#improveAutofill').disabled=false;$('#improveAutofill').textContent='Improve Autofill';$('#improveAutofillStatus').textContent='';$('#undoAutofillImprovement').hidden=true;$('#undoAutofillImprovement').disabled=false};
window.recordAutofillResult=function(result,url){autofillBaseline={url,...Object.fromEntries(learningFields.map(k=>[k,String(result[k]||'').trim()]))}};
$('#improveAutofill').onclick=async()=>{
 const button=$('#improveAutofill'),values=learningValues(),generation=++learningGeneration;
 const current=()=>generation===learningGeneration&&$('#jobDialog').open;
 const unchanged=()=>JSON.stringify(values)===JSON.stringify(learningValues());
 if(!values.url){$('#improveAutofillStatus').textContent='Enter the original posting URL, then correct any fields below.';return}
 const corrections=Object.fromEntries(learningFields.filter(k=>values[k]&&(!autofillBaseline||autofillBaseline.url!==values.url||values[k]!==autofillBaseline[k])).map(k=>[k,values[k]]));
 if(!Object.keys(corrections).length){$('#improveAutofillStatus').textContent='Correct the title, company or location first, then click Improve Autofill.';return}
 button.disabled=true;button.textContent='Checking the page…';$('#improveAutofillStatus').textContent='Looking for your corrected values. You can still save this application.';
 try{
  const proposal=await api('autofill/learn',{url:values.url,corrections});if(!current())return;
  if(!unchanged()){$('#improveAutofillStatus').textContent='Your fields changed while checking. Click Improve Autofill again to use the latest values.';return}
  const skipped=Object.entries(proposal.skipped).map(([k,reason])=>`${learningLabels[k]}: ${reason}`).join(' ');
  if(!proposal.token){$('#improveAutofillStatus').textContent='Nothing changed. '+skipped;return}
  const result=await api('autofill/learn/save',{token:proposal.token});if(!current())return;
  lastAutofillImprovement=result.id;$('#undoAutofillImprovement').hidden=false;
  if(unchanged()){autofillBaseline={...(autofillBaseline||{}),url:values.url};for(const k of result.fields)autofillBaseline[k]=values[k]}
  $('#improveAutofillStatus').textContent=`Improved ${result.fields.map(k=>learningLabels[k]).join(', ')} for similar pages on ${result.scope}. It will read each new job’s own values. ${skipped}`;
 }catch(e){if(current())$('#improveAutofillStatus').textContent=e.message+' Your application fields are unchanged.'}
 finally{if(current()){button.disabled=false;button.textContent='Improve Autofill'}}
};
$('#undoAutofillImprovement').onclick=async()=>{
 const id=lastAutofillImprovement,generation=learningGeneration,button=$('#undoAutofillImprovement');if(!id)return;button.disabled=true;
 try{await api('autofill/learn/undo',{id});if(generation!==learningGeneration)return;lastAutofillImprovement=null;autofillBaseline=null;button.hidden=true;$('#improveAutofillStatus').textContent='Improvement undone. Your application fields are unchanged.'}
 catch(e){if(generation===learningGeneration)$('#improveAutofillStatus').textContent=e.message}
 finally{button.disabled=false}
};
async function showLearnedAutofill(){
 try{const result=await api('extraction-rules');$('#learnedAutofillList').innerHTML=result.learned.length?result.learned.map(r=>`<div class="learned-autofill"><p><b>${esc(r.scope)}</b><br>${r.fields.map(k=>esc(learningLabels[k])).join(', ')}</p><button type="button" data-undo-learning="${esc(r.id)}">Remove improvement</button></div>`).join(''):'<p>No saved improvements yet. Correct fields in an application and click Improve Autofill to teach it.</p>'}
 catch(e){$('#learnedAutofillList').textContent=e.message}
}
$('#learnedAutofillList').onclick=async e=>{const button=e.target.closest('button');if(!button)return;if(!button.dataset.undoLearning){await showLearnedAutofill();return}button.disabled=true;try{await api('autofill/learn/undo',{id:button.dataset.undoLearning});await showLearnedAutofill()}catch(e){button.disabled=false;toast(e.message)}};
