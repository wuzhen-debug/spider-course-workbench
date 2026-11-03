import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';

// Execute the production handlers with isolated dependencies. This does not
// render React, call the service/model, read the business DB, or approve a run.
const require=createRequire(import.meta.url),ts=require('../../frontend/node_modules/typescript');
const pageUrl=new URL('../../frontend/src/pages/platforms/xhs/course-visual-workflow-page.tsx',import.meta.url);
const source=fs.readFileSync(pageUrl,'utf8');
const tree=ts.createSourceFile(pageUrl.pathname,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const page=tree.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='CourseVisualWorkflowPage');
assert.ok(page?.body,'The actual workflow page must be available');
const extract=name=>{const node=page.body.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text===name);assert.ok(node,`Production handler ${name} exists`);return node.getText(tree);};
const transpile=value=>ts.transpileModule(value,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const moduleFrom=async value=>import('data:text/javascript;base64,'+Buffer.from(transpile(value)).toString('base64'));
const context=await moduleFrom(fs.readFileSync(new URL('../../frontend/src/lib/course-visual-context.ts',import.meta.url),'utf8'));
const stageNavigation=await moduleFrom(fs.readFileSync(new URL('../../frontend/src/lib/course-visual-navigation.ts',import.meta.url),'utf8'));
const coverHelpers=await moduleFrom(fs.readFileSync(new URL('../../frontend/src/lib/course-cover-sample.ts',import.meta.url),'utf8'));
const pdfPageHelpers=await moduleFrom(fs.readFileSync(new URL('../../frontend/src/lib/course-pdf-pages.ts',import.meta.url),'utf8'));
const names=['requireCoverSample','visualWorkflowAction','action','showStep','refreshHistoryAfterMutation','act','submitRevision','approve','showPrompt'];
const {bind}=await moduleFrom(`export function bind(deps,context,stageNavigation,coverHelpers,pdfPageHelpers){
 const {run,plan,editing,brief,busy,dirty,visualDirty,innerDirty,pdfPagesDirty=false,pdfPagePlan=null,bufferConflict,briefDirty,generation,navigation,checks,
 rawWorkflowAction,receive,loadHistory,setHistoryNotice,setNotice,setBusy,setError,
 setStep,setParams,removeCourseEditBuffer,editScope,errorText,setPrompt,setConsent,aiKey,bundleKey}=deps;
 const {inCourseContext,CourseContextChanged}=context;
 const {visualStageParams,nextVisualStage}=stageNavigation;const {coverSampleIssue}=coverHelpers;const {pdfPageIssue}=pdfPageHelpers;
 ${names.map(extract).join('\n')}
 return {act,submitRevision,approve,refreshHistoryAfterMutation,showPrompt};
}`);

const tests=[];
async function test(name,fn){await fn();tests.push(name);}
function fixture(overrides={}){
 const calls=[],received=[],steps=[],routes=[],removed=[],historyNotices=[],errors=[],busyValues=[],notices=[],prompts=[],consents=[];
 let historyCalls=0,route=new URLSearchParams('run=4&file_id=19901&stage=set&filter=kept');
 const run={id:4,file_id:19901,row_version:7,approved:{copy:true,cover:true},digests:{copy:'copy-v7',cover:'cover-v7',set:'set-v7'},data:{copy:{title:'Synthetic copy',body:'Retained body'},cover:{id:'cover-old'},source:{page_count:56},images:[],operation:null,evidence_review:{limited:false}}};
 const next={...structuredClone(run),row_version:8,approved:{copy:true},data:{...structuredClone(run.data),cover:{id:'cover-new'},images:[]}};
 const deps={run,plan:{sample_pages:[2]},editing:{id:'cover-old',kind:'cover'},brief:{title:'Synthetic revision',layout:'product-hero',nodes:[]},briefDirty:false,busy:'',dirty:false,visualDirty:false,innerDirty:false,bufferConflict:null,generation:{current:12},navigation:{current:20},checks:{},aiKey:{current:'existing-request-key'},bundleKey:{current:'synthetic-bundle'},
  rawWorkflowAction:async(path,data,method)=>{calls.push({path,data,method});return next;},
  receive:value=>received.push(value),loadHistory:async()=>{historyCalls++;},setHistoryNotice:value=>historyNotices.push(value),setNotice:value=>notices.push(value),setBusy:value=>busyValues.push(value),setError:value=>errors.push(value),setStep:value=>steps.push(value),
  setParams:(value,options)=>{route=typeof value==='function'?value(route):new URLSearchParams(value);routes.push({params:new URLSearchParams(route),options});},
  setPrompt:value=>prompts.push(value),setConsent:value=>consents.push(value),
  removeCourseEditBuffer:value=>removed.push(value),editScope:id=>({userId:2,feature:'visual-workbench',recordId:String(id)}),errorText:error=>error.message,
  ...overrides};
 const browserNavigate=stage=>{if(stage!==route.get('stage'))deps.navigation.current++;route.set('stage',stage);};
 return {deps,next,calls,received,steps,routes,removed,historyNotices,errors,busyValues,notices,prompts,consents,browserNavigate,get currentStage(){return route.get('stage');},get historyCalls(){return historyCalls;},handlers:bind(deps,context,stageNavigation,coverHelpers,pdfPageHelpers)};
}
function assertStage(f,expected){
 assert.equal(f.steps.at(-1),expected);
 assert.equal(f.routes.at(-1)?.params.get('stage'),stageNavigation.visualStageNames[expected]);
 assert.equal(f.routes.at(-1)?.params.get('run'),'4');assert.equal(f.routes.at(-1)?.params.get('file_id'),'19901');assert.equal(f.routes.at(-1)?.params.get('filter'),'kept');
}
function assertNoSuccessfulMutation(f){assert.deepEqual(f.received,[]);assert.deepEqual(f.steps,[]);assert.deepEqual(f.routes,[]);assert.deepEqual(f.removed,[]);assert.equal(f.historyCalls,0);}

for(const [stage,target] of [['cover',2],['set',4]])await test(`render ${stage} lands on its review stage without issuing any approval or export`,async()=>{
 const f=fixture();const before=structuredClone(f.deps.run);await f.handlers.act('render',{stage},'本机制作');
 assert.deepEqual(f.calls,[{path:'/4/render',data:{expected_version:7,stage},method:'post'}]);assertStage(f,target);
 assert.deepEqual(f.received,[f.next]);assert.deepEqual(f.deps.run,before);assert.equal(f.next.approved.cover,undefined);assert.equal(f.next.approved.set,undefined);assert.equal(f.historyCalls,1);
});
await test('successful render stays successful if only the work-record list refresh fails',async()=>{
 const f=fixture({loadHistory:async()=>{throw new Error('record-list offline');}});await f.handlers.act('render',{stage:'cover'},'制作封面');
 assert.deepEqual(f.received,[f.next]);assertStage(f,2);assert.deepEqual(f.errors.filter(Boolean),[]);assert.equal(f.busyValues.at(-1),'');
 assert.match(f.historyNotices.at(-1),/保存成功/);assert.match(f.historyNotices.at(-1),/不必重复/);assert.equal(f.calls.length,1);
});
await test('export stays on the set and preserves the exact newly returned draft association',async()=>{
 const f=fixture();f.next.data.export={draft_id:732,draft_available:true};await f.handlers.act('export',{reviewed:true,digest:'set-v7'},'另存新草稿');
 assert.deepEqual(f.calls,[{path:'/4/export',data:{expected_version:7,reviewed:true,digest:'set-v7'},method:'post'}]);assertStage(f,4);assert.equal(f.received[0].data.export.draft_id,732);
 assert.deepEqual(f.removed,[]);assert.equal(f.calls.some(call=>/publish|auto-ops|schedule/.test(call.path)),false);
});
await test('restore selects the actionable stage from returned data without inferring approval',async()=>{
 const f=fixture();f.next.approved={};f.next.data.cover=null;await f.handlers.act('restore',{revision:2},'以旧版重新编辑');assertStage(f,1);assert.deepEqual(f.received[0].approved,{});
});
for(const [endpoint,target] of [['generate-copy',1]])await test(`${endpoint} lands on its editing/review stage only`,async()=>{
 const f=fixture();await f.handlers.act(endpoint,{request_key:'synthetic'},'生成');assertStage(f,target);assert.equal(f.calls.length,1);assert.equal(f.calls[0].path,`/4/${endpoint}`);
});
await test('explicit approval does not automatically skip to the next review node',async()=>{
 const f=fixture({checks:{cover:true}});await f.handlers.approve('cover');
 assert.deepEqual(f.calls,[{path:'/4/approve',data:{expected_version:7,stage:'cover',reviewed:true,limited_sources_reviewed:false,digest:'cover-v7'},method:'post'}]);
 assert.deepEqual(f.steps,[]);assert.deepEqual(f.routes,[]);assert.equal(f.calls.length,1);
});
await test('an unchecked review is never rewritten as reviewed by the handler',async()=>{
 const f=fixture({checks:{}});await f.handlers.approve('cover');assert.equal(f.calls[0].data.reviewed,false);assert.deepEqual(f.steps,[]);assert.deepEqual(f.routes,[]);
});

for(const [kind,target] of [['cover',2],['sample',4],['method',4]])await test(`revising a ${kind} returns to the appropriate review stage and only clears the submitted buffer`,async()=>{
 const f=fixture({editing:{id:'synthetic-image',kind}});await f.handlers.submitRevision();assertStage(f,target);
 assert.deepEqual(f.calls,[{path:'/4/revise',data:{expected_version:7,asset_id:'synthetic-image',brief:f.deps.brief},method:'post'}]);
 assert.deepEqual(f.removed,[{userId:2,feature:'visual-workbench',recordId:'4'}]);assert.deepEqual(f.received,[f.next]);assert.equal(f.calls.length,1);
});
await test('successful single-image revision is not reported failed after a history-list error',async()=>{
 const f=fixture({loadHistory:async()=>{throw new Error('history offline');}});await f.handlers.submitRevision();assertStage(f,2);
 assert.deepEqual(f.errors.filter(Boolean),[]);assert.equal(f.received.length,1);assert.equal(f.removed.length,1);assert.match(f.historyNotices.at(-1),/保存成功/);
});
for(const [label,override] of Object.entries({
 busy:{busy:'制作内页'},copy_edits:{dirty:true},visual_edits:{visualDirty:true},conflict:{bufferConflict:{value:{}}},missing_run:{run:null},missing_image:{editing:null},missing_brief:{brief:null},
 generating:{run:{id:4,row_version:7,data:{operation:{status:'generating'}}}},
}))await test(`single-image revision cannot submit while ${label}`,async()=>{
 const f=fixture(override);await f.handlers.submitRevision();assert.deepEqual(f.calls,[]);assertNoSuccessfulMutation(f);
});
await test('failed mutation retains existing record, image, edit buffer and stage',async()=>{
 const f=fixture({rawWorkflowAction:async()=>{throw new Error('render unavailable');}});await f.handlers.submitRevision();assertNoSuccessfulMutation(f);assert.equal(f.errors.at(-1),'render unavailable');assert.equal(f.busyValues.at(-1),'');
});
for(const handler of ['act','submitRevision'])await test(`${handler} rejects a late result after changing course or account`,async()=>{
 let finish;const f=fixture({rawWorkflowAction:()=>new Promise(resolve=>{finish=resolve;})});
 const pending=handler==='act'?f.handlers.act('render',{stage:'set'},'制作整套'):f.handlers.submitRevision();assert.equal(typeof finish,'function');
 f.deps.generation.current++;const writes={busy:f.busyValues.length,error:f.errors.length};finish(f.next);await pending;
 assertNoSuccessfulMutation(f);assert.deepEqual({busy:f.busyValues.length,error:f.errors.length},writes);
});
for(const movement of ['back','back-forward'])for(const operation of ['render-cover','render-set','export','revise-cover','revise-sample'])await test(`${operation} accepts its saved result without taking over a ${movement} browser navigation`,async()=>{
 let finish;const f=fixture({rawWorkflowAction:()=>new Promise(resolve=>{finish=resolve;}),...(operation==='revise-sample'?{editing:{id:'sample-old',kind:'sample'}}:{})});
 const pending=operation.startsWith('revise')?f.handlers.submitRevision():operation==='export'?f.handlers.act('export',{reviewed:true,digest:'set-v7'},'另存草稿'):f.handlers.act('render',{stage:operation==='render-cover'?'cover':'set'},'本机制作');
 assert.equal(typeof finish,'function');const recordEpoch=f.deps.generation.current,navigationEpoch=f.deps.navigation.current;
 f.browserNavigate('copy');if(movement==='back-forward')f.browserNavigate('set');
 const chosenStage=f.currentStage;assert.equal(f.deps.navigation.current,navigationEpoch+(movement==='back'?1:2));assert.equal(f.deps.generation.current,recordEpoch,'Navigation must not invalidate a same-record mutation');
 finish(f.next);await pending;
 assert.deepEqual(f.received,[f.next],'The successful new record must still be shown');assert.deepEqual(f.steps,[]);assert.deepEqual(f.routes,[]);assert.equal(f.currentStage,chosenStage,'Completion must leave the browser-selected stage alone');assert.equal(f.historyCalls,1);assert.deepEqual(f.errors.filter(Boolean),[]);assert.equal(f.busyValues.at(-1),'');
 assert.equal(f.removed.length,operation.startsWith('revise')?1:0);
});
await test('a prompt prepared for the current stage can still open normally',async()=>{
 const f=fixture();await f.handlers.showPrompt('visual');assert.deepEqual(f.prompts,[f.next]);assert.deepEqual(f.consents,[false]);assert.notEqual(f.deps.aiKey.current,'existing-request-key');assert.equal(f.calls[0].path,'/4/prompts?purpose=visual');
});
for(const movement of ['back','back-forward'])await test(`a late prompt cannot reopen a modal after ${movement} navigation`,async()=>{
 let finish;const f=fixture({rawWorkflowAction:()=>new Promise(resolve=>{finish=resolve;})});const pending=f.handlers.showPrompt('visual');assert.equal(typeof finish,'function');
 f.browserNavigate('copy');if(movement==='back-forward')f.browserNavigate('set');finish({prompt:'A synthetic prepared prompt'});await pending;
 assert.deepEqual(f.prompts,[]);assert.deepEqual(f.consents,[]);assert.equal(f.deps.aiKey.current,'existing-request-key');assert.deepEqual(f.routes,[]);assert.deepEqual(f.errors.filter(Boolean),[]);assert.equal(f.busyValues.at(-1),'');
});
await test('history context cancellation does not leak a stale success warning into another course',async()=>{
 const f=fixture({loadHistory:async()=>{throw new context.CourseContextChanged();}});await f.handlers.refreshHistoryAfterMutation();assert.deepEqual(f.historyNotices,[]);assert.deepEqual(f.errors,[]);
});
await test('a later successful history refresh clears the non-blocking warning',async()=>{
 const f=fixture();await f.handlers.refreshHistoryAfterMutation();assert.deepEqual(f.historyNotices,['']);assert.equal(f.historyCalls,1);
});

// Verify the production UI links a saved run to that exact draft and preserves
// the explicit cover/set approval checkboxes before the export action.
function walk(node,visit){visit(node);ts.forEachChild(node,n=>walk(n,visit));}
const elements=[];walk(page,n=>{if(ts.isJsxElement(n)||ts.isJsxSelfClosingElement(n))elements.push(n);});
const opening=node=>ts.isJsxElement(node)?node.openingElement:node;
const attr=(node,name)=>opening(node).attributes.properties.find(p=>p.name?.getText(tree)===name);
const exactDraftLink=elements.find(node=>opening(node).tagName.getText(tree)==='Link'&&attr(node,'to')?.initializer?.getText(tree).includes('run.data.export.draft_id'));
assert.ok(exactDraftLink,'The saved run must link to its exact draft ID');assert.ok(attr(exactDraftLink,'to').initializer.getText(tree).includes('/platforms/xhs/drafts?draft_id='));
for(const label of ['仅确认成品，暂不另存']){
 const button=elements.find(node=>opening(node).tagName.getText(tree)==='Button'&&node.getText(tree).includes(`>${label}</Button>`));assert.ok(button,`${label} stays explicit`);
 const predicate=attr(button,'disabled').initializer.expression.getText(tree);const disabled=Function('locked','checks','run',`return (${predicate});`);
 assert.equal(!!disabled(false,{}, {approved:{}}),true);assert.equal(!!disabled(false,{set:true},{approved:{}}),false);assert.equal(!!disabled(true,{set:true},{approved:{}}),true);
}
tests.push('production UI keeps exact draft links and one deliberate combined review gate');

// Evaluate just the actual set-stage JSX with inert element factories. This
// checks each visible state without matching one long line of source text.
let setStageCard;
walk(page,node=>{
 if(!ts.isBinaryExpression(node)||node.operatorToken.kind!==ts.SyntaxKind.AmpersandAmpersandToken||!ts.isBinaryExpression(node.left))return;
 const condition=node.left;
 if(condition.operatorToken.kind===ts.SyntaxKind.EqualsEqualsEqualsToken&&ts.isIdentifier(condition.left)&&condition.left.text==='step'&&ts.isNumericLiteral(condition.right)&&condition.right.text==='4')setStageCard=node.right;
});
assert.ok(setStageCard,'The set stage must remain a separately rendered review step');
const setPreviewCode=`export function renderSet({run,checks={},locked=false,busy='',briefDirty=false,dirty=false,visualDirty=false,innerDirty=false,bufferConflict=null}) {
 const plan=run.data.visual_plan||{method_text:''},innerPlan=run.data.set_plan||{sample_pages:[1],sample_instructions:[],extra_explanations:[]};
 const innerPagesText=innerPlan.sample_pages.join(', '),plannedCount=1+(plan.method_text.trim()?1:0)+innerPlan.extra_explanations.length+innerPlan.sample_pages.length+1,innerTextLimit=200;
 const React={Fragment:'Fragment',createElement:(type,props,...children)=>({type,props:props||{},children})};
 const [Card,Space,Button,Tag,Alert,Text,Paragraph,Checkbox,Link,Collapse,Select,PlusOutlined]=['Card','Space','Button','Tag','Alert','Text','Paragraph','Checkbox','Link','Collapse','Select','PlusOutlined'];const Input={TextArea:'TextArea'};
 const productionOptions=[],setProductionOptions=()=>{};const pdfPageControls=()=>null,apiImageControls=()=>null;
 const reviewGallery=assets=>({type:'ReviewGallery',props:{assets},children:[]});
 return (${setStageCard.getText(tree)});
}`;
const setPreviewModule=ts.transpileModule(setPreviewCode,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.React}}).outputText;
const {renderSet}=await import('data:text/javascript;base64,'+Buffer.from(setPreviewModule).toString('base64'));
const displayedNodes=root=>{const out=[];const visit=value=>{if(!value||typeof value!=='object')return;if(Array.isArray(value)){value.forEach(visit);return;}out.push(value);visit(value.children);};visit(root);return out;};
const displayedText=node=>typeof node==='string'||typeof node==='number'?String(node):Array.isArray(node)?node.map(displayedText).join(''):node&&typeof node==='object'?displayedText(node.children):'';
const setFixture=()=>({approved:{copy:true,cover:true,set:false},digests:{set:'synthetic-set'},data:{images:[],cover:{id:'synthetic-cover'},export:null,source:{page_count:56}}});
await test('an ungenerated set explains the next step and does not present unavailable review or draft controls',async()=>{
 const nodes=displayedNodes(renderSet({run:setFixture()}));
 const warning=nodes.find(node=>node.type==='Alert'&&node.props.type==='warning');assert.equal(warning?.props.message,'整套图片尚未生成，当前无法审核或另存');
 assert.equal(nodes.some(node=>node.type==='Checkbox'),false,'There are no images to review or export yet');
 assert.deepEqual(nodes.filter(node=>node.type==='Button'&&node.props.type==='primary').map(displayedText),[]);assert.equal(displayedText(warning.props.action),'去制作图片');
 assert.equal(nodes.some(node=>node.type==='Button'&&/确认当前整套图|确认后另存/.test(displayedText(node))),false);
});
await test('a generated unreviewed set presents deliberate review and explains why draft saving waits',async()=>{
 const run=setFixture();run.data.images=[{id:'synthetic-image'}];const nodes=displayedNodes(renderSet({run}));
 assert.equal(nodes.filter(node=>node.type==='ReviewGallery').length,1);assert.equal(nodes.filter(node=>node.type==='Checkbox').length,1);
 assert.equal(nodes.find(node=>node.type==='Button'&&displayedText(node)==='审核通过并另存新草稿')?.props.disabled,true);
 assert.equal(nodes.some(node=>node.type==='Button'&&displayedText(node)==='另存为新草稿'),false);
 assert.ok(nodes.some(node=>node.type==='Alert'&&node.props.message==='请核对封面和全部内页'));
});
await test('an approved set exposes the explicit draft check and preserves its exact saved-draft link',async()=>{
 const run=setFixture();run.data.images=[{id:'synthetic-image'}];run.approved.set=true;
 let nodes=displayedNodes(renderSet({run}));assert.equal(nodes.filter(node=>node.type==='Checkbox').length,1,'Only the next deliberate export check remains after set review');
 assert.equal(nodes.some(node=>node.type==='Button'&&displayedText(node)==='审核通过并另存新草稿'),false,'Completed review does not leave an inactive confirmation button');
 assert.equal(nodes.find(node=>node.type==='Button'&&displayedText(node)==='另存为新草稿')?.props.disabled,true);
 nodes=displayedNodes(renderSet({run,checks:{set:true}}));assert.equal(nodes.find(node=>node.type==='Button'&&displayedText(node)==='另存为新草稿')?.props.disabled,false);
 run.data.export={draft_id:732,draft_available:true};nodes=displayedNodes(renderSet({run}));
 assert.equal(nodes.find(node=>node.type==='Link')?.props.to,'/platforms/xhs/drafts?draft_id=732');
 assert.equal(nodes.some(node=>node.type==='Button'&&displayedText(node)==='另存为新草稿'),false,'Already-saved state must not invite duplicate export');
 run.data.export.draft_available=false;nodes=displayedNodes(renderSet({run}));assert.equal(nodes.some(node=>node.type==='Link'),false);
});
console.log(JSON.stringify({passed:tests.length,tests,network_calls:0,model_calls:0,business_writes:0},null,2));
