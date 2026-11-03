import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { createRequire } from 'node:module';
import { wrapMeasuredText } from './course_visual_linebreak.mjs';
const require = createRequire(import.meta.url);
let sharp;
try { sharp = require('sharp'); }
catch { sharp = createRequire(path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/'))('sharp'); }
const input = JSON.parse(await fs.readFile(process.argv[2], 'utf8')), OUT = process.argv[3];
const { data, pages, source_images, logo, backgrounds = {} } = input;
const C = { blue: '#0755A2', ink: '#172F47', orange: '#F58A25', line: '#CEDDEB', pale: '#EFF5FB', muted: '#63798E' };
const FONT = 'Hiragino Sans GB, Arial Unicode MS, sans-serif';
const esc = s => String(s).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const rect = (x,y,w,h,fill='white',stroke='none',rx=0) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}" fill="${fill}" stroke="${stroke}" stroke-width="1.4"/>`;
const line = (x,y,x2,y2) => `<path d="M${x} ${y}L${x2} ${y2}" stroke="${C.line}" stroke-width="2" fill="none"/>`;
const caches = new Map(), measurements = new Map(); let texts = [], pictures = [];
async function uri(file) { if (!caches.has(file)) { const b=await fs.readFile(file),m=await sharp(b).metadata();caches.set(file,`data:image/${m.format};base64,${b.toString('base64')}`); } return caches.get(file); }
async function measure(s,n,w=400) { if(String(s)==='')return 0;const k=[s,n,w].join('|');if(!measurements.has(k)){const m=await sharp({text:{text:esc(s),font:`Hiragino Sans GB ${w>=700?'Bold ':''}${n}`,dpi:72,rgba:true}}).metadata();measurements.set(k,m.width||0);}return measurements.get(k); }
function t(x,y,s,n=36,color=C.ink,weight=400,anchor='start') { texts.push({x,y,s,n,weight,anchor});return `<text x="${x}" y="${y}" font-family="${FONT}" font-size="${n}" font-weight="${weight}" fill="${color}" text-anchor="${anchor}">${esc(s)}</text>`; }
async function paragraph(x,y,s,width=936,n=36,leading=50,color=C.ink,weight=400,bottom=1200,measureOnly=false) {
 const rows=await wrapMeasuredText(s,width,value=>measure(value,n,weight));
 const end=y+(rows.length-1)*leading;
 if(!measureOnly&&end>bottom)throw Error(`图内文字超出可读范围：该区域需要${rows.length}行，当前可容纳${Math.max(0,Math.floor((bottom-y)/leading)+1)}行；请调整该段布局或内容，旧图未被覆盖`);
 return {svg:measureOnly?'':rows.map((s,i)=>t(x,y+i*leading,s,n,color,weight)).join(''),end,rows:rows.length};
}
const paragraphSize=(s,width,n,leading,weight=400)=>paragraph(0,0,s,width,n,leading,C.ink,weight,Infinity,true);
async function image(file,x,y,w,h,record={}) { pictures.push({x,y,w,h,...record});return `<image href="${await uri(file)}" x="${x}" y="${y}" width="${w}" height="${h}" preserveAspectRatio="xMidYMid meet"/>`; }
async function paper(number,x,y,w,rotation=0) { const file=source_images[String(number)],m=await sharp(file).metadata(),h=w*m.height/m.width;return `<g transform="rotate(${rotation} ${x+w/2} ${y+h/2})" filter="url(#shadow)">${rect(x,y,w,h,'white','#D8E2EB')}${await image(file,x,y,w,h,{kind:'real_pdf',source_page:number,full_page:true,rotation})}</g>`; }
const defs = `<defs><filter id="shadow" x="-40%" y="-30%" width="180%" height="180%"><feGaussianBlur in="SourceAlpha" stdDeviation="13"/><feOffset dy="14"/><feComponentTransfer><feFuncA type="linear" slope="0.13"/></feComponentTransfer><feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>`;
const header = () => t(72,111,`${data.source.university} · ${data.source.course_code}`,31,C.blue,700)+line(72,132,1008,132);
async function footer() { return line(72,1315,426,1315)+line(654,1315,1008,1315)+await image(logo,465,1228,150,150,{kind:'real_brand_logo'}); }
const TEMPLATE_IDS = new Set(['question-led','decision-map','sample-led','magazine-a']);
function templateFor(page) {
 const id=page.template_id||'legacy';
 if(id!=='legacy'&&!TEMPLATE_IDS.has(id))throw Error('所选视觉模板不可用，请重新选择；旧图保留');
 return id;
}
function checkDensity(page,value,label,compact,standard) {
 if(Array.from(String(value)).length>(page.density==='compact'?compact:standard))throw Error(`${label}超过当前信息密度，请精简文字或选择标准密度；不会缩小字体硬塞，旧图保留`);
}
function contentSample() {
 const explicit=data.visual_plan.cover_sample_page;
 const number=explicit==null?data.visual_plan.sample_pages.find(n=>Number(n)>1&&source_images[String(n)]):explicit;
 if(!Number.isInteger(number)||number<2||number>data.source.page_count||!source_images[String(number)])throw Error('请在“图片规划与制作”的“封面正文样张”选择第2页及以后的有效正文样页，保存方案后再制作；旧文案和旧图均保留');
 return number;
}
async function fittedPaper(number,x,y,maxWidth,maxHeight) {
 const meta=await sharp(source_images[String(number)]).metadata();
 return paper(number,x,y,Math.min(maxWidth,maxHeight*meta.width/meta.height));
}
function coverSchool() { return t(72,111,data.source.university,31,C.blue,700); }
async function modernCover(page,template) {
 const number=contentSample();checkDensity(page,page.title,'封面标题',22,26);
 let b=coverSchool();
 if(template==='question-led') {
  b+=t(72,207,data.source.course_code,86,C.blue,700)+rect(72,239,936,4,C.orange);
  const headline=await paragraph(72,350,page.title,936,88,102,C.ink,700,452);b+=headline.svg;
  const subtitle=await paragraph(76,518,page.subtitle||'',920,34,46,C.ink,400,610);b+=subtitle.svg;
  const shift=subtitle.rows?Math.max(0,subtitle.end-564):0;
  b+=rect(72,617+shift,8,112,C.orange)+t(100,660+shift,'真实讲义',42,C.ink,700);
  b+=(await paragraph(100,716+shift,data.source.material_type,330,34,45,C.blue,700,761+shift)).svg;
  b+=await fittedPaper(1,138,790+shift,260,350-shift);
  b+=await fittedPaper(number,504,583+shift,504,585-shift);
  b+=t(72,1206,`${data.source.page_count} 页 PDF · 先看内容，再判断是否适合`,28,C.muted);
 } else if(template==='decision-map') {
  b+=t(72,205,data.source.course_code,72,C.blue,700);
  b+=(await paragraph(72,313,page.title,936,76,92,C.ink,700,405)).svg;
  const subtitle=await paragraph(76,455,page.subtitle||'',932,32,42,C.ink,400,539);b+=subtitle.svg;
  const nodes=page.nodes?.length?page.nodes.slice(0,3):['了解内容｜先看真实样张与讲解方式','核对需要｜对照自己的课程材料与当前疑问','判断适合｜确认讲义是否符合复习需要'];
  if(page.nodes?.length>3)throw Error('判断模板最多展示3个有内容的节点，请精简；旧图保留');
  const cards=[];
  for(const value of nodes){
   const [heading,...rest]=String(value).split('｜'),description=rest.join('｜');
   checkDensity(page,heading+description,'判断节点',42,54);
   const head=await paragraphSize(heading,370,38,43,700),body=await paragraphSize(description,370,36,42);
   cards.push({heading,description,height:subtitle.rows>1?Math.max(138,47+head.end+(body.rows?43+body.end:0)+24):198});
  }
  let top=subtitle.rows?Math.max(507,subtitle.end+52):507,gap=24;
  const required=cards.reduce((sum,card)=>sum+card.height,0);
  if(top+required+gap*(cards.length-1)>1178)gap=18;
  if(top+required+gap*(cards.length-1)>1178)throw Error('封面副标题与判断节点合计超出可读空间，请精简重复说明；文字和旧图均保留');
  for(let i=0;i<cards.length;i++) {
   const {heading,description,height}=cards[i];
   b+=rect(72,top,422,height,i%2?'white':C.pale,C.line,12)+rect(72,top,6,height,i===nodes.length-1?C.orange:C.blue);
   const head=await paragraph(98,top+47,heading,370,38,43,C.blue,700,top+90);b+=head.svg;
   if(description)b+=(await paragraph(98,head.end+43,description,370,36,42,C.ink,400,top+height-16)).svg;
   if(i<nodes.length-1)b+=`<path d="M283 ${top+height+6}V${top+height+gap-6}M278 ${top+height+gap-11}L283 ${top+height+gap-6}L288 ${top+height+gap-11}" stroke="${C.orange}" stroke-width="3" fill="none"/>`;
   top+=height+gap;
  }
  const paperTop=subtitle.rows?Math.max(532,subtitle.end+77):532;
  b+=await fittedPaper(number,548,paperTop,460,1178-paperTop);
 } else {
  b+=t(72,205,data.source.course_code,72,C.blue,700);
  b+=(await paragraph(72,313,page.title,936,76,92,C.ink,700,405)).svg;
  b+=line(72,440,1008,440);
  b+=t(72,514,'先看真实内容',40,C.blue,700)+rect(72,535,76,5,C.orange);
  const subtitle=await paragraph(72,607,page.subtitle||'',344,36,49,C.ink,400,999);b+=subtitle.svg;
  const countY=subtitle.rows?Math.max(980,subtitle.end+64):980;
  b+=t(72,countY,`${data.source.page_count} 页 PDF`,36,C.blue,700);
  b+=(await paragraph(72,Math.max(1042,countY+62),data.source.material_type,344,36,49,C.ink,700,1140)).svg;
  b+=await fittedPaper(number,474,477,534,705);
 }
 return b;
}
async function modernMethod(page) {
 checkDensity(page,page.text,'方法页说明',110,200);
 let b=header();const title=await paragraph(72,228,page.title,936,62,80,C.ink,700,310);b+=title.svg;
 const subtitle=await paragraph(76,Math.max(374,title.end+64),page.subtitle||'',936,32,42,C.ink,400,458);b+=subtitle.svg;
 const start=Math.max(465,subtitle.rows?subtitle.end+68:title.end+96);
 if((page.layout==='flow'||page.layout==='comparison')&&page.nodes?.length>=2) {
  if(page.nodes.length>3)throw Error('当前方法模板最多展示3个节点，请分清本页重点；旧图保留');
  const cards=[];
  for(const value of page.nodes){
   const [heading,...rest]=String(value).split('｜'),description=rest.join('｜');
   const head=await paragraphSize(heading,246,38,46,700),body=await paragraphSize(description,606,36,44);
   cards.push({heading,description,height:Math.max(108,61+head.end+30,body.rows?56+body.end+30:0)});
  }
  const body=await paragraphSize(page.text,928,36,49);
  let gap=32,bodyGap=64;
  const endAt=()=>start+cards.reduce((sum,c)=>sum+c.height,0)+gap*(cards.length-1)+bodyGap+body.end;
  if(endAt()>1178){gap=24;bodyGap=40;}
  if(endAt()>1178)throw Error('方法说明与节点合计超出本页可读空间，请减少重复说明或调整节点；文字和旧图均保留');
  let top=start;
  for(let i=0;i<cards.length;i++) {
   const {heading,description,height}=cards[i];
   b+=rect(72,top,936,height,i%2?'white':C.pale,C.line,10);
   b+=(await paragraph(98,top+61,heading,246,38,46,C.blue,700,top+height-24)).svg;
   if(description)b+=(await paragraph(374,top+56,description,606,36,44,C.ink,400,top+height-24)).svg;
   if(i<cards.length-1)b+=t(540,top+height+gap/2+8,page.layout==='flow'?'↓':'↔',22,C.orange,700,'middle');
   top+=height+(i<cards.length-1?gap:0);
  }
  b+=(await paragraph(76,top+bodyGap,page.text,928,36,49,C.ink,400,1178)).svg;
 } else b+=(await paragraph(76,Math.max(478,start),page.text,928,38,55,C.ink,400,1164)).svg;
 return b;
}
async function modernSample(page) {
 let b=header();const title=await paragraph(72,201,page.title,936,52,64,C.ink,700,329);b+=title.svg;
 const caption=await paragraph(92,title.end+45,page.subtitle||'',916,32,42,C.ink,400,490);b+=rect(72,title.end+19,5,32,C.orange)+caption.svg;
 const top=(caption.rows?caption.end:title.end+45)+18;
 const file=source_images[String(page.source_page)],meta=await sharp(file).metadata();
 const maxHeight=Math.min(944,1208-top),width=Math.min(936,maxHeight*meta.width/meta.height),height=width*meta.height/meta.width,x=(1080-width)/2;
 if(height<700)throw Error('样张说明占用过多空间，请调整说明；完整PDF样张和旧图保留');
 b+=rect(x,top,width,height,'white','#DFE7EF')+await image(file,x,top,width,height,{kind:'real_pdf',source_page:page.source_page,full_page:true});
 b+=`<text x="540" y="${top+height-76}" text-anchor="middle" transform="rotate(-18 540 ${top+height-76})" font-family="${FONT}" font-size="31" font-weight="700" fill="${C.blue}" opacity="0.13">星途留学 · 资料预览</text>`;
 return b;
}
async function modernUse(page,template) {
 const number=contentSample();checkDensity(page,page.text,'资料使用说明',88,150);
 if(page.nodes.length>5)throw Error('使用路线最多5项，请精简；旧图保留');
 let b=header();const title=await paragraph(72,228,page.title,936,66,82,C.ink,700,474);b+=title.svg;
 const sourceY=Math.max(374,title.end+64);b+=t(76,sourceY,`${data.source.page_count} 页 PDF · ${data.source.material_type}`,34);
 const sampleLeft=template==='sample-led',textX=sampleLeft?460:124,textWidth=sampleLeft?548:520,dotX=sampleLeft?424:88;
 let next=Math.max(510,sourceY+60),last=next;
 for(let i=0;i<page.nodes.length;i++) {
  const y=next;
  checkDensity(page,page.nodes[i],'使用路线',26,40);
  const size=await paragraphSize(page.nodes[i],textWidth,36,42);last=y+size.end;next=y+Math.max(88,size.end+48);
  b+=`<circle cx="${dotX}" cy="${y-12}" r="7" fill="${i===page.nodes.length-1?C.orange:C.blue}"/>`;
  if(i<page.nodes.length-1)b+=line(dotX,y+15,dotX,next-30);
  b+=(await paragraph(textX,y,page.nodes[i],textWidth,36,42,C.ink,400,936)).svg;
 }
 const divider=Math.max(962,last+52),sampleTop=Math.max(477,sourceY+38);
 b+=await fittedPaper(number,sampleLeft?72:700,sampleTop,sampleLeft?300:308,Math.min(426,divider-sampleTop-36));
 b+=line(72,divider,1008,divider);
 b+=(await paragraph(72,divider+68,page.text,936,38,54,C.ink,400,1140)).svg;
 b+=t(72,1190,'资料用于学习辅助；考试范围以本学期学校 LMS 为准。',26,C.muted);
 return b;
}
// A is the selected wide editorial master. It uses only the current brief's
// course identity and explanation; ACC1001 examples never become defaults.
const A = {line:'#CBDCEA',pale:'#F0F6FB',warm:'#FFF5EA',muted:'#5C7082'};
const aLine = (x,y,x2,y2,color=A.line,width=2) => `<path d="M${x} ${y}L${x2} ${y2}" stroke="${color}" stroke-width="${width}" fill="none"/>`;
function aHeader(cover=false) {
 return t(72,92,data.source.university,40,C.blue,700)
  +(cover?'':t(1008,92,data.source.course_code,44,C.blue,700,'end'))+aLine(72,122,1008,122);
}
async function aFooter() {
 return aLine(72,1348,424,1348)+aLine(656,1348,1008,1348)
  +await image(logo,466,1265,148,148,{kind:'real_brand_logo'});
}
function aNode(value) {
 const [heading,...rest]=String(value).split('｜');
 if(!heading.trim())throw Error('A版讲解模块需要有意义的标题；空白不会替代真实内容，旧图保留');
 return {heading:heading.trim(),description:rest.join('｜').trim()};
}
const aClauses = value => String(value).replace(/([。；])\s*(?=\S)/gu,'$1\n');
async function magazineCover(page) {
 checkDensity(page,page.title,'A版封面标题',26,32);
 let b=aHeader(true)+t(72,230,data.source.course_code,94,C.blue,700);
 const headline=await paragraph(72,340,page.title,936,80,95,C.ink,700,435);b+=headline.svg;
 const subtitle=await paragraph(76,502,page.subtitle||'',928,34,46,A.muted,400,548);b+=subtitle.svg;
 const nodes=page.nodes||[];
 if(nodes.length>3)throw Error('A版封面最多3个有内容的讲解模块；请减少重复内容，旧图保留');
 const top=subtitle.rows?Math.max(557,subtitle.end+55):557;
 if(nodes.length===2) {
  for(let i=0;i<2;i++) {
   const {heading,description}=aNode(nodes[i]),x=72+i*480;
   // Emphasize a result only when it is already explicitly supplied as an
   // equality in the brief. The renderer never calculates or invents values.
   const given=description.match(/^(.+?)[；;]\s*([^；;，,]+?=\s*([$¥]?-?\d+(?:\.\d+)?%?))(.*)$/u);
   b+=rect(x,top,456,given?416:366,i?A.warm:A.pale,'none',10);
   const head=await paragraph(x+29,top+57,heading,398,34,46,C.blue,700,top+103);b+=head.svg;
   if(given&&head.rows===1) {
    b+=(await paragraph(x+29,top+109,given[1],398,34,46,C.ink,700,top+155)).svg;
    b+=t(x+29,top+230,given[3],94,i?C.orange:C.blue,700);
    b+=(await paragraph(x+29,top+289,given[2],398,32,44,C.ink,400,top+333)).svg;
    const rest=given[4].replace(/^[，,；;]\s*/u,'');
    if(rest)b+=(await paragraph(x+29,top+350,rest,398,30,42,C.ink,400,top+396)).svg;
   } else if(description)b+=(await paragraph(x+29,Math.max(top+128,head.end+61),description,398,36,52,C.ink,400,top+328)).svg;
  }
 } else if(nodes.length) {
  let next=top;
  for(let i=0;i<nodes.length;i++) {
   const {heading,description}=aNode(nodes[i]);
   const head=await paragraphSize(heading,884,38,48,700),body=await paragraphSize(description,884,34,49);
   const height=47+head.end+(body.rows?54+body.end:0)+28;
   if(next+height>1108)throw Error('A版封面讲解超出可读空间；请精简模块，旧图保留');
   b+=rect(72,next,936,height,i%2?'white':A.pale,'none',8)+rect(72,next,6,height,i===nodes.length-1?C.orange:C.blue);
   b+=(await paragraph(98,next+47,heading,884,38,48,C.blue,700,next+height-24)).svg;
   if(description)b+=(await paragraph(98,next+47+head.end+54,description,884,34,49,C.ink,400,next+height-24)).svg;
   next+=height+24;
  }
 } else if(page.text?.trim()) {
  b+=(await paragraph(76,top+62,page.text,928,38,56,C.ink,400,1108)).svg;
 }
 const material=data.source.material_type||'课程资料';
 b+=rect(72,1140,936,88,A.pale,'none',8);
 b+=(await paragraph(96,1192,material,888,34,46,C.blue,700,1192)).svg;
 return b;
}
async function aMethodLayout(page,{adaptiveHeader=false,compactRows=false,columns=(page.nodes||[]).length>=4}={}) {
 // Measure the entire page before drawing it. Typography never shrinks to fit.
 const title=await paragraphSize(page.title,936,70,85,700);
 const subtitle=await paragraphSize(page.subtitle||'',928,34,51);
 const titleY=adaptiveHeader?198:219,titleBottom=titleY+title.end;
 const subtitleY=adaptiveHeader?titleBottom+54:377;
 const subtitleBottom=subtitleY+subtitle.end;
 if(!adaptiveHeader&&(titleBottom>304||subtitleBottom>428))return null;
 const top=adaptiveHeader?(subtitle.rows?subtitleBottom+56:titleBottom+88):(subtitle.rows?Math.max(474,subtitleBottom+54):Math.max(400,titleBottom+80));
 const cards=[];
 const headSize=(page.nodes||[]).length>=4?38:40;
 let headWidth=244;
 if(columns&&adaptiveHeader)for(const node of (page.nodes||[]).map(aNode))headWidth=Math.max(headWidth,Math.min(328,Math.ceil((await measure(node.heading,headSize,700))/8)*8));
 const detailWidth=928-headWidth-30,detailX=76+headWidth+30;
 const headY=compactRows?44:62,detailY=compactRows?44:58;
 for(const node of (page.nodes||[]).map(aNode)) {
  const description=columns?node.description:aClauses(node.description);
  const head=await paragraphSize(node.heading,columns?headWidth:928,columns?headSize:40,50,700),detail=await paragraphSize(description,columns?detailWidth:928,34,49);
  const height=compactRows?(columns?Math.max(104,headY+head.end+30,detail.rows?detailY+detail.end+30:0):headY+head.end+(detail.rows?54+detail.end:0)+30)
   :(columns?Math.max(128,62+head.end+30,detail.rows?58+detail.end+34:0):62+head.end+(detail.rows?58+detail.end:0)+50);
  cards.push({...node,description,head,detail,height});
 }
 const tail=await paragraphSize(page.text||'',928,34,51);
 const tailY=top+cards.reduce((sum,node)=>sum+node.height,0)+(cards.length?18:0);
 const contentBottom=tail.rows?tailY+tail.end:top+cards.reduce((sum,node)=>sum+node.height,0);
 return {titleY,subtitleY,titleBottom,subtitleBottom,top,columns,headSize,headWidth,detailWidth,detailX,headY,detailY,cards,tail,tailY,contentBottom,
  profile:compactRows?'adaptive-rows':adaptiveHeader?'adaptive-header':'original'};
}
async function magazineMethod(page) {
 const nodes=(page.nodes||[]).map(aNode);
 if(nodes.length>5)throw Error('A版内页最多5个讲解段落，请减少重复内容；旧图保留');
 const candidates=[await aMethodLayout(page),await aMethodLayout(page,{adaptiveHeader:true})];
 if(nodes.length)candidates.push(await aMethodLayout(page,{adaptiveHeader:true,compactRows:true,columns:true}));
 const fitted=candidates.find(layout=>layout&&layout.contentBottom<=1208&&layout.titleBottom<=1208&&layout.subtitleBottom<=1208);
 if(!fitted)throw Error('A版内页文字超出可读范围：已按实测字宽调整标题间距和节点布局，完整内容仍超过单页容量；不会缩小字号、裁切文字或覆盖旧图');
 const {columns,cards,tail,headSize,headWidth,detailWidth,detailX,headY,detailY}=fitted;let top=fitted.top;
 let b=aHeader();
 b+=(await paragraph(72,fitted.titleY,page.title,936,70,85,C.ink,700,1208)).svg;
 b+=(await paragraph(76,fitted.subtitleY,page.subtitle||'',928,34,51,A.muted,400,1208)).svg;
 for(let i=0;i<cards.length;i++) {
  const node=cards[i];b+=aLine(72,top,1008,top,i===0?C.orange:A.line,i===0?3:2);
  b+=(await paragraph(76,top+headY,node.heading,columns?headWidth:928,columns?headSize:40,50,C.blue,700,1208)).svg;
  if(node.detail.rows)b+=(await paragraph(columns?detailX:76,top+(columns?detailY:headY+54+(fitted.profile==='adaptive-rows'?0:4)+node.head.end),node.description,columns?detailWidth:928,34,49,C.ink,400,1208)).svg;
  top+=node.height;
 }
 if(tail.rows)b+=(await paragraph(76,fitted.tailY,page.text,928,34,51,C.ink,400,1208)).svg;
 page.layout_fit={profile:fitted.profile,content_bottom:fitted.contentBottom,body_font_px:34,title_font_px:70,columns,heading_width:headWidth};
 return b;
}
async function rawPdfPage(page,template) {
 const number=page.source_page;
 if(!Number.isInteger(number)||number<1||number>data.source.page_count||!source_images[String(number)])throw Error('请选择当前PDF范围内有效的物理页；旧图与原PDF保留');
 const source=source_images[String(number)],meta=await sharp(source).metadata(),width=meta.width,height=meta.height;
 if(!width||!height)throw Error('原PDF页图片不可读，旧图保留');
 // The PNG is the exact original raster, not a resized SVG screenshot. The SVG
 // is a source-download wrapper containing one intact original page only.
 const name=page.slot,svg=`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><image href="${await uri(source)}" x="0" y="0" width="${width}" height="${height}" preserveAspectRatio="xMidYMid meet"/></svg>`;
 await fs.writeFile(path.join(OUT,name+'.svg'),svg,{flag:'wx'});
 await fs.writeFile(path.join(OUT,name+'.png'),await fs.readFile(source),{flag:'wx'});
 return {file:name+'.png',svg_file:name+'.svg',slot:page.slot,kind:'pdf-page',role:page.title.replaceAll('\n',' / '),
  source_page:number,full_page:true,raw_pdf:true,width,height,template_id:template,density:page.density||'standard',
  brief:{title:page.title,subtitle:page.subtitle,text:page.text,layout:page.layout,nodes:page.nodes}};
}
async function collage(page) {
 const selected=page.source_pages;
 if(!Array.isArray(selected)||selected.length!==4||new Set(selected).size!==4||selected.some(n=>!Number.isInteger(n)||n<2||n>data.source.page_count||!source_images[String(n)]))throw Error('四宫格需要4张不同且有效的正文物理页；旧图与原PDF保留');
 let b=(await paragraph(72,111,page.title||'真实讲义样张',936,32,40,C.blue,700,111)).svg+rect(72,132,76,4,C.orange);
 let gridTop=156;
 if(page.subtitle) {
  const caption=await paragraph(72,175,page.subtitle,936,28,36,C.muted,400,175);b+=caption.svg;
  gridTop=200;
 }
 const gap=20,cellWidth=(936-gap)/2,cellHeight=(1208-gridTop-gap)/2;
 for(let i=0;i<selected.length;i++) {
  const number=selected[i],file=source_images[String(number)],meta=await sharp(file).metadata();
  const scale=Math.min(cellWidth/meta.width,cellHeight/meta.height),width=meta.width*scale,height=meta.height*scale;
  const x=72+(i%2)*(cellWidth+gap)+(cellWidth-width)/2,y=gridTop+Math.floor(i/2)*(cellHeight+gap)+(cellHeight-height)/2;
  b+=rect(x,y,width,height,'white','#DFE7EF')+await image(file,x,y,width,height,{kind:'real_pdf',source_page:number,full_page:true});
 }
 const center=gridTop+(1208-gridTop)/2;
 b+=`<text x="540" y="${center+6}" text-anchor="middle" font-family="${FONT}" font-size="14" font-weight="700" fill="${C.blue}" opacity="0.18">星途留学 · 资料预览</text>`;
 return b;
}
async function pdfPage(page) {
 const number=page.source_page;
 if(!Number.isInteger(number)||number<1||number>data.source.page_count||!source_images[String(number)])throw Error('请选择当前PDF范围内有效的物理页；旧图与原PDF保留');
 let b=(await paragraph(72,111,page.title||'真实讲义样张',936,32,40,C.blue,700,111)).svg+rect(72,132,76,4,C.orange);
 let top=156;
 if(page.subtitle) {
  const caption=await paragraph(72,175,page.subtitle,936,28,36,C.muted,400,247);b+=caption.svg;
  top=caption.end+24;
 }
 const file=source_images[String(number)],meta=await sharp(file).metadata();
 const scale=Math.min(936/meta.width,(1208-top)/meta.height),width=meta.width*scale,height=meta.height*scale;
 const x=(1080-width)/2,y=top+(1208-top-height)/2;
 b+=rect(x,y,width,height,'white','#DFE7EF')+await image(file,x,y,width,height,{kind:'real_pdf',source_page:number,full_page:true});
 b+=`<text x="540" y="1223" text-anchor="middle" font-family="${FONT}" font-size="12" font-weight="700" fill="${C.blue}" opacity="0.18">星途留学 · 资料预览</text>`;
 return b;
}
const files=[];let activePage=null;
try {
 for(const page of pages) {
  activePage=page;texts=[];pictures=[];let b='';const template=templateFor(page),modern=template!=='legacy';
  if(page.kind==='pdf-page'&&template==='magazine-a') {files.push(await rawPdfPage(page,template));continue;}
  if(page.kind==='collage')b+=await collage(page);
  else if(page.kind==='pdf-page')b+=await pdfPage(page);
  else if(page.kind==='cover'&&template==='magazine-a')b+=await magazineCover(page);
  else if(page.kind==='method'&&template==='magazine-a')b+=await magazineMethod(page);
  else if(page.kind==='cover'&&modern)b+=await modernCover(page,template);
  else if(page.kind==='method'&&modern)b+=await modernMethod(page);
  else if(page.kind==='use'&&modern)b+=await modernUse(page,template);
  else if(page.kind==='sample'&&modern)b+=await modernSample(page);
  else if(page.kind==='cover') {
   b+=t(72,111,`${data.source.university} / UniMelb`,31,C.ink,700);
   // Only the confirmed Melbourne source receives its confirmed English label.
   if(data.source.university!=='墨尔本大学') {b=t(72,111,data.source.university,31,C.ink,700);}
   b+=t(72,207,data.source.course_code,90,C.blue,700);
   const title=await paragraph(72,316,page.title,936,96,110,C.ink,700,426);b+=title.svg;
   // Last headline line receives the single orange emphasis.
   const last=texts.at(-1); b=b.replace(`fill="${C.ink}" text-anchor="start">${esc(last.s)}</text>`,`fill="${C.orange}" text-anchor="start">${esc(last.s)}</text>`);
   if(page.subtitle) b+=(await paragraph(76,481,page.subtitle,936,32,42,C.ink,400,481)).svg;
   const selected=data.visual_plan.sample_pages;
   if(page.layout==='evidence-grid') {
    b+=await paper(1,84,565,290,-4);
    b+=await paper(selected[0],390,550,290,0);
    if(selected.length>1)b+=await paper(selected[1],696,565,290,4);
   } else {
    b+=await paper(selected[0],116,594,342,-10);
    if(selected.length>1)b+=await paper(selected[1],623,594,329,10);
    b+=await paper(1,316,516,448,-3);
   }
   b+=t(540,1207,`${data.source.page_count} 页 PDF · 真实讲义 / 练习与解析`,29,C.blue,700,'middle');
  } else if(page.kind==='method') {
   b+=header();const title=await paragraph(72,228,page.title,936,62,80,C.ink,700,310);b+=title.svg;
   if(page.subtitle)b+=(await paragraph(76,374,page.subtitle,936,32,42,C.ink,400,374)).svg;
   let y=450;
   if((page.layout==='flow'||page.layout==='comparison')&&page.nodes.length>=2) {
    const count=page.nodes.length,gap=48,width=(936-gap*(count-1))/count;
    for(let i=0;i<count;i++) { const x=72+i*(width+gap),parts=page.nodes[i].split('｜');
     b+=rect(x,438,width,210,i%2?'white':C.pale,C.line,8);
     b+=(await paragraph(x+24,516,parts[0],width-48,count>2?30:40,48,C.blue,700,565)).svg;
     if(parts[1])b+=(await paragraph(x+24,589,parts[1],width-48,29,38,C.ink,400,615)).svg;
     if(i<count-1)b+=t(x+width+gap/2,556,page.layout==='flow'?'→':'／',36,C.orange,700,'middle');
    }y=748;
   }
   const blocks=page.text.split(/\n\s*\n/).filter(Boolean);
   if(blocks.length>1&&blocks.every(s=>s.includes('\n')&&s.split('\n')[0].length<=18)) {
    let top=y;
    for(let i=0;i<blocks.length;i++) {
     const [heading,...rest]=blocks[i].split('\n');
     b+=rect(72,top-34,5,145,i%2?C.blue:C.orange)+t(100,top,heading,36,C.blue,700);
     const body=await paragraph(100,top+61,rest.join('\n'),908,36,51,C.ink,400,1164);b+=body.svg;
     top=Math.max(body.end+126,top+230);
    }
   } else {const body=await paragraph(76,y,page.text,928,36,54,C.ink,400,1164);b+=body.svg;}
  } else if(page.kind==='sample') {
   b+=header()+t(72,201,page.title,52,C.ink,700)+rect(72,220,5,32,C.orange);
   b+=(await paragraph(92,246,page.subtitle,916,32,42,C.ink,400,246)).svg;
   const file=source_images[String(page.source_page)],m=await sharp(file).metadata(),h=944,w=h*m.width/m.height,x=(1080-w)/2;
   b+=rect(x,264,w,h,'white','#DFE7EF')+await image(file,x,264,w,h,{kind:'real_pdf',source_page:page.source_page,full_page:true});
   b+=`<text x="540" y="1132" text-anchor="middle" transform="rotate(-18 540 1132)" font-family="${FONT}" font-size="31" font-weight="700" fill="${C.blue}" opacity="0.13">星途留学 · 资料预览</text>`;
  } else {
   b+=header();b+=(await paragraph(72,228,page.title,936,66,82,C.ink,700,310)).svg;
   b+=t(76,374,`${data.source.page_count} 页 PDF · ${data.source.material_type}`,34);
   b+=t(72,452,'复习一章，走完这条路线',36,C.blue,700);
   for(let i=0;i<page.nodes.length;i++) {const y=522+i*96;if(y>906)throw Error('使用步骤过多，请控制在5条以内');
    b+=`<circle cx="88" cy="${y-12}" r="7" fill="${i===page.nodes.length-1?C.orange:C.blue}"/>`;
    if(i<page.nodes.length-1)b+=line(88,y+18,88,y+68);
    b+=(await paragraph(124,y,page.nodes[i],520,36,44,C.ink,400,y)).svg;
   }
   b+=await paper(1,697,473,280,0);b+=line(72,949,1008,949);
   b+=t(72,1006,'先了解，再决定是否购买',42,C.ink,700);
   b+=(await paragraph(72,1069,page.text,936,34,48,C.ink,400,1140)).svg;
   b+=t(72,1190,'资料用于学习辅助；考试范围以本学期学校 LMS 为准。',26,C.muted);
  }
  const backdrop=template!=='magazine-a'&&backgrounds[page.slot]&&page.kind!=='sample'&&page.kind!=='collage'&&page.kind!=='pdf-page'?`<image href="${await uri(backgrounds[page.slot])}" x="0" y="0" width="1080" height="1440" preserveAspectRatio="xMidYMid meet"/>`:'';
  b+=template==='magazine-a'?await aFooter():await footer();const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1440" viewBox="0 0 1080 1440">${defs}${rect(0,0,1080,1440)}${backdrop}${b}</svg>`;
  const issues=[];
  for(const v of texts){const width=await measure(v.s,v.n,v.weight),left=v.anchor==='middle'?v.x-width/2:template==='magazine-a'&&v.anchor==='end'?v.x-width:v.x;if(left<71||left+width>1009||v.y-v.n<(template==='magazine-a'?45:79)||v.y>1208)issues.push({text:v.s,kind:'text_bounds'});}
  for(const v of pictures){const a=(v.rotation||0)*Math.PI/180,dx=Math.abs(v.w*Math.cos(a))+Math.abs(v.h*Math.sin(a)),dy=Math.abs(v.w*Math.sin(a))+Math.abs(v.h*Math.cos(a));if(v.x+v.w/2-dx/2<70||v.x+v.w/2+dx/2>1010||v.y+v.h/2-dy/2<80||v.y+v.h/2+dy/2>(template==='magazine-a'?1415:1380))issues.push({kind:'image_bounds'});}
  if(issues.length)throw Error('当前文字或图稿超出安全边距，请调整布局。'+JSON.stringify(issues));
  const name=page.slot;await fs.writeFile(path.join(OUT,name+'.svg'),svg);await sharp(Buffer.from(svg)).png().toFile(path.join(OUT,name+'.png'));
  files.push({file:name+'.png',svg_file:name+'.svg',slot:page.slot,kind:page.kind,role:page.title.replaceAll('\n',' / '),...(page.kind==='collage'?{source_pages:[...page.source_pages],full_pages:true}:{source_page:page.source_page,full_page:page.kind==='sample'||page.kind==='pdf-page'}),brief:{title:page.title,subtitle:page.subtitle,text:page.text,layout:page.layout,nodes:page.nodes},...(modern?{template_id:template,density:page.density||'standard'}:{}),...(page.layout_fit?{layout_fit:page.layout_fit}:{})});
 }
 process.stdout.write(JSON.stringify({files}));
} catch(e) {const label=activePage?`${({method:'方法说明',sample:'真实样张','pdf-page':'PDF原页',collage:'真实样张拼图',use:'使用路线',cover:'封面'})[activePage.kind]||'图片'}「${activePage.title.replaceAll('\n',' / ')}」：`:'';process.stdout.write(JSON.stringify({error:label+e.message}));process.exitCode=2;}
