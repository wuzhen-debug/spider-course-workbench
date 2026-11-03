import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createRequire} from 'node:module';
const require=createRequire(new URL('../../frontend/package.json',import.meta.url));
const ts=require('typescript');
const compile=source=>ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const context={exports:{},Set};vm.createContext(context);
vm.runInContext(compile(fs.readFileSync(new URL('../../frontend/src/lib/official-publish.ts',import.meta.url),'utf8')),context);
assert.equal(context.exports.officialPublishBody('正文\n第二段\n',['BISM1201','#期末复习','BISM1201']),'正文\n第二段\n\n#BISM1201 #期末复习');
assert.equal(context.exports.officialPublishBody('保留正文',[]),'保留正文');
const source=fs.readFileSync(new URL('../../frontend/src/lib/api.ts',import.meta.url),'utf8');
const tree=ts.createSourceFile('api.ts',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TS);
const fn=tree.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='downloadOfficialPublishPackage');
assert.ok(fn);
const calls=[],download=[];let revoked=false;
const ctx={exports:{},Blob,Error,JSON,
  http:{post:async(path,body,options)=>{calls.push({path,body,options});return{data:new Blob(['fixture zip'])};}},
  URL:{createObjectURL:()=> 'blob:fixture',revokeObjectURL:()=>{revoked=true;}},
  document:{body:{appendChild(){}},createElement:()=>{const a={click(){download.push(this.download);},remove(){}};return a;}}};
vm.createContext(ctx);vm.runInContext(compile(fn.getText(tree)),ctx);
await ctx.exports.downloadOfficialPublishPackage(2,['BISM1201']);
assert.equal(calls.length,1);assert.equal(calls[0].path,'/publish/jobs/2/official-package');
assert.equal(calls[0].options.responseType,'blob');assert.equal(download[0],'xhs-note-2.zip');assert.ok(revoked);
ctx.http.post=async()=>{throw{response:{data:new Blob([JSON.stringify({detail:'图片已不可用'})])}};};
await assert.rejects(()=>ctx.exports.downloadOfficialPublishPackage(2,[]),/图片已不可用/);
console.log('Official handoff copy, download destination and error handling passed; no submit/upload requests.');
