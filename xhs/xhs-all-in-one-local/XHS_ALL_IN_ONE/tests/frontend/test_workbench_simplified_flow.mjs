import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),ts=require('../../frontend/node_modules/typescript');
const pageUrl=new URL('../../frontend/src/pages/platforms/xhs/course-visual-workflow-page.tsx',import.meta.url),source=fs.readFileSync(pageUrl,'utf8');
const tree=ts.createSourceFile(pageUrl.pathname,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX),page=tree.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='CourseVisualWorkflowPage');
const extract=name=>{const n=page.body.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text===name);assert.ok(n,name);return n.getText(tree);};
const transpile=s=>ts.transpileModule(s,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const from=async s=>import('data:text/javascript;base64,'+Buffer.from(transpile(s)).toString('base64'));
const context=await from(fs.readFileSync(new URL('../../frontend/src/lib/course-visual-context.ts',import.meta.url),'utf8'));
const navigation=await from(fs.readFileSync(new URL('../../frontend/src/lib/course-visual-navigation.ts',import.meta.url),'utf8'));
const coverHelpers=await from(fs.readFileSync(new URL('../../frontend/src/lib/course-cover-sample.ts',import.meta.url),'utf8'));
const pdfPageHelpers=await from(fs.readFileSync(new URL('../../frontend/src/lib/course-pdf-pages.ts',import.meta.url),'utf8'));
const issue=tree.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='innerPlanIssue').getText(tree);
const {bind}=await from(`${issue}
export function bind(d,context,helpers,coverHelpers,pdfPageHelpers){
 const {run,copy,plan,innerPlan,busy,bufferConflict,briefDirty,dirty,visualDirty,innerDirty,pdfPagesDirty=false,pdfPagePlan=null,hasEdits,checks,generation,navigation,bundleKey,
 rawWorkflowAction,rawWorkflowGet,receive,loadHistory,removeCourseEditBuffer,editScope,setHistoryNotice,setNotice,setBusy,setError,setStep,setParams,errorText,setPrompt,setConsent,aiKey}=d;
 const {inCourseContext,CourseContextChanged}=context;const {visualStageParams,nextVisualStage}=helpers;const {coverSampleIssue}=coverHelpers;const {pdfPageIssue}=pdfPageHelpers;
 ${['visualWorkflowGet','visualWorkflowAction','action','showStep','refreshHistoryAfterMutation','recoverBundle','requireCoverSample','act','saveAndRender','approveAndExport','showPrompt'].map(extract).join('\n')}
 return {saveAndRender,approveAndExport,recoverBundle,act,showPrompt};
}`);
const tests=[];async function test(name,fn){await fn();tests.push(name);}
function fixture(overrides={}){
 const plan={template_id:'decision-map',density:'standard',sample_pages:[2,3]},innerPlan={sample_pages:[2,3],sample_instructions:['Read a','Read b'],extra_explanations:[]};
 const run={id:7,file_id:17766,row_version:10,approved:{copy:true,cover:false,set:false},digests:{copy:'copy-10',cover:'cover-10',set:'set-10'},data:{copy:{title:'Approved title',body:'Retained body'},source:{page_count:20},visual_plan:plan,set_plan:innerPlan,images:[{id:'old-cover'},{id:'old-sample'}],cover:{id:'old-cover'},operation:null}};
 const patched={...structuredClone(run),row_version:11},rendered={...structuredClone(run),row_version:13,data:{...structuredClone(run.data),images:[{id:'new-cover'},{id:'new-sample'}],cover:{id:'new-cover'}}};
 const approved={...structuredClone(rendered),row_version:14,approved:{copy:true,cover:true,set:true},digests:{copy:'copy-10',cover:'cover-13',set:'set-13'}};
 const exported={...structuredClone(approved),row_version:15,data:{...structuredClone(approved.data),export:{draft_id:42}}};
 const calls=[],reads=[],received=[],removed=[],steps=[],notices=[],errors=[],routes=[],prompts=[],consents=[];let historyCalls=0;
 let params=new URLSearchParams('run=7&file_id=17766&stage=visual&filter=kept');
 const d={run,copy:run.data.copy,plan,innerPlan,busy:'',bufferConflict:null,briefDirty:false,dirty:false,visualDirty:false,innerDirty:false,hasEdits:false,checks:{set:true},generation:{current:2},navigation:{current:3},bundleKey:{current:'bundle-original'},aiKey:{current:'ai-original'},setPrompt:x=>prompts.push(x),setConsent:x=>consents.push(x),
  rawWorkflowAction:async(path,body,method)=>{calls.push({path,body,method});return method==='patch'?patched:path.endsWith('/approve')?approved:path.endsWith('/export')?exported:path.endsWith('/generate-visual-plan')?patched:rendered;},
  rawWorkflowGet:async(path)=>{reads.push(path);return patched;},receive:x=>received.push(x),loadHistory:async()=>{historyCalls++;},removeCourseEditBuffer:x=>removed.push(x),editScope:id=>({userId:1,feature:'visual-workbench',recordId:String(id)}),setHistoryNotice:()=>{},setNotice:x=>notices.push(x),setBusy:()=>{},setError:x=>errors.push(x),setStep:x=>steps.push(x),setParams:x=>{params=x(params);routes.push(new URLSearchParams(params));},errorText:e=>e.message,...overrides};
 return {d,calls,reads,received,removed,steps,notices,errors,routes,prompts,consents,patched,rendered,approved,exported,get historyCalls(){return historyCalls;},get params(){return params;},handlers:bind(d,context,navigation,coverHelpers,pdfPageHelpers)};
}
await test('a reviewed copy with no cover approval generates one bundle and goes straight to final review',async()=>{
 const f=fixture(),before=structuredClone(f.d.run);await f.handlers.saveAndRender();
 assert.deepEqual(f.calls,[{path:'/7/render-bundle',body:{expected_version:10,request_key:'bundle-original'},method:'post'}]);assert.deepEqual(f.steps,[4]);assert.equal(f.params.get('stage'),'set');assert.equal(f.params.get('file_id'),'17766');assert.equal(f.params.get('filter'),'kept');assert.deepEqual(f.d.run,before);assert.equal(f.calls.some(x=>/approve|export|generate-copy|publish|auto/.test(x.path)),false);assert.equal(f.historyCalls,1);
});
await test('one click saves visual and inner edits together then renders with the returned version, preserving copy',async()=>{
 const f=fixture({visualDirty:true,innerDirty:true});await f.handlers.saveAndRender();
 assert.deepEqual(f.calls[0],{path:'/7',body:{expected_version:10,visual_plan:f.d.plan,set_plan:f.d.innerPlan},method:'patch'});assert.equal(f.calls[1].body.expected_version,11);assert.notEqual(f.calls[1].body.request_key,'bundle-original');assert.equal(f.removed.length,1);assert.deepEqual(f.received,[f.patched,f.rendered]);assert.equal('copy' in f.calls[0].body,false);
});
for(const [name,override] of Object.entries({busy:{busy:'working'},conflict:{bufferConflict:{}},single_edit:{briefDirty:true},no_run:{run:null},no_plan:{plan:null},no_inner:{innerPlan:null},dirty_copy:{dirty:true},unreviewed_copy:{run:{id:7,approved:{copy:false},data:{operation:null}}},generating:{run:{data:{operation:{status:'generating'}}}}}))await test(`bundle generation is guarded for ${name}`,async()=>{const f=fixture(override);await f.handlers.saveAndRender();assert.deepEqual(f.calls,[]);assert.deepEqual(f.removed,[]);});
await test('invalid sample plan cannot be saved or rendered',async()=>{const f=fixture({innerPlan:{sample_pages:[2,2],extra_explanations:[]}});await f.handlers.saveAndRender();assert.deepEqual(f.calls,[]);assert.ok(f.errors.at(-1));});
await test('failed plan save retains buffer and never submits a render',async()=>{const f=fixture({visualDirty:true,rawWorkflowAction:async()=>{throw Error('save failed');}});await f.handlers.saveAndRender();assert.deepEqual(f.removed,[]);assert.deepEqual(f.received,[]);assert.deepEqual(f.steps,[]);assert.equal(f.errors.at(-1),'save failed');});
await test('uncertain network outcome preserves its bundle key for idempotent retry',async()=>{
 const f=fixture({rawWorkflowAction:async()=>{throw Error('response lost');},rawWorkflowGet:async()=>{throw Error('read offline');}});await f.handlers.saveAndRender();assert.equal(f.d.bundleKey.current,'bundle-original');assert.deepEqual(f.received,[]);assert.equal(f.errors.at(-1),'response lost');
});
await test('confirmed same-key failure rotates the bundle key only after reading the server record',async()=>{
 const latest={id:7,row_version:12,data:{operation:{key:'bundle-original',status:'failed'}}},f=fixture({rawWorkflowGet:async()=>latest});await f.handlers.recoverBundle(7,'bundle-original');assert.notEqual(f.d.bundleKey.current,'bundle-original');assert.deepEqual(f.received,[latest]);
});
await test('completed or unrelated request does not lose the retry key',async()=>{
 for(const operation of [{key:'bundle-original',status:'ready'},{key:'another-key',status:'failed'}]){const f=fixture({rawWorkflowGet:async()=>({id:7,data:{operation}})});await f.handlers.recoverBundle(7,'bundle-original');assert.equal(f.d.bundleKey.current,'bundle-original');}
});
await test('late bundle success after navigation updates the record without stealing the chosen step',async()=>{
 let finish;const f=fixture({rawWorkflowAction:()=>new Promise(resolve=>{finish=resolve;})});const pending=f.handlers.saveAndRender();f.d.navigation.current++;finish(f.rendered);await pending;assert.deepEqual(f.received,[f.rendered]);assert.deepEqual(f.steps,[]);assert.deepEqual(f.routes,[]);assert.equal(f.notices.some(x=>x.includes('已生成')),false);
});
await test('context change after plan submission prevents a render in the old course',async()=>{
 let finish;const f=fixture({visualDirty:true,rawWorkflowAction:()=>new Promise(resolve=>{finish=resolve;})});const pending=f.handlers.saveAndRender();f.d.generation.current++;finish(f.patched);await pending;assert.deepEqual(f.received,[]);assert.deepEqual(f.removed,[]);assert.deepEqual(f.steps,[]);
});
await test('consented AI visual planning directly renders the returned saved version and never rewrites approved copy',async()=>{
 const f=fixture();await f.handlers.act('generate-visual-plan',{external_consent:true,request_key:'ai-confirmed'},'AI规划并制作');assert.deepEqual(f.calls.map(x=>x.path),['/7/generate-visual-plan','/7/render-bundle']);assert.equal(f.calls[1].body.expected_version,11);assert.deepEqual(f.steps,[4]);assert.equal(f.calls.some(x=>/generate-copy|approve|export/.test(x.path)),false);
});
await test('AI plan render failure preserves the saved plan and ambiguous render key',async()=>{
 const f=fixture({rawWorkflowAction:async(path)=>{if(path.endsWith('/generate-visual-plan'))return {id:7,row_version:11,data:{}};throw Error('render offline');},rawWorkflowGet:async()=>{throw Error('read offline');}});await f.handlers.act('generate-visual-plan',{external_consent:true},'AI');assert.equal(f.received.length,1);assert.equal(f.d.bundleKey.current,'bundle-original');assert.deepEqual(f.steps,[]);assert.equal(f.errors.at(-1),'render offline');
});
await test('a single explicit final review approves the full set then exports its returned current digest and version',async()=>{
 const f=fixture();await f.handlers.approveAndExport();assert.deepEqual(f.calls,[{path:'/7/approve',body:{expected_version:10,stage:'set',reviewed:true,combined_review:true,digest:'set-10'},method:'post'},{path:'/7/export',body:{expected_version:14,reviewed:true,digest:'set-13'},method:'post'}]);assert.deepEqual(f.received,[f.approved,f.exported]);assert.deepEqual(f.steps,[4]);assert.equal(f.calls.some(x=>/publish|auto/.test(x.path)),false);
});
for(const [name,override] of Object.entries({unchecked:{checks:{}},busy:{busy:'work'},unsaved:{hasEdits:true},conflict:{bufferConflict:{}},no_run:{run:null},no_images:{run:{approved:{copy:true},data:{images:[]}}},unreviewed_copy:{run:{approved:{copy:false},data:{images:[{}]}}}}))await test(`review-and-save refuses ${name}`,async()=>{const f=fixture(override);await f.handlers.approveAndExport();assert.deepEqual(f.calls,[]);assert.deepEqual(f.received,[]);});
await test('an already reviewed set retries export without inserting another approval',async()=>{const f=fixture();f.d.run.approved.set=true;await f.handlers.approveAndExport();assert.equal(f.calls.length,1);assert.equal(f.calls[0].path,'/7/export');});
await test('export failure keeps the genuine human approval and exposes a retry without pretending the draft exists',async()=>{
 let f;f=fixture({rawWorkflowAction:async(path)=>{if(path.endsWith('/approve'))return f.approved;throw Error('export failed');}});await f.handlers.approveAndExport();assert.deepEqual(f.received,[f.approved]);assert.equal(f.received[0].data.export,undefined);assert.deepEqual(f.steps,[]);assert.equal(f.errors.at(-1),'export failed');
});
await test('context change during final approval prevents exporting into the former course',async()=>{
 let finish;const f=fixture({rawWorkflowAction:()=>new Promise(resolve=>{finish=resolve;})});const pending=f.handlers.approveAndExport();f.d.generation.current++;finish(f.approved);await pending;assert.deepEqual(f.received,[]);assert.deepEqual(f.steps,[]);assert.deepEqual(f.routes,[]);
});
await test('same-course navigation during review-and-save receives the saved result without jumping back',async()=>{
 let finish;let f;f=fixture({rawWorkflowAction:async(path)=>path.endsWith('/approve')?f.approved:new Promise(resolve=>{finish=resolve;})});const pending=f.handlers.approveAndExport();await new Promise(resolve=>setTimeout(resolve,0));f.d.navigation.current++;finish(f.exported);await pending;assert.deepEqual(f.received,[f.approved,f.exported]);assert.deepEqual(f.steps,[]);assert.deepEqual(f.routes,[]);
});
await test('visual AI preparation saves selected template and sample edits before showing an external-consent dialog, without calling AI or rendering',async()=>{
 const f=fixture({visualDirty:true,innerDirty:true});await f.handlers.showPrompt('visual');assert.deepEqual(f.calls.map(x=>x.path),['/7','/7/prompts?purpose=visual']);assert.deepEqual(f.calls[0].body,{expected_version:10,visual_plan:f.d.plan,set_plan:f.d.innerPlan});assert.deepEqual(f.consents,[false]);assert.equal(f.prompts.length,1);assert.equal(f.calls.some(x=>/generate-|render|approve|export/.test(x.path)),false);assert.equal(f.removed.length,1);
});
await test('visual AI preparation refuses an unreviewed or changed copy before any save or model preparation',async()=>{
 for(const override of [{dirty:true},{run:{approved:{copy:false},data:{operation:null}}}]){const f=fixture(override);await f.handlers.showPrompt('visual');assert.deepEqual(f.calls,[]);assert.deepEqual(f.prompts,[]);}
});
await test('a late visual consent dialog cannot reopen after same-course navigation',async()=>{
 let finish;const f=fixture({rawWorkflowAction:()=>new Promise(resolve=>{finish=resolve;})});const pending=f.handlers.showPrompt('visual');f.d.navigation.current++;finish({prompt:'prepared'});await pending;assert.deepEqual(f.prompts,[]);assert.deepEqual(f.consents,[]);
});
await test('missing cover body page directs the user to the visible picker before any save, rendering or model preparation',async()=>{
 for(const invoke of ['saveAndRender','showPrompt']){const f=fixture({plan:{template_id:'decision-map',density:'standard',sample_pages:[1]}});await f.handlers[invoke](...(invoke==='showPrompt'?['visual']:[]));assert.deepEqual(f.calls,[]);assert.deepEqual(f.steps,[2]);assert.ok(f.errors.at(-1).includes('封面正文样张'));}
});
await test('an explicit selected cover body page saves on visual_plan independently of all inner pages and is used by the immediately following bundle',async()=>{
 const f=fixture({plan:{template_id:'decision-map',density:'standard',sample_pages:[1],cover_sample_page:5},visualDirty:true});const before=structuredClone(f.d.innerPlan);await f.handlers.saveAndRender();assert.equal(f.calls[0].body.visual_plan.cover_sample_page,5);assert.deepEqual(f.calls[0].body.visual_plan.sample_pages,[1]);assert.equal('set_plan' in f.calls[0].body,false);assert.deepEqual(f.d.innerPlan,before);assert.equal(f.calls[1].path,'/7/render-bundle');assert.equal(f.calls[1].body.expected_version,11);
});
const labels=page.body.statements.find(n=>ts.isVariableStatement(n)&&n.declarationList.declarations.some(d=>d.name.getText(tree)==='labels')).declarationList.declarations[0].initializer;
assert.equal(labels.elements.length,4);assert.equal(source.includes('确认当前封面</Button>'),false);assert.equal(source.includes('重新规划本篇图片内容'),true);assert.equal(source.includes('调整图片内容与样张（可选）'),true);
tests.push('the production UI has four stages, optional collapsed content editing and explicit planning and generation controls');
console.log(JSON.stringify({passed:tests.length,tests,network_calls:0,model_calls:0,business_writes:0},null,2));
