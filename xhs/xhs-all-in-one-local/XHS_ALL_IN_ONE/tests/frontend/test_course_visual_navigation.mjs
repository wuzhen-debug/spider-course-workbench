import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),ts=require('../../frontend/node_modules/typescript');
const source=fs.readFileSync(new URL('../../frontend/src/lib/course-visual-navigation.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {visualStageNames,visualStageIndex,visualStageParams,nextVisualStage}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));

assert.deepEqual(visualStageNames,['research','copy','visual','cover','set']);
for(const [index,stage] of visualStageNames.entries())assert.equal(visualStageIndex(stage),index);
for(const [alias,index] of [['plan',2],['images',4],['preview',3]])assert.equal(visualStageIndex(alias),index);
for(const invalid of [null,'','unknown','constructor','toString','-1','5'])assert.equal(visualStageIndex(invalid),null);

const original=new URLSearchParams('run=4&file_id=19901&stage=visual&return=course%20center&filter=one&filter=two');
const originalText=original.toString();
for(const [step,stage] of visualStageNames.entries()){
  const moved=visualStageParams(original,step);
  assert.equal(original.toString(),originalText,'Moving a step must not mutate the old browser history entry');
  assert.equal(moved.get('run'),'4');assert.equal(moved.get('file_id'),'19901');
  assert.equal(moved.get('return'),'course center');assert.deepEqual(moved.getAll('filter'),['one','two']);
  assert.equal(moved.get('stage'),stage);
  const reloaded=new URLSearchParams(moved.toString());
  assert.equal(visualStageIndex(reloaded.get('stage')),step,'Refresh restores the same requested step');
}
const first=visualStageParams(original,3),second=visualStageParams(first,4);
assert.equal(visualStageIndex(new URLSearchParams(first.toString()).get('stage')),3,'Back returns to cover');
assert.equal(visualStageIndex(new URLSearchParams(second.toString()).get('stage')),4,'Forward returns to set');
assert.equal(new URLSearchParams(first.toString()).get('run'),new URLSearchParams(second.toString()).get('run'));
for(const invalid of [-1,5,1.5,NaN,Infinity])assert.throws(()=>visualStageParams(original,invalid),RangeError);

const progress=(data={},approved={})=>({approved,data});
assert.equal(nextVisualStage(progress()),0);
assert.equal(nextVisualStage(progress({copy:{title:'',body:'body'}})),0);
assert.equal(nextVisualStage(progress({copy:{title:'title',body:'  '}})),0);
assert.equal(nextVisualStage(progress({copy:{title:'title',body:'body'}})),1);
assert.equal(nextVisualStage(progress({copy:{title:'title',body:'body'}},{copy:true})),2,'Approved copy goes to picture planning and production');
assert.equal(nextVisualStage(progress({cover:{id:'cover'}},{copy:true})),2,'An existing cover can continue straight to full-set planning');
assert.equal(nextVisualStage(progress({cover:{id:'cover'}},{copy:true,cover:true})),2,'Approved cover is retained while planning the set');
assert.equal(nextVisualStage(progress({images:[{id:'cover'},{id:'sample'}]})),4,'A generated set goes to its review before export');
assert.equal(nextVisualStage(progress({images:[{id:'sample'}],cover:{id:'cover'}},{copy:true,cover:true,set:true})),4);
assert.equal(nextVisualStage(progress({export:{draft_id:99}})),0,'An export alone must not invent content or approval');
const input=progress({copy:{title:'title',body:'body'},cover:{id:'cover'},images:[]},{copy:true});
const snapshot=JSON.stringify(input);nextVisualStage(input);assert.equal(JSON.stringify(input),snapshot);
console.log('Visual navigation passed: canonical/alias stage parsing, invalid stages, immutable same-record URLs, refresh/back/forward restoration and actionable stage progression. No API, model or business writes.');
