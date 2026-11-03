// Actual hook with a deterministic hooks harness, synthetic storage/API only.
import assert from 'node:assert/strict';
import fs from 'node:fs';import path from 'node:path';import vm from 'node:vm';
import {createRequire} from 'node:module';import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const require=createRequire(path.join(root,'frontend/package.json'));const ts=require('typescript');
const storage=new Map();const localStorage={getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};
function load(file,imports={}){const ctx={exports:{},require:n=>imports[n],localStorage,URLSearchParams,window:{addEventListener(){},removeEventListener(){}}};vm.createContext(ctx);vm.runInContext(ts.transpileModule(fs.readFileSync(path.join(root,'frontend/src',file),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,ctx);return ctx.exports;}
const buffers=load('lib/course-edit-buffer.ts');const selection=load('lib/draft-route-selection.ts');
const make=id=>({id,title:`Title ${id}`,body:`Body ${id}`,tags:[{name:'TEST',id:''}],platform:'xhs',created_at:''});
assert.throws(()=>selection.parseRequestedDraft('bad'));
assert.equal((await selection.resolveRequestedDraft('30',[make(1)],1,async id=>make(id))).id,30);
await assert.rejects(()=>selection.resolveRequestedDraft('404',[make(1)],1,async()=>{throw Error('missing');}));
assert.equal(selection.draftEditorValue({...make(1),tags:['old-string-tag']}).tags[0].name,'old-string-tag');
let route='1',owner=1;let slots=[],cursor=0,pendingEffects=[],needs=true,result;
const api={fetchDrafts:async()=>({items:[make(1),make(2)]}),fetchDraft:async id=>make(id)};
const state={drafts:[],selectedId:null,title:'',body:'',tags:[],loading:false,error:null};
function set(k,v){const next=typeof v==='function'?v(state[k]):v;if(!Object.is(next,state[k])){state[k]=next;needs=true;}}
const react={
 useState(initial){const i=cursor++;if(!slots[i])slots[i]={value:initial};return [slots[i].value,v=>{const next=typeof v==='function'?v(slots[i].value):v;if(!Object.is(next,slots[i].value)){slots[i].value=next;needs=true;}}];},
 useRef(initial){const i=cursor++;if(!slots[i])slots[i]={current:initial};return slots[i];},
 useEffect(fn,deps){const i=cursor++,prior=slots[i];if(!prior||deps.some((x,n)=>!Object.is(x,prior.deps[n]))){pendingEffects.push(()=>{prior?.cleanup?.();slots[i]={deps,cleanup:fn()};});}}
};
const hook=load('hooks/use-draft-route-editor.ts',{'react':react,'react-router-dom':{useSearchParams:()=>[new URLSearchParams(route===null?'':`draft_id=${route}`),p=>{route=p.get('draft_id');needs=true;}]},'./use-auth':{useAuth:()=>({user:{id:owner}})},'../lib/api':api,'../lib/course-edit-buffer':buffers,'../lib/draft-route-selection':selection}).useDraftRouteEditor;
function render(){needs=false;cursor=0;pendingEffects=[];const b={...state};for(const [key,name] of Object.entries({drafts:'Drafts',selectedId:'SelectedId',title:'Title',body:'Body',tags:'Tags',loading:'Loading',error:'Error'}))b['set'+name]=v=>set(key,v);result=hook(b);for(const fn of pendingEffects)fn();}
async function settle(){for(let i=0;i<30;i++){if(needs)render();await Promise.resolve();}assert.equal(needs,false,'harness failed to settle');}
const scope=id=>({userId:owner,feature:'draft-workshop',recordId:String(id)});
await settle();assert.equal(state.selectedId,1);
set('body','Unsaved local body');await settle();assert.equal(buffers.readCourseEditBuffer(scope(1)).value.body,'Unsaved local body');
const oldEditorOperation=result.captureEditorOperation();
route='2';needs=true;await settle();assert.equal(state.selectedId,2);assert.equal(oldEditorOperation(),false,'old AI results cannot be applied to another draft');
route='1';needs=true;await settle();assert.equal(state.body,'Unsaved local body','route return restores local text');
// Fresh server response must not erase the old base or silently overwrite server edits.
api.fetchDrafts=async()=>({items:[{...make(1),body:'New server body'},make(2)]});
let deliver;api.fetchDraft=id=>new Promise(resolve=>{deliver=()=>resolve({...make(id),body:'New server body'});});
void result.loadDrafts();await settle();assert.equal(result.editorBlocked,true);
assert.equal(buffers.readCourseEditBuffer(scope(1)).baseVersion,selection.draftEditorKey(selection.draftEditorValue(make(1))));
deliver();await settle();assert.equal(state.body,'New server body');assert.equal(result.editConflict.value.body,'Unsaved local body');
assert.equal(result.editorBlocked,true);assert.equal(buffers.readCourseEditBuffer(scope(1)).value.body,'Unsaved local body');
result.resolveEditConflict(true);await settle();assert.equal(state.body,'Unsaved local body');assert.equal(result.editorBlocked,false);
result.acceptSaved({...make(1),body:'Unsaved local body'});await settle();assert.equal(buffers.readCourseEditBuffer(scope(1)),null);
// Rapid route changes: only the latest detail response is accepted.
const deliveries={};api.fetchDraft=id=>new Promise(resolve=>deliveries[id]=()=>resolve(make(id)));
route='11';needs=true;await settle();route='12';needs=true;await settle();
deliveries[12]();await settle();assert.equal(state.selectedId,12);deliveries[11]();await settle();assert.equal(state.selectedId,12);
// Explicit missing ID produces an empty editor, never another queue item.
api.fetchDraft=async()=>{throw {response:{status:404}};};set('drafts',[]);route='999';needs=true;await settle();assert.equal(state.selectedId,null);assert.equal(state.title,'');assert.equal(state.body,'');assert.match(result.selectionError,/不存在/);
assert.deepEqual(Array.from(state.drafts,d=>d.id),[1,2],'missing explicit target must retain the fetched owned queue without selecting it');
// Owner changes cannot restore the previous owner's buffered editor.
api.fetchDraft=async id=>make(id);owner=2;route='1';needs=true;await settle();assert.equal(state.body,'Body 1');assert.equal(buffers.readCourseEditBuffer(scope(1)),null);
console.log('10 draft selection, recovery, conflict, ownership and stale response checks passed');
