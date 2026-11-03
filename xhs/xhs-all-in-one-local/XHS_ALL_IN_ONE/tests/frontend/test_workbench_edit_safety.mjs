import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';

// Exercise the actual current handlers in isolation: no React rendering, API,
// localStorage, database, or copied implementation of the safety conditions.
const require=createRequire(import.meta.url);
const ts=require('../../frontend/node_modules/typescript');
const path=new URL('../../frontend/src/pages/platforms/xhs/course-visual-workflow-page.tsx',import.meta.url);
const source=fs.readFileSync(path,'utf8');
const tree=ts.createSourceFile(path.pathname,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const component=tree.statements.find(node=>ts.isFunctionDeclaration(node)&&node.name?.text==='CourseVisualWorkflowPage');
assert.ok(component?.body,'CourseVisualWorkflowPage must be available for real-handler extraction');
const names=['changeCopy','changePlan','changeBrief','discardEdits','discardBrief'];
const handlers=names.map(name=>{
  const node=component.body.statements.find(node=>ts.isFunctionDeclaration(node)&&node.name?.text===name);
  assert.ok(node,`Missing production handler: ${name}`);
  return node.getText(tree);
}).join('\n');
const declares=(node,name)=>ts.isVariableStatement(node)&&node.declarationList.declarations.some(declaration=>ts.isIdentifier(declaration.name)&&declaration.name.text===name);
const start=component.body.statements.findIndex(node=>declares(node,'liveRecord'));
const routeRef=component.body.statements.findIndex(node=>declares(node,'liveRoute'));
assert.ok(start>=0&&routeRef>start,'Production render-time context refs must be present');
const routeGuard=component.body.statements[routeRef+1];
assert.ok(ts.isIfStatement(routeGuard)&&routeGuard.expression.getText(tree).includes('routeScope'),'Expected the production render-time context guard');
const renderScope=component.body.statements.slice(start,routeRef+2).map(node=>node.getText(tree)).join('\n');
const effects=component.body.statements.filter(node=>ts.isExpressionStatement(node)&&ts.isCallExpression(node.expression)&&node.expression.expression.getText(tree)==='useEffect').map(node=>node.expression);
const stageEffect=effects.find(node=>node.arguments[1]?.getText(tree)==='[requestedStage]');
const recordEffect=effects.find(node=>node.arguments[1]?.getText(tree)==='[fileContext,requestedRun,userId]');
assert.ok(recordEffect,'Record loading must depend on record identity, not the selected workflow stage');
assert.ok(stageEffect,'Stage-only navigation must have its own effect');
const transpile=s=>ts.transpileModule(s,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const navigation=await import('data:text/javascript;base64,'+Buffer.from(transpile(fs.readFileSync(new URL('../../frontend/src/lib/course-visual-navigation.ts',import.meta.url),'utf8'))).toString('base64'));
const context=await import('data:text/javascript;base64,'+Buffer.from(transpile(fs.readFileSync(new URL('../../frontend/src/lib/course-visual-context.ts',import.meta.url),'utf8'))).toString('base64'));
const harness=`
export function bindHandlers(deps) {
  const {busy,bufferConflict,briefDirty,run,generation,navigation,liveRecord,liveStage,Modal,editScope,
    removeCourseEditBuffer,receive,setCopy,setPlan,setBrief,setChecks,setPrompt,
    setEditing,setEditOpen}=deps;
  ${handlers}
  return {${names.join(',')}};
}
export function renderContext(deps,useRef) {
  const {run,userId,fileContext,requestedRun,requestedStage,generation}=deps;
  ${renderScope}
  return {liveRecord,liveRoute,liveStage,navigation};
}
export function runStageEffect(deps,navigation) {
  const {requestedStage,setStep,setChecks,setPrompt,setConsent,setPdfPrompt=()=>{},setPdfConsent=()=>{},setImageAction,setBgOptions,setBgPrompt,setBgConsent,
    setRun,setCopy,setPlan,setSelected,setBrief,setEditing,setEditOpen,removeCourseEditBuffer,writeCourseEditBuffer,receive}=deps;
  const {visualStageIndex}=navigation;
  (${stageEffect.arguments[0].getText(tree)})();
}`;
const compiled=ts.transpileModule(harness,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {bindHandlers,renderContext,runStageEffect}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));

let checks=0;
function check(name,fn){fn();checks++;console.log(`PASS ${name}`);}
function fixture(overrides={}) {
  const run={id:17,row_version:4};
  const state={copy:{title:'original copy',body:'kept body'},plan:{style:'product-editorial',cta:'kept CTA'},brief:{title:'original image',subtitle:'kept subtitle'},editing:{id:'image-a'},editOpen:true,checks:{copy:true},prompt:{purpose:'copy'}};
  const writes=[],modals=[],removed=[],received=[];
  const setter=name=>value=>{writes.push(name);state[name]=typeof value==='function'?value(state[name]):value;};
  const deps={busy:'',bufferConflict:null,briefDirty:false,run,generation:{current:9},navigation:{current:0},liveRecord:{current:run},liveStage:{current:'visual'},
    Modal:{confirm:options=>{modals.push(options);}},editScope:id=>({userId:2,feature:'visual-workbench',recordId:String(id)}),
    removeCourseEditBuffer:scope=>removed.push(scope),receive:record=>received.push(record),
    setCopy:setter('copy'),setPlan:setter('plan'),setBrief:setter('brief'),setChecks:setter('checks'),setPrompt:setter('prompt'),setEditing:setter('editing'),setEditOpen:setter('editOpen'),...overrides};
  return {state,writes,modals,removed,received,deps,handlers:bindHandlers(deps)};
}

for(const busy of ['保存修改','修改单张并出图']) {
  check(`all edit handlers reject input while busy: ${busy}`,()=>{
    const f=fixture({busy});const before=structuredClone(f.state);
    f.handlers.changeCopy({title:'late typing'});f.handlers.changePlan({cta:'late plan'});f.handlers.changeBrief({title:'late image'});
    assert.deepEqual(f.state,before);assert.deepEqual(f.writes,[]);
  });
}
check('conflicted buffers reject all input handlers',()=>{
  const f=fixture({bufferConflict:{value:{}}});
  f.handlers.changeCopy({title:'blocked'});f.handlers.changePlan({cta:'blocked'});f.handlers.changeBrief({title:'blocked'});
  assert.deepEqual(f.writes,[]);
});
check('unsaved single-image editing blocks main copy and plan',()=>{
  const f=fixture({briefDirty:true});
  f.handlers.changeCopy({title:'blocked'});f.handlers.changePlan({cta:'blocked'});
  assert.deepEqual(f.writes,[]);
  f.handlers.changeBrief({title:'current image edit'});assert.equal(f.state.brief.title,'current image edit');
});
check('idle current-context edits still work and preserve untouched fields',()=>{
  const f=fixture();f.handlers.changeCopy({title:'new copy'});f.handlers.changePlan({cta:'new CTA'});f.handlers.changeBrief({title:'new image'});
  assert.deepEqual(f.state.copy,{title:'new copy',body:'kept body'});
  assert.deepEqual(f.state.plan,{style:'product-editorial',cta:'new CTA'});
  assert.deepEqual(f.state.brief,{title:'new image',subtitle:'kept subtitle'});
  assert.deepEqual(f.state.checks,{});assert.equal(f.state.prompt,null);
});

const staleContexts={
  'generation changed':f=>{f.deps.generation.current++;},
  'record changed':f=>{f.deps.liveRecord.current={id:18,row_version:4};},
  'record version changed':f=>{f.deps.liveRecord.current={id:17,row_version:5};},
  'record was cleared':f=>{f.deps.liveRecord.current=null;},
};
for(const handler of ['discardEdits','discardBrief']) {
  for(const [label,transition] of Object.entries(staleContexts)) {
    check(`${handler} deferred confirmation is harmless after ${label}`,()=>{
      const f=fixture();f.handlers[handler]();assert.equal(f.modals.length,1);
      transition(f);f.modals[0].onOk();
      assert.deepEqual(f.removed,[]);assert.deepEqual(f.received,[]);assert.deepEqual(f.writes,[]);
    });
  }
  check(`${handler} does not open while busy`,()=>{
    const f=fixture({busy:'生成'});f.handlers[handler]();assert.deepEqual(f.modals,[]);
  });
  check(`${handler} does not open without a record`,()=>{
    const f=fixture({run:null});f.handlers[handler]();assert.deepEqual(f.modals,[]);
  });
}
check('current-record discard clears its buffer and reloads only that record',()=>{
  const f=fixture();f.handlers.discardEdits();f.modals[0].onOk();
  assert.deepEqual(f.removed,[{userId:2,feature:'visual-workbench',recordId:'17'}]);
  assert.deepEqual(f.received,[f.deps.run]);assert.deepEqual(f.writes,[]);
});
check('current-record single-image discard preserves the main copy and buffer',()=>{
  const f=fixture();const copy=structuredClone(f.state.copy),plan=structuredClone(f.state.plan);
  f.handlers.discardBrief();f.modals[0].onOk();
  assert.equal(f.state.editing,null);assert.equal(f.state.brief,null);assert.equal(f.state.editOpen,false);
  assert.deepEqual(f.state.copy,copy);assert.deepEqual(f.state.plan,plan);
  assert.deepEqual(f.removed,[]);assert.deepEqual(f.received,[]);
});

function renderFixture(){
  const refs=[];let cursor=0;
  const deps={run:{id:17,row_version:4},userId:2,fileContext:23,requestedRun:17,requestedStage:'visual',generation:{current:9}};
  const render=()=>{cursor=0;return renderContext(deps,value=>{const index=cursor++;return refs[index]??(refs[index]={current:value});});};
  return {deps,render};
}
check('same-route render preserves the generation and refreshes live record ref',()=>{
  const f=renderFixture();const initial=f.render();f.deps.run={id:17,row_version:5};const next=f.render();
  assert.equal(f.deps.generation.current,9);assert.equal(next.liveRecord,initial.liveRecord);assert.equal(next.liveRecord.current.row_version,5);
  assert.equal(next.navigation.current,0,'A saved record update alone is not a navigation event');
});
for(const [field,value] of [['userId',3],['fileContext',24],['requestedRun',18]]) {
  check(`${field} change invalidates a pending confirmation before effects`,()=>{
    const route=renderFixture();const refs=route.render();
    const f=fixture({run:route.deps.run,generation:route.deps.generation,navigation:refs.navigation,liveRecord:refs.liveRecord,liveStage:refs.liveStage});
    f.handlers.discardEdits();route.deps[field]=value;route.render(); // No effect/setup execution.
    assert.equal(route.deps.generation.current,10);
    f.modals[0].onOk();assert.deepEqual(f.removed,[]);assert.deepEqual(f.received,[]);
    route.render();assert.equal(route.deps.generation.current,10);
  });
}
for(const handler of ['discardEdits','discardBrief'])check(`${handler} stale stage confirmation is blocked without invalidating the record`,()=>{
  const route=renderFixture(),refs=route.render();
  const f=fixture({run:route.deps.run,generation:route.deps.generation,navigation:refs.navigation,liveRecord:refs.liveRecord,liveStage:refs.liveStage});
  f.handlers[handler]();route.deps.requestedStage='cover';const next=route.render();
  assert.equal(route.deps.generation.current,9,'Stage navigation must preserve outstanding record API context');
  assert.equal(next.navigation.current,1,'Stage navigation has its own epoch for delayed UI transitions');
  assert.equal(next.liveStage.current,'cover');assert.equal(next.liveRecord.current,route.deps.run);
  f.modals[0].onOk();assert.deepEqual(f.removed,[]);assert.deepEqual(f.received,[]);assert.deepEqual(f.writes,[]);
});
for(const handler of ['discardEdits','discardBrief'])check(`${handler} old confirmation stays invalid after back-forward returns to the original stage`,()=>{
  const route=renderFixture(),refs=route.render();
  const f=fixture({run:route.deps.run,generation:route.deps.generation,navigation:refs.navigation,liveRecord:refs.liveRecord,liveStage:refs.liveStage});
  f.handlers[handler]();route.deps.requestedStage='cover';route.render();route.deps.requestedStage='visual';route.render();
  assert.equal(refs.liveStage.current,'visual','The old confirmation and current page can have identical stage strings');
  assert.equal(refs.navigation.current,2,'Both navigation events must invalidate the old confirmation');
  assert.equal(route.deps.generation.current,9,'Record API context remains unchanged');
  f.modals[0].onOk();assert.deepEqual(f.removed,[]);assert.deepEqual(f.received,[]);assert.deepEqual(f.writes,[]);
});
check('same-record back and forward each invalidate old view transitions without changing API context',()=>{
  const route=renderFixture(),initial=route.render();
  route.deps.requestedStage='cover';route.render();route.render();assert.equal(initial.navigation.current,1);
  route.deps.requestedStage='visual';route.render();assert.equal(initial.navigation.current,2);
  route.deps.requestedStage='cover';route.render();assert.equal(initial.navigation.current,3);
  assert.equal(route.deps.generation.current,9);assert.equal(initial.liveRecord.current,route.deps.run);
});
check('stage-only effect preserves unsaved editor and cached single-image changes',()=>{
  const preserved={run:{id:17},copy:{title:'Unsubmitted copy'},plan:{cta:'Unsubmitted plan'},selected:['source-a'],brief:{title:'Unsubmitted single image'},cache:{recordId:'17',baseVersion:4}};
  const before=structuredClone(preserved),changed=[];
  const deps={requestedStage:'cover'};
  for(const name of ['setStep','setChecks','setPrompt','setConsent','setImageAction','setBgOptions','setBgPrompt','setBgConsent'])deps[name]=value=>changed.push([name,value]);
  for(const name of ['setRun','setCopy','setPlan','setSelected','setBrief','setEditing','setEditOpen','removeCourseEditBuffer','writeCourseEditBuffer','receive'])deps[name]=()=>assert.fail(`${name} must not run just because the stage changed`);
  runStageEffect(deps,navigation);
  assert.deepEqual(changed.find(([name])=>name==='setStep'),['setStep',3]);assert.deepEqual(preserved,before);
});
{
  const route=renderFixture(),refs=route.render();let finish;
  const pending=context.inCourseContext(()=>new Promise(resolve=>{finish=resolve;}),()=>route.deps.generation.current);
  route.deps.requestedStage='set';route.render();finish({id:17,row_version:5});
  assert.deepEqual(await pending,{id:17,row_version:5},'A same-record stage change must not discard an outstanding API result');
  assert.equal(refs.navigation.current,1);assert.equal(route.deps.generation.current,9);
  checks++;console.log('PASS outstanding API context remains valid across same-record stage navigation');
}
console.log(`${checks} workbench edit/confirmation safety checks passed; actual production handlers, no network, model, filesystem-data, or database mutations`);
