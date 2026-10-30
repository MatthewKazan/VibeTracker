(function(root){
function build(jobs){
 const nodes=new Map(),links=new Map(),round=s=>Math.min(100,Number(/^Interview (\d+)$/i.exec(s||'')?.[1]||0));let inferredJobs=0,restartedJobs=0;
 const add=name=>{const id=JSON.stringify(['status',name]);if(!nodes.has(id))nodes.set(id,{id,name,current:0});return id;};
 const origin='applications';nodes.set(origin,{id:origin,name:'Applications',current:jobs.length,root:true});
 for(const job of jobs){const raw=String(job.status||'Waiting'),current=round(raw)?'Interview '+round(raw):raw,history=Array.isArray(job.status_history)?job.status_history.map(String):[],r=round(current),known=Math.max(0,...history.map(round)),highest=Math.min(100,Math.max(known,Number(job.interviews_completed)||0)),n=current==='Waiting'?0:r||highest;
 if((current==='Waiting'&&highest)||(r&&highest>r))restartedJobs++;
 const offer=['Offer','Accepted','Offer declined'].includes(current)||(!r&&current!=='Waiting'&&history.includes('Offer'));
 const path=[origin,...Array.from({length:n},(_,i)=>add('Interview '+(i+1)))];if(offer)path.push(add('Offer'));const end=add(current);if(path.at(-1)!==end)path.push(end);nodes.get(end).current++;
 let inferred=false;
 for(let i=1;i<path.length;i++){const from=path[i-1],to=path[i],fromName=nodes.get(from).name,toName=nodes.get(to).name,observed=from===origin?history[0]===toName||history.find(s=>s!=='Waiting')===toName||toName==='Waiting':history.some((s,k)=>s===fromName&&history.slice(k+1).find(x=>x!==s)===toName);const key=JSON.stringify([from,to]);if(!links.has(key))links.set(key,{source:from,target:to,value:0,inferred:0});links.get(key).value++;if(!observed){links.get(key).inferred++;inferred=true;}}
 if(inferred)inferredJobs++;
 }
 return {nodes:[...nodes.values()],links:[...links.values()],total:jobs.length,inferredJobs,restartedJobs};
}
const api={build};if(typeof module!=='undefined')module.exports=api;else root.jobSankey=api;
})(globalThis);
