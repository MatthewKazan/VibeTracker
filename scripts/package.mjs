import {execFileSync} from 'node:child_process';import fs from 'node:fs/promises';import path from 'node:path';
const [platform,arch]=process.argv.slice(2);if(!['mac','win','linux'].includes(platform)||!['arm64','x64'].includes(arch))throw Error('Specify mac|win|linux and arm64|x64');
execFileSync(process.execPath,['scripts/runtime.mjs',`${platform}-${arch}`],{stdio:'inherit'});
execFileSync(process.execPath,['scripts/icons.mjs'],{stdio:'inherit'});
execFileSync(process.execPath,['node_modules/electron-builder/out/cli/cli.js',`--${platform}`,`--${arch}`,'--publish','never',`-c.electronDownload.cache=${path.resolve('work/electron-cache')}`],{stdio:'inherit',env:{...process.env,CSC_IDENTITY_AUTO_DISCOVERY:'false'}});
