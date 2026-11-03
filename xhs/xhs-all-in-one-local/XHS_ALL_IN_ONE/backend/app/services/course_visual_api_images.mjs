// No network. Preserve the complete API bitmap; add the real logo and exact identity locally.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);let sharp;
try{sharp=require('sharp');}catch{sharp=createRequire(path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/'))('sharp');}
const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
try{
 const input=JSON.parse(await fs.readFile(process.argv[2],'utf8')),out=process.argv[3];
 const source=await fs.readFile(input.source),logo=await fs.readFile(input.logo);
 const uri=async bytes=>`data:image/${(await sharp(bytes).metadata()).format};base64,${bytes.toString('base64')}`;
 async function fitted(s,start,min){for(let size=start;size>=min;size--){const m=await sharp({text:{text:esc(s),font:`Hiragino Sans GB Bold ${size}`,dpi:72,rgba:true}}).metadata();if(m.width<=884)return size;}throw Error('Identity cannot fit without unreadably small type');}
 const schoolSize=await fitted(input.university,52,40),codeSize=await fitted(input.course_code,84,56);
 const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1440" viewBox="0 0 1080 1440">
 <rect width="1080" height="1440" fill="#ffffff"/>
 <rect x="60" y="12" width="960" height="172" rx="16" fill="#0755A2"/>
 <text x="98" y="76" font-family="Hiragino Sans GB, Arial Unicode MS, sans-serif" font-size="${schoolSize}" font-weight="700" fill="#ffffff">${esc(input.university)}</text>
 <path d="M98 94H982" stroke="#F58A25" stroke-width="3"/>
 <text x="98" y="164" font-family="Hiragino Sans GB, Arial Unicode MS, sans-serif" font-size="${codeSize}" font-weight="700" fill="#ffffff">${esc(input.course_code)}</text>
 <image href="${await uri(source)}" x="60" y="198" width="960" height="1064" preserveAspectRatio="xMidYMid meet"/>
 <image href="${await uri(logo)}" x="466" y="1284" width="148" height="148" preserveAspectRatio="xMidYMid meet"/>
 </svg>`;
 const file=`${input.slot}.png`,svgFile=`${input.slot}.svg`;
 await fs.writeFile(path.join(out,svgFile),svg,{flag:'wx'});
 await sharp(Buffer.from(svg)).png().toFile(path.join(out,file));
 process.stdout.write(JSON.stringify({file,svg_file:svgFile,school_font:schoolSize,course_font:codeSize}));
}catch{process.stdout.write(JSON.stringify({error:'Local composition failed; provider bytes and old artwork retained'}));process.exitCode=2;}
