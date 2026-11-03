// JXA bridge: reads messages without marking them read or modifying Mail.
// Scan all account folders, including archived correspondence and Sent.
function run(argv) {
    let options=argv[4]?JSON.parse(argv[4]):null;
    if(argv[0]==='batch'){ObjC.import('Foundation');const data=JSON.parse($.NSString.stringWithContentsOfFileEncodingError(argv[1],$.NSUTF8StringEncoding,null).js);argv=data.argv;options=data.options;}
    const started=Date.now(),budget=options?Math.min(4000,options.budgetMs||4000):4000;
    const rest=()=>{if(typeof delay==='function')delay(0.15)};
    const expired=()=>Date.now()-started>=budget;
    const mail = Application('Mail');
    if(argv[0]==='accounts')return JSON.stringify(mail.accounts().map(a=>({id:a.id(),name:a.name(),addresses:a.emailAddresses()})));
    if(!argv[2])throw Error('Choose a job-search account before syncing Mail.');
    const accounts=mail.accounts().filter(a=>a.id()===argv[2]);
    if(accounts.length!==1)throw Error('The selected Mail account is unavailable. Choose it again in JobTracker.');
    // Never compete with the user actively working in Mail.
    const inUse=()=>{try{return typeof mail.frontmost==='function'&&mail.frontmost()}catch{return false}};
    if(inUse())return JSON.stringify(argv[0]==='bounds'?{oldest:null,folders:[],complete:false,deferred:true}:{messages:[],scanned:[],folders:[],complete:false,deferred:true});
    if(argv[0]==='bounds'){
        let oldest=null,complete=true,queries=0;const done=new Set(options?.folders||[]),folders=[];
        function visit(box,path=[]){
            if(expired()||queries>=12){complete=false;return;}
            const name=box.name(),key=JSON.stringify([...path,name]);
            if(/^(trash|deleted messages|drafts)$/i.test(name))return;
            if(!done.has(key)){
                queries++;for(const date of box.messages.dateReceived()){const value=new Date(date).getTime();if(Number.isFinite(value)&&value>0&&(oldest===null||value<oldest))oldest=value}
                folders.push(key);rest();
            }
            for(const child of box.mailboxes())visit(child,[...path,name]);
        }
        for(const account of accounts)for(const box of account.mailboxes())visit(box);
        return JSON.stringify({oldest:oldest===null?null:new Date(oldest).toISOString(),folders,complete});
    }
    const lower = new Date(new Date(argv[0]).getTime()-1), upper = new Date(argv[1]);
    const output = [], seen = new Set(), profiles=argv[3]?JSON.parse(argv[3]):[];
    const terms=[...new Set(profiles.reduce((all,p)=>all.concat(p.terms||[],p.domains||[]),[]))].filter(Boolean);
    const normalize=text=>String(text).normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}_]+/gu,' ').trim().replace(/\s+/g,' ');
    const names=terms.map(normalize).filter(Boolean);
    const matches=text=>{const normalized=' '+normalize(text)+' ',compact=normalized.replace(/\s/g,'');return names.some(name=>normalized.includes(' '+name+' ')||(name.length>=8&&compact.includes(name.replace(/\s/g,''))))};
    const cached=new Set(options?.seen||[]),finished=new Set(options?.folders||[]),folders=[],scanned=[];
    const maxBodies=options?Math.min(8,Math.max(1,options.maxBodies||8)):Infinity;
    const maxFolders=options?Math.min(12,Math.max(1,options.maxFolders||12)):Infinity;
    let complete=true,queries=0,deferred=false;
    function scan(box,path=[]) {
        if(options&&(expired()||scanned.length>=maxBodies||queries>=maxFolders)){complete=false;return;}
        const name=box.name(),key=JSON.stringify([...path,name]);
        if (/^(trash|deleted messages|drafts)$/i.test(name)) return;
        if(!finished.has(key)){
            const conditions=[{dateReceived:{_greaterThan:lower}},{dateReceived:{_lessThan:upper}}];
            const selection=box.messages.whose({_and:conditions});queries++;
            // Bulk IDs are metadata only. Bodies are fetched individually under
            // the strict page budget, and already-read bodies are never reloaded.
            const ids=options&&typeof selection.messageId==='function'?selection.messageId():null;
            const localIds=ids&&typeof selection.id==='function'?selection.id():null;
            const messages=ids?null:selection();
            const length=ids?ids.length:messages.length;
            let folderComplete=true;
            for(let index=0;index<length;index++){
                if(options&&(expired()||scanned.length>=maxBodies)){folderComplete=false;complete=false;break;}
                const m=localIds?box.messages.byId(localIds[index]):ids?selection[index]:messages[index],id=(ids?ids[index]:m.messageId())||('mail-local-'+argv[2]+'-'+m.id());
                if(seen.has(id)||cached.has(id))continue;
                if(options&&inUse()){deferred=true;folderComplete=false;complete=false;break;}
                const sender=m.sender(),subject=m.subject(),body=m.content(),received=m.dateReceived().toISOString();
                // An interrupted automation call cannot add progress to this page.
                scanned.push({message_id:id,received_at:received,body_complete:!!body.trim()});seen.add(id);rest();
                if(names.length&&!matches(sender+' '+subject+' '+body))continue;
                output.push({message_id:id,sender:sender,subject:subject,body:body.slice(0,2000000),received_at:received});
            }
            if(folderComplete)folders.push(key);
            if(!folderComplete)return;
        }
        for (const child of box.mailboxes())scan(child,[...path,name]);
    }
    // Fail the entire page on inaccessible folders; never silently advance it.
    for (const account of accounts)for(const box of account.mailboxes())scan(box);
    if(options)return JSON.stringify({messages:output,scanned,folders,complete,deferred});
    return JSON.stringify(output);
}
