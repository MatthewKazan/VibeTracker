// Only reproducible build outputs: never user data, models, sources or git history.
import fs from 'node:fs/promises';
import path from 'node:path';
const {version}=JSON.parse(await fs.readFile('package.json','utf8'));
const keep=new Set([`JobTracker-${version}-arm64.dmg`,`JobTracker-${version}-arm64.dmg.blockmap`,`JobTracker-${version}-arm64-mac.zip`,`JobTracker-${version}-arm64-mac.zip.blockmap`,'mac-arm64','latest-mac.yml','builder-debug.yml']);
for(const item of await fs.readdir('release',{withFileTypes:true}).catch(()=>[])){
 if(keep.has(item.name)||item.name.startsWith(`JobTracker-${version}-`)||item.name===version)continue;
 if(/^JobTracker-\d+\./.test(item.name)||/^\d+\.\d+\.\d+$/.test(item.name))await fs.rm(path.join('release',item.name),{recursive:true,force:true});
}
for(const folder of ['work/npm-cache','work/ui-electron','work/electron-cache','work/builder-cache/downloads'])await fs.rm(folder,{recursive:true,force:true});
console.log('Removed obsolete installers and regenerable build caches; kept current macOS release.');
