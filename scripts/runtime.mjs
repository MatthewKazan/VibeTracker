import fs from 'node:fs/promises';import path from 'node:path';import crypto from 'node:crypto';import {execFileSync} from 'node:child_process';
const target=process.argv[2]||({darwin:'mac',win32:'win',linux:'linux'}[process.platform]+'-'+process.arch);
const manifest=JSON.parse(await fs.readFile(new URL('runtimes.json',import.meta.url)));const entry=manifest[target];if(!entry)throw Error('Unsupported target '+target);
await fs.mkdir('work/downloads',{recursive:true});const archive=path.resolve(`work/downloads/python-${target}.tar.gz`);
try{await fs.access(archive);}catch{const response=await fetch(entry.url);if(!response.ok)throw Error('Runtime download '+response.status);await fs.writeFile(archive,Buffer.from(await response.arrayBuffer()));}
const digest=crypto.createHash('sha256').update(await fs.readFile(archive)).digest('hex');if(digest!==entry.sha256)throw Error('Python runtime checksum mismatch');
await fs.rm('build/runtime',{recursive:true,force:true});await fs.mkdir('build/runtime',{recursive:true});execFileSync('tar',['-xzf',archive,'--strip-components=1','-C','build/runtime'],{stdio:'inherit'});await fs.writeFile('build/runtime-target.txt',target);console.log('Verified Python runtime: '+target);
