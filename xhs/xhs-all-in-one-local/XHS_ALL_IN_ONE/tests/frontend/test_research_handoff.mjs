import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),ts=require('../../frontend/node_modules/typescript');
const path=new URL('../../frontend/src/pages/platforms/xhs/course-research-panel.tsx',import.meta.url);
const source=fs.readFileSync(path,'utf8'),tree=ts.createSourceFile(path.pathname,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const component=tree.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='CourseResearchPanel');
const handlers=['prepareHandoff','confirmHandoff'].map(name=>component.body.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text===name).getText(tree)).join('\n');
const auto=component.body.statements.find(n=>ts.isExpressionStatement(n)&&ts.isCallExpression(n.expression)&&n.expression.expression.getText(tree)==='useEffect'&&n.expression.arguments[1]?.getText(tree).includes('handoffOpen'));
assert.ok(auto,'Opening the handoff should automatically read the selected PDF version');
let pdfClick;
function walk(n){
  if(ts.isJsxElement(n)&&n.openingElement.tagName.getText(tree)==='Button'&&n.children.some(x=>ts.isJsxText(x)&&x.getText(tree).trim()==='查看原 PDF')){
    pdfClick=n.openingElement.attributes.properties.find(p=>p.name?.getText(tree)==='onClick').initializer.expression.getText(tree);
  }
  ts.forEachChild(n,walk);
}
walk(component);assert.ok(pdfClick);
const harness=`export function bind(deps){
 const {handoffPlan,handoffFileId,handoffReviewed,handoffKey,busy,draft,workspace,draftRecovery,dirty,directory,
 setHandoffError,setHandoffPlan,setHandoffReviewed,setMaterials,setHandoffKey,setHandoffOpen,
 fetchResearchContext,visualWorkflowAction,sameContext,act,navigate}=deps;
 ${handlers}
 return {prepareHandoff,confirmHandoff};
}
export function automatic(handoffOpen,handoffFileId,prepareHandoff){return (${auto.expression.arguments[0].getText(tree)})();}
export function preview(setHandoffTab){return (${pdfClick})();}`;
const compiled=ts.transpileModule(harness,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {bind,automatic,preview}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
function fixture(overrides={}){
 const calls=[],errors=[],navigation=[],closed=[];
 const deps={handoffPlan:{research_id:6,research_draft_id:6,source:{revision_id:172},review_digest:'d'.repeat(64),evidence_review:{limited:true}},handoffFileId:19901,handoffReviewed:true,handoffKey:'request',busy:'',draft:{id:6},workspace:{id:6},draftRecovery:null,dirty:false,directory:'02墨大/FNCE10002/期末复习讲义',
 setHandoffError:x=>errors.push(x),setHandoffPlan:()=>{},setHandoffReviewed:()=>{},setMaterials:()=>{},setHandoffKey:()=>{},setHandoffOpen:x=>closed.push(x),
 fetchResearchContext:async()=>({materials:[{id:19901,revision_id:172}]}),visualWorkflowAction:async(path,data)=>{calls.push({path,data});return path.endsWith('plan')?{review_digest:'d'.repeat(64)}:{id:44};},sameContext:()=>true,act:async(_name,fn)=>fn(()=>{}),navigate:x=>navigation.push(x),...overrides};
 return {deps,calls,errors,navigation,closed,handlers:bind(deps)};
}
for(const override of [{handoffReviewed:false},{handoffPlan:null},{handoffFileId:undefined},{busy:'reading'}]){
 const f=fixture(override);await f.handlers.confirmHandoff();assert.equal(f.calls.length,0);assert.equal(f.navigation.length,0);
}
const limited=fixture();await limited.handlers.confirmHandoff();
assert.equal(limited.calls[0].data.limited_sources_reviewed,true);assert.equal(limited.calls[0].data.revision_id,172);
assert.equal(limited.calls[0].data.file_id,19901);assert.equal(limited.calls[0].data.research_draft_id,6);
assert.deepEqual(limited.navigation,['/platforms/xhs/visual-workbench?run=44&stage=visual']);
const full=fixture({handoffPlan:{...limited.deps.handoffPlan,evidence_review:{limited:false}}});await full.handlers.confirmHandoff();assert.equal(full.calls[0].data.limited_sources_reviewed,false);
const missing=fixture({fetchResearchContext:async()=>({materials:[]})});await missing.handlers.prepareHandoff();assert.equal(missing.calls.length,0);assert.ok(missing.errors.some(x=>x.includes('不在当前课程')));
const stale=fixture({act:async(_name,fn)=>fn(()=>{throw new Error('course changed');})});await assert.rejects(stale.handlers.confirmHandoff(),/course changed/);assert.equal(stale.navigation.length,0);assert.equal(stale.closed.length,0);
let reads=0;automatic(true,19901,()=>reads++);automatic(false,19901,()=>reads++);automatic(true,undefined,()=>reads++);assert.equal(reads,1);
const tabs=[];preview(x=>tabs.push(x));assert.deepEqual(tabs,['pdf']);
console.log('Research handoff: automatic read, in-window PDF switch, explicit source-limit acknowledgement, exact navigation, stale response and missing-material guards passed. No real API or model calls.');
