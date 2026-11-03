import { BookOutlined, CheckOutlined, EditOutlined, FileSearchOutlined, GlobalOutlined, LinkOutlined, PlusOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Checkbox, Col, Collapse, Drawer, Empty, Form, Input, Modal, Row, Select, Space, Spin, Table, Tabs, Tag, Typography } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { researchEntryMatches } from '../../../lib/course-creations';
import { CoursePdfInlinePreview } from '../../../components/course-pdf-inline-preview';
import { CourseBrandSelect } from '../../../components/course-brand-select';
import { fetchAccounts, fetchResearch, fetchResearchContext, fetchResearchHistory, researchAction, visualWorkflowAction } from '../../../lib/api';
import type { EvidenceReview, ResearchContext, ResearchDraft, ResearchHistory, ResearchMaterial, ResearchSource, ResearchWorkspace, WritingOptions, WritingPlan } from '../../../lib/course-research-types';
import type { PlatformAccount } from '../../../types';
import { useAuth } from '../../../hooks/use-auth';
import { readCourseEditBuffer,writeCourseEditBuffer,removeCourseEditBuffer,hasCourseEditStorage } from '../../../lib/course-edit-buffer';
import type { CourseEditBuffer,CourseEditScope } from '../../../lib/course-edit-buffer';

const {Title,Text,Paragraph}=Typography;
const emptyContext:ResearchContext={university:'',course_code:'',course_name:'',term:'',library_directory:''};
const sorts=[{value:2,label:'最多点赞'},{value:4,label:'最多收藏'},{value:3,label:'最多评论'},{value:1,label:'最新发布'},{value:0,label:'综合排序'}];
const draftStatus:Record<string,string>={saved:'已保存到草稿工坊',pending:'待人工审核',generating:'生成中',failed:'生成未完成'};
function message(e:unknown) {
  const d=(e as {response?:{data?:{detail?:unknown}}})?.response?.data?.detail;
  return typeof d==='string'?d:Array.isArray(d)?d.map(x=>x.msg).join('；'):'操作未完成，请检查本机服务后重试。';
}
function stamp(s:string){return new Date(s).toLocaleString('zh-CN',{hour12:false});}
function Metric({value}:{value:number|null}){return value===null?<Text type="secondary">未知</Text>:<Text>{value.toLocaleString()}</Text>;}
function Original({source}:{source:ResearchSource}){return <a href={source.source_url} target="_blank" rel="noopener noreferrer"><LinkOutlined/> 原文</a>;}
function status(s:ResearchSource){return s.content_status==='detail'?'已读正文':s.content_status==='manual_excerpt'?'手动摘录':'搜索摘要';}
type ResearchEdit={context:ResearchContext;keyword:string;source:'xhs'|'web';sort:number;timeRange:number;selected:string[];topic:string;purpose:'learning'|'product';brand:string;facts:string;instruction:string;materialIds:number[];draftId:number|null};
type DraftEdit={title:string;body:string;tags:string[]};
type ResearchHandoffPlan={research_id:number;research_draft_id:number;review_digest:string;copy:DraftEdit&{topic:string};source:{filename:string;relative_path:string;revision_id:number;sha256:string;university:string;course_code:string};evidence:ResearchSource[];evidence_review:EvidenceReview;brand:{name:string};changed_since_draft:{sources:string[];material:boolean};scope:string};
const strings=(v:unknown):v is string[]=>Array.isArray(v)&&v.every(x=>typeof x==='string');
function isResearchEdit(v:unknown):v is ResearchEdit{
  if(!v||typeof v!=='object')return false;const x=v as ResearchEdit;
  return !!x.context&&['university','course_code','course_name','term','library_directory'].every(k=>typeof x.context[k as keyof ResearchContext]==='string')&&
    [x.keyword,x.topic,x.brand,x.facts,x.instruction].every(s=>typeof s==='string')&&['xhs','web'].includes(x.source)&&['learning','product'].includes(x.purpose)&&
    Number.isInteger(x.sort)&&Number.isInteger(x.timeRange)&&strings(x.selected)&&Array.isArray(x.materialIds)&&x.materialIds.every(Number.isInteger)&&
    (x.draftId===null||Number.isInteger(x.draftId));
}
function isDraftEdit(v:unknown):v is DraftEdit{const x=v as DraftEdit;return !!x&&typeof x.title==='string'&&typeof x.body==='string'&&strings(x.tags);}

export function CourseResearchPanel({directory,onOpenPdf}:{directory:string;onOpenPdf:(id:number)=>void}) {
  const {user}=useAuth();const userId=user?.id;
  const navigate=useNavigate();const [params]=useSearchParams();
  const requestedFileId=Number(params.get('file_id'))||undefined;
  const requestedResearchId=Number(params.get('research_id'))||undefined;
  const requestedDraftId=Number(params.get('research_draft_id'))||undefined;
  const bufferContext=JSON.stringify([userId,directory]);
  const operationScope=JSON.stringify([userId,directory,requestedFileId,requestedResearchId,requestedDraftId]);
  const [context,setContext]=useState<ResearchContext>(emptyContext);
  const [initialContext,setInitialContext]=useState<ResearchContext>(emptyContext);
  const [materials,setMaterials]=useState<ResearchMaterial[]>([]);
  const [suggestions,setSuggestions]=useState<string[]>([]);
  const [accounts,setAccounts]=useState<PlatformAccount[]>([]);
  const [accountId,setAccountId]=useState<number|null>(null);
  const [history,setHistory]=useState<ResearchHistory[]>([]);
  const [workspace,setWorkspace]=useState<ResearchWorkspace|null>(null);
  const [keyword,setKeyword]=useState('');const [source,setSource]=useState<'xhs'|'web'>('xhs');
  const [sort,setSort]=useState(2);const [timeRange,setTimeRange]=useState(0);
  const [selected,setSelected]=useState<string[]>([]);const [sourceDetail,setSourceDetail]=useState<string|null>(null);
  const [showExcluded,setShowExcluded]=useState(false);
  const [busy,setBusy]=useState('loading');const [error,setError]=useState('');const [notice,setNotice]=useState('');
  const [unavailableEntry,setUnavailableEntry]=useState(false);
  const [importOpen,setImportOpen]=useState(false);const [importForm]=Form.useForm();
  const [topic,setTopic]=useState('');const [purpose,setPurpose]=useState<'learning'|'product'>('learning');
  const [brand,setBrand]=useState('');const [facts,setFacts]=useState('');const [instruction,setInstruction]=useState('');
  const [materialIds,setMaterialIds]=useState<number[]>([]);const [prepared,setPrepared]=useState<WritingPlan|null>(null);
  const [consent,setConsent]=useState(false);const [requestKeys,setRequestKeys]=useState({outline:'',ai:''});
  const [draft,setDraft]=useState<ResearchDraft|null>(null);const [draftTitle,setDraftTitle]=useState('');const [draftBody,setDraftBody]=useState('');const [draftTags,setDraftTags]=useState<string[]>([]);const [reviewed,setReviewed]=useState(false);
  const [draftError,setDraftError]=useState('');const [draftNotice,setDraftNotice]=useState('');
  const [bufferReady,setBufferReady]=useState<string|null>(null);const [bufferIssue,setBufferIssue]=useState('');
  const [bufferRestored,setBufferRestored]=useState(false);const [draftRecovery,setDraftRecovery]=useState<CourseEditBuffer<DraftEdit>|null>(null);
  const [handoffOpen,setHandoffOpen]=useState(false);const [handoffFileId,setHandoffFileId]=useState<number|undefined>();
  const [handoffPlan,setHandoffPlan]=useState<ResearchHandoffPlan|null>(null);const [handoffReviewed,setHandoffReviewed]=useState(false);
  const [handoffKey,setHandoffKey]=useState('');const [handoffError,setHandoffError]=useState('');
  const [handoffTab,setHandoffTab]=useState('review');
  const generation=useRef(0);
  const liveScope=useRef(operationScope);liveScope.current=operationScope;
  const options:WritingOptions=useMemo(()=>({topic,selected_ids:selected,purpose,brand,facts,instruction,material_ids:materialIds}),[topic,selected,purpose,brand,facts,instruction,materialIds]);
  useEffect(()=>{setPrepared(null);setConsent(false);setRequestKeys({outline:'',ai:''});},[options,workspace?.updated_at]);
  useEffect(()=>{setReviewed(false);setDraftError('');setDraftNotice('');},[draftTitle,draftBody,draftTags,draft?.id]);
  useEffect(()=>{setHandoffPlan(null);setHandoffReviewed(false);setHandoffError('');},[handoffFileId,draft?.id,draft?.review_digest,workspace?.id,workspace?.updated_at]);
  useEffect(()=>{if(handoffOpen&&handoffFileId)void prepareHandoff();},[handoffOpen,handoffFileId,draft?.id,draft?.review_digest,workspace?.id,workspace?.updated_at]);
  useEffect(()=>{if(prepared)document.getElementById('research-writing-plan')?.scrollIntoView({behavior:'smooth',block:'start'});},[prepared]);
  useEffect(()=>{
    if(userId===undefined)return;
    const seq=++generation.current;const current=()=>seq===generation.current&&liveScope.current===operationScope;
    setBusy('loading');setUnavailableEntry(false);setBufferReady(null);setWorkspace(null);setPrepared(null);setDraft(null);setSelected([]);setMaterialIds([]);setError('');setNotice('');setBufferRestored(false);setHandoffOpen(false);setHandoffPlan(null);setHandoffReviewed(false);setBufferIssue(hasCourseEditStorage()?'':'浏览器无法保存本机编辑缓冲，请保存研究稿或复制内容后再离开。');
    void (async()=>{
      try {
        const [loaded,accts]=await Promise.all([fetchResearchContext(directory),fetchAccounts('xhs').catch(()=>[])]);
        if(!current())return;
        setContext(loaded.context);setInitialContext(loaded.context);setMaterials(loaded.materials);setSuggestions(loaded.suggested_keywords);setKeyword(loaded.context.course_code);
        const pc=accts.filter(a=>a.sub_type==='pc');setAccounts(pc);setAccountId(v=>pc.some(a=>a.id===v)?v:pc[0]?.id??null);
        const previous=await fetchResearchHistory(loaded.context.course_code,loaded.context.university);
        if(!current())return;setHistory(previous.items);
        const remembered=readCourseEditBuffer<{researchId:number|null}>({userId,feature:'research-last',recordId:directory});
        const requested=requestedResearchId??previous.items.find(r=>r.id===remembered?.value.researchId)?.id??previous.items[0]?.id;
        const old=requested&&(loaded.context.course_code||requestedResearchId)?await fetchResearch(requested):null;
        if(!current())return;
        if(requestedResearchId&&!researchEntryMatches(loaded.context,old?.context)){
          setError('指定研究不属于当前大学与课程，未切换到其他研究。');setUnavailableEntry(true);return;
        }
        const returnedDraft=requestedResearchId&&requestedDraftId?old?.drafts.find(d=>d.id===requestedDraftId):null;
        if(requestedDraftId&&!returnedDraft){setError('当前研究中找不到指定文案，未改为打开其他稿件。请返回本课程研究后核对历史记录。');setUnavailableEntry(true);return;}
        restoreEditor(old,loaded.context,loaded.materials,true,requestedFileId);
        if(returnedDraft)openDraft(returnedDraft);setBufferReady(bufferContext);
      } catch(e){if(current()){setError(message(e));if(requestedResearchId||requestedDraftId)setUnavailableEntry(true);}}
      finally{if(current())setBusy('');}
    })();return()=>{generation.current++;};
  },[directory,userId,requestedFileId,requestedResearchId,requestedDraftId]);
  function formScope(id:number|null):CourseEditScope{return {userId:userId!,feature:'research-form',recordId:String(id??'new'),context:directory};}
  function draftScope(row:ResearchDraft):CourseEditScope{return {userId:userId!,feature:'research-draft',recordId:String(row.id),context:String(row.research_id)};}
  function restoreEditor(row:ResearchWorkspace|null,fallback:ResearchContext,available:ResearchMaterial[],restore=true,entryFileId?:number){
    const saved=restore&&userId!==undefined?readCourseEditBuffer<ResearchEdit>(formScope(row?.id??null)):null;
    const edit=saved&&isResearchEdit(saved.value)?saved.value:null;
    const next=edit?.context??row?.context??fallback;
    setWorkspace(row);setContext(next);setKeyword(edit?.keyword??next.course_code);setSource(edit?.source??'xhs');setSort(edit?.sort??2);setTimeRange(edit?.timeRange??0);
    const same=!!row&&(['university','course_code','course_name','term'] as const).every(k=>row.context[k]===next[k]);
    setSelected(same?(edit?.selected??[]).filter(id=>row.evidence.some(e=>e.id===id&&!e.excluded)).slice(0,8):[]);
    setTopic(edit?.topic??'');setPurpose(edit?.purpose??'learning');setBrand(edit?.brand??'');setFacts(edit?.facts??'');setInstruction(edit?.instruction??'');
    const entrySelection=entryFileId&&available.some(m=>m.id===entryFileId)?[entryFileId]:[];
    setMaterialIds(next.course_code===fallback.course_code&&next.university===fallback.university?(edit?.materialIds??entrySelection).filter(id=>available.some(m=>m.id===id)).slice(0,2):[]);
    setPrepared(null);setConsent(false);setDraft(null);setDraftRecovery(null);setReviewed(false);setBufferRestored(!!edit);
    const active=same?row.drafts.find(d=>d.id===edit?.draftId):null;if(active)openDraft(active);
  }
  useEffect(()=>{
    if(userId===undefined||bufferReady!==bufferContext||busy==='loading')return;
    const edit:ResearchEdit={context,keyword,source,sort,timeRange,selected,topic,purpose,brand,facts,instruction,materialIds,draftId:draft?.id??null};
    const ok=writeCourseEditBuffer(formScope(workspace?.id??null),edit,workspace?.updated_at)&&
      writeCourseEditBuffer({userId,feature:'research-last',recordId:directory},{researchId:workspace?.id??null});
    setBufferIssue(ok?'':'浏览器无法保存本机编辑缓冲，请先保存研究稿或复制编辑内容后再离开。');
  },[userId,bufferReady,bufferContext,directory,context,keyword,source,sort,timeRange,selected,topic,purpose,brand,facts,instruction,materialIds,draft?.id,workspace?.id,workspace?.updated_at,busy]);
  useEffect(()=>{
    if(userId===undefined||!draft||draft.status!=='pending'||draftRecovery||bufferReady!==bufferContext||busy)return;
    const changed=draftTitle!==draft.title||draftBody!==draft.body||JSON.stringify(draftTags)!==JSON.stringify(draft.tags);
    const ok=changed?writeCourseEditBuffer(draftScope(draft),{title:draftTitle,body:draftBody,tags:draftTags},draft.review_digest):removeCourseEditBuffer(draftScope(draft));
    if(!ok)setBufferIssue('浏览器无法保存本机改稿，请先点击“保存修改，保持待审核”或复制内容再离开。');
  },[userId,draft,draftTitle,draftBody,draftTags,draftRecovery,bufferReady,bufferContext,directory,busy]);
  useEffect(()=>{
    const guard=(event:BeforeUnloadEvent)=>{if(bufferIssue){event.preventDefault();event.returnValue='';}};
    window.addEventListener('beforeunload',guard);return()=>window.removeEventListener('beforeunload',guard);
  },[bufferIssue]);
  function updateContext(key:keyof ResearchContext,value:string){setContext(c=>({...c,[key]:value}));setSelected([]);setDraft(null);setDraftRecovery(null);if(key==='university'||key==='course_code')setMaterialIds([]);}
  function captureOperation(){
    const seq=generation.current,scope=operationScope;
    const current=()=>seq===generation.current&&liveScope.current===scope;
    return {current,guard:()=>{if(!current())throw new Error('课程研究页面已切换，旧请求结果仅保留在原研究。');}};
  }
  async function openResearch(id:number){await act('history',async guard=>{const row=await fetchResearch(id);guard();restoreEditor(row,initialContext,materials);});}
  async function refreshHistory(guard:()=>void){const r=await fetchResearchHistory(context.course_code,context.university);guard();setHistory(r.items);}
  function sameContext(){return workspace&&(['university','course_code','course_name','term'] as const).every(key=>workspace.context[key]===context[key]);}
  async function ensureResearch(fresh:boolean,guard:()=>void){
    guard();
    if(!fresh&&sameContext())return workspace!;
    const row=await researchAction<ResearchWorkspace>('',{...context,library_directory:directory,course_directory:undefined,course_id:undefined});
    guard();
    if(fresh)restoreEditor(row,initialContext,materials,false);
    else {setWorkspace(row);setSelected([]);setPrepared(null);setDraft(null);setDraftRecovery(null);}
    return row;
  }
  async function act(name:string,fn:(guard:()=>void)=>Promise<void>,reportError:(text:string)=>void=setError){
    const operation=captureOperation();if(!operation.current())return;
    setBusy(name);setError('');setNotice('');
    try{await fn(operation.guard);}catch(e){if(operation.current())reportError(message(e));}finally{if(operation.current())setBusy('');}
  }
  function updateWorkspace(row:ResearchWorkspace,guard:()=>void){guard();setWorkspace(row);setSelected(v=>v.filter(id=>row.evidence.some(e=>e.id===id&&!e.excluded)));}
  async function search(page=1){
    if(!keyword.trim()){setError('请输入课程或主题关键词。');return;}
    await act('search',async guard=>{
      const row=await ensureResearch(false,guard);
      try{const next=await researchAction<ResearchWorkspace>(`/${row.id}/search`,{source,keyword,page,sort,time_range:timeRange,account_id:accountId});updateWorkspace(next,guard);await refreshHistory(guard);}
      catch(e){guard();updateWorkspace(await fetchResearch(row.id),guard);throw e;}
    });
  }
  async function readSource(item:ResearchSource){
    if(!workspace||!accountId){setError('请先选择小红书PC账号。');return;}
    await act('read-'+item.id,async guard=>{const row=await researchAction<ResearchWorkspace>(`/${workspace.id}/sources/${item.id}/read`,{account_id:accountId});updateWorkspace(row,guard);});
  }
  async function importSource(){
    const operation=captureOperation();
    try{const values=await importForm.validateFields();operation.guard();await act('import',async guard=>{const row=await ensureResearch(false,guard);updateWorkspace(await researchAction<ResearchWorkspace>(`/${row.id}/sources`,values),guard);setImportOpen(false);importForm.resetFields();await refreshHistory(guard);});}
    catch(e){if(!operation.current()||(e as {errorFields?:unknown}).errorFields)return;setError(message(e));}
  }
  async function prepare(){
    await act('prepare',async guard=>{const row=await ensureResearch(false,guard);const next=await researchAction<WritingPlan>(`/${row.id}/writing-plan`,options);guard();setPrepared(next);setConsent(false);setRequestKeys({outline:crypto.randomUUID(),ai:crypto.randomUUID()});});
  }
  function openDraft(row:ResearchDraft){
    const saved=userId===undefined?null:readCourseEditBuffer<DraftEdit>(draftScope(row));
    const valid=saved&&isDraftEdit(saved.value)?saved:null;const recover=valid&&valid.baseVersion===row.review_digest&&row.status==='pending'?valid.value:null;
    setDraft(row);setDraftTitle(recover?.title??row.title);setDraftBody(recover?.body??row.body);setDraftTags(recover?.tags??row.tags);
    setDraftRecovery(valid&&!recover?valid:null);setReviewed(false);setDraftError('');setDraftNotice(recover?'已恢复本机未提交改稿，请保存并重新核对；没有自动审核或外发。':'');
  }
  async function generate(mode:'outline'|'ai'){
    if(!workspace||!prepared)return;
    await act('generate-'+mode,async guard=>{
      const row=await researchAction<ResearchDraft>(`/${workspace.id}/drafts`,{...prepared.options,mode,plan_digest:prepared.plan_digest,external_consent:mode==='ai'&&consent,request_key:requestKeys[mode]});
      guard();openDraft(row);updateWorkspace(await fetchResearch(workspace.id),guard);setNotice(mode==='ai'?'AI文案已保存为待审核草稿。':'本地写作提纲已保存，可继续编辑。');
    });
  }
  const dirty=!!draft&&(draftTitle!==draft.title||draftBody!==draft.body||JSON.stringify(draftTags)!==JSON.stringify(draft.tags));
  // Python's len() counts Unicode code points; keep the editor consistent with the API.
  const titleLength=Array.from(draftTitle).length;const bodyLength=Array.from(draftBody).length;
  const titleIssue=!draftTitle.trim()?'标题不能为空。':titleLength>20?`标题共 ${titleLength} 字，超出 ${titleLength-20} 字；请精简到 20 字以内。`:'';
  const bodyIssue=!draftBody.trim()?'正文不能为空。':bodyLength>1000?`正文共 ${bodyLength} 字，超出 ${bodyLength-1000} 字；请精简到 1000 字以内。`:'';
  function focusDraftField(field:'title'|'body'){
    const input=document.getElementById(`research-draft-${field}`);
    input?.scrollIntoView({behavior:'smooth',block:'center'});input?.focus({preventScroll:true});
  }
  async function saveDraft(){
    if(!draft||!workspace||busy)return;setDraftError('');setDraftNotice('');
    if(draftRecovery){setDraftError('请先恢复或放弃保留的本机改稿，再编辑保存。');return;}
    if(!dirty){setDraftNotice('当前内容已保存，暂无需要保存的修改。核对后可勾选审核确认。');return;}
    if(!draftTitle.trim()||!draftBody.trim()){setDraftError(!draftTitle.trim()?'请先填写标题。':'请先填写正文。');focusDraftField(!draftTitle.trim()?'title':'body');return;}
    await act('save',async guard=>{const r=await researchAction<ResearchDraft>(`/${workspace.id}/drafts/${draft.id}`,{title:draftTitle,body:draftBody,tags:draftTags},'patch');guard();removeCourseEditBuffer(draftScope(draft));openDraft(r);setDraftNotice('修改已保存，继续保持待审核。请重新核对并勾选审核确认。');updateWorkspace(await fetchResearch(workspace.id),guard);},setDraftError);
  }
  async function approve(){
    if(!draft||!workspace||busy)return;setDraftError('');setDraftNotice('');
    if(draftRecovery){setDraftError('请先处理保留的本机改稿，再重新审核。');return;}
    if(titleIssue||bodyIssue){setDraftError(titleIssue||bodyIssue);focusDraftField(titleIssue?'title':'body');return;}
    if(dirty){setDraftError('有未保存的修改，请先点击“保存修改，保持待审核”，再核对并勾选审核确认。');return;}
    if(!reviewed){setDraftError('请先核对文案、来源和资料事实，并勾选下方的审核确认。');return;}
    await act('approve',async guard=>{const r=await researchAction<ResearchDraft>(`/${workspace.id}/drafts/${draft.id}/approve`,{reviewed,review_digest:draft.review_digest});guard();openDraft(r);updateWorkspace(await fetchResearch(workspace.id),guard);setNotice('已保存到草稿工坊，未创建发布任务。');},setDraftError);
  }
  function startHandoff(){
    if(!draft||!workspace||busy)return;
    if(draftRecovery||dirty){setDraftError('请先处理本机改稿并保存当前文案，再核对进入图文制作。');return;}
    if(titleIssue||bodyIssue){setDraftError(titleIssue||bodyIssue);focusDraftField(titleIssue?'title':'body');return;}
    if(!sameContext()){setDraftError('课程范围已改变，请先切回本稿的大学与课程，再进入图文制作。');return;}
    const briefMaterials=Array.isArray(draft.brief.materials)?draft.brief.materials as {file_id:number}[]:[];
    const candidates=materialIds.length?materialIds:briefMaterials.map(m=>m.file_id);
    const chosen=candidates.length===1&&materials.some(m=>m.id===candidates[0])?candidates[0]:requestedFileId&&materials.some(m=>m.id===requestedFileId)?requestedFileId:materials.length===1?materials[0].id:undefined;
    setHandoffFileId(chosen);setHandoffPlan(null);setHandoffReviewed(false);setHandoffError('');setHandoffKey('');setHandoffTab('review');setHandoffOpen(true);
  }
  async function prepareHandoff(){
    if(!draft||!workspace||!handoffFileId||busy)return;
    if(dirty||draftRecovery||!sameContext()){setHandoffError('文案或课程范围已改变，请先关闭此窗口，保存并重新核对。');return;}
    setHandoffPlan(null);setHandoffReviewed(false);setHandoffError('');
    await act('handoff-plan',async guard=>{
      const current=await fetchResearchContext(directory);guard();setMaterials(current.materials);
      const file=current.materials.find(m=>m.id===handoffFileId);
      if(!file){setHandoffError('这份PDF已不在当前课程可用资料中，请重新选择。');return;}
      const plan=await visualWorkflowAction<ResearchHandoffPlan>('/from-research/plan',{research_id:workspace.id,research_draft_id:draft.id,file_id:file.id,revision_id:file.revision_id});
      guard();setHandoffPlan(plan);setHandoffKey(crypto.randomUUID());
    },setHandoffError);
  }
  async function confirmHandoff(){
    if(!handoffPlan||!handoffFileId||!handoffReviewed||busy)return;
    setHandoffError('');
    await act('handoff',async guard=>{
      const row=await visualWorkflowAction<{id:number}>('/from-research',{research_id:handoffPlan.research_id,research_draft_id:handoffPlan.research_draft_id,file_id:handoffFileId,revision_id:handoffPlan.source.revision_id,reviewed:true,limited_sources_reviewed:handoffReviewed&&handoffPlan.evidence_review.limited,review_digest:handoffPlan.review_digest,request_key:handoffKey});
      guard();setHandoffOpen(false);navigate(`/platforms/xhs/visual-workbench?run=${row.id}&stage=visual`);
    },setHandoffError);
  }
  const sortedSources=useMemo(()=>[...(workspace?.evidence??[])].filter(e=>showExcluded||!e.excluded).sort((a,b)=>{
    const key=sort===4?'collects':sort===3?'comments':'likes';return (b.metrics[key]??-1)-(a.metrics[key]??-1);
  }),[workspace?.evidence,sort,showExcluded]);
  const detail=workspace?.evidence.find(e=>e.id===sourceDetail);const pattern=workspace?.analysis.reference_patterns.find(e=>e.source_id===sourceDetail);
  const matchingSearches=workspace?.searches.filter(r=>r.source===source&&r.keyword===keyword&&r.sort===sort&&r.status==='completed')??[];
  const lastSearch=matchingSearches[matchingSearches.length-1];
  const localMaterials=context.course_code===initialContext.course_code&&context.university===initialContext.university?materials:[];
  const handoffMaterial=localMaterials.find(m=>m.id===handoffFileId);
  const query=encodeURIComponent(keyword||context.course_code);
  if(busy==='loading')return <Card><Spin/> <Text>正在读取课程研究入口…</Text></Card>;
  if(unavailableEntry)return <Alert type="error" showIcon message={error||'指定研究或文案暂不可用。'} action={<Button onClick={()=>{const next=new URLSearchParams(params);next.delete('research_id');next.delete('research_draft_id');navigate(`/platforms/xhs/course-center?${next.toString()}`);}}>返回本课程研究</Button>}/>;
  return <div className="course-research">
    <div className="research-intro"><div><Space wrap><Tag color="blue">整门课程</Tag><Tag>手动研究 · 人工审核</Tag><Text strong>{context.university} · {context.course_code}</Text></Space><Title level={3}>先找学生关心的话题，再决定怎么写</Title><Paragraph type="secondary">从课程、主题或关键词出发，比较参考笔记，收集真实问题，再结合需要的资料制作原创草稿。</Paragraph></div><Button icon={<PlusOutlined/>} disabled={!!busy} onClick={()=>void act('new',async guard=>{await ensureResearch(true,guard);await refreshHistory(guard);setNotice('已新建研究，原研究与草稿均保留。');})}>新建课程研究</Button></div>
    {error&&<Alert type="error" showIcon message={error} closable onClose={()=>setError('')} style={{marginBottom:16}}/>}
    {notice&&<Alert type="success" showIcon message={notice} closable onClose={()=>setNotice('')} style={{marginBottom:16}}/>}
    <Alert type={bufferIssue?'warning':'info'} showIcon message={bufferIssue||`${bufferRestored?'已恢复上次编辑。':''}选题、写作选项和未提交改稿自动缓存在本浏览器，按账号、目录和研究分别保存；不会自动调用 AI、审核或保存到草稿工坊。`} style={{marginBottom:16}}/>
    <Card size="small" className="research-context" title={<Space><BookOutlined/>课程与研究范围</Space>} extra={history.length?<Select aria-label="打开已保存课程研究" placeholder="已保存的研究" value={workspace?.id} style={{width:210}} disabled={!!busy} options={history.map(h=>({value:h.id,label:`研究 #${h.id} · ${h.source_count} 个来源`}))} onChange={id=>void openResearch(id)}/>:null}>
      <Row gutter={[12,12]}>{(['university','course_code','course_name','term'] as const).map((key,index)=><Col xs={24} sm={12} xl={6} key={key}><label className="research-label" htmlFor={'research-'+key}>{['大学','课程代码','课程名称（可补充）','学期（可选）'][index]}</label><Input id={'research-'+key} value={context[key]} disabled={!!busy} maxLength={key==='course_name'?240:key==='university'?180:40} onChange={e=>updateContext(key,key==='course_code'?e.target.value.toUpperCase():e.target.value)}/></Col>)}</Row>
      <Text type="secondary">选题覆盖整门课；当前所在的资料类型文件夹不会限制搜索范围。{workspace&&` · 研究 #${workspace.id} 已保存在本机`}</Text>
    </Card>
    <div className="research-workspace">
      <div className="research-evidence-column">
        <Card className="research-search" title={<Space><SearchOutlined/>搜索参考内容</Space>}>
          <Tabs activeKey={source} onChange={key=>setSource(key as 'xhs'|'web')} items={[{key:'xhs',label:'小红书笔记'},{key:'web',label:'公开网页'}]}/>
          <Space wrap style={{marginBottom:12}}>{suggestions.map(s=><Button key={s} size="small" disabled={!!busy} onClick={()=>setKeyword(s)}>{s}</Button>)}</Space>
          <label className="research-label" htmlFor="research-keyword">搜索关键词</label><Input id="research-keyword" value={keyword} maxLength={120} disabled={!!busy} onChange={e=>setKeyword(e.target.value)} onPressEnter={()=>void search()} placeholder="课程代码、课程名称，或你想研究的主题"/>
          {source==='xhs'&&<Row gutter={[10,10]} style={{marginTop:12}}><Col xs={24} md={12}><label className="research-label">搜索账号</label><Select aria-label="课程研究搜索账号" style={{width:'100%'}} value={accountId} disabled={!!busy} onChange={setAccountId} placeholder="选择PC账号" options={accounts.map(a=>({value:a.id,label:`${a.nickname||`PC ${a.id}`} · ${a.status}`}))}/></Col><Col xs={12} md={6}><label className="research-label">排序</label><Select aria-label="课程研究笔记排序" style={{width:'100%'}} value={sort} disabled={!!busy} onChange={setSort} options={sorts}/></Col><Col xs={12} md={6}><label className="research-label">时间</label><Select aria-label="课程研究时间范围" style={{width:'100%'}} value={timeRange} disabled={!!busy} onChange={setTimeRange} options={[{value:0,label:'不限时间'},{value:1,label:'一天内'},{value:2,label:'一周内'},{value:3,label:'半年内'}]}/></Col></Row>}
          <Space wrap style={{marginTop:16}}><Button type="primary" icon={<SearchOutlined/>} loading={busy==='search'} disabled={!!busy||(source==='xhs'&&!accountId)||!context.university||!context.course_code} onClick={()=>void search()}>{source==='xhs'?'搜索小红书笔记':'搜索公开网页'}</Button><Button icon={<PlusOutlined/>} disabled={!!busy} onClick={()=>setImportOpen(true)}>添加原文链接与摘录</Button><a href={`https://duckduckgo.com/?q=${query}`} target="_blank" rel="noopener noreferrer"><GlobalOutlined/> 网页搜索</a><a href={`https://www.xiaohongshu.com/search_result?keyword=${query}`} target="_blank" rel="noopener noreferrer">小红书网页搜索</a></Space>
          {source==='xhs'&&!accounts.length&&<Alert type="info" message={<span>绑定PC账号后可直接搜索，也可以先添加已有链接。<Link to="/platforms/xhs/accounts">去绑定账号</Link></span>} style={{marginTop:12}}/>}
          {source==='web'&&<Paragraph type="secondary" style={{marginTop:12,marginBottom:0}}>公开网页用于课程背景与选题线索；网页搜索摘要没有小红书点赞、收藏等站内数据。</Paragraph>}
        </Card>
        <Card title={<Space wrap>参考笔记与网页<Tag>{sortedSources.length} 个来源</Tag><Text type="secondary">已选 {selected.length}/8</Text></Space>} className="research-sources">
          {!!workspace?.evidence.some(e=>e.excluded)&&<Checkbox checked={showExcluded} onChange={e=>setShowExcluded(e.target.checked)} style={{marginBottom:12}}>显示已排除的参考（{workspace.evidence.filter(e=>e.excluded).length}）</Checkbox>}
          {!sortedSources.length?<Empty description="搜索后在这里比较参考内容，也可以添加你已经找到的笔记链接。"/>:<>
          <Table<ResearchSource> rowKey="id" size="small" dataSource={sortedSources} pagination={false} scroll={{x:640,y:520}}
            rowSelection={{selectedRowKeys:selected,onChange:keys=>{setSelected(keys.map(String).slice(0,8));if(keys.length>8)setNotice('每篇最多使用8个参考来源，已选择前8个；可取消后重新挑选。');},getCheckboxProps:r=>({disabled:!!busy||!!r.excluded||selected.length>=8&&!selected.includes(r.id)})}}
            columns={[
              {title:'参考内容 / 来源',key:'source',width:300,render:(_,r)=><div><Space wrap size={4}><Tag color={r.source_kind==='xhs'?'red':'blue'}>{r.source_kind==='xhs'?'小红书':'网页'}</Tag><Tag>{status(r)}</Tag></Space><button className="research-source-title" onClick={()=>setSourceDetail(r.id)}>{r.title||'未提供标题'}</button><Space wrap><Original source={r}/><Text type="secondary">{stamp(r.observed_at)}</Text></Space>{context.course_code&&!`${r.title} ${r.content}`.replace(/\s/g,'').toUpperCase().includes(context.course_code.replace(/\s/g,'').toUpperCase())&&<div><Text type="warning">请核对是否与本课相关</Text></div>}</div>},
              {title:'点赞',key:'likes',width:75,render:(_,r)=><Metric value={r.metrics.likes}/>},{title:'收藏',key:'collects',width:75,render:(_,r)=><Metric value={r.metrics.collects}/>},{title:'评论',key:'comments',width:75,render:(_,r)=><Metric value={r.metrics.comments}/>},
              {title:'读取',key:'read',width:115,render:(_,r)=>r.source_kind==='xhs'?<Button size="small" disabled={!!busy||!accountId} loading={busy==='read-'+r.id} onClick={()=>void readSource(r)}>正文与评论</Button>:<Button size="small" onClick={()=>setSourceDetail(r.id)}>查看摘录</Button>},
            ]}/>
          {lastSearch?.has_more&&<Button style={{marginTop:12}} disabled={!!busy||lastSearch.page>=5} onClick={()=>void search(lastSearch.page+1)}>读取下一批搜索结果</Button>}
          <Paragraph type="secondary" className="research-scope-note">{workspace?.analysis.scope_note}</Paragraph></>}
          {!!workspace?.searches.length&&<Collapse size="small" items={[{key:'log',label:`搜索记录（${workspace.searches.length}）`,children:<div className="research-scroll-text">{[...workspace.searches].reverse().map((r,i)=><Paragraph key={`${r.at}-${i}`}><Tag color={r.status==='failed'?'orange':'default'}>{r.status==='failed'?'未完成':`${r.returned}条`}</Tag>{r.keyword} · {r.source==='xhs'?'小红书':'公开网页'} · {stamp(r.at)}{r.error&&<Text type="warning"> · {r.error}</Text>}</Paragraph>)}</div>}]} style={{marginTop:16}}/>}
        </Card>
        <Card title={<Space>学生问题与选题线索<Tag>{workspace?.analysis.question_count??0} 条问句</Tag></Space>}>
          {!workspace?.analysis.angles.length?<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="读取参考笔记的正文与评论后，在这里整理问题与选题。"/>:workspace.analysis.angles.map((a,i)=><div className="research-angle" key={i}><div><Tag color="blue">{a.category}</Tag><Text strong>{a.topic}</Text><Paragraph type="secondary" style={{margin:'6px 0'}}>{a.basis}</Paragraph><Space wrap>{a.source_ids.map(id=>{const r=workspace.evidence.find(e=>e.id===id);return r?<Original key={id} source={r}/>:null;})}</Space></div><Button size="small" disabled={!!busy} onClick={()=>{setTopic(a.topic);setSelected(v=>Array.from(new Set([...v,...a.source_ids])).slice(0,8));document.getElementById('research-topic')?.scrollIntoView({behavior:'smooth',block:'center'});}}>用这个方向</Button></div>)}
          {workspace&&<Text type="secondary">已读取 {workspace.analysis.notes_with_detail} 篇正文、{workspace.analysis.comments_read} 条评论。问句是研究线索，仍需判断作者身份、语境及本课适用性。</Text>}
        </Card>
      </div>
      <div className="research-writing-column">
        <Card title={<Space><EditOutlined/>选题与AI写作提示词</Space>}>
          <label className="research-label" htmlFor="research-topic">本篇想解决的问题 / 主题</label><Input.TextArea id="research-topic" value={topic} maxLength={240} autoSize={{minRows:2,maxRows:4}} disabled={!!busy} onChange={e=>setTopic(e.target.value)} placeholder="可以研究整门课的难点、复习方法、选课体验或资料需求，不必先选PDF"/>
          <label className="research-label research-spaced">内容方向</label><Select aria-label="课程研究内容方向" value={purpose} style={{width:'100%'}} disabled={!!busy} onChange={setPurpose} options={[{value:'learning',label:'课程话题 / 学习内容'},{value:'product',label:'结合真实资料做产品介绍'}]}/>
          <div style={{marginTop:12}}><CourseBrandSelect value={brand} onChange={setBrand} disabled={!!busy} label="本篇使用的品牌"/></div>
          <label className="research-label research-spaced">参考PDF（可选，最多2份）</label><Select aria-label="课程研究参考PDF" mode="multiple" maxCount={2} style={{width:'100%'}} value={materialIds} disabled={!!busy} onChange={setMaterialIds} placeholder="整门课程的所有资料类型，可不选" options={localMaterials.map(m=>({value:m.id,label:`${m.material_type||'资料'} · ${m.filename}`}))} optionFilterProp="label"/>
          <Text type="secondary">准备提示词时仅提取所选PDF第1页，先在下方预览。选题不会被资料类别限制。</Text>
          {!!materialIds.length&&<Space wrap style={{marginTop:8}}>{materialIds.map(id=><Button key={id} icon={<FileSearchOutlined/>} size="small" onClick={()=>onOpenPdf(id)}>预览 {localMaterials.find(m=>m.id===id)?.material_type||'PDF'}</Button>)}</Space>}
          <label className="research-label research-spaced" htmlFor="research-facts">补充已核实的课程 / 产品事实</label><Input.TextArea id="research-facts" value={facts} maxLength={3000} autoSize={{minRows:3,maxRows:7}} disabled={!!busy} onChange={e=>setFacts(e.target.value)} placeholder="可补充从PDF、Word或课程官方资料中核对的信息；没有证据的考试要求和产品卖点先留空"/>
          <label className="research-label research-spaced" htmlFor="research-instruction">写作要求与希望借鉴的表达方式</label><Input.TextArea id="research-instruction" value={instruction} maxLength={1200} autoSize={{minRows:3,maxRows:6}} disabled={!!busy} onChange={e=>setInstruction(e.target.value)} placeholder="例如：回应已选评论中的问题，借鉴参考笔记的图解思路，用自己的例子讲清楚"/>
          <Button block type="primary" icon={<EditOutlined/>} style={{marginTop:16}} disabled={!!busy||!brand||!topic.trim()||!context.university||!context.course_code} loading={busy==='prepare'} onClick={()=>void prepare()}>整理提示词与生成范围</Button>
        </Card>
        {prepared&&<Card id="research-writing-plan" title="提示词与生成范围" className="research-plan">
          <Space wrap><Tag>{prepared.source_count} 个参考</Tag><Tag>{prepared.comments_count} 条评论摘录</Tag><Tag>{prepared.materials.length} 份PDF选页</Tag></Space>
          <Paragraph copyable={{text:prepared.prompt}} style={{marginTop:12}}>复制完整写作提示词，可用于你自己的AI对话。</Paragraph>
          <Collapse items={[{key:'prompt',label:`查看完整提示词（${prepared.characters} 字符）`,children:<pre className="research-scroll-text">{prepared.prompt}</pre>},...prepared.materials.map(m=>({key:String(m.file_id),label:`PDF选页文字：${m.source.filename}`,children:<pre className="research-scroll-text">{m.pages.map(p=>p.text).join('\n')}</pre>}))]}/>
          <Paragraph type="secondary" style={{marginTop:12}}>AI接收方：{prepared.model?`${prepared.model.name} · ${prepared.model.model_name} · ${prepared.model.destination}`:'尚未配置默认文本模型'}</Paragraph>
          <Paragraph type="secondary">{prepared.external_scope}</Paragraph>
          <Checkbox checked={consent} disabled={!!busy||!prepared.model?.configured} onChange={e=>setConsent(e.target.checked)}>我已检查上述内容，同意发送给显示的AI服务生成待审核文案</Checkbox>
          {!prepared.model?.configured&&<Paragraph><Link to="/models">前往模型配置</Link></Paragraph>}
          <Space wrap style={{marginTop:16}}><Button type="primary" disabled={!!busy||!consent||!prepared.model?.configured} loading={busy==='generate-ai'} onClick={()=>void generate('ai')}>AI生成待审核草稿</Button><Button disabled={!!busy} loading={busy==='generate-outline'} onClick={()=>void generate('outline')}>保存本地写作提纲</Button></Space>
        </Card>}
        <Card title="本次研究的草稿" extra={workspace?<Button size="small" icon={<ReloadOutlined/>} disabled={!!busy} onClick={()=>void act('reload',async guard=>updateWorkspace(await fetchResearch(workspace.id),guard))}>刷新</Button>:null}>
          {!workspace?.drafts.length?<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="生成后保留在待审核区，审核保存后再进入草稿工坊。"/>:workspace.drafts.map(d=><button className="research-draft-choice" key={d.id} disabled={!!busy} onClick={()=>openDraft(d)}><span>{d.title}</span><Tag color={d.status==='saved'?'green':d.status==='failed'?'orange':'blue'}>{draftStatus[d.status]??d.status}</Tag><small>{d.mode==='ai'?'AI文案':'本地提纲'} · {stamp(d.created_at)}</small></button>)}
        </Card>
      </div>
    </div>
    <Drawer width={760} title="参考内容与表达拆解" open={!!sourceDetail} onClose={()=>setSourceDetail(null)}>
      {detail&&<><Title level={4}>{detail.title}</Title><Space wrap><Original source={detail}/><Tag>{status(detail)}</Tag><Text type="secondary">{stamp(detail.observed_at)}</Text></Space>
      <div style={{marginTop:12}}><Button disabled={!!busy} onClick={()=>void act('review-source',async guard=>{if(workspace)updateWorkspace(await researchAction<ResearchWorkspace>(`/${workspace.id}/sources/${detail.id}`,{excluded:!detail.excluded},'patch'),guard);})}>{detail.excluded?'恢复为可选参考':'与本课无关，排除参考'}</Button><Text type="secondary"> 原文与历史记录保留</Text></div>
      {pattern&&<Card size="small" title="可参考的表达方式" style={{margin:'16px 0'}}>{pattern.title_methods.map(t=><Paragraph key={t}>{t}</Paragraph>)}{pattern.opening&&<Paragraph>开头摘录：{pattern.opening}</Paragraph>}<Paragraph>{pattern.structure}</Paragraph><Text type="secondary">{pattern.visual}</Text></Card>}
      {detail.source_kind==='xhs'&&<Button disabled={!!busy||!accountId} loading={busy==='read-'+detail.id} onClick={()=>void readSource(detail)}>读取正文与评论</Button>}
      {detail.detail_error&&<Alert style={{marginTop:12}} type="warning" message={detail.detail_error}/>}{detail.comments_error&&<Alert style={{marginTop:12}} type="warning" message={detail.comments_error}/>}
      <Title level={5}>{detail.content_status==='detail'?'笔记正文':'可见摘要 / 手动摘录'}</Title><Paragraph style={{whiteSpace:'pre-wrap'}}>{detail.content||'尚未取得正文，暂不能分析完整结构。'}</Paragraph>
      <Title level={5}>已取得的评论（{detail.comments.length}）</Title><Paragraph type="secondary">本次读取当前评论页，最多保留50条，不代表全部评论。</Paragraph>{detail.comments.length?detail.comments.map(c=><Card key={c.comment_id} size="small" style={{marginBottom:8}}><Paragraph style={{margin:0}}>{c.content}</Paragraph>{c.manually_entered&&<Tag>手动摘录 · 待核对</Tag>}</Card>):<Text type="secondary">当前没有取得评论；没有评论不代表没有学生需求。</Text>}</>}
    </Drawer>
    <Modal open={importOpen} title="添加已有原文与摘录" onCancel={()=>setImportOpen(false)} onOk={()=>void importSource()} confirmLoading={busy==='import'} okText="保存参考" destroyOnHidden>
      <Form form={importForm} layout="vertical" initialValues={{source_kind:'xhs',content:'',question:''}}><Form.Item label="来源类型" name="source_kind"><Select options={[{value:'xhs',label:'小红书笔记'},{value:'web',label:'公开网页'}]}/></Form.Item><Form.Item label="原文链接" name="source_url" rules={[{required:true}]}><Input maxLength={2000} placeholder="保留可核对的原文来源"/></Form.Item><Form.Item label="标题" name="title" rules={[{required:true}]}><Input maxLength={500}/></Form.Item><Form.Item label="你实际读到的内容摘录" name="content"><Input.TextArea rows={4} maxLength={6000}/></Form.Item><Form.Item label="评论中的具体问题（可选）" name="question"><Input.TextArea rows={2} maxLength={1200}/></Form.Item></Form><Text type="secondary">手动摘录会保留标记，不会被当成已由系统读取的完整正文。</Text>
    </Modal>
    <Drawer open={!!draft} width={850} title="课程研究文案 · 先审核" onClose={()=>{setDraft(null);setDraftRecovery(null);}}>
      {draft&&<><Space wrap><Tag color={draft.status==='saved'?'green':draft.status==='failed'?'orange':'blue'}>{draftStatus[draft.status]??draft.status}</Tag><Tag>{draft.mode==='ai'?'AI生成':'本地提纲'}</Tag><Text type="secondary">参考来源与提示词已随本稿保存</Text></Space>
      {draftRecovery&&<Alert type="warning" showIcon style={{marginTop:12}} message="服务器稿件已变化，上次本机改稿已保留，未覆盖当前内容" description={<><Collapse items={[{key:'local-copy',label:'查看保留的本机文字',children:<><Paragraph style={{whiteSpace:'pre-wrap'}}>{draftRecovery.value.title}</Paragraph><Paragraph style={{whiteSpace:'pre-wrap'}}>{draftRecovery.value.body}</Paragraph><Paragraph>{draftRecovery.value.tags.join(' / ')}</Paragraph></>} ]}/><Space style={{marginTop:8}} wrap>{draft.status==='pending'&&<Button disabled={!!busy} onClick={()=>{setDraftTitle(draftRecovery.value.title);setDraftBody(draftRecovery.value.body);setDraftTags(draftRecovery.value.tags);setDraftRecovery(null);setReviewed(false);setDraftNotice('已恢复为待保存编辑，请与当前资料核对后手动保存。');}}>恢复本机文字，重新核对</Button>}<Button disabled={!!busy} onClick={()=>{if(removeCourseEditBuffer(draftScope(draft)))setDraftRecovery(null);else setBufferIssue('本机缓冲无法清除，已保留，请勿关闭仍需保留的文字。');}}>放弃这份本机缓冲</Button></Space></>}/>}
      <label className="research-label research-spaced" htmlFor="research-draft-title">标题（{titleLength}/20）</label><Input id="research-draft-title" value={draftTitle} status={titleIssue?'error':undefined} aria-invalid={!!titleIssue} aria-describedby={titleIssue?'research-title-help':undefined} disabled={!!busy||!!draftRecovery||draft.status!=='pending'} onChange={e=>setDraftTitle(e.target.value)} maxLength={256}/>
      {titleIssue&&<Paragraph id="research-title-help" type="danger" style={{margin:'6px 0 0'}}>{titleIssue}</Paragraph>}
      <label className="research-label research-spaced" htmlFor="research-draft-body">正文（{bodyLength}/1000）</label><Input.TextArea id="research-draft-body" value={draftBody} status={bodyIssue?'error':undefined} aria-invalid={!!bodyIssue} aria-describedby={bodyIssue?'research-body-help':undefined} disabled={!!busy||!!draftRecovery||draft.status!=='pending'} onChange={e=>setDraftBody(e.target.value)} autoSize={{minRows:12,maxRows:24}} maxLength={6000}/>
      {bodyIssue&&<Paragraph id="research-body-help" type="danger" style={{margin:'6px 0 0'}}>{bodyIssue}</Paragraph>}
      <label className="research-label research-spaced">标签</label><Select aria-label="课程研究草稿标签" mode="tags" value={draftTags} disabled={!!busy||!!draftRecovery||draft.status!=='pending'} maxCount={10} style={{width:'100%'}} onChange={setDraftTags}/>
      <Collapse style={{margin:'18px 0'}} items={[{key:'sources',label:'本稿使用的参考来源',children:draft.brief.sources.map(s=><Paragraph key={s.id}><Original source={s}/> {s.title} · {status(s)}</Paragraph>)},{key:'prompt',label:'本稿写作提示词',children:<pre className="research-scroll-text">{draft.prompt}</pre>}]}/>
      {typeof draft.brief.image_suggestions==='string'&&<Card size="small" title="配图建议" style={{marginBottom:16}}><Paragraph style={{whiteSpace:'pre-wrap',margin:0}}>{draft.brief.image_suggestions}</Paragraph></Card>}
      {typeof draft.brief.fact_checks==='string'&&<Alert type="warning" showIcon style={{marginBottom:16}} message="待核实事项" description={<span style={{whiteSpace:'pre-wrap'}}>{draft.brief.fact_checks}</span>}/>}
      {draft.status==='saved'?<Alert type="success" message={<span>研究文案已保存。{draft.draft_available!==false&&draft.draft_id?<Link to={`/platforms/xhs/drafts?draft_id=${draft.draft_id}`}>打开草稿 #{draft.draft_id}</Link>:'原草稿关联暂不可用，原文案仍保留。'}</span>} description="这一步保存文案；继续使用下方“核对文案与资料，去图文制作”制作封面与内页。返回题库后可从“我的课程创作”找回。"/>:draft.status!=='pending'?<Alert type="warning" message="该请求正在处理或上次未完成。关闭后刷新研究记录；需要重试时重新整理提示词与生成范围。"/>:<>
        {(titleIssue||bodyIssue)&&<Alert type="warning" showIcon style={{marginBottom:12}} message="保存到草稿工坊前需要调整" description={<Space direction="vertical" size={4}>{titleIssue&&<span>{titleIssue}<Button type="link" size="small" onClick={()=>focusDraftField('title')}>去修改标题</Button></span>}{bodyIssue&&<span>{bodyIssue}<Button type="link" size="small" onClick={()=>focusDraftField('body')}>去修改正文</Button></span>}<Text type="secondary">超长内容仍可保存为待审核研究稿；原文不会被自动截断。</Text></Space>}/>}
        {draftError&&<Alert type="error" showIcon role="alert" message={draftError} style={{marginBottom:12}}/>}
        {draftNotice&&<Alert type="success" showIcon role="status" message={draftNotice} style={{marginBottom:12}}/>}
        <Paragraph type="secondary">{dirty?'有未保存的修改，请先保存，再勾选审核确认。':reviewed?'已勾选当前版本的审核确认。':'当前内容已保存；核对后勾选下方审核确认。'}</Paragraph>
        <Button disabled={!!busy||!!draftRecovery} loading={busy==='save'} onClick={()=>void saveDraft()}>保存修改，保持待审核</Button><div style={{margin:'18px 0'}}><Checkbox checked={reviewed} disabled={!!busy||dirty||!!draftRecovery} onChange={e=>setReviewed(e.target.checked)}>我已核对文案、来源、课程与资料事实，并确认保存当前版本</Checkbox></div><Button icon={<CheckOutlined/>} disabled={!!busy||!!draftRecovery} loading={busy==='approve'} onClick={()=>void approve()}>仅保存文字到草稿工坊</Button>
      </>}
      {['pending','saved'].includes(draft.status)&&<Card size="small" style={{marginTop:18}} title="下一步 · 制作这篇图文">
        <Paragraph>确认这篇文案、参考来源和 PDF 后，直接进入图片规划与整套制作；封面和内页生成后一起审核，不再分别确认封面。</Paragraph>
        {draft.status==='saved'&&draftError&&<Alert type="error" showIcon message={draftError} style={{marginBottom:12}}/>}
        <Button type="primary" icon={<FileSearchOutlined/>} disabled={!!busy||!!draftRecovery} onClick={startHandoff}>核对文案与资料，去图文制作</Button>
        <Paragraph type="secondary" style={{margin:'10px 0 0'}}>保留原研究稿和已保存草稿；此步骤不重新搜索、不重写文案、不调用 AI，也不创建发布任务。</Paragraph>
      </Card>}
      </>}
    </Drawer>
    <Modal open={handoffOpen} title="核对后进入图文制作" width={880} centered styles={{body:{maxHeight:'60vh',overflowY:'auto'}}} onCancel={()=>{if(!busy)setHandoffOpen(false);}} destroyOnHidden footer={<div style={{textAlign:'left'}}>
      <Checkbox checked={handoffReviewed} disabled={!handoffPlan||!!busy} onChange={e=>setHandoffReviewed(e.target.checked)}>我已核对本篇文案、参考来源和 PDF 版本。{handoffPlan?.evidence_review.limited?'我已了解目前只有摘要，不把它当作已验证的学生反馈或热榜依据。':''}</Checkbox>
      <Space wrap style={{display:'flex',justifyContent:'flex-end',marginTop:12}}><Button disabled={!!busy} onClick={()=>setHandoffOpen(false)}>返回文案</Button><Button type="primary" disabled={!handoffPlan||!handoffReviewed||!!busy} loading={busy==='handoff'} onClick={()=>void confirmHandoff()}>确认并进入图文制作</Button></Space>
    </div>}>
      <Paragraph>选定 PDF 后自动读取当前版本。在这里完成文案与资料核对，再进入图片规划与整套制作，最后统一审核成品。</Paragraph>
      <Select aria-label="图文制作使用的PDF" style={{width:'100%'}} placeholder="请选择一份明确的课程资料" value={handoffFileId} disabled={!!busy} options={localMaterials.map(m=>({value:m.id,label:`${m.material_type} · ${m.filename}`}))} onChange={id=>{setHandoffPlan(null);setHandoffReviewed(false);setHandoffError('');setHandoffFileId(id);}}/>
      <Space wrap style={{margin:'12px 0'}}><Button disabled={!handoffFileId||!!busy} loading={busy==='handoff-plan'} onClick={()=>void prepareHandoff()}>{handoffError?'重试读取当前版本':'刷新文案与资料版本'}</Button>{handoffFileId&&<Button disabled={!!busy} onClick={()=>setHandoffTab('pdf')}>查看原 PDF</Button>}</Space>
      {handoffError&&<Alert type="error" showIcon message={handoffError} style={{marginBottom:12}}/>}
      <Tabs activeKey={handoffTab} onChange={setHandoffTab} destroyOnHidden items={[{key:'review',label:'文案与来源核对',children:handoffPlan?<>
        <Alert type={handoffPlan.evidence_review.limited?'warning':'info'} showIcon message={handoffPlan.evidence_review.message} style={{marginBottom:12}}/>
        {(handoffPlan.changed_since_draft.material||!!handoffPlan.changed_since_draft.sources.length)&&<Alert type="warning" showIcon style={{marginBottom:12}} message="来源或资料与生成研究稿时不同，请重新核对" description={`${handoffPlan.changed_since_draft.material?'本次选择了不同的PDF或新资料版本。':''}${handoffPlan.changed_since_draft.sources.length?'部分参考来源已更新；下方显示本次实际承接的内容。':''}`}/>}
        <Card size="small" title={`${handoffPlan.brand.name} · ${handoffPlan.source.university} · ${handoffPlan.source.course_code}`}>
          <Paragraph>{handoffPlan.source.filename} · PDF 版本 #{handoffPlan.source.revision_id}</Paragraph>
          <Title level={5}>{handoffPlan.copy.title}</Title><Paragraph style={{whiteSpace:'pre-wrap',maxHeight:300,overflowY:'auto'}}>{handoffPlan.copy.body}</Paragraph><Text>{handoffPlan.copy.tags.join(' / ')}</Text>
        </Card>
        <Collapse style={{margin:'12px 0'}} items={[{key:'handoff-sources',label:`查看 ${handoffPlan.evidence.length} 个参考来源与读取状态`,children:handoffPlan.evidence.map(s=><div key={s.id}><Paragraph><Original source={s}/> {s.title} <Tag>{status(s)}</Tag></Paragraph><Paragraph style={{whiteSpace:'pre-wrap'}}>{s.content||'尚未读取正文。'}</Paragraph>{s.comments.length?s.comments.map(c=><Paragraph key={c.comment_id} type="secondary">评论：{c.content}</Paragraph>):<Paragraph type="secondary">未读取到评论。</Paragraph>}</div>)},{key:'handoff-version',label:'资料版本详情',children:<Text copyable>{handoffPlan.source.sha256}</Text>}]}/>
      </>:busy==='handoff-plan'?<Space><Spin/><Text>正在读取文案、来源和 PDF 版本…</Text></Space>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={handoffError?'读取未完成，请查看上方提示并重试。':'请选择这篇图文使用的 PDF。'}/>},
      {key:'pdf',label:'原 PDF · 可翻页',children:handoffMaterial?<CoursePdfInlinePreview fileId={handoffMaterial.id} revisionId={handoffPlan?.source.revision_id??handoffMaterial.revision_id} filename={handoffMaterial.filename}/>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请先选择一份 PDF。"/>}]}/>
    </Modal>
  </div>;
}
