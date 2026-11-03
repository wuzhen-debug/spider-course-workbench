import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),ts=require('../../frontend/node_modules/typescript');
const source=fs.readFileSync(new URL('../../frontend/src/pages/platforms/xhs/course-visual-workflow-page.tsx',import.meta.url),'utf8');
const tree=ts.createSourceFile('workbench.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const page=tree.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='CourseVisualWorkflowPage');
const fn=name=>page.body.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text===name).getText(tree);
const from=async text=>import('data:text/javascript;base64,'+Buffer.from(ts.transpileModule(text,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString('base64'));
const helpers=fs.readFileSync(new URL('../../frontend/src/lib/course-visual-production.ts',import.meta.url),'utf8');
const {productionReadiness,bind}=await from(`${helpers}
export function bind(d){
 const {run,copy,plan,innerPlan,pdfPagePlan,busy='',bufferConflict=null,briefDirty=false,dirty=false,pdfPagesDirty=false,visualDirty=false,innerDirty=false,imageMode='api',productionIntent,
 setProductionOptions,showPrompt,prepareApiImages,saveAndRender,appendPdfPages,setError,showStep,action,visualWorkflowAction,visualWorkflowGet,receive,aiKey,bundleKey,apiImageDigest,apiImageKey,setApiImagePlan,setApiImageConsent,setNotice,refreshHistoryAfterMutation,recoverBundle}=d;
 const coverSampleIssue=()=>'';class CourseContextChanged extends Error{}
 ${fn('startProduction')}
 ${fn('act')}
 return {startProduction,act};
}`);
const copy={title:'BISM1201期末考是纸笔吗'};
const plan={template_id:'magazine-a',cover_lines:[],method_title:'核对四个字段',method_text:''};
const inner={sample_pages:[1],extra_explanations:[{title:'Practice',text:''},{title:'Check',text:''}]},pdf={pages:[2,3,4,5,6,7,8,9,10]};
let total=0;async function test(name,check){await check();total++;}
function fixture(overrides={}){
 const calls=[],steps=[],plans=[],notices=[];let current=true;
 const run={id:11,row_version:2,approved:{copy:true},data:{images:[],visual_plan:plan,source:{page_count:94}}};
 const result={...structuredClone(run),row_version:4};
 const d={run,copy,plan:structuredClone(plan),innerPlan:structuredClone(inner),pdfPagePlan:pdf,productionIntent:{current:{mode:'api',target:'bundle'}},
 setProductionOptions:()=>{},showPrompt:async purpose=>calls.push({kind:'prompt',purpose}),prepareApiImages:async target=>calls.push({kind:'api-prepare',target}),saveAndRender:async()=>calls.push({kind:'local'}),appendPdfPages:async()=>calls.push({kind:'pdf-only'}),setError:error=>calls.push({kind:'error',error}),showStep:step=>steps.push(step),
 action:async(name,task)=>task(()=>current),visualWorkflowAction:async(path,body)=>{calls.push({path,body});return path.endsWith('/api-image-plan')?{plan_digest:'image-scope',row_version:4}:result;},visualWorkflowGet:async()=>result,receive:()=>{},aiKey:{current:'text-key'},bundleKey:{current:'bundle-key'},apiImageKey:{current:'image-key'},apiImageDigest:{current:''},setApiImagePlan:plan=>plans.push(plan),setApiImageConsent:()=>{},setNotice:notice=>notices.push(notice),refreshHistoryAfterMutation:async()=>{},recoverBundle:async()=>{},...overrides};
 return {d,calls,steps,plans,notices,leave:()=>{current=false;},h:bind(d)};
}
await test('an unfinished research handoff has thirteen planned slots and cannot appear ready',()=>{
 const state=productionReadiness(copy,plan,inner,pdf);assert.equal(state.plannedCount,13);assert.equal(state.needsPlanning,true);assert.equal(state.pages.filter(p=>!p.ready).length,3);
});
await test('the unified entry plans missing content without making an image request',async()=>{
 const f=fixture();await f.h.startProduction();assert.deepEqual(f.calls,[{kind:'prompt',purpose:'visual'}]);assert.deepEqual(f.d.productionIntent.current,{mode:'api',target:'bundle'});
});
const ready={plan:{...plan,method_text:'Concrete method'},innerPlan:{...inner,extra_explanations:inner.extra_explanations.map(p=>({...p,text:'Concrete explanation'}))}};
await test('ready API choice prepares exact image consent and never takes the local branch',async()=>{
 const f=fixture(ready);await f.h.startProduction('cover');assert.deepEqual(f.calls,[{kind:'api-prepare',target:'cover'}]);
});
await test('ready local choice renders without an image provider',async()=>{
 const f=fixture({...ready,imageMode:'local'});await f.h.startProduction();assert.deepEqual(f.calls,[{kind:'local'}]);
});
await test('replacing only PDF pages never regenerates paid knowledge images',async()=>{
 const f=fixture({...ready,pdfPagesDirty:true,run:{id:11,approved:{copy:true},data:{images:[{}],source:{page_count:94}}}});await f.h.startProduction();assert.deepEqual(f.calls,[{kind:'pdf-only'}]);
});
await test('text planning in API mode ends at separate image consent and uses returned version',async()=>{
 const f=fixture();await f.h.act('generate-visual-plan',{request_key:'text-key'},'plan',{mode:'api',target:'bundle'});
 assert.deepEqual(f.calls.map(c=>c.path),['/11/generate-visual-plan','/11/api-image-plan']);assert.equal(f.calls[1].body.expected_version,4);assert.equal(f.plans.length,1);assert.deepEqual(f.steps,[]);assert.ok(f.calls.every(c=>!/render|generate-api|approve|export/.test(c.path)));
});
await test('navigation during text planning cannot open image consent in the former stage',async()=>{
 const f=fixture();f.d.visualWorkflowAction=async(path,body)=>{f.calls.push({path,body});f.leave();return {id:11,row_version:4,data:{images:[]}};};f.h=bind(f.d);
 await f.h.act('generate-visual-plan',{},'plan',{mode:'api',target:'bundle'});assert.equal(f.calls.length,1);assert.deepEqual(f.plans,[]);assert.deepEqual(f.steps,[]);
});
await test('incomplete content remains incomplete after a single manual explanation is filled',()=>{
 const state=productionReadiness(copy,{...plan,method_text:'A method'},{...inner,extra_explanations:[{title:'one',text:'ready'},{title:'two',text:''}]},pdf);assert.equal(state.plannedCount,13);assert.equal(state.needsPlanning,true);
});
const effects=page.body.statements.filter(n=>ts.isExpressionStatement(n)&&ts.isCallExpression(n.expression)&&n.expression.expression.getText(tree)==='useEffect').map(n=>n.expression);
const focusEffect=effects.find(e=>e.arguments[0].getText(tree).includes('pdfPickerRequested.current'));
assert.ok(focusEffect);
const {focusPicker}=await from(`export function focusPicker(d){const {pdfPickerRequested,productionOptions,window,document}=d;return (${focusEffect.arguments[0].getText(tree)})();}`);
await test('a PDF edit focuses the real lazy input after opening, with a cancellable short animation delay',()=>{
 const calls=[];let callback;const request={current:true};const cleanup=focusPicker({pdfPickerRequested:request,productionOptions:['remake'],window:{setTimeout:(fn,ms)=>{callback=fn;assert.equal(ms,360);return 7;},clearTimeout:id=>calls.push(['cancel',id])},document:{querySelector:selector=>{assert.equal(selector,'.vd-pdf-pages-panel');return {querySelector:()=>({focus:options=>calls.push(['focus',options])}),scrollIntoView:options=>calls.push(['scroll',options])};}}});
 assert.deepEqual(calls,[]);callback();assert.equal(request.current,false);assert.deepEqual(calls.map(c=>c[0]),['focus','scroll']);cleanup();assert.deepEqual(calls.at(-1),['cancel',7]);
});
await test('normal stage rendering never schedules unsolicited PDF scrolling',()=>{for(const [requested,options] of [[false,['remake']],[true,[]]]){assert.equal(focusPicker({pdfPickerRequested:{current:requested},productionOptions:options,window:{setTimeout:()=>assert.fail('unsolicited scroll')},document:{}}),undefined);}});
console.log(JSON.stringify({passed:total,external_model_calls:0,publication_calls:0}));
