// Launch test: starts the packaged app (bundled Python backend + Electron UI) in smoke mode and checks it reported success.
import {spawn} from 'node:child_process';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
const exe={darwin:'release/mac-arm64/JobTracker.app/Contents/MacOS/JobTracker',win32:'release/win-unpacked/JobTracker.exe',linux:'release/linux-unpacked/jobtracker'}[process.platform];
if(!exe||!fs.existsSync(exe))throw Error('Packaged app not found: '+exe+'. Build it first.');
const result=path.join(fs.mkdtempSync(path.join(os.tmpdir(),'jobtracker-smoke-')),'result.txt');
const child=spawn(path.resolve(exe),[],{stdio:'inherit',env:{...process.env,WAYPOINT_SMOKE:'1',WAYPOINT_SMOKE_RESULT:result}});
const timer=setTimeout(()=>{child.kill();console.error('Smoke test timed out after 120 s.');process.exit(1);},120000);
child.on('exit',code=>{
 clearTimeout(timer);
 const text=fs.existsSync(result)?fs.readFileSync(result,'utf8'):'no result written';
 console.log('Smoke test:',text,'(exit code '+code+')');
 process.exit(text.startsWith('ok ')?0:1);
});
