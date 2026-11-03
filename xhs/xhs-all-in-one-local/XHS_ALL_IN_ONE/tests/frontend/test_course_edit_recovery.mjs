// Real helper and research restoration functions, synthetic local state only.
// No browser, network, model, business database, or approval actions.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const require=createRequire(path.join(root,'frontend/package.json'));
const ts=require('typescript');
const storage=new Map();let broken=false;
const localStorage={getItem:k=>{if(broken)throw Error('blocked');return storage.get(k)??null;},setItem:(k,v)=>{if(broken)throw Error('quota');storage.set(k,String(v));},removeItem:k=>{if(broken)throw Error('blocked');storage.delete(k);}};
const helperSource=fs.readFileSync(path.join(root,'frontend/src/lib/course-edit-buffer.ts'),'utf8');
const helper={exports:{},localStorage};vm.createContext(helper);
vm.runInContext(ts.transpileModule(helperSource,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,helper);
const {readCourseEditBuffer:read,writeCourseEditBuffer:write,removeCourseEditBuffer:clear,hasCourseEditStorage:available}=helper.exports;
let passed=0;const tests=[];
function test(name,fn){fn();tests.push(name);passed++;}
const a={userId:1,feature:'research-form',recordId:'10',context:'school/course'};
test('restore editable fields and base version',()=>{assert.equal(write(a,{topic:'Synthetic topic'},'rev1'),true);assert.equal(read(a).value.topic,'Synthetic topic');assert.equal(read(a).baseVersion,'rev1');});
test('separate users research records and directories',()=>{for(const changed of [{userId:2},{recordId:'11'},{context:'other/course'},{feature:'visual'}])assert.equal(read({...a,...changed}),null);});
test('clear only selected buffer',()=>{write({...a,recordId:'11'},{topic:'other'});clear(a);assert.equal(read(a),null);assert.equal(read({...a,recordId:'11'}).value.topic,'other');});
test('malformed and oversized storage never restore',()=>{storage.set(helper.exports.courseEditBufferKey(a),'invalid-json');assert.equal(read(a),null);assert.equal(write(a,{text:'x'.repeat(1_000_001)}),false);});
test('storage unavailable fails closed without throwing',()=>{broken=true;assert.equal(available(),false);assert.equal(write(a,{}),false);assert.equal(read(a),null);assert.equal(clear(a),false);broken=false;});

const researchSource=fs.readFileSync(path.join(root,'frontend/src/pages/platforms/xhs/course-research-panel.tsx'),'utf8');
const source=ts.createSourceFile('research.tsx',researchSource,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const wanted=new Set(['isResearchEdit','isDraftEdit','formScope','draftScope','restoreEditor','openDraft','captureOperation','act','updateWorkspace','readSource','prepare','generate','importSource','search','ensureResearch','refreshHistory','openResearch','sameContext','prepareHandoff','confirmHandoff']);const functions=[];
function visit(node){if(ts.isFunctionDeclaration(node)&&node.name&&wanted.has(node.name.text))functions.push(node.getText(source));ts.forEachChild(node,visit);}visit(source);
assert.equal(functions.length,wanted.size);
const state={};const ctx={...helper.exports,userId:1,directory:'school/course',strings:v=>Array.isArray(v)&&v.every(x=>typeof x==='string')};
for(const name of ['Workspace','Context','Keyword','Source','Sort','TimeRange','Selected','Topic','Purpose','Brand','Facts','Instruction','MaterialIds','Prepared','Consent','Draft','DraftRecovery','Reviewed','BufferRestored','DraftTitle','DraftBody','DraftTags','DraftError','DraftNotice','Busy','Error','Notice','History','ImportOpen','RequestKeys','Materials','HandoffPlan','HandoffReviewed','HandoffError','HandoffKey','HandoffOpen'])ctx['set'+name]=v=>{state[name]=v;};
vm.createContext(ctx);vm.runInContext(ts.transpileModule(functions.join('\n'),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,ctx);
const context={university:'Example University',course_code:'TEST1000',course_name:'Example',term:'S1',library_directory:'school/course'};
const draft={id:21,research_id:10,title:'Server title',body:'Server body',tags:['server'],status:'pending',review_digest:'digest1'};
const row={id:10,context,evidence:[{id:'good'},{id:'excluded',excluded:true}],drafts:[draft]};
const edit={context,keyword:'TEST1000 topic',source:'web',sort:4,timeRange:2,selected:['good','excluded','missing'],topic:'Student problem',purpose:'product',brand:'Synthetic brand',facts:'Verified fact',instruction:'Write clearly',materialIds:[5,6],draftId:null};
test('restore writing form but filter unavailable sources and PDFs',()=>{
  write(ctx.formScope(10),edit);ctx.restoreEditor(row,context,[{id:5}]);
  assert.equal(state.Topic,edit.topic);assert.equal(state.Brand,edit.brand);assert.equal(state.Keyword,edit.keyword);
  assert.deepEqual(Array.from(state.Selected),['good']);assert.deepEqual(Array.from(state.MaterialIds),[5]);
  assert.equal(state.Prepared,null);assert.equal(state.Consent,false);assert.equal(state.Reviewed,false);
});
test('changed course cannot carry old source or material selections',()=>{
  write(ctx.formScope(10),{...edit,context:{...context,course_code:'OTHER2000'}});ctx.restoreEditor(row,context,[{id:5}]);
  assert.equal(state.Context.course_code,'OTHER2000');assert.equal(state.Selected.length,0);assert.equal(state.MaterialIds.length,0);
});
test('matching draft revision recovers edits without approval',()=>{
  write(ctx.draftScope(draft),{title:'Local title',body:'Local body',tags:['local']},'digest1');ctx.openDraft(draft);
  assert.equal(state.DraftTitle,'Local title');assert.equal(state.DraftRecovery,null);assert.equal(state.Reviewed,false);
});
test('server revision changes retain old local text but do not overwrite server',()=>{
  ctx.openDraft({...draft,review_digest:'digest2'});assert.equal(state.DraftTitle,'Server title');assert.equal(state.DraftRecovery.value.title,'Local title');assert.equal(state.Reviewed,false);
});
test('saved drafts never silently become editable recovered drafts',()=>{
  ctx.openDraft({...draft,status:'saved'});assert.equal(state.DraftTitle,'Server title');assert.equal(state.Draft.status,'saved');assert.equal(state.DraftRecovery.value.body,'Local body');
});
test('loading another research does not reuse previous form',()=>{
  ctx.restoreEditor({...row,id:11},context,[]);assert.equal(state.Topic,'');assert.equal(state.Selected.length,0);assert.equal(state.Draft,null);
});
test('last open draft can restore after whole-page refresh',()=>{
  write(ctx.formScope(10),{...edit,draftId:draft.id});ctx.restoreEditor(row,context,[{id:5}]);assert.equal(state.Draft.id,21);assert.equal(state.DraftTitle,'Local title');assert.equal(state.Reviewed,false);
});
test('PDF entry preselection is scoped and never replaces restored choices',()=>{
  clear(ctx.formScope(10));ctx.restoreEditor(row,context,[{id:5}],true,5);assert.deepEqual(Array.from(state.MaterialIds),[5]);
  ctx.restoreEditor(row,context,[{id:5}],true,99);assert.equal(state.MaterialIds.length,0);
  write(ctx.formScope(10),{...edit,materialIds:[]});ctx.restoreEditor(row,context,[{id:5}],true,5);assert.equal(state.MaterialIds.length,0);
  write(ctx.formScope(10),{...edit,materialIds:[6]});ctx.restoreEditor(row,context,[{id:5},{id:6}],true,5);assert.deepEqual(Array.from(state.MaterialIds),[6]);
});

async function asyncTest(name,fn){await fn();tests.push(name);passed++;}
function resetAsync(){
  Object.assign(ctx,{generation:{current:1},liveScope:{current:'scope-a'},bufferContext:'scope-a',operationScope:'scope-a',workspace:row,context,accountId:7,prepared:{options:{},plan_digest:'fixture-plan'},consent:false,requestKeys:{outline:'fixture-request',ai:'fixture-request'},options:{topic:'fixture'},keyword:'TEST1000',source:'xhs',sort:2,timeRange:0,initialContext:context,materials:[],message:()=> 'fixture error',crypto:{randomUUID:()=> 'fixture-key'}});
  state.Workspace='unchanged';state.Prepared='unchanged';state.Draft='unchanged';state.Busy='';state.Error='';state.Notice='';
  ctx.fetchResearch=async()=>row;ctx.fetchResearchHistory=async()=>({items:[]});
}
function switchScope(){ctx.liveScope.current='scope-b';ctx.generation.current++;state.Busy='new course loading';state.Error='new course error';}
async function pendingAction(run,reply){
  resetAsync();let resolve,called=false;
  ctx.researchAction=()=>{called=true;return new Promise(r=>{resolve=r;});};
  const promise=run();for(let i=0;i<12&&!called;i++)await Promise.resolve();assert.equal(called,true);
  switchScope();resolve(reply);await promise;
  assert.equal(state.Busy,'new course loading');assert.equal(state.Error,'new course error');
}
await asyncTest('late read response cannot overwrite new course or clear its loading state',async()=>{
  await pendingAction(()=>ctx.readSource({id:'good'}),row);assert.equal(state.Workspace,'unchanged');
});
await asyncTest('late writing plan cannot attach to another course',async()=>{
  await pendingAction(()=>ctx.prepare(),{prompt:'old plan'});assert.equal(state.Prepared,'unchanged');
});
await asyncTest('late generated draft cannot open under another course buffer',async()=>{
  await pendingAction(()=>ctx.generate('outline'),draft);assert.equal(state.Draft,'unchanged');assert.equal(state.Workspace,'unchanged');
});
await asyncTest('late search response cannot update sources or recover old workspace',async()=>{
  await pendingAction(()=>ctx.search(),row);assert.equal(state.Workspace,'unchanged');
});
await asyncTest('late import validation does not submit source after scope switch',async()=>{
  resetAsync();let resolve,calls=0;ctx.importForm={validateFields:()=>new Promise(r=>{resolve=r;}),resetFields:()=>{throw Error('must not reset new form');}};ctx.researchAction=async()=>{calls++;return row;};
  const promise=ctx.importSource();switchScope();resolve({title:'old input'});await promise;assert.equal(calls,0);assert.equal(state.Error,'new course error');
});
await asyncTest('late research handoff preview cannot attach to a new course',async()=>{
  resetAsync();Object.assign(ctx,{draft,dirty:false,draftRecovery:null,busy:'',handoffFileId:5});
  ctx.fetchResearchContext=async()=>({materials:[{id:5,revision_id:3}]});
  let resolve,called=false;ctx.visualWorkflowAction=()=>{called=true;return new Promise(r=>{resolve=r;});};
  const promise=ctx.prepareHandoff();for(let i=0;i<12&&!called;i++)await Promise.resolve();assert.equal(called,true);
  switchScope();resolve({review_digest:'old-preview'});await promise;
  assert.equal(state.HandoffPlan,null);assert.equal(state.Busy,'new course loading');assert.equal(state.HandoffReviewed,false);
});
await asyncTest('late confirmed handoff never navigates away from another course',async()=>{
  resetAsync();Object.assign(ctx,{busy:'',handoffFileId:5,handoffReviewed:true,handoffKey:'synthetic-key',handoffPlan:{research_id:10,research_draft_id:21,source:{revision_id:3},evidence_review:{limited:false},review_digest:'preview'}});
  let resolve,navigations=0;ctx.navigate=()=>{navigations++;};ctx.visualWorkflowAction=()=>new Promise(r=>{resolve=r;});
  const promise=ctx.confirmHandoff();switchScope();resolve({id:42});await promise;
  assert.equal(navigations,0);assert.equal(state.Busy,'new course loading');
});
test('scope mismatch alone stops a late operation before effect cleanup',()=>{
  resetAsync();const operation=ctx.captureOperation();ctx.liveScope.current='other-account';assert.equal(operation.current(),false);assert.throws(()=>operation.guard());
});
test('same-directory query switch invalidates operations without changing buffer scope',()=>{
  resetAsync();ctx.operationScope='same-directory-research-10';ctx.liveScope.current=ctx.operationScope;
  const operation=ctx.captureOperation();assert.equal(operation.current(),true);
  ctx.liveScope.current='same-directory-research-11';assert.equal(ctx.bufferContext,'scope-a');assert.equal(ctx.generation.current,1);
  assert.equal(operation.current(),false);assert.throws(()=>operation.guard());
});
test('conflicting recovery locks all draft text controls until resolved',()=>{
  const expressions=[];
  function scan(node){
    if(ts.isJsxSelfClosingElement(node)||ts.isJsxOpeningElement(node)){
      const attrs=node.attributes.properties;
      const targeted=attrs.some(a=>ts.isJsxAttribute(a)&&['id','aria-label'].includes(a.name.getText(source))&&a.initializer&&ts.isStringLiteral(a.initializer)&&['research-draft-title','research-draft-body','课程研究草稿标签'].includes(a.initializer.text));
      const disabled=attrs.find(a=>ts.isJsxAttribute(a)&&a.name.getText(source)==='disabled');
      if(targeted&&disabled?.initializer&&ts.isJsxExpression(disabled.initializer))expressions.push(disabled.initializer.expression.getText(source));
    }
    ts.forEachChild(node,scan);
  }
  scan(source);assert.equal(expressions.length,3);
  for(const expression of expressions){
    assert.equal(vm.runInNewContext(expression,{busy:'',draftRecovery:{},draft:{status:'pending'}}),true);
    assert.equal(vm.runInNewContext(expression,{busy:'',draftRecovery:null,draft:{status:'pending'}}),false);
  }
});
console.log(JSON.stringify({passed,tests,network_calls:0,model_calls:0,limitations:'Pure in-memory tests of actual storage/restoration functions; browser refresh and navigation should also be verified.'},null,2));
