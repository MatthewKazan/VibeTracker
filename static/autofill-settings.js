let autofillRulesLoaded=false,autofillRulesDirty=false,autofillDefaults=[];
async function loadAutofillRules(){
 if(autofillRulesLoaded||autofillRulesDirty)return;
 try{const data=await api('extraction-rules');autofillDefaults=data.defaults;if(!autofillRulesDirty){$('#autofillRules').value=JSON.stringify(data.rules,null,2);autofillRulesLoaded=true}}
 catch(e){$('#autofillRulesStatus').textContent=e.message}
}
$('#autofillRulesPanel').addEventListener('toggle',()=>{if($('#autofillRulesPanel').open)loadAutofillRules()});
$('#autofillRules').oninput=()=>{autofillRulesDirty=true;$('#autofillRulesStatus').textContent='Unsaved rules. Preview them before saving.'};
$('#autofillRulesDefaults').onclick=async()=>{try{const data=await api('extraction-rules');autofillDefaults=data.defaults;$('#autofillRules').value=JSON.stringify(autofillDefaults,null,2);autofillRulesLoaded=true;autofillRulesDirty=true;$('#autofillRulesStatus').textContent='Built-in rules loaded into the editor. Save to apply them.'}catch(e){$('#autofillRulesStatus').textContent=e.message}};
$('#autofillRulesSave').onclick=async()=>{
 const button=$('#autofillRulesSave');button.disabled=true;
 try{const value=$('#autofillRules').value,rules=JSON.parse(value);await api('settings',{extraction_rules:rules});state.settings.extraction_rules=rules;autofillRulesDirty=$('#autofillRules').value!==value;$('#autofillRulesStatus').textContent=autofillRulesDirty?'Saved the submitted rules. Your newer edits are not saved yet.':'Saved. The next Autofill uses these rules immediately; no rebuild or restart needed.'}
 catch(e){$('#autofillRulesStatus').textContent=e.message}
 finally{button.disabled=false}
};
$('#autofillRulesPreview').onclick=async()=>{
 const button=$('#autofillRulesPreview');button.disabled=true;$('#autofillRulesResult').textContent='Reading the posting with the rules in this editor…';
 try{const rules=JSON.parse($('#autofillRules').value),result=await api('extraction-rules/preview',{rules,url:$('#autofillRulesURL').value.trim()});$('#autofillRulesResult').textContent=`${result.source}\n\nTitle: ${result.title||'(not found)'}\nCompany: ${result.company||'(not found)'}\nLocation: ${result.location||'(not found)'}${result.warning?'\nReview: '+result.warning:''}\n\nJob description:\n${result.description||'(not found)'}`}
 catch(e){$('#autofillRulesResult').textContent=e.message}
 finally{button.disabled=false}
};
