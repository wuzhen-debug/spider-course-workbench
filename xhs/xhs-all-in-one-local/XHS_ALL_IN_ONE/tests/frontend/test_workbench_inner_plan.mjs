import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';

// Run the real editor/normalization/save/cache handlers with isolated setters.
// No browser, HTTP, model, business database, or user storage is accessed.
const require=createRequire(import.meta.url),ts=require('../../frontend/node_modules/typescript');
const url=new URL('../../frontend/src/pages/platforms/xhs/course-visual-workflow-page.tsx',import.meta.url);
const source=fs.readFileSync(url,'utf8'),tree=ts.createSourceFile(url.pathname,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const page=tree.statements.find(node=>ts.isFunctionDeclaration(node)&&node.name?.text==='CourseVisualWorkflowPage');
const declaration=(list,name)=>list.find(node=>ts.isVariableStatement(node)&&node.declarationList.declarations.some(d=>d.name.getText(tree)===name));
const outer=name=>{const node=declaration(tree.statements,name)||tree.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text===name);assert.ok(node,name);return node.getText(tree);};
const extract=name=>{const node=page.body.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text===name);assert.ok(node,name);return node.getText(tree);};
const transpile=value=>ts.transpileModule(value,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const moduleFrom=async value=>import('data:text/javascript;base64,'+Buffer.from(transpile(value)).toString('base64'));
const context=await moduleFrom(fs.readFileSync(new URL('../../frontend/src/lib/course-visual-context.ts',import.meta.url),'utf8'));
const navigationHelpers=await moduleFrom(fs.readFileSync(new URL('../../frontend/src/lib/course-visual-navigation.ts',import.meta.url),'utf8'));
const comparison=await moduleFrom(fs.readFileSync(new URL('../../frontend/src/lib/course-visual-edits.ts',import.meta.url),'utf8'));
const pdfPageHelpers=await moduleFrom(fs.readFileSync(new URL('../../frontend/src/lib/course-pdf-pages.ts',import.meta.url),'utf8'));
const effects=page.body.statements.filter(n=>ts.isExpressionStatement(n)&&ts.isCallExpression(n.expression)&&n.expression.expression.getText(tree)==='useEffect').map(n=>n.expression);
const cacheEffect=effects.find(n=>n.arguments[1]?.getText(tree).startsWith('[run,copy,plan,innerPlan,innerPagesText,'));assert.ok(cacheEffect);
const innerNames=['visualWorkflowAction','action','showStep','refreshHistoryAfterMutation','saveEdits','saveInner','changeInner','changeInnerPages','changeExplanation','applyEditor','receive'];
const flags=['dirty','visualDirty','innerDirty','pdfPagesDirty','briefDirty','hasEdits'].map(name=>declaration(page.body.statements,name).getText(tree)).join('\n');
const {bind,editFlags,plannedTotal,normalSetPlan}=await moduleFrom(`
${fs.readFileSync(new URL('../../frontend/src/lib/course-visual-production.ts',import.meta.url),'utf8')}
${['normalPlan','normalSetPlan','innerPlanIssue'].map(outer).join('\n')}
export {normalSetPlan};
export function editFlags(deps,comparison){const {run,copy,plan,innerPlan,pdfPagePlan=null,selected,editing,brief}=deps;const {sameVisualEdit}=comparison;${flags};return {dirty,visualDirty,innerDirty,briefDirty,hasEdits};}
export function plannedTotal(plan,innerPlan,pdfPagePlan=null){const production=productionReadiness({title:'Fixture'},plan,innerPlan,pdfPagePlan);${declaration(page.body.statements,'plannedCount').getText(tree)};return plannedCount;}
export function bind(deps,context,navigationHelpers,pdfPageHelpers){
 const {run,copy,plan,innerPlan,innerPagesText,selected,pagesText,editing,brief,busy,bufferConflict,dirty,visualDirty,innerDirty,pdfPagesDirty=false,pdfPagePlan=null,pdfPagesText='',briefDirty,hasEdits,userId,generation,navigation,editorReady,
 rawWorkflowAction,loadHistory,setHistoryNotice,setNotice,setBusy,setError,errorText,setParams,setRecordsOpen,setStep,
 setRun,setCopy,setPlan,setPdfPagePlan,setPdfPagesText,setInnerPlan,setInnerPagesText,setPagesText,setSelected,setEditing,setBrief,setEditOpen,setImageAction,setChecks,setPrompt,setConsent,setPdfPrompt=()=>{},setPdfConsent=()=>{},setBgOptions,setBgPrompt,setBgConsent,setBufferConflict,setBufferStatus,
 readCourseEditBuffer,writeCourseEditBuffer,removeCourseEditBuffer}=deps;
 const legacyCollageBuffer={current:{}};const {inCourseContext,CourseContextChanged}=context;const {visualStageParams}=navigationHelpers;const {pdfPageIssue,pdfPageText}=pdfPageHelpers;
 const editScope=id=>({userId,feature:'visual-workbench',recordId:String(id)});
 ${innerNames.map(extract).join('\n')}
 return {${innerNames.filter(name=>!['visualWorkflowAction','action','showStep','refreshHistoryAfterMutation'].includes(name)).join(',')},cacheEdits:()=>(${cacheEffect.arguments[0].getText(tree)})()};
}`);
const tests=[];async function test(name,fn){await fn();tests.push(name);}
const basePlan=()=>({cover_lines:['Synthetic cover'],method_title:'Original method',method_text:'One existing explanation',sample_pages:[2,3],sample_instructions:['First real sample','Second real sample'],usage_steps:['Read','Practice'],cta:'Learn about the material',style:'product-editorial',method_layout:'editorial',method_nodes:[],template_id:'sample-led',density:'standard'});
const expanded=()=>({sample_pages:[2,3,23,24],sample_instructions:['A','B','C','D'],extra_explanations:[{title:'One additional explanation',subtitle:'Read the conditions',text:'A concrete explanation to review.',layout:'flow',nodes:['Condition','Decision','Method']}]});
function fixture(overrides={}){
 const calls=[],routes=[],removed=[],cacheWrites=[],errors=[],notices=[],writes=[],history=[];let cached=null;
 const run={id:5,file_id:19901,row_version:9,approved:{copy:true,cover:true},data:{copy:{topic:'Synthetic topic',title:'Existing title',body:'Existing body',tags:[],takeaway:'A concrete benefit'},visual_plan:basePlan(),source:{page_count:56},selected_source_ids:['source-a'],cover:{id:'approved-cover',brief:{title:'Existing image',nodes:[]}},images:[],operation:null}};
 const next={...structuredClone(run),row_version:10,data:{...structuredClone(run.data),set_plan:expanded()}};
 const state={run,copy:run.data.copy,plan:run.data.visual_plan,innerPlan:normalSetPlan(undefined,run.data.visual_plan),innerPagesText:'2, 3',editing:null,brief:null};
 const setter=name=>value=>{writes.push(name);state[name]=typeof value==='function'?value(state[name]):value;};
 const deps={run,copy:structuredClone(run.data.copy),plan:basePlan(),innerPlan:expanded(),innerPagesText:'2, 3, 23, 24',selected:['source-a'],pagesText:'2, 3',editing:null,brief:null,busy:'',bufferConflict:null,dirty:false,visualDirty:false,innerDirty:true,briefDirty:false,hasEdits:true,userId:2,generation:{current:13},navigation:{current:3},editorReady:{current:5},
 rawWorkflowAction:async(path,data,method)=>{calls.push({path,data,method});return next;},loadHistory:async()=>history.push('refresh'),setParams:value=>routes.push(value),setRecordsOpen:()=>{},setStep:value=>routes.push(value),setHistoryNotice:()=>{},setNotice:value=>notices.push(value),setBusy:setter('busy'),setError:value=>errors.push(value),errorText:error=>error.message,
 ...Object.fromEntries(['Run','Copy','Plan','PdfPagePlan','PdfPagesText','InnerPlan','InnerPagesText','PagesText','Selected','Editing','Brief','EditOpen','ImageAction','Checks','Prompt','Consent','BgOptions','BgPrompt','BgConsent','BufferConflict','BufferStatus'].map(name=>['set'+name,setter(name[0].toLowerCase()+name.slice(1))])),
 readCourseEditBuffer:()=>cached,writeCourseEditBuffer:(scope,value,baseVersion)=>{cacheWrites.push({scope,value:structuredClone(value),baseVersion});cached={scope,value,baseVersion};return true;},removeCourseEditBuffer:scope=>{removed.push(scope);cached=null;},...overrides};
 return {deps,next,state,calls,routes,removed,cacheWrites,errors,notices,writes,history,setCache:value=>{cached=value;},get cache(){return cached;},handlers:bind(deps,context,navigationHelpers,pdfPageHelpers)};
}

await test('missing set_plan inherits saved samples without mutating either plan or creating unsaved edits',()=>{
 const f=fixture(),r=f.deps.run,before=structuredClone(r);const inner=normalSetPlan(undefined,r.data.visual_plan);
 assert.deepEqual(inner,{sample_pages:[2,3],sample_instructions:r.data.visual_plan.sample_instructions,extra_explanations:[]});
 assert.deepEqual(editFlags({...f.deps,innerPlan:inner},comparison),{dirty:false,visualDirty:false,innerDirty:false,briefDirty:false,hasEdits:false});assert.deepEqual(r,before);
 assert.equal(editFlags({...f.deps,innerPlan:expanded()},comparison).innerDirty,true);
});
await test('the proposed cover, existing method, one explanation, four samples and usage total eight without padding',()=>{assert.equal(plannedTotal(basePlan(),expanded()),8);});
await test('saving only inner content PATCHes set_plan and preserves the confirmed copy, visual plan and cover',async()=>{
 const f=fixture(),before=structuredClone(f.deps.run);await f.handlers.saveInner();
 assert.deepEqual(f.calls,[{path:'/5',data:{expected_version:9,set_plan:f.deps.innerPlan},method:'patch'}]);assert.equal(f.routes[0],2);
 assert.equal(f.routes[1](new URLSearchParams('run=5&stage=cover')).get('stage'),'visual');
 assert.deepEqual(f.deps.run,before);assert.deepEqual(f.state.copy,before.data.copy);assert.deepEqual(f.state.plan,basePlan());assert.deepEqual(f.next.data.cover,before.data.cover);
 assert.deepEqual(f.state.innerPlan,expanded());assert.equal(f.removed.length,1);assert.ok(f.notices.some(value=>value.includes('已确认封面保留')));
});
for(const [label,override,target] of [['copy',{dirty:true},1],['visual',{visualDirty:true},2],['copy_and_visual',{dirty:true,visualDirty:true},1]])await test(`global ${label} and inner edits save together without discarding either`,async()=>{
 const f=fixture(override);await f.handlers.saveEdits();assert.equal(f.calls.length,1);const body=f.calls[0].data;assert.deepEqual(body.set_plan,expanded());
 if(override.dirty){assert.deepEqual(body.copy,f.deps.copy);assert.deepEqual(body.selected_source_ids,['source-a']);}else assert.equal('copy' in body,false);
 if(override.visualDirty)assert.deepEqual(body.visual_plan,f.deps.plan);else assert.equal('visual_plan' in body,false);
 assert.equal(f.routes[0],target);
});
await test('the dedicated inner save preserves simultaneous unsaved copy or visual edits and points to the global save',async()=>{
 for(const override of [{dirty:true},{visualDirty:true}]){const f=fixture(override);await f.handlers.saveInner();assert.deepEqual(f.calls,[]);assert.deepEqual(f.removed,[]);assert.ok(f.errors.at(-1).includes('保存当前修改'));}
});
for(const [label,override] of Object.entries({busy:{busy:'Rendering'},conflict:{bufferConflict:{value:{}}},single_image:{briefDirty:true},generating:{run:{id:5,data:{operation:{status:'generating'}}}},missing_inner:{innerPlan:null}}))await test(`${label} cannot save or clear retained edits`,async()=>{
 const f=fixture(override);await f.handlers.saveInner();assert.deepEqual(f.calls,[]);assert.deepEqual(f.removed,[]);assert.deepEqual(f.routes,[]);
});
for(const [label,mutate] of [
 ['empty_samples',value=>value.sample_pages=[]],['repeated_samples',value=>value.sample_pages=[2,2]],['out_of_range_sample',value=>value.sample_pages=[57]],['noninteger_sample',value=>value.sample_pages=[2.5]],
 ['oversized_body',value=>value.extra_explanations[0].text='a'.repeat(201)],['too_many_nodes',value=>value.extra_explanations[0].nodes=['a','b','c','d']],
])await test(`invalid ${label} reports the precise problem without cropping content or submitting an empty page`,async()=>{
 const value=expanded();mutate(value);const f=fixture({innerPlan:value}),before=structuredClone(value);await f.handlers.saveInner();assert.deepEqual(f.calls,[]);assert.deepEqual(f.removed,[]);assert.ok(f.errors.at(-1));assert.deepEqual(value,before);
});
await test('unfinished explanations save as WIP without being represented as ready images',async()=>{for(const field of ['title','text']){const value=expanded();value.extra_explanations[0][field]='';const f=fixture({innerPlan:value});await f.handlers.saveInner();assert.equal(f.calls.length,1);assert.deepEqual(f.calls[0].data.set_plan,value);assert.deepEqual(f.state.run.data.images,[]);}});
await test('compact profile displays and enforces the stricter explanation limit without silent truncation',async()=>{
 const value=expanded();value.extra_explanations[0].text='a'.repeat(111);const f=fixture({innerPlan:value,plan:{...basePlan(),density:'compact'}});await f.handlers.saveInner();assert.equal(f.calls.length,0);assert.ok(f.errors.at(-1).includes('110'));assert.equal(value.extra_explanations[0].text.length,111);
});
await test('legacy content retains its existing explanation capacity',async()=>{
 const value=expanded();value.extra_explanations[0].text='a'.repeat(250);const f=fixture({innerPlan:value,plan:{...basePlan(),template_id:'legacy'}});await f.handlers.saveInner();assert.equal(f.calls.length,1);
});
await test('failed save retains the buffer and all editable fields',async()=>{
 const f=fixture({rawWorkflowAction:async()=>{throw new Error('save offline');}});f.setCache({value:{innerPlan:expanded()}});await f.handlers.saveInner();assert.equal(f.removed.length,0);assert.equal(f.state.run.row_version,9);assert.deepEqual(f.cache.value.innerPlan,expanded());assert.equal(f.errors.at(-1),'save offline');
});
await test('same-record navigation while saving accepts the result without jumping back to the set',async()=>{
 let finish;const f=fixture({rawWorkflowAction:()=>new Promise(resolve=>{finish=resolve;})});const pending=f.handlers.saveInner();f.deps.navigation.current++;finish(f.next);await pending;
 assert.deepEqual(f.routes,[]);assert.equal(f.state.run.row_version,10);assert.equal(f.removed.length,1);
});
await test('a cross-course late result cannot clear the local buffer or overwrite the new context',async()=>{
 let finish;const f=fixture({rawWorkflowAction:()=>new Promise(resolve=>{finish=resolve;})});const pending=f.handlers.saveInner();f.deps.generation.current++;finish(f.next);await pending;
 assert.deepEqual(f.routes,[]);assert.equal(f.removed.length,0);assert.equal(f.state.run.row_version,9);
});
await test('inner editing obeys busy, conflict and single-image guards including typed page input',()=>{
 for(const override of [{busy:'Rendering'},{bufferConflict:{}},{briefDirty:true}]){const f=fixture(override);f.handlers.changeInner({sample_pages:[23]});f.handlers.changeInnerPages('23, 24');f.handlers.changeExplanation(0,{title:'late title'});assert.deepEqual(f.writes,[]);}
});
await test('inner plan and its page input are included in the real local edit buffer',()=>{
 const f=fixture();f.handlers.cacheEdits();assert.equal(f.cacheWrites.length,1);assert.deepEqual(f.cacheWrites[0].value.innerPlan,expanded());assert.equal(f.cacheWrites[0].value.innerPagesText,'2, 3, 23, 24');assert.equal(f.cacheWrites[0].baseVersion,'9');
});
await test('receive restores a same-version inner buffer and preserves the saved cover',()=>{
 const f=fixture();f.setCache({baseVersion:'9',value:{copy:f.deps.copy,plan:f.deps.plan,selected:f.deps.selected,pagesText:'2, 3',innerPlan:expanded(),innerPagesText:'2, 3, 23, 24'}});f.handlers.receive(f.deps.run);assert.deepEqual(f.state.innerPlan,expanded());assert.equal(f.state.innerPagesText,'2, 3, 23, 24');assert.equal(f.state.run.data.cover.id,'approved-cover');
});
await test('old buffers without inner fields retain the latest saved inner plan rather than erasing it',()=>{
 const f=fixture();const r=structuredClone(f.deps.run);r.data.set_plan=expanded();f.handlers.applyEditor(r,{copy:f.deps.copy,plan:f.deps.plan,selected:f.deps.selected,pagesText:'2, 3'});assert.deepEqual(f.state.innerPlan,expanded());assert.equal(f.state.innerPagesText,'2, 3, 23, 24');
});
await test('an older version buffer is retained as a conflict, not silently written over the current inner content',()=>{
 const f=fixture();f.setCache({baseVersion:'8',value:{copy:f.deps.copy,plan:f.deps.plan,selected:[],pagesText:'2',innerPlan:expanded()}});f.handlers.receive(f.deps.run);assert.ok(f.state.bufferConflict);assert.deepEqual(f.state.innerPlan,normalSetPlan(undefined,f.deps.run.data.visual_plan));assert.equal(f.removed.length,0);
});
console.log(JSON.stringify({passed:tests.length,tests,network_calls:0,model_calls:0,business_writes:0},null,2));
