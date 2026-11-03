import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';

// Execute the production normalization and fork handlers without a service,
// account, filesystem writes, browser, model, or workflow mutations.
const require=createRequire(import.meta.url),ts=require('../../frontend/node_modules/typescript');
const url=new URL('../../frontend/src/pages/platforms/xhs/course-visual-workflow-page.tsx',import.meta.url);
const source=fs.readFileSync(url,'utf8'),tree=ts.createSourceFile(url.pathname,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const page=tree.statements.find(node=>ts.isFunctionDeclaration(node)&&node.name?.text==='CourseVisualWorkflowPage');
const extract=name=>{const node=page.body.statements.find(node=>ts.isFunctionDeclaration(node)&&node.name?.text===name);assert.ok(node,`Production ${name} is available`);return node.getText(tree);};
const variable=name=>{const statement=tree.statements.find(node=>ts.isVariableStatement(node)&&node.declarationList.declarations.some(d=>d.name.getText(tree)===name));assert.ok(statement);return statement.getText(tree);};
const transpile=value=>ts.transpileModule(value,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const moduleFrom=async value=>import('data:text/javascript;base64,'+Buffer.from(transpile(value)).toString('base64'));
const context=await moduleFrom(fs.readFileSync(new URL('../../frontend/src/lib/course-visual-context.ts',import.meta.url),'utf8'));
const {normalPlan}=await moduleFrom(variable('normalPlan')+'\nexport {normalPlan};');
const {bind}=await moduleFrom(`export function bind(deps,context){
 const {run,plan,briefDirty,busy,hasEdits,bufferConflict,generation,navigation,rawWorkflowAction,setParams,setRecordsOpen,setNotice,setBusy,setError,errorText,loadHistory,setHistoryNotice,receive,showStep}=deps;
 const {inCourseContext,CourseContextChanged}=context;
 ${['visualWorkflowAction','action','refreshHistoryAfterMutation','forkRun','selectMagazineTemplate'].map(extract).join('\n')}
 return {forkRun,selectMagazineTemplate};
}`);
const tests=[];
async function test(name,fn){await fn();tests.push(name);}
function fixture(overrides={}){
 const calls=[],routes=[],notices=[],errors=[],busy=[],recordDrawer=[];let refreshes=0;
 const run={id:4,file_id:19901,row_version:7,data:{copy:{title:'Existing copy'},visual_plan:{style:'product-editorial'},operation:null}};
 const next={...structuredClone(run),id:8,row_version:1};
 const deps={run,plan:run.data.visual_plan,briefDirty:false,receive:()=>{},showStep:()=>{},busy:'',hasEdits:false,bufferConflict:null,generation:{current:6},navigation:{current:2},rawWorkflowAction:async(path,data,method)=>{calls.push({path,data,method});return next;},setParams:value=>routes.push(value),setRecordsOpen:value=>recordDrawer.push(value),setNotice:value=>notices.push(value),setBusy:value=>busy.push(value),setError:value=>errors.push(value),errorText:error=>error.message,loadHistory:async()=>{refreshes++;},setHistoryNotice:()=>{},...overrides};
 return {deps,next,calls,routes,notices,errors,busy,recordDrawer,get refreshes(){return refreshes;},handlers:bind(deps,context)};
}

await test('legacy data normalizes symmetrically without inventing a new template selection or modifying source',()=>{
 const saved={style:'product-editorial',method_layout:'editorial',method_nodes:[],sample_pages:[1]};const original=structuredClone(saved);
 const editor=normalPlan(saved);assert.deepEqual(normalPlan(editor),normalPlan(saved));assert.deepEqual(saved,original);
 assert.equal(editor.template_id,'legacy');assert.equal(editor.density,'standard');
 assert.notDeepEqual(normalPlan({...editor,template_id:'sample-led'}),normalPlan(saved));
});
await test('new template and standard survive normalization and repeated reload',()=>{
 const plan={template_id:'decision-map',density:'compact',style:'product-editorial',sample_pages:[7],method_nodes:['条件｜说明']};
 const normalized=normalPlan(plan);assert.equal(normalized.template_id,'decision-map');assert.equal(normalized.density,'compact');assert.deepEqual(normalPlan(normalized),normalized);assert.deepEqual(normalized.sample_pages,[7]);
});
await test('fork creates one new pending record and routes by its exact ID without overwriting the current record',async()=>{
 const f=fixture(),before=structuredClone(f.deps.run);await f.handlers.forkRun();
 assert.deepEqual(f.calls,[{path:'/4/fork',data:{expected_version:7},method:'post'}]);
 assert.deepEqual(f.routes,[{run:'8',file_id:'19901',stage:'copy'}]);assert.deepEqual(f.deps.run,before);
 assert.deepEqual(f.recordDrawer,[false]);assert.equal(f.busy.at(-1),'');assert.equal(f.calls.some(c=>/approve|export|publish|auto/.test(c.path)),false);
});
for(const [label,override] of Object.entries({busy:{busy:'Saving'},unsaved:{hasEdits:true},conflict:{bufferConflict:{value:{}}},generating:{run:{id:4,row_version:7,data:{operation:{status:'generating'}}}},missing:{run:null}}))await test(`fork rejects ${label} before API or route changes`,async()=>{
 const f=fixture(override);await f.handlers.forkRun();assert.deepEqual(f.calls,[]);assert.deepEqual(f.routes,[]);assert.deepEqual(f.notices,[]);
});
await test('a fork finishing after same-record navigation preserves the chosen page and leaves a discoverable record notice',async()=>{
 let finish;const f=fixture({rawWorkflowAction:()=>new Promise(resolve=>{finish=resolve;})});
 const pending=f.handlers.forkRun();f.deps.navigation.current++;finish(f.next);await pending;
 assert.deepEqual(f.routes,[]);assert.ok(f.notices.some(message=>message.includes('#8')));assert.equal(f.refreshes,1);assert.equal(f.busy.at(-1),'');
});
await test('late fork response cannot change a different course/account view',async()=>{
 let finish;const f=fixture({rawWorkflowAction:()=>new Promise(resolve=>{finish=resolve;})});const pending=f.handlers.forkRun();
 f.deps.generation.current++;const count=f.notices.length;finish(f.next);await pending;
 assert.deepEqual(f.routes,[]);assert.equal(f.notices.length,count);assert.deepEqual(f.recordDrawer,[]);
});
await test('failed fork preserves current work and shows the actual operation failure',async()=>{
 const f=fixture({rawWorkflowAction:async()=>{throw new Error('version conflict');}}),before=structuredClone(f.deps.run);await f.handlers.forkRun();
 assert.deepEqual(f.routes,[]);assert.deepEqual(f.deps.run,before);assert.equal(f.errors.at(-1),'version conflict');assert.equal(f.busy.at(-1),'');
});

function walk(node,visit){visit(node);ts.forEachChild(node,n=>walk(n,visit));}
const nodes=[];walk(page,node=>{if(ts.isJsxElement(node)||ts.isJsxSelfClosingElement(node))nodes.push(node);});
const opening=node=>ts.isJsxElement(node)?node.openingElement:node;
const attr=(node,name)=>opening(node).attributes.properties.find(p=>p.name?.getText(tree)===name)?.initializer;
await test('template selection edits only the plan field and never starts a model/render/approval action',()=>{
 const button=nodes.find(node=>opening(node).tagName.getText(tree)==='button'&&attr(node,'aria-label')?.getText(tree).includes('template.name'));
 assert.ok(button);const handler=attr(button,'onClick').expression.getText(tree),writes=[];
 Function('template','changePlan',`return (${handler})();`)({id:'sample-led'},value=>writes.push(value));assert.deepEqual(writes,[{template_id:'sample-led'}]);
 assert.equal(attr(button,'aria-pressed').expression.getText(tree),'plan.template_id===template.id');
 assert.ok(attr(button,'disabled').expression.getText(tree).includes('briefDirty'));
});
await test('goal and density selectors change independently without creating AI consent or changing copy automatically',()=>{
 const selectors=nodes.filter(node=>opening(node).tagName.getText(tree)==='Select');
 const goal=selectors.find(node=>attr(node,'aria-label')?.getText(tree)==='"文案目标"');const density=selectors.find(node=>attr(node,'aria-label')?.getText(tree)==='"图内信息标准"');assert.ok(goal&&density);
 const changes=[];
 const getArrow=node=>ts.transpileModule('const handler='+attr(node,'onChange').expression.getText(tree)+';',{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
 Function('changeCopy',getArrow(goal)+'handler("sample-trial");')(value=>changes.push(['copy',value]));
 Function('changePlan',getArrow(density)+'handler("compact");')(value=>changes.push(['plan',value]));
 assert.deepEqual(changes,[['copy',{goal:'sample-trial'}],['plan',{density:'compact'}]]);
});
await test('previews are labelled as examples rather than a completed asset',()=>{
 assert.ok(source.includes('模板示例仅用于比较版式，不是本篇已生成图片'));
 const preview=tree.statements.find(node=>ts.isFunctionDeclaration(node)&&node.name?.text==='TemplatePreview');assert.ok(preview);
 assert.ok(preview.getText(tree).includes('URL.revokeObjectURL(object)'));
 assert.equal(preview.getText(tree).includes('visualWorkflowAction'),false);
});
await test('new-template cover editing hides controls that the renderer does not use while retaining legacy and inner-page editing',()=>{
 const drawer=nodes.find(node=>opening(node).tagName.getText(tree)==='Drawer'&&attr(node,'title')?.getText(tree)==='"调整这张图，另存新版本"');assert.ok(drawer);
 let selection;walk(drawer,node=>{if(ts.isConditionalExpression(node)&&node.condition.getText(tree).includes("template_id!=='legacy'"))selection=node;});assert.ok(selection);
 const newCover=Function('editing','run',`return !!(${selection.condition.getText(tree)});`);
 for(const id of ['question-led','decision-map','sample-led'])assert.equal(newCover({kind:'cover'},{data:{visual_plan:{template_id:id}}}),true);
 for(const id of [undefined,'legacy'])assert.equal(newCover({kind:'cover'},{data:{visual_plan:{template_id:id}}}),false);
 for(const kind of ['method','use','sample'])assert.equal(newCover({kind},{data:{visual_plan:{template_id:'decision-map'}}}),false);
 assert.ok(selection.whenFalse.getText(tree).includes('value={brief.layout}'));assert.ok(selection.whenFalse.getText(tree).includes('value={brief.text}'));
 assert.equal(selection.whenTrue.getText(tree).includes('brief.layout'),false);assert.equal(selection.whenTrue.getText(tree).includes('brief.text'),false);
 assert.ok(selection.whenTrue.getText(tree).includes('当前模板：'));assert.ok(selection.whenTrue.getText(tree).includes('修改模板请到“模板与标准”'));
 assert.equal(selection.whenTrue.getText(tree).includes('chooseStep'),false,'Informational guidance must not navigate away from unsaved single-image edits');
 assert.ok(drawer.getText(tree).includes('value={brief.title}'));assert.ok(drawer.getText(tree).includes('value={brief.subtitle}'));
});
await test('advanced cover nodes are editable only for decision-map or legacy, with inner-page behavior retained',()=>{
 const drawer=nodes.find(node=>opening(node).tagName.getText(tree)==='Drawer'&&attr(node,'title')?.getText(tree)==='"调整这张图，另存新版本"');let nodesGuard,outerGuard;
 walk(drawer,node=>{if(ts.isBinaryExpression(node)&&node.operatorToken.kind===ts.SyntaxKind.AmpersandAmpersandToken){
  if(node.right.getText(tree).startsWith('<Collapse')&&node.left.getText(tree).includes("template_id==='decision-map'"))nodesGuard=node.left;
  if(node.left.getText(tree)==="editing.kind!=='sample'&&editing.kind!=='collage'&&editing.kind!=='pdf-page'"&&node.right.getText(tree).includes('value={brief.layout}'))outerGuard=node.left;
 }});assert.ok(nodesGuard&&outerGuard);
 const visible=Function('editing','run',`return (${outerGuard.getText(tree)})&&(${nodesGuard.getText(tree)});`);
 for(const id of ['question-led','sample-led'])assert.equal(visible({kind:'cover'},{data:{visual_plan:{template_id:id}}}),false);
 for(const id of [undefined,'legacy','decision-map','magazine-a'])assert.equal(visible({kind:'cover'},{data:{visual_plan:{template_id:id}}}),true);
 for(const kind of ['method','use'])assert.equal(visible({kind},{data:{visual_plan:{template_id:'question-led'}}}),true);
 for(const kind of ['sample','collage','pdf-page'])assert.equal(visible({kind},{data:{visual_plan:{template_id:'decision-map'}}}),false);
});
await test('explicit A selection atomically initializes a new visual plan, without approval or image generation',async()=>{const received=[],stages=[],f=fixture({receive:r=>received.push(r),showStep:s=>stages.push(s)}),before=structuredClone(f.deps.run);await f.handlers.selectMagazineTemplate();assert.deepEqual(f.calls,[{path:'/4/select-template',data:{expected_version:7,template_id:'magazine-a'},method:'post'}]);assert.deepEqual(received,[f.next]);assert.deepEqual(stages,[2]);assert.deepEqual(f.deps.run,before);assert.equal(f.calls.some(c=>/render|approve|export|publish|auto/.test(c.path)),false);});
for(const [name,override] of Object.entries({unsaved:{hasEdits:true},busy:{busy:'Saving'},single_image:{briefDirty:true},conflict:{bufferConflict:{}},already_A:{plan:{template_id:'magazine-a'}},generating:{run:{id:4,row_version:7,data:{operation:{status:'generating'}}}}}))await test(`A selection preserves ${name} without API writes`,async()=>{const f=fixture(override);await f.handlers.selectMagazineTemplate();assert.deepEqual(f.calls,[]);assert.deepEqual(f.routes,[]);});
await test('A preview fallback and template button are available without rewriting existing legacy records',()=>{const p=normalPlan({sample_pages:[1]});assert.equal(p.template_id,'legacy');assert.ok(source.includes("id:'magazine-a',name:'A 杂志讲解版（已确认）'"));const button=nodes.find(node=>opening(node).tagName.getText(tree)==='button'&&attr(node,'aria-label')?.getText(tree).includes('template.name'));const handler=attr(button,'onClick').expression.getText(tree),actions=[];Function('template','changePlan','selectMagazineTemplate',`return (${handler})();`)({id:'magazine-a'},()=>actions.push('legacy'),()=>actions.push('A'));assert.deepEqual(actions,['A']);});
await test('A hides paid background controls while preserving them for the existing templates',()=>{let guard;walk(page,node=>{if(ts.isBinaryExpression(node)&&node.operatorToken.kind===ts.SyntaxKind.AmpersandAmpersandToken&&node.left.getText(tree)==="plan?.template_id!=='magazine-a'"&&node.right.getText(tree).includes('AI 背景 · 按服务商计费'))guard=node.left;});assert.ok(guard);const show=Function('plan',`return (${guard.getText(tree)});`);assert.equal(show({template_id:'magazine-a'}),false);for(const template_id of ['legacy','question-led','decision-map','sample-led'])assert.equal(show({template_id}),true);const modal=nodes.find(node=>opening(node).tagName.getText(tree)==='Modal'&&attr(node,'title')?.getText(tree)==='"AI 背景 · 真实资料在本机合成"');assert.ok(modal);const open=Function('bgOptions','plan',`return (${attr(modal,'open').expression.getText(tree)});`);assert.equal(open({slot:'cover'},{template_id:'magazine-a'}),false);assert.equal(open({slot:'cover'},{template_id:'question-led'}),true);});
console.log(JSON.stringify({passed:tests.length,tests,network_calls:0,model_calls:0,business_writes:0},null,2));
