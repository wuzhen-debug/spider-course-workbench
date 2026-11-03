import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),ts=require('../../frontend/node_modules/typescript');
const pageUrl=new URL('../../frontend/src/pages/platforms/xhs/course-visual-workflow-page.tsx',import.meta.url);
const source=fs.readFileSync(pageUrl,'utf8'),tree=ts.createSourceFile(pageUrl.pathname,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const page=tree.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='CourseVisualWorkflowPage');
const extract=name=>{const n=page.body.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text===name);assert.ok(n,`Production handler ${name} exists`);return n.getText(tree);};
const handlers=['visualWorkflowAction','action','refreshHistoryAfterMutation','showStep','saveEdits','saveCopy','saveVisual'].map(extract).join('\n');
const contextSource=fs.readFileSync(new URL('../../frontend/src/lib/course-visual-context.ts',import.meta.url),'utf8');
const transpile=s=>ts.transpileModule(s,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const context=await import('data:text/javascript;base64,'+Buffer.from(transpile(contextSource)).toString('base64'));
const navigation=await import('data:text/javascript;base64,'+Buffer.from(transpile(fs.readFileSync(new URL('../../frontend/src/lib/course-visual-navigation.ts',import.meta.url),'utf8'))).toString('base64'));
const pdfPageHelpers=await import('data:text/javascript;base64,'+Buffer.from(transpile(fs.readFileSync(new URL('../../frontend/src/lib/course-pdf-pages.ts',import.meta.url),'utf8'))).toString('base64'));
const harness=`export function bind(deps,context,navigationHelpers,pdfPageHelpers){
 const {run,copy,plan,innerPlan,busy,bufferConflict,briefDirty,dirty,visualDirty,innerDirty,pdfPagesDirty=false,pdfPagePlan=null,step,selected,generation,navigation,
 rawWorkflowAction,removeCourseEditBuffer,editScope,receive,loadHistory,setHistoryNotice,setNotice,setStep,setParams,setBusy,setError,errorText}=deps;
 const {inCourseContext,CourseContextChanged}=context;
 const {visualStageParams}=navigationHelpers;const {pdfPageIssue}=pdfPageHelpers;
 ${handlers}
 return {saveEdits,saveCopy,saveVisual,showStep,refreshHistoryAfterMutation};
}`;
const {bind}=await import('data:text/javascript;base64,'+Buffer.from(transpile(harness)).toString('base64'));
const tests=[];
async function test(name,fn){await fn();tests.push(name);}
function fixture(overrides={}){
 const calls=[],removed=[],received=[],steps=[],notices=[],historyNotices=[],errors=[],busyValues=[],routes=[];let historyCalls=0;
 let params=new URLSearchParams('run=4&file_id=19901&stage=cover&filter=kept');
 const next={id:4,row_version:4,data:{operation:null}};
 const deps={run:{id:4,row_version:3,data:{operation:null,source:{page_count:56}}},copy:{title:'Synthetic copy',body:'Kept body'},plan:{cover_lines:['Synthetic cover'],sample_pages:[1,4]},innerPlan:{sample_pages:[1,4],sample_instructions:[],extra_explanations:[]},innerDirty:false,busy:'',bufferConflict:null,briefDirty:false,dirty:false,visualDirty:true,step:3,selected:['source-a'],generation:{current:9},navigation:{current:0},
 rawWorkflowAction:async(path,data,method)=>{calls.push({path,data,method});return next;},removeCourseEditBuffer:x=>removed.push(x),editScope:id=>({userId:1,feature:'visual-workbench',recordId:String(id)}),receive:x=>received.push(x),loadHistory:async()=>{historyCalls++;},setHistoryNotice:x=>historyNotices.push(x),setNotice:x=>notices.push(x),setStep:x=>steps.push(x),setParams:(update,options)=>{params=typeof update==='function'?update(params):new URLSearchParams(update);routes.push({params:new URLSearchParams(params),options});},setBusy:x=>busyValues.push(x),setError:x=>errors.push(x),errorText:e=>e.message,...overrides};
 return {deps,calls,removed,received,steps,notices,historyNotices,errors,busyValues,routes,get params(){return params;},get historyCalls(){return historyCalls;},handlers:bind(deps,context,navigation,pdfPageHelpers)};
}
await test('visual edits save directly from cover step without rendering or approving',async()=>{
 const f=fixture();await f.handlers.saveEdits();assert.equal(f.calls.length,1);
 assert.equal(f.calls[0].path,'/4');assert.equal(f.calls[0].method,'patch');
 assert.deepEqual(f.calls[0].data,{expected_version:3,visual_plan:f.deps.plan});
 assert.deepEqual(f.steps,[2]);assert.equal(f.params.get('stage'),'visual');assert.equal(f.received.length,1);assert.equal(f.removed.length,1);assert.equal(f.historyCalls,1);
});
await test('copy and plan are saved together and return to copy review from cover',async()=>{
 const f=fixture({dirty:true});await f.handlers.saveEdits();
 assert.deepEqual(f.calls[0].data,{expected_version:3,copy:f.deps.copy,selected_source_ids:['source-a'],visual_plan:f.deps.plan});
 assert.deepEqual(f.steps,[1]);assert.ok(f.notices.at(-1).includes('重新确认文案'));
 assert.equal(f.params.get('stage'),'copy');assert.equal(f.params.get('run'),'4');assert.equal(f.params.get('file_id'),'19901');assert.equal(f.params.get('filter'),'kept');
});
await test('copy review step stays in place after saving copy',async()=>{
 const f=fixture({dirty:true,visualDirty:false,step:1});await f.handlers.saveCopy();assert.deepEqual(f.steps,[1]);assert.equal(f.params.get('stage'),'copy');
 assert.deepEqual(f.calls[0].data,{expected_version:3,copy:f.deps.copy,selected_source_ids:['source-a']});
});
await test('visual save alias uses the same guarded PATCH',async()=>{
 const f=fixture();await f.handlers.saveVisual();assert.equal(f.calls[0].method,'patch');assert.equal(f.calls[0].path,'/4');
});
await test('navigation updates the same run URL without editor reload, buffer removal or API calls',async()=>{
 const f=fixture();const copy=structuredClone(f.deps.copy),plan=structuredClone(f.deps.plan);
 f.handlers.showStep(2);f.handlers.showStep(3,true);f.handlers.showStep(4);
 assert.deepEqual(f.steps,[2,3,4]);assert.deepEqual(f.routes.map(route=>route.params.get('stage')),['visual','cover','set']);
 assert.deepEqual(f.routes.map(route=>route.options),[{replace:false},{replace:true},{replace:false}]);
 for(const route of f.routes){assert.equal(route.params.get('run'),'4');assert.equal(route.params.get('file_id'),'19901');assert.equal(route.params.get('filter'),'kept');}
 assert.deepEqual(f.calls,[]);assert.deepEqual(f.removed,[]);assert.deepEqual(f.received,[]);assert.equal(f.historyCalls,0);assert.equal(f.deps.generation.current,9);
 assert.deepEqual(f.deps.copy,copy);assert.deepEqual(f.deps.plan,plan);
});
await test('history refresh failure does not turn a completed PATCH into a failed save',async()=>{
 let historyCalls=0;const f=fixture({loadHistory:async()=>{historyCalls++;throw new Error('history temporarily unavailable');}});
 await f.handlers.saveEdits();assert.equal(f.calls.length,1);assert.equal(f.received.length,1);assert.equal(f.removed.length,1);assert.equal(historyCalls,1);
 assert.deepEqual(f.steps,[2]);assert.equal(f.params.get('stage'),'visual');assert.equal(f.errors.at(-1),'');
 assert.ok(f.historyNotices.at(-1).includes('当前操作已保存成功'));assert.ok(f.notices.at(-1).includes('视觉方案已保存'));
});
await test('history context change is ignored rather than warning in a different record',async()=>{
 const f=fixture({loadHistory:async()=>{throw new context.CourseContextChanged();}});await f.handlers.refreshHistoryAfterMutation();
 assert.deepEqual(f.historyNotices,[]);assert.deepEqual(f.errors,[]);assert.deepEqual(f.calls,[]);
});
for(const [label,override] of Object.entries({
 busy:{busy:'制作封面'},'remote generation':{run:{id:4,row_version:3,data:{operation:{status:'generating'}}}},
 'single image edit':{briefDirty:true},conflict:{bufferConflict:{value:{}}},'no edits':{dirty:false,visualDirty:false},
 'missing run':{run:null},'missing copy':{copy:null},'missing plan':{plan:null},
}))await test(`${label} cannot submit or clear local buffers`,async()=>{
 const f=fixture(override);await f.handlers.saveEdits();await f.handlers.saveCopy();await f.handlers.saveVisual();
 assert.deepEqual(f.calls,[]);assert.deepEqual(f.removed,[]);assert.deepEqual(f.received,[]);
});
await test('failed PATCH preserves the buffer, current editor and review step',async()=>{
 const f=fixture({dirty:true,rawWorkflowAction:async()=>{throw new Error('save failed');}});await f.handlers.saveEdits();
 assert.deepEqual(f.removed,[]);assert.deepEqual(f.received,[]);assert.deepEqual(f.steps,[]);assert.equal(f.historyCalls,0);assert.equal(f.errors.at(-1),'save failed');
});
for(const dirty of [false,true])await test(`${dirty?'copy':'visual'} PATCH finishes after same-run navigation without taking the user back to its old stage`,async()=>{
 let finish;const f=fixture({dirty,rawWorkflowAction:()=>new Promise(resolve=>{finish=resolve;})});
 const saving=f.handlers.saveEdits();assert.equal(typeof finish,'function');
 f.handlers.showStep(4);f.deps.navigation.current++; // Mirrors the production render-time stage epoch.
 assert.equal(f.deps.generation.current,9,'Same-run navigation must keep the pending API context valid');
 const saved={id:4,row_version:4,data:{copy:f.deps.copy,visual_plan:f.deps.plan}};
 finish(saved);await saving;
 assert.deepEqual(f.received,[saved],'The valid save response still updates the current record');
 assert.deepEqual(f.removed,[{userId:1,feature:'visual-workbench',recordId:'4'}],'The submitted buffer is cleared only after success');
 assert.equal(f.historyCalls,1);assert.deepEqual(f.steps,[4],'The delayed save must not steal navigation back to copy or cover');
 assert.equal(f.params.get('stage'),'set');assert.equal(f.params.get('run'),'4');assert.equal(f.routes.length,1);assert.equal(f.errors.at(-1),'');
 assert.deepEqual(f.notices,[''],'A delayed save must not place its old-stage instruction in the new stage');assert.equal(f.busyValues.at(-1),'');
});
await test('actual context guard rejects a late response before buffer or editor changes',async()=>{
 let finish;const f=fixture({dirty:true,rawWorkflowAction:()=>new Promise(resolve=>{finish=resolve;})});
 const saving=f.handlers.saveEdits();assert.equal(typeof finish,'function');f.deps.generation.current++;
 const busyCount=f.busyValues.length,errorCount=f.errors.length,noticeCount=f.notices.length;
 finish({id:4,row_version:4,data:{}});await saving;
 assert.deepEqual(f.removed,[]);assert.deepEqual(f.received,[]);assert.deepEqual(f.steps,[]);assert.equal(f.historyCalls,0);
 assert.equal(f.busyValues.length,busyCount);assert.equal(f.errors.length,errorCount);assert.equal(f.notices.length,noticeCount);
});

function walk(node,visit){visit(node);ts.forEachChild(node,n=>walk(n,visit));}
const elements=[];walk(tree,n=>{if(ts.isJsxElement(n)||ts.isJsxSelfClosingElement(n))elements.push(n);});
const opening=n=>ts.isJsxElement(n)?n.openingElement:n;
const attr=(n,name)=>opening(n).attributes.properties.find(p=>p.name?.getText(tree)===name);
const pending=elements.find(n=>opening(n).tagName.getText(tree)==='Alert'&&attr(n,'className')?.initializer?.text==='vd-pending-actions');
assert.ok(pending,'Save controls must be visible outside individual editing steps');
assert.ok(pending.getText(tree).includes('保存当前修改'));
assert.ok(pending.getStart(tree)<source.indexOf('{step===0'));
const css=fs.readFileSync(new URL('../../frontend/src/pages/platforms/xhs/course-visual-workflow.css',import.meta.url),'utf8');
assert.match(css,/\.vd-pending-actions\s*\{[^}]*position\s*:\s*sticky/);
const gallery=tree.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='ReviewGallery');
const galleryElements=[];walk(gallery,n=>{if(ts.isJsxElement(n)||ts.isJsxSelfClosingElement(n))galleryElements.push(n);});
const downloads=galleryElements.filter(n=>opening(n).tagName.getText(tree)==='Button'&&/下载当前原图|下载 SVG 源文件/.test(n.getText(tree)));
assert.equal(downloads.length,2);
for(const button of downloads)assert.equal(attr(button,'disabled').initializer.expression.getText(tree),'busy','Unsaved text must not disable old-image downloads');
for(const button of galleryElements.filter(n=>opening(n).tagName.getText(tree)==='button'))assert.equal(attr(button,'disabled'),undefined,'Thumbnail review is read-only');
const editTooltip=galleryElements.find(n=>opening(n).tagName.getText(tree)==='Tooltip'&&n.getText(tree).includes('onEdit(asset)'));
assert.ok(editTooltip);assert.ok(attr(editTooltip,'title').initializer.expression.getText(tree).includes('lockReason'));
const picture=tree.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='Picture');
let image;walk(picture,n=>{if(ts.isJsxSelfClosingElement(n)&&n.tagName.getText(tree)==='Image')image=n;});
const previewExpression=attr(image,'preview').initializer.expression.getText(tree),previewOption=Function('thumbnail','asset','detailUrl','url',`return (${previewExpression});`);
assert.equal(previewOption(true,{kind:'collage'},'blob:source','blob:png'),false);
assert.equal(previewOption(false,{kind:'cover'},'','blob:png'),true,'Ordinary full images remain zoomable independently of dirty state');
assert.deepEqual(previewOption(false,{kind:'collage'},'blob:source','blob:png'),{src:'blob:source'},'Collage zoom uses the retained high-detail SVG');
assert.deepEqual(previewOption(false,{kind:'collage'},'','blob:png'),{src:'blob:png'},'Missing SVG never blocks PNG review');
tests.push('sticky save controls, read-only previews/downloads and explanatory edit tooltip are wired in production JSX');
console.log(JSON.stringify({passed:tests.length,tests,network_calls:0,model_calls:0,business_writes:0},null,2));
