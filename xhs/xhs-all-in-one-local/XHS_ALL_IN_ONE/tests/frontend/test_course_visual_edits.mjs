import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),ts=require('../../frontend/node_modules/typescript');
const source=fs.readFileSync(new URL('../../frontend/src/lib/course-visual-edits.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {sameVisualEdit}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));

const copy={topic:'公式调用',title:'公式都会，但考试不会用',body:'先画时间轴，再判断公式。',tags:['FNCE10002','墨尔本大学'],takeaway:'识别题目条件'};
const reordered={takeaway:copy.takeaway,tags:[...copy.tags],body:copy.body,title:copy.title,topic:copy.topic};
assert.equal(sameVisualEdit(copy,reordered),true,'A reordered API JSON object is not an edit');
assert.equal(sameVisualEdit(reordered,copy),true);
const plan={cover_lines:['公式都会','但考试不会用'],sample_pages:[1,4],method_nodes:[{title:'条件',text:'时间轴'},{title:'方法',text:'匹配公式'}],style:'product-editorial'};
const planReordered={style:'product-editorial',method_nodes:[{text:'时间轴',title:'条件'},{text:'匹配公式',title:'方法'}],sample_pages:[1,4],cover_lines:['公式都会','但考试不会用']};
assert.equal(sameVisualEdit(plan,planReordered),true,'Nested object order does not create false visualDirty');
const brief={title:'公式都会',subtitle:'先看条件',text:'真实讲义样张',layout:'product-hero',nodes:['题目','条件']};
assert.equal(sameVisualEdit(brief,{nodes:['题目','条件'],layout:'product-hero',text:'真实讲义样张',subtitle:'先看条件',title:'公式都会'}),true);

for(const changed of [
  {...copy,title:copy.title+'！'},
  {...copy,body:copy.body+' '},
  {...copy,body:'  '+copy.body},
  {...copy,tags:[...copy.tags].reverse()},
  {...copy,takeaway:''},
])assert.equal(sameVisualEdit(copy,changed),false,'Exact copy changes must still require saving');
for(const changed of [
  {...plan,cover_lines:[...plan.cover_lines].reverse()},
  {...plan,sample_pages:[4,1]},
  {...plan,sample_pages:[1,5]},
  {...plan,sample_pages:[1,4,5]},
  {...plan,sample_pages:[1,'4']},
  {...plan,method_nodes:[...plan.method_nodes].reverse()},
  {...plan,method_nodes:[{title:'条件',text:'新的条件'},plan.method_nodes[1]]},
])assert.equal(sameVisualEdit(plan,changed),false,'Meaningful layout/page changes must still require saving');
assert.equal(sameVisualEdit(brief,{...brief,nodes:['条件','题目']}),false);
assert.equal(sameVisualEdit({a:1},{b:1}),false);
assert.equal(sameVisualEdit({a:null},{}),false);
assert.equal(sameVisualEdit(null,{}),false);
assert.equal(sameVisualEdit([],{}),false);
assert.equal(sameVisualEdit({a:1},{a:2}),false);
assert.equal(sameVisualEdit({a:true},{a:false}),false);
assert.equal(sameVisualEdit({a:undefined},{}),false);
assert.equal(sameVisualEdit(new Date(0),{}),false);
assert.equal(sameVisualEdit(Object.assign(Object.create(null),{a:1}),{a:1}),true);
console.log('Visual edit comparison passed: JSON key order is ignored; copy whitespace, cover/page order, node content, types and numeric changes remain edits. No API, model or data writes.');
