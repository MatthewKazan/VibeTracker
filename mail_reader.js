// JXA bridge: reads messages without marking them read or modifying Mail.
// Scan all account folders, including archived correspondence and Sent.
function run(argv) {
    const mail = Application('Mail');
    if(argv[0]==='accounts')return JSON.stringify(mail.accounts().map(a=>({id:a.id(),name:a.name(),addresses:a.emailAddresses()})));
    if(!argv[2])throw Error('Choose a job-search account before syncing Mail.');
    const accounts=mail.accounts().filter(a=>a.id()===argv[2]);
    if(accounts.length!==1)throw Error('The selected Mail account is unavailable. Choose it again in JobTracker.');
    if(argv[0]==='bounds'){
        let oldest=null;function visit(box){if(/^(trash|deleted messages|drafts)$/i.test(box.name()))return;for(const date of box.messages.dateReceived()){const value=new Date(date).getTime();if(Number.isFinite(value)&&value>0&&(oldest===null||value<oldest))oldest=value}for(const child of box.mailboxes())visit(child)}
        for(const account of accounts)for(const box of account.mailboxes())visit(box);return JSON.stringify({oldest:oldest===null?null:new Date(oldest).toISOString()});
    }
    const lower = new Date(new Date(argv[0]).getTime()-1), upper = new Date(argv[1]);
    const output = [], seen = new Set(), profiles=argv[3]?JSON.parse(argv[3]):[];
    const terms=[...new Set(profiles.reduce((all,p)=>all.concat(p.terms||[],p.domains||[]),[]))].filter(Boolean);
    const normalize=text=>String(text).normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}_]+/gu,' ').trim().replace(/\s+/g,' ');
    const names=terms.map(normalize).filter(Boolean);
    const matches=text=>{const normalized=' '+normalize(text)+' ',compact=normalized.replace(/\s/g,'');return names.some(name=>normalized.includes(' '+name+' ')||(name.length>=8&&compact.includes(name.replace(/\s/g,''))))};
    function scan(box) {
        const name = box.name();
        if (/^(trash|deleted messages|drafts)$/i.test(name)) return;
        const conditions=[{dateReceived:{_greaterThan:lower}},{dateReceived:{_lessThan:upper}}];
        const messages = box.messages.whose({_and:conditions})();
        for (const m of messages) {
            const id = m.messageId() || ('mail-local-'+argv[2]+'-'+m.id());
            if (seen.has(id)) continue;
            // Read each body only once. Native multi-company content predicates
            // can make Mail reread the same rich text for every search term.
            const sender=m.sender(),subject=m.subject(),body=m.content();
            if(names.length&&!matches(sender+' '+subject+' '+body))continue;
            seen.add(id);
            // Keep the email rather than abort collection for an unusually long thread.
            output.push({message_id:id,sender:sender,subject:subject,body:body.slice(0,2000000),received_at:m.dateReceived().toISOString()});
        }
        for (const child of box.mailboxes()) scan(child);
    }
    // Fail the entire scan on inaccessible folders; never silently skip and advance.
    for (const account of accounts) for (const box of account.mailboxes()) scan(box);
    return JSON.stringify(output);
}
