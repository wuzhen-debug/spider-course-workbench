import {useEffect,useRef,useState} from 'react';
import type {Dispatch,SetStateAction} from 'react';
import {useSearchParams} from 'react-router-dom';
import {useAuth} from './use-auth';
import {fetchDraft,fetchDrafts} from '../lib/api';
import {readCourseEditBuffer,writeCourseEditBuffer,removeCourseEditBuffer} from '../lib/course-edit-buffer';
import {draftEditorKey,draftEditorValue,resolveRequestedDraft,type DraftEditorValue} from '../lib/draft-route-selection';
import type {Draft} from '../types';

type Bindings={drafts:Draft[];setDrafts:Dispatch<SetStateAction<Draft[]>>;selectedId:number|null;setSelectedId:(id:number|null)=>void;
 title:string;setTitle:(value:string)=>void;body:string;setBody:(value:string)=>void;tags:DraftEditorValue['tags'];setTags:(value:DraftEditorValue['tags'])=>void;
 setLoading:(value:boolean)=>void;setError:(value:string|null)=>void};
type Conflict={draftId:number;value:DraftEditorValue};

export function useDraftRouteEditor(bindings:Bindings){
 const {user}=useAuth();const userId=user?.id;const [params,setParams]=useSearchParams();const requested=params.get('draft_id');
 const [bufferNotice,setBufferNotice]=useState('');const [selectionError,setSelectionError]=useState('');
 const [editConflict,setEditConflict]=useState<Conflict|null>(null);const conflictRef=useRef<Conflict|null>(null);
 const [hydrating,setHydrating]=useState(true);const hydratingRef=useRef(true);
 const loaded=useRef<{owner:number;id:number;base:string}|null>(null);const requestSeq=useRef(0);
 const live=useRef({bindings,userId,requested});live.current={bindings,userId,requested};
 const scope=(owner:number,id:number)=>({userId:owner,feature:'draft-workshop',recordId:String(id)});
 const loading=(value:boolean)=>{hydratingRef.current=value;setHydrating(value);bindings.setLoading(value);};
 const conflict=(value:Conflict|null)=>{conflictRef.current=value;setEditConflict(value);};
 function setEditor(value:DraftEditorValue){bindings.setTitle(value.title);bindings.setBody(value.body);bindings.setTags(value.tags);}
 function remember():boolean{
  const {bindings:b,userId:owner}=live.current;const record=loaded.current;
  if(hydratingRef.current||conflictRef.current||owner===undefined||!record||record.owner!==owner||record.id!==b.selectedId)return true;
  const value={title:b.title,body:b.body,tags:b.tags};
  if(draftEditorKey(value)===record.base){removeCourseEditBuffer(scope(owner,record.id));setBufferNotice('');return true;}
  const ok=writeCourseEditBuffer(scope(owner,record.id),value,record.base);
  setBufferNotice(ok?'当前修改已缓存在本浏览器，尚未保存到草稿。':'本机编辑缓存不可用，请先保存当前改稿再离开。');
  return ok;
 }
 function receive(draft:Draft|null,owner:number){
  bindings.setSelectedId(draft?.id??null);conflict(null);
  if(!draft){loaded.current=null;setEditor({title:'',body:'',tags:[]});setBufferNotice('');return;}
  const initial=draftEditorValue(draft);const base=draftEditorKey(initial);
  loaded.current={owner,id:draft.id,base};
  const saved=readCourseEditBuffer<DraftEditorValue>(scope(owner,draft.id));
  const valid=saved&&typeof saved.value?.title==='string'&&typeof saved.value?.body==='string'&&Array.isArray(saved.value?.tags)&&saved.value.tags.every(t=>typeof t?.name==='string'&&typeof t?.id==='string');
  if(valid&&saved.baseVersion!==base&&draftEditorKey(saved.value)!==base){
   conflict({draftId:draft.id,value:saved.value});setEditor(initial);setBufferNotice('');return;
  }
  setEditor(valid?saved.value:initial);
  setBufferNotice(valid&&draftEditorKey(saved.value)!==base?'已恢复本机未保存编辑，保存后才会更新草稿。':'');
 }
 async function loadDrafts(){
  if(!remember()){setSelectionError('目标草稿尚未打开：请先保存当前未缓存的修改。');return;}
  const seq=++requestSeq.current,owner=userId,route=requested;if(owner===undefined)return;
  const current=()=>seq===requestSeq.current&&live.current.userId===owner&&live.current.requested===route;
  loading(true);bindings.setError(null);setSelectionError('');
  if(loaded.current&&loaded.current.owner!==owner)bindings.setDrafts([]);
  if(loaded.current?.owner!==owner||(route!==null&&route!==String(bindings.selectedId)))receive(null,owner);
  let ownedItems:Draft[]|null=null;
  try{
   const result=await fetchDrafts('xhs');if(!current())return;
   ownedItems=result.items;
   const selected=await resolveRequestedDraft(route,result.items,live.current.bindings.selectedId,fetchDraft);if(!current())return;
   // Commit the list and editor together. Never mix old editable text with a new base.
   bindings.setDrafts(selected?[selected,...result.items.filter(d=>d.id!==selected.id)]:result.items);
   receive(selected,owner);
  }catch(error){if(!current())return;receive(null,owner);
   // A missing explicit target must not hide the successfully fetched owned queue.
   // Keep the editor empty; only an explicit user selection may open another draft.
   if(ownedItems!==null)bindings.setDrafts(ownedItems);
   const response=(error as {response?:{status?:number}}).response;
   setSelectionError(response?.status===404?'指定草稿不存在或无权访问，请从列表重新选择。':error instanceof Error&&error.message.startsWith('草稿链接')?error.message:route!==null?'指定草稿读取失败，请重试；没有打开其他草稿。':'草稿列表读取失败，请重试。');
  }finally{if(current())loading(false);}
 }
 function chooseDraft(draft:Draft){
  if(!remember()){setSelectionError('请先保存当前未缓存的修改，再切换草稿。');return;}
  if(params.get('draft_id')===String(draft.id)){void loadDrafts();return;}
  const next=new URLSearchParams(params);next.set('draft_id',String(draft.id));setParams(next);
 }
 function resolveEditConflict(useBuffer:boolean){
  const record=loaded.current,pending=conflictRef.current;
  if(!record||!pending||record.owner!==userId||record.id!==pending.draftId)return;
  if(useBuffer){setEditor(pending.value);writeCourseEditBuffer(scope(record.owner,record.id),pending.value,record.base);setBufferNotice('已恢复本机副本，尚未保存；请核对后保存。');}
  else{removeCourseEditBuffer(scope(record.owner,record.id));setBufferNotice('已保留服务器版本。');}
  conflict(null);
 }
 function acceptSaved(draft:Draft){
  const record=loaded.current;
  if(!record||record.owner!==live.current.userId||record.id!==draft.id)return;
  record.base=draftEditorKey(draftEditorValue(draft));
  remember();
 }
 function captureEditorOperation(){
  const owner=userId,id=bindings.selectedId,route=requested,seq=requestSeq.current;
  return ()=>owner===live.current.userId&&id===live.current.bindings.selectedId&&route===live.current.requested&&seq===requestSeq.current;
 }
 async function refreshCourseOrigin(draftId:number){
  const owner=userId;
  try{
   const fresh=await fetchDraft(draftId);
   if(owner!==live.current.userId)return;
   live.current.bindings.setDrafts(items=>items.map(d=>d.id===draftId?{...d,course_origin:fresh.course_origin}:d));
  }catch{if(owner===live.current.userId)bindings.setError('素材已更新，但来源状态暂未刷新，请点击刷新草稿核对。');}
 }
 useEffect(()=>{void loadDrafts();return()=>{requestSeq.current++;};},[requested,userId]);
 useEffect(()=>{remember();},[bindings.selectedId,bindings.title,bindings.body,JSON.stringify(bindings.tags),userId]);
 useEffect(()=>{const handler=(event:BeforeUnloadEvent)=>{if(!remember()){event.preventDefault();event.returnValue='';}};window.addEventListener('beforeunload',handler);return()=>window.removeEventListener('beforeunload',handler);},[]);
 return {loadDrafts,chooseDraft,acceptSaved,captureEditorOperation,refreshCourseOrigin,bufferNotice,selectionError,editConflict,resolveEditConflict,editorBlocked:hydrating||!!editConflict};
}
