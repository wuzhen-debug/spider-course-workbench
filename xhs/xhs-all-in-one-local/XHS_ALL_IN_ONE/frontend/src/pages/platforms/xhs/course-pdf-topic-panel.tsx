import { FilePdfOutlined, ReloadOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Collapse, Empty, Input, Select, Space, Spin, Tag, Typography } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../../../hooks/use-auth';
import { fetchResearchContext, visualWorkflowAction, visualWorkflowGet } from '../../../lib/api';
import { positiveRouteId } from '../../../lib/course-creations';
import { readCourseEditBuffer, writeCourseEditBuffer } from '../../../lib/course-edit-buffer';
import { generatePdfTopics, pdfTopicHistory, requirePdfTopicRun, type PdfTopicHistory, type PdfTopicPreview, type PdfTopicRun } from '../../../lib/course-topic-research';
import type { ResearchMaterial } from '../../../lib/course-research-types';
import { PdfAnalysisReview } from '../../../components/course-pdf-analysis';
import { CourseBrandSelect } from '../../../components/course-brand-select';

const {Title,Text,Paragraph}=Typography;
function errorText(error:unknown){const detail=(error as {response?:{data?:{detail?:unknown}}})?.response?.data?.detail;return typeof detail==='string'?detail:error instanceof Error?error.message:'读取未完成，请刷新后重试。';}

export function CoursePdfTopicPanel({directory,onOpenPdf}:{directory:string;onOpenPdf:(id:number)=>void}){
 const {user}=useAuth();const [params,setParams]=useSearchParams();const navigate=useNavigate();
 const [materials,setMaterials]=useState<ResearchMaterial[]>([]);const [context,setContext]=useState({university:'',course_code:''});
 const [loading,setLoading]=useState(true);const [reload,setReload]=useState(0);const [error,setError]=useState('');const [notice,setNotice]=useState('');
 const requestedFile=positiveRouteId(params.get('file_id'));const requestedRun=positiveRouteId(params.get('pdf_run'));
 const fileId=requestedFile??materials.find(m=>m.material_type==='期末复习讲义')?.id??materials[0]?.id;
 const material=materials.find(m=>m.id===fileId);
 const [run,setRun]=useState<PdfTopicRun|null>(null);const runRef=useRef<PdfTopicRun|null>(null);
 const [history,setHistory]=useState<PdfTopicHistory[]>([]);const [topic,setTopic]=useState('');const [formReady,setFormReady]=useState('');
 const [brandId,setBrandId]=useState('');
 const [preview,setPreview]=useState<PdfTopicPreview|null>(null);const [preparing,setPreparing]=useState(false);const [planError,setPlanError]=useState('');const [prepareRetry,setPrepareRetry]=useState(0);
 const [busy,setBusy]=useState(false);const busyRef=useRef(false);const [unresolved,setUnresolved]=useState(false);
 const scope=JSON.stringify([user?.id,directory,fileId,material?.revision_id]);const liveScope=useRef(scope);liveScope.current=scope;
 const alive=useRef(true);const paramsRef=useRef(params);paramsRef.current=params;
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
 useEffect(()=>{
  if(user?.id===undefined)return;let active=true;setLoading(true);setError('');
  void fetchResearchContext(directory).then(result=>{if(active){setContext(result.context);setMaterials(result.materials);}}).catch(e=>{if(active)setError(errorText(e));}).finally(()=>{if(active)setLoading(false);});
  return()=>{active=false;};
 },[directory,user?.id,reload]);
 function formScope(){return {userId:user!.id,feature:'pdf-topic-form',recordId:String(fileId),context:String(material?.revision_id)};}
 useEffect(()=>{
  if(!material||user?.id===undefined)return;
  const saved=readCourseEditBuffer<{topic:string}>(formScope());setTopic(typeof saved?.value.topic==='string'?saved.value.topic:'');setBrandId('');setFormReady(scope);setUnresolved(false);setNotice('');
 },[scope]);
 useEffect(()=>{if(material&&user?.id!==undefined&&formReady===scope)writeCourseEditBuffer(formScope(),{topic});},[scope,formReady,topic]);
 function remember(next:PdfTopicRun){
  if(!alive.current||next.file_id!==fileId)return;
  if(runRef.current?.id===next.id&&runRef.current.row_version>next.row_version)return;
  runRef.current=next;setRun(next);
 }
 function runParams(id:number){const next=new URLSearchParams(paramsRef.current);next.set('research_lane','pdf');next.set('file_id',String(fileId));next.set('pdf_run',String(id));return next;}
 useEffect(()=>{
  if(!material)return;let active=true;const captured=scope;
  if(runRef.current?.id===requestedRun&&runRef.current.file_id===fileId)return;
  runRef.current=null;setRun(null);setHistory([]);
  void (async()=>{
   const response=await visualWorkflowGet<{items:PdfTopicHistory[]}>('',{file_id:fileId});
   if(!active||liveScope.current!==captured)return;
   const rows=pdfTopicHistory(response.items,fileId!,material.revision_id);setHistory(rows);
   const id=requestedRun??rows[0]?.id;if(!id)return;
   const saved=await visualWorkflowGet<PdfTopicRun>(`/${id}`);if(!active||liveScope.current!==captured)return;
   requirePdfTopicRun(saved,fileId!,material.revision_id);remember(saved);
  })().catch(e=>{if(active&&liveScope.current===captured)setError(errorText(e));});
  return()=>{active=false;};
 },[scope,requestedRun]);
 useEffect(()=>{
  let active=true;setPreview(null);setPlanError('');
  if(!material||formReady!==scope||!brandId){setPreparing(false);return;}
  setPreparing(true);const captured=scope;
  const timer=setTimeout(()=>{
   void visualWorkflowAction<PdfTopicPreview>('/pdf-topic-plan',{file_id:fileId,revision_id:material.revision_id,brand_id:brandId,topic:topic.trim(),goal:'student-question'})
    .then(value=>{if(active&&liveScope.current===captured)setPreview(value);})
    .catch(e=>{if(active&&liveScope.current===captured)setPlanError(errorText(e));}).finally(()=>{if(active&&liveScope.current===captured)setPreparing(false);});
  },350);
  return()=>{active=false;clearTimeout(timer);};
 },[scope,formReady,topic,brandId,prepareRetry]);
 async function refreshRun(){
  if(!run||busyRef.current)return;const captured=scope;
  try{const next=await visualWorkflowGet<PdfTopicRun>(`/${run.id}`);if(alive.current&&liveScope.current===captured){requirePdfTopicRun(next,fileId!,material!.revision_id);remember(next);setUnresolved(false);setError('');}}
  catch(e){if(alive.current&&liveScope.current===captured)setError(errorText(e));}
 }
 async function generate(){
  if(!preview||!material||busyRef.current||preparing||unresolved||run?.data.operation?.status==='generating')return;
  const captured=scope;let attemptId:number|undefined;busyRef.current=true;setBusy(true);setError('');setNotice('');
  const guard=()=>{if(!alive.current||liveScope.current!==captured)throw new Error('页面已切换；结果保留在原PDF的工作记录中。');};
  try{
   const result=await generatePdfTopics({fileId:material.id,revisionId:material.revision_id,brandId,topic:topic.trim(),goal:'student-question',createKey:crypto.randomUUID(),requestKey:crypto.randomUUID(),preview},{
    create:payload=>visualWorkflowAction<PdfTopicRun>('',payload),
    patch:(row,payload)=>visualWorkflowAction<PdfTopicRun>(`/${row.id}`,payload,'patch'),
    prepare:row=>visualWorkflowAction(`/${row.id}/pdf-analysis-plan`,{expected_version:row.row_version}),
    generate:(row,payload)=>visualWorkflowAction<PdfTopicRun>(`/${row.id}/generate-from-pdf`,payload),
   },guard,next=>{attemptId=next.id;remember(next);});
   guard();setTopic(result.data.copy.topic);setNotice('PDF选题与文案已另存为待审工作记录，原稿保留。');
   const rows=await visualWorkflowGet<{items:PdfTopicHistory[]}>('',{file_id:material.id});guard();setHistory(pdfTopicHistory(rows.items,material.id,material.revision_id));setParams(runParams(result.id),{replace:true});
  }catch(e){
   if(!alive.current||liveScope.current!==captured)return;
   if(attemptId)try{const latest=await visualWorkflowGet<PdfTopicRun>(`/${attemptId}`);guard();remember(latest);setParams(runParams(latest.id),{replace:true});if(latest.data.operation?.status==='completed'&&latest.data.pdf_analysis){setTopic(latest.data.copy.topic);setNotice('已找回完成的PDF研究，没有重复调用模型。');return;}if(latest.data.operation?.status==='generating')setUnresolved(true);}catch{setUnresolved(true);}
   setError(errorText(e));setPrepareRetry(v=>v+1);
  }finally{if(alive.current&&liveScope.current===captured){busyRef.current=false;setBusy(false);}}
 }
 const current=run&&run.file_id===fileId&&run.data.source.revision_id===material?.revision_id?run:null;
 const analysis=current?.data.pdf_analysis;const model=preview?.model;
 const changedTopic=!!current&&!!topic.trim()&&topic.trim()!==current.data.copy.topic.trim();
 if(loading)return <Card><Spin/> 正在读取PDF选题入口…</Card>;
 return <section className="course-pdf-topics" aria-label="PDF选题研究">
  <Card size="small" className="pdf-topic-source" title={<Space><FilePdfOutlined/>根据PDF选题 <Tag color="blue">{context.university} · {context.course_code}</Tag></Space>}>
   {error&&<Alert type="error" showIcon message={error} closable onClose={()=>setError('')} style={{marginBottom:12}}/>}
   {notice&&<Alert type="success" message={notice} style={{marginBottom:12}}/>}
   <div className="pdf-topic-controls">
    <Select aria-label="PDF选题使用的讲义" placeholder="选择一份课程PDF" value={material?.id} disabled={busy} showSearch optionFilterProp="label" options={materials.map(m=>({value:m.id,label:`${m.material_type} · ${m.filename}`}))} onChange={id=>{const next=new URLSearchParams(paramsRef.current);next.set('file_id',String(id));next.set('research_lane','pdf');next.delete('pdf_run');setParams(next);}}/>
    <Button disabled={!material||busy} onClick={()=>material&&onOpenPdf(material.id)}>查看PDF</Button>
   </div>
   {!material?<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={requestedFile?'当前课程找不到指定PDF，请重新选择。':'请先进入一门课程并选择PDF。'}/>:<>
    <div style={{marginTop:12,maxWidth:320}}><CourseBrandSelect value={brandId} onChange={setBrandId} disabled={busy} label="本次新创作的品牌"/></div>
    <Input aria-label="PDF选题重点" value={topic} maxLength={240} disabled={busy} onChange={e=>setTopic(e.target.value)} placeholder="可选：限定一个知识点；留空则由讲义推荐选题" style={{marginTop:12}}/>
    <Space wrap style={{marginTop:12}}>
     <Button className="pdf-topic-generate" type="primary" loading={busy} disabled={!model?.configured||preparing||busy||unresolved||current?.data.operation?.status==='generating'} onClick={()=>void generate()}>{model?`用${model.model_name}生成PDF选题与文案`:'生成PDF选题与文案'}</Button>
     <Button icon={<ReloadOutlined/>} disabled={busy} onClick={()=>{setPrepareRetry(v=>v+1);setReload(v=>v+1);}}>刷新资料</Button>
     {current&&<Button disabled={busy} onClick={()=>void refreshRun()}>读取上次结果</Button>}
    </Space>
    {preparing?<Paragraph type="secondary" className="pdf-topic-scope">正在本机读取讲义文字…</Paragraph>:preview&&<Paragraph type="secondary" className="pdf-topic-scope">{model?.destination} · 本次发送{preview.coverage.excerpt_pages.length}页文字摘录；PDF、图片与Logo留在本机。</Paragraph>}
    {planError&&<Alert type="warning" message={planError} action={<Button size="small" onClick={()=>{setPrepareRetry(v=>v+1);setReload(v=>v+1);}}>重新读取</Button>} style={{marginTop:12}}/>}
    {preview&&<Collapse size="small" items={[{key:'scope',label:'查看讲义摘录与生成范围',children:<><Paragraph>{preview.scope}</Paragraph>{preview.material.pages.map(p=><div key={p.page}><Text strong>讲义第{p.page}页</Text><pre className="research-scroll-text">{p.text}</pre></div>)}</>}]} style={{marginTop:12}}/>}
   </>}
  </Card>
  {current?.data.operation?.status==='generating'&&<Alert type="info" showIcon message="PDF研究正在处理中，读取上次结果即可查看进度，不会自动重复生成。" style={{margin:'12px 0'}}/>}
  {analysis?<div className="pdf-topic-results">
   <Card title="根据讲义推荐的选题" size="small">
    {analysis.topic_candidates.map(candidate=><article className="pdf-topic-option" key={candidate.id}>
     <Space wrap><Text strong>{candidate.topic}</Text>{candidate.id===analysis.recommended_topic_id&&<Tag color="blue">推荐</Tag>}</Space>
     <Paragraph>{candidate.reader_takeaway}</Paragraph><Text type="secondary">讲义依据：第{candidate.pdf_pages.join('、')}页</Text>
     <Button size="small" disabled={busy} onClick={()=>setTopic(candidate.topic)}>选用这个方向</Button>
    </article>)}
    <PdfAnalysisReview analysis={analysis} disabled={busy} onTopic={candidate=>setTopic(candidate.topic)} showCandidates={false}/>
   </Card>
   <Card title="待审核文案" size="small" extra={<Space><Tag>{current.data.brand.name}</Tag><Tag color="gold">待审核</Tag></Space>}>
    <Title level={4}>{current.data.copy.title}</Title><Paragraph style={{whiteSpace:'pre-wrap'}}>{current.data.copy.body}</Paragraph><Space wrap>{current.data.copy.tags.map(tag=><Tag key={tag}>#{tag}</Tag>)}</Space>
    {changedTopic&&<Alert type="info" message="已选择新方向；当前文案尚未重写。点击上方生成，将另存新版本。" style={{marginTop:12}}/>}
    <Button type="primary" disabled={busy||changedTopic} style={{marginTop:16}} onClick={()=>navigate(`/platforms/xhs/visual-workbench?run=${current.id}&file_id=${current.file_id}&stage=copy`)}>审核文案，继续制作图文</Button>
   </Card>
  </div>:<Card size="small" className="pdf-topic-empty"><Text type="secondary">生成后在这里选择话题、查看讲义依据和文案，再进入审核与制图。</Text></Card>}
  {!!history.length&&<Collapse size="small" items={[{key:'history',label:`PDF选题记录（${history.length}）`,children:<Select aria-label="打开PDF选题记录" value={current?.id} style={{width:'100%'}} options={history.map(h=>({value:h.id,label:`#${h.id} · ${h.title}`}))} onChange={id=>setParams(runParams(id))}/>}]}/>}
 </section>;
}
