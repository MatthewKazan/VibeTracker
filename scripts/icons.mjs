import sharp from 'sharp';import fs from 'node:fs/promises';import {execFileSync} from 'node:child_process';
await fs.mkdir('build/icons',{recursive:true});const source=await fs.readFile('build/icon.svg');
for(const size of [16,24,32,48,64,128,256,512,1024])await sharp(source).resize(size,size).png().toFile(`build/icons/${size}x${size}.png`);
await fs.copyFile('build/icons/1024x1024.png','build/icon.png');
const sizes=[16,32,48,64,128,256];const buffers=await Promise.all(sizes.map(n=>fs.readFile(`build/icons/${n}x${n}.png`)));const header=Buffer.alloc(6+16*sizes.length);header.writeUInt16LE(1,2);header.writeUInt16LE(sizes.length,4);let offset=header.length;
sizes.forEach((n,i)=>{const p=6+i*16;header[p]=n===256?0:n;header[p+1]=n===256?0:n;header.writeUInt16LE(1,p+4);header.writeUInt16LE(32,p+6);header.writeUInt32LE(buffers[i].length,p+8);header.writeUInt32LE(offset,p+12);offset+=buffers[i].length;});await fs.writeFile('build/icon.ico',Buffer.concat([header,...buffers]));
// ICNS entries contain PNGs, so this works on all build hosts.
const entries=[];for(const [type,size] of [['ic07',128],['ic08',256],['ic09',512],['ic10',1024]]){const bytes=await fs.readFile(`build/icons/${size}x${size}.png`);const h=Buffer.alloc(8);h.write(type);h.writeUInt32BE(bytes.length+8,4);entries.push(h,bytes);}const h=Buffer.alloc(8);h.write('icns');h.writeUInt32BE(8+entries.reduce((n,b)=>n+b.length,0),4);await fs.writeFile('build/icon.icns',Buffer.concat([h,...entries]));
