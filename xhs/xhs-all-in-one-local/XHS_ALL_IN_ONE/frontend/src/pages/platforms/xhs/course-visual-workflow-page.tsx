import {useEffect,useRef,useState} from 'react';
import { CourseBrandSelect } from '../../../components/course-brand-select';
import {Link,useSearchParams} from 'react-router-dom';
import {Alert,Button,Card,Checkbox,Collapse,Drawer,Empty,Image,Input,Modal,Select,Space,Spin,Steps,Tag,Tooltip,Typography} from 'antd';
import {CheckCircleOutlined,EditOutlined,FileImageOutlined,PlusOutlined,ReloadOutlined,SaveOutlined} from '@ant-design/icons';
import {fetchAccounts,visualWorkflowGet as rawWorkflowGet,visualWorkflowAction as rawWorkflowAction,visualWorkflowImage,visualWorkflowTemplatePreview} from '../../../lib/api';
import type {PlatformAccount} from '../../../types';
import type {EvidenceReview} from '../../../lib/course-research-types';
import {useAuth} from '../../../hooks/use-auth';
import {readCourseEditBuffer,writeCourseEditBuffer,removeCourseEditBuffer,type CourseEditBuffer} from '../../../lib/course-edit-buffer';
import {inCourseContext,initialCourseRun,CourseContextChanged} from '../../../lib/course-visual-context';
import {sameVisualEdit} from '../../../lib/course-visual-edits';
import {nextVisualStage,visualStageIndex,visualStageParams} from '../../../lib/course-visual-navigation';
import {coverSamplePage,coverSampleIssue} from '../../../lib/course-cover-sample';
import {CoursePdfInlinePreview} from '../../../components/course-pdf-inline-preview';
import {CoursePdfPagesPanel} from '../../../components/course-pdf-pages-panel';
import {defaultPdfPagePlan,pdfPageText,pdfPageIssue,parsePdfPageText,type PdfPagePlan} from '../../../lib/course-pdf-pages';
import {entryMode,pdfVisualStale,type EntryMode,type PdfAnalysis,type PdfAnalysisPrompt,type VisualCandidate} from '../../../lib/course-pdf-lane';
import {CourseEntryChoices,PdfAnalysisReview,PdfAnalysisConsent} from '../../../components/course-pdf-analysis';
import {ApiImageConsent,type ApiImagePlan} from '../../../components/course-api-image-panel';
import {productionReadiness,type ProductionMode,type ProductionIntent} from '../../../lib/course-visual-production';
import './course-visual-workflow.css';

const {Title,Text,Paragraph}=Typography;
type CopyGoal='student-question'|'method-save'|'sample-trial';
type TemplateId='legacy'|'question-led'|'decision-map'|'sample-led'|'magazine-a';
type Density='compact'|'standard';
type Copy={topic:string;title:string;body:string;tags:string[];takeaway:string;goal?:CopyGoal};
type Brief={title:string;subtitle:string;text:string;layout:string;nodes:string[]};
type Plan={cover_lines:string[];cover_subtitle?:string;method_title:string;method_text:string;sample_pages:number[];sample_instructions:string[];cover_sample_page?:number|null;usage_steps:string[];cta:string;style:string;method_layout:string;method_nodes:string[];template_id?:TemplateId;density?:Density};
type Explanation={title:string;subtitle:string;text:string;layout:'editorial'|'flow'|'comparison';nodes:string[]};
type SetPlan={sample_pages:number[];sample_instructions:string[];extra_explanations:Explanation[]};
type Asset={id:string;slot:string;kind:string;role:string;brief:Brief;source_page?:number;source_pages?:number[];sha256:string;svg_file?:string;api_generated?:{model:{name:string;model_name:string};local_header_logo:boolean};background?:{style:string;strength:string;ai_generated:boolean;model:{model_name:string}}};
type BackgroundOptions={slot:string;style:string;strength:string};
type BackgroundPrompt=BackgroundOptions&{prompt:string;scope:string;plan_digest:string;supported:boolean;estimated_cost:string;model:{name:string;model_name:string;destination:string;configured:boolean}|null};
type BackgroundRequest={status:string;signature:string;slot:string;input_digest:string;at?:string;consent_digest?:string;options?:BackgroundOptions;asset?:{request_key:string;style:string;strength:string}};
type Evidence={id:string;title:string;source_url:string;content:string;content_status:string;evidence_type?:string;pdf_pages?:number[];published_at?:string;observed_at?:string;metrics?:{likes:number|null;collects:number|null;comments:number|null};comments:{comment_id:string;content:string;is_author?:boolean}[]};
type Direction={style_report:Record<string,string>;master:string;page_count_reason:string;pages:{slot:string;title:string;task:string;layout:string;prompt:string;negative_prompt:string}[]};
type ResearchHandoff={research_id:number;research_draft_id:number;source_draft_id:number|null;research_directory:string;reviewed_at:string};
type Quality={summary:string;checks:{id:string;label:string;status:'ready'|'attention'|'manual';detail:string}[]};
type Run={id:number;file_id:number;row_version:number;approved:Record<string,boolean>;digests:Record<string,string>;direction:Direction;quality?:Quality;data:{revision:number;entry_mode?:EntryMode;pdf_analysis?:PdfAnalysis;visual_candidate?:VisualCandidate;source:{university:string;course_code:string;filename:string;material_type:string;page_count:number;revision_id:number;relative_path:string;sha256:string};copy:Copy;visual_plan:Plan;set_plan?:SetPlan;pdf_page_plan?:PdfPagePlan;brand:{name:string};rules:{version:string;skills:{skill:string;file:string;sha256:string}[];text:string};evidence:Evidence[];evidence_review?:EvidenceReview;selected_source_ids:string[];research_id:number|null;research_handoff?:ResearchHandoff;cover:Asset|null;images:Asset[];display_treatment?:string;export:{draft_id:number;draft_available?:boolean}|null;history:{revision:number;reason:string;at:string;images:Asset[];cover:Asset|null;export:{draft_id:number;draft_available?:boolean}|null}[];render_bundle?:{status:string;digest:string};analysis?:{angles:{topic:string;basis:string}[]};operation?:{status:string;key?:string};background_requests?:Record<string,BackgroundRequest>}};
type Material={id:number;filename:string;course_code:string;university:string;revision_id:number};
type VisualTemplate={id:Exclude<TemplateId,'legacy'>;name:string;description:string;suitable_for:string;preview_available:boolean};
type GoalOption={id:CopyGoal;name:string;description:string};
type DensityOption={id:Density;name:string;description:string};
type Catalog={brand:{name:string};rules:string;version:string;materials:Material[];skills:{skill:string;file:string;sha256:string}[];templates?:VisualTemplate[];writing_goals?:GoalOption[];densities?:DensityOption[]};
type History={id:number;file_id:number;title:string;course_code:string;draft_id:number|null};
type EditorBuffer={copy:Copy;plan:Plan;selected:string[];pagesText:string;innerPlan?:SetPlan;innerPagesText?:string;pdfPagePlan?:PdfPagePlan|null;pdfPagesText?:string;collagePlan?:{groups:number[][]}|null;collagePagesText?:string[];editingId?:string;brief?:Brief};
type Prompt={purpose:'copy'|'visual';prompt:string;scope:string;plan_digest:string;model:{name:string;model_name:string;destination:string;configured:boolean}|null;visual_direction:Direction};
const cleanLines=(s:string)=>s.split('\n').map(t=>t.trim()).filter(Boolean);
const normalPlan=(p:Plan):Plan=>({...p,style:p.style||'product-editorial',method_layout:p.method_layout||'editorial',method_nodes:p.method_nodes||[],template_id:p.template_id||'legacy',density:p.density||'standard'});
const normalSetPlan=(value:SetPlan|undefined,plan:Plan):SetPlan=>({sample_pages:value?.sample_pages||plan.sample_pages,sample_instructions:value?.sample_instructions||plan.sample_instructions||[],extra_explanations:(value?.extra_explanations||[]).map(page=>({...page,subtitle:page.subtitle||'',text:page.text||'',layout:page.layout||'editorial',nodes:page.nodes||[]}))});
function innerPlanIssue(value:SetPlan,plan:Plan,pageCount:number,allowIncomplete=false){
 if(plan.template_id!=='magazine-a'&&(!value.sample_pages.length||value.sample_pages.length>4||new Set(value.sample_pages).size!==value.sample_pages.length||value.sample_pages.some(n=>!Number.isInteger(n)||n<1||n>pageCount)))return `请选择1至4张不重复的真实样页，页码范围1至${pageCount}。`;
 if(!allowIncomplete&&plan.template_id==='magazine-a'&&value.extra_explanations.length!==2)return 'A模板需要2张补充干货，加上封面和方法讲解共4张；请先规划或补齐本篇内容。';
 if(value.extra_explanations.length>3)return '补充讲解最多3张，请保留有实际内容的页面。';
 const limit=plan.template_id==='legacy'||plan.template_id==='magazine-a'||!plan.template_id?800:plan.density==='compact'?110:200;
 for(const [index,page] of value.extra_explanations.entries()){
  if(!allowIncomplete&&(!page.title.trim()||!page.text.trim()))return `补充讲解${index+1}尚未完成，请先规划图片内容，或在可选设置中补全。`;
  if(page.text.length>limit)return `补充讲解${index+1}正文为${page.text.length}字，当前标准最多${limit}字，请精简后保存。`;
  const nodeLimit=plan.template_id==='magazine-a'?5:3;if(page.nodes.length>nodeLimit)return `补充讲解${index+1}最多${nodeLimit}个节点，请保留关键判断。`;
 }
 return '';
}
const defaultTemplates:VisualTemplate[]=[
 {id:'magazine-a',name:'A 杂志讲解版（已确认）',description:'宽正文讲清学生问题，4张干货之后追加9张原样PDF预览。',suitable_for:'课程介绍、知识讲解、例题与资料使用方法',preview_available:false},
 {id:'question-led',name:'问题大标题',description:'放大一个具体卡点，用真实讲义承接问题。',suitable_for:'学生问题、条件混淆、具体学习情境',preview_available:false},
 {id:'decision-map',name:'判断方法图',description:'把选择条件与方法连起来，让读者学会判断。',suitable_for:'方法选择、解题路径、概念关系',preview_available:false},
 {id:'sample-led',name:'真实样张试读',description:'突出真实正文样张，用外部说明解释资料价值。',suitable_for:'资料试读、讲解方式、购买前判断',preview_available:false},
];
const defaultGoals:GoalOption[]=[{id:'student-question',name:'问题切入',description:'从具体学习情境开始，讲清卡在哪里以及下一步怎么做。'},{id:'method-save',name:'方法收藏',description:'给出可执行的判断方法和条件，让读者不购买也有收获。'},{id:'sample-trial',name:'资料试读',description:'用真实内容说明讲义怎样使用、适合谁，再自然承接了解动作。'}];
const defaultDensities:DensityOption[]=[{id:'compact',name:'简洁大字',description:'精简说明与节点，重点突出；内容过长时提示精简，不缩小字体硬塞。'},{id:'standard',name:'标准讲解',description:'保留必要说明和知识关系，真实样张保持完整。'}];
const errorText=(e:unknown)=>{const x=(e as {response?:{data?:{detail?:unknown}}}).response?.data?.detail;return typeof x==='string'?x:Array.isArray(x)?x.map(t=>t.msg).join('；'):'操作未完成，请检查本机服务后重试。';};

function Picture({run,asset,thumbnail=false}:{run:number;asset:Asset;thumbnail?:boolean}){
 const [url,setUrl]=useState('');const [detailUrl,setDetailUrl]=useState('');const [error,setError]=useState(false);
 useEffect(()=>{let live=true,object='',detail='';setUrl('');setDetailUrl('');setError(false);
  void visualWorkflowImage(run,asset.id).then(b=>{object=URL.createObjectURL(b);if(live)setUrl(object);else URL.revokeObjectURL(object);}).catch(()=>{if(live)setError(true);});
  if((asset.kind==='collage'||asset.kind==='pdf-page')&&!thumbnail)void visualWorkflowImage(run,asset.id,true).then(blob=>{detail=URL.createObjectURL(blob);if(live)setDetailUrl(detail);else URL.revokeObjectURL(detail);}).catch(()=>{/* The PNG preview remains usable if the editable source is unavailable. */});
  return()=>{live=false;if(object)URL.revokeObjectURL(object);if(detail)URL.revokeObjectURL(detail);};
 },[run,asset.id,asset.kind,thumbnail]);
 return error?<Alert type="error" message="图片未读取，刷新后重试"/>:url?<Image src={url} alt={asset.role} preview={thumbnail?false:asset.kind==='collage'||asset.kind==='pdf-page'?{src:detailUrl||url}:true} style={{width:'100%'}}/>:<Spin/>;
}

function TemplatePreview({template}:{template:VisualTemplate}){
 const [url,setUrl]=useState('');
 useEffect(()=>{let live=true,object='';setUrl('');if(template.preview_available)void visualWorkflowTemplatePreview(template.id).then(blob=>{object=URL.createObjectURL(blob);if(live)setUrl(object);else URL.revokeObjectURL(object);}).catch(()=>{});return()=>{live=false;if(object)URL.revokeObjectURL(object);};},[template.id,template.preview_available]);
 return <div className={`vd-template-art vd-template-art-${template.id}`} aria-label={`${template.name}版式预览`}>
  {url?<img src={url} alt={`${template.name}模板示例，当前资料需另行制作`}/>:<div className="vd-template-diagram" aria-label="版式示意，非本篇成品"><span className="vd-template-school">学校 · 课程代码</span><strong>{template.id==='magazine-a'?<>课程干货<br/><em>宽正文讲解</em></>:template.id==='question-led'?<>具体问题<br/><em>重点放大</em></>:template.id==='decision-map'?<>先看条件<br/><em>再选方法</em></>:<>真实样张<br/><em>看见内容</em></>}</strong><div className="vd-template-doc"><i/><i/><i/><i/><i/></div>{template.id==='decision-map'&&<div className="vd-template-nodes"><span>条件</span><b>↓</b><span>判断</span><b>↓</b><span>方法</span></div>}<small>真实品牌 Logo</small></div>}
  <span className="vd-template-preview-label">{url?'模板示例':'版式示意'}</span>
 </div>;
}

/** Keep selection outside the parent render cycle so checking review boxes does not reset it. */
function ReviewGallery({run,assets,locked,lockReason,busy,onEdit,onDownload,rawPdf=false}:{run:number;assets:Asset[];locked:boolean;lockReason:string;busy:boolean;onEdit:(asset:Asset)=>void;onDownload:(asset:Asset,source?:boolean)=>void;rawPdf?:boolean}){
 const [slot,setSlot]=useState('');const asset=assets.find(a=>a.slot===slot)||assets[0];
 if(!asset)return null;
 return <section className="vd-review-gallery" aria-label="图片审核预览">
  <div className="vd-review-header"><Space wrap><Text strong>{asset.role}</Text><Tag>{asset.kind==='pdf-page'?'独立PDF样页':asset.kind==='collage'?'四宫格真实样张':asset.kind==='sample'?'真实讲义样张':asset.kind==='cover'?'封面':'内页'}</Tag><Text type="secondary">{assets.indexOf(asset)+1} / {assets.length}</Text></Space><Tooltip title={locked?lockReason:undefined}><span><Button icon={<EditOutlined/>} disabled={locked} onClick={()=>onEdit(asset)}>{rawPdf&&asset.kind==='pdf-page'?'更换PDF选页':asset.kind==='cover'?'修改封面':'修改这张图'}</Button></span></Tooltip></div>
  <div className="vd-review-stage"><Picture run={run} asset={asset}/></div>
  {assets.length>1&&<div className="vd-thumbnails" aria-label="选择审核图片">{assets.map((a,i)=><button type="button" key={a.id} className={`vd-thumbnail ${a.id===asset.id?'active':''}`} aria-label={`查看第${i+1}张：${a.role}`} aria-pressed={a.id===asset.id} onClick={()=>setSlot(a.slot)}><Picture run={run} asset={a} thumbnail/><span>{i+1} · {a.role}</span></button>)}</div>}
  <div className="vd-review-tools"><Text type="secondary">{asset.kind==='collage'||asset.kind==='pdf-page'?'点击大图放大查看真实样页与公式':'点击大图可放大核对细字与公式'}</Text><Button disabled={busy} onClick={()=>onDownload(asset)}>下载当前原图</Button></div>
  <Collapse size="small" items={[{key:'asset-details',label:'高级：制作信息与源文件',children:<><Paragraph>{rawPdf&&asset.kind==='pdf-page'?'原PDF本机直接导出':asset.api_generated?`API完整知识图 · ${asset.api_generated.model.name} · 大学、课程代码和真实Logo本机添加`:asset.background?'AI 背景与真实资料在本机合成':'本机排版'}{asset.source_page?` · PDF 原页 ${asset.source_page}`:''}{asset.source_pages?.length?` · PDF 原页 ${asset.source_pages.join('、')}`:''}</Paragraph><Paragraph copyable={{text:asset.sha256}}>图片指纹：{asset.sha256}</Paragraph>{asset.svg_file&&<Button disabled={busy} onClick={()=>onDownload(asset,true)}>下载 SVG 源文件</Button>}</>} ]}/>
 </section>;
}

export function CourseVisualWorkflowPage(){
 const {user}=useAuth();const userId=user?.id;
 const [params,setParams]=useSearchParams();const [catalog,setCatalog]=useState<Catalog|null>(null);const [history,setHistory]=useState<History[]>([]);const [run,setRun]=useState<Run|null>(null);
 const fileContext=Number(params.get('file_id'))||undefined,requestedRun=Number(params.get('run'))||undefined,requestedStage=params.get('stage');
 const imageMode:ProductionMode=params.get('image_mode')==='local'||run?.data.visual_plan.template_id!=='magazine-a'?'local':'api';
 const productionIntent=useRef<ProductionIntent>({mode:'local',target:'bundle'});
 const [productionOptions,setProductionOptions]=useState<string[]>([]);
 const pdfPickerRequested=useRef(false);
 const [material,setMaterial]=useState<number|null>(Number(params.get('file_id'))||null);const [accounts,setAccounts]=useState<PlatformAccount[]>([]);const [account,setAccount]=useState<number|null>(null);
 const [newEntryMode,setNewEntryMode]=useState<EntryMode>('pdf-driven');
 const [newBrandId,setNewBrandId]=useState('');
 const [pdfPrompt,setPdfPrompt]=useState<PdfAnalysisPrompt|null>(null);const [pdfPromptVersion,setPdfPromptVersion]=useState<number|null>(null);const [pdfConsent,setPdfConsent]=useState(false);const pdfKey=useRef(crypto.randomUUID());const pdfPlanDigest=useRef('');
 const [apiImagePlan,setApiImagePlan]=useState<ApiImagePlan|null>(null);const [apiImageConsent,setApiImageConsent]=useState(false);const [apiImageWorking,setApiImageWorking]=useState(false);const [apiImageProgress,setApiImageProgress]=useState('');const apiImageKey=useRef(crypto.randomUUID());const apiImageDigest=useRef('');
 const [busy,setBusy]=useState('加载');const [error,setError]=useState('');const [notice,setNotice]=useState('');const [step,setStep]=useState(0);const [keyword,setKeyword]=useState('');const [sort,setSort]=useState(2);
 const [copy,setCopy]=useState<Copy|null>(null);const [plan,setPlan]=useState<Plan|null>(null);const [innerPlan,setInnerPlan]=useState<SetPlan|null>(null);const [innerPagesText,setInnerPagesText]=useState('');const [selected,setSelected]=useState<string[]>([]);const [checks,setChecks]=useState<Record<string,boolean>>({});
 const [pdfPagePlan,setPdfPagePlan]=useState<PdfPagePlan|null>(null);const [pdfPagesText,setPdfPagesText]=useState<string>(pdfPageText(null));const pdfPagesKey=useRef(crypto.randomUUID());const legacyCollageBuffer=useRef<Pick<EditorBuffer,'collagePlan'|'collagePagesText'>>({});
 const [prompt,setPrompt]=useState<Prompt|null>(null);const [consent,setConsent]=useState(false);const [editing,setEditing]=useState<Asset|null>(null);const [brief,setBrief]=useState<Brief|null>(null);
 const [bgOptions,setBgOptions]=useState<BackgroundOptions|null>(null);const [bgPrompt,setBgPrompt]=useState<BackgroundPrompt|null>(null);const [bgConsent,setBgConsent]=useState(false);const bgKey=useRef(crypto.randomUUID());
 const [pagesText,setPagesText]=useState('');const generation=useRef(0);const createKey=useRef(crypto.randomUUID());const aiKey=useRef(crypto.randomUUID());const bundleKey=useRef(crypto.randomUUID());const catalogSeq=useRef(0);
 const [editOpen,setEditOpen]=useState(false);const [bufferStatus,setBufferStatus]=useState('');const [bufferConflict,setBufferConflict]=useState<CourseEditBuffer<EditorBuffer>|null>(null);const editorReady=useRef<number|null>(null);
 const [recordsOpen,setRecordsOpen]=useState(false);const [imageAction,setImageAction]=useState<{slot:string;asset?:Asset}|null>(null);const [historyNotice,setHistoryNotice]=useState('');const [historyOpen,setHistoryOpen]=useState<string[]>([]);
 const liveRecord=useRef(run);liveRecord.current=run;const navigation=useRef(0);const liveStage=useRef(requestedStage);if(liveStage.current!==requestedStage){navigation.current++;liveStage.current=requestedStage;}const routeScope=JSON.stringify([userId,fileContext,requestedRun]);const liveRoute=useRef(routeScope);if(liveRoute.current!==routeScope){generation.current++;liveRoute.current=routeScope;}
 const dirty=!!run&&!!copy&&(!sameVisualEdit(copy,run.data.copy)||!sameVisualEdit(selected,run.data.selected_source_ids));
 const visualDirty=!!run&&!!plan&&!sameVisualEdit(normalPlan(plan),normalPlan(run.data.visual_plan));
 const innerDirty=!!run&&!!innerPlan&&!sameVisualEdit(normalSetPlan(innerPlan,run.data.visual_plan),normalSetPlan(run.data.set_plan,run.data.visual_plan));
 const pdfPagesDirty=!!run&&!sameVisualEdit(pdfPagePlan??null,run.data.pdf_page_plan??null);
 const briefDirty=!!editing&&!!brief&&!sameVisualEdit(brief,{...editing.brief,nodes:editing.brief.nodes||[]});
 const hasEdits=dirty||visualDirty||innerDirty||pdfPagesDirty||briefDirty;
 const creationMaterials:Material[]=run&&!catalog?.materials.some(f=>f.id===run.file_id)
  ? [{id:run.file_id,revision_id:run.data.source.revision_id,filename:run.data.source.filename,university:run.data.source.university,course_code:run.data.source.course_code},...(catalog?.materials||[])]
  : catalog?.materials||[];
 useEffect(()=>{setApiImagePlan(null);setApiImageConsent(false);},[routeScope,requestedStage]);
 useEffect(()=>{setApiImageWorking(false);setApiImageProgress('');},[routeScope]);
 useEffect(()=>{setApiImagePlan(p=>p&&(p.run_id!==run?.id||p.row_version!==run?.row_version)?null:p);setApiImageConsent(false);},[run?.id,run?.row_version]);
 useEffect(()=>{
  if(!apiImageWorking||!run)return;
  let live=true,reading=false;const seq=generation.current,id=run.id;
  const timer=window.setInterval(()=>{if(reading)return;reading=true;void rawWorkflowGet<Run>(`/${id}`).then(r=>{const progress=r.data.operation as {completed?:number;total?:number;key?:string}|undefined;if(live&&seq===generation.current&&progress?.key===apiImageKey.current)setApiImageProgress(`已完成 ${progress.completed||0} / ${progress.total||1} 张知识图`);}).catch(()=>{}).finally(()=>{reading=false;});},2500);
  return()=>{live=false;window.clearInterval(timer);};
 },[apiImageWorking,run?.id]);
 function visualWorkflowGet<T>(path:string,options?:Record<string,unknown>){return inCourseContext(()=>rawWorkflowGet<T>(path,options),()=>generation.current);}
 function visualWorkflowAction<T>(path:string,data:unknown,method:'post'|'patch'='post'){return inCourseContext(()=>rawWorkflowAction<T>(path,data,method),()=>generation.current);}
 const editScope=(id:number)=>({userId:userId!,feature:'visual-workbench',recordId:String(id)});
 function applyEditor(r:Run,b:EditorBuffer){legacyCollageBuffer.current={...(b.collagePlan!==undefined?{collagePlan:b.collagePlan}:{}),...(b.collagePagesText!==undefined?{collagePagesText:b.collagePagesText}:{})};const restoredPdfPages=b.pdfPagePlan===undefined?r.data.pdf_page_plan??null:b.pdfPagePlan;setPdfPagePlan(restoredPdfPages);setPdfPagesText(b.pdfPagesText??pdfPageText(restoredPdfPages));const restoredInner=normalSetPlan(b.innerPlan||r.data.set_plan,r.data.visual_plan);setInnerPlan(restoredInner);setInnerPagesText(b.innerPagesText??restoredInner.sample_pages.join(', '));setCopy(b.copy);setPlan(normalPlan(b.plan));setPagesText(b.pagesText);setSelected(b.selected);const a=([...(r.data.cover?[r.data.cover]:[]),...r.data.images]).find(a=>a.id===b.editingId);setEditing(a||null);setBrief(a&&b.brief?b.brief:null);setEditOpen(!!a&&!!b.brief);setChecks({});}
 function receive(r:Run){
  setPdfPrompt(null);setPdfConsent(false);
  editorReady.current=null;legacyCollageBuffer.current={};const savedPdfPages=r.data.pdf_page_plan??null;setPdfPagePlan(savedPdfPages);setPdfPagesText(pdfPageText(savedPdfPages));const savedInner=normalSetPlan(r.data.set_plan,r.data.visual_plan);setInnerPlan(savedInner);setInnerPagesText(savedInner.sample_pages.join(', '));setRun(r);setCopy(r.data.copy);setPlan(normalPlan(r.data.visual_plan));setPagesText(r.data.visual_plan.sample_pages.join(', '));setSelected(r.data.selected_source_ids);setEditing(null);setBrief(null);setEditOpen(false);setImageAction(null);setChecks({});setPrompt(null);setConsent(false);setBgOptions(null);setBgPrompt(null);setBgConsent(false);setBufferConflict(null);setBufferStatus('');
  const cached=userId!==undefined?readCourseEditBuffer<EditorBuffer>(editScope(r.id)):null;
  if(cached?.value?.copy&&cached.value.plan&&Array.isArray(cached.value.selected)&&typeof cached.value.pagesText==='string'){
   if(cached.baseVersion===String(r.row_version)){applyEditor(r,cached.value);setBufferStatus('已恢复本机未提交修改；仍需保存并重新审核。');}
   else{setBufferConflict(cached);setBufferStatus('工作记录已更新，旧的本机修改仍保留，请先选择如何处理。');}
  }
  editorReady.current=r.id;
 }
 async function loadHistory(){setHistory((await visualWorkflowGet<{items:History[]}>('',{file_id:fileContext})).items);}
 async function refreshHistoryAfterMutation(){try{await loadHistory();setHistoryNotice('');}catch(e){if(!(e instanceof CourseContextChanged))setHistoryNotice('当前操作已保存成功，工作记录列表暂未刷新。可稍后点击刷新，不必重复制作或另存。');}}
 function showStep(next:number,replace=false){setStep(next);setParams(current=>visualStageParams(current,next),{replace});}
 async function action(name:string,fn:(viewCurrent:()=>boolean)=>Promise<void>){const seq=generation.current,view=navigation.current;setBusy(name);setError('');setNotice('');try{await fn(()=>seq===generation.current&&view===navigation.current);}catch(e){if(seq===generation.current&&!(e instanceof CourseContextChanged))setError(errorText(e));}finally{if(seq===generation.current)setBusy('');}}
 useEffect(()=>{
  if(userId===undefined)return;
  const seq=++generation.current;editorReady.current=null;setBusy('加载');setRun(null);setCopy(null);setPlan(null);setInnerPlan(null);setInnerPagesText('');setPdfPagePlan(null);setPdfPagesText(pdfPageText(null));setEditing(null);setBrief(null);setEditOpen(false);setImageAction(null);setHistory([]);setHistoryNotice('');setError('');setNotice('');setBufferStatus('');setBufferConflict(null);setMaterial(fileContext||null);
  void(async()=>{try{
   const [c,h]=await Promise.all([visualWorkflowGet<Catalog>('/catalog',{file_id:fileContext}),visualWorkflowGet<{items:History[]}>('',{file_id:fileContext})]);
   if(seq!==generation.current)return;setCatalog(c);setHistory(h.items);
   const id=initialCourseRun(h.items,fileContext,requestedRun);
   if(id){const r=await visualWorkflowGet<Run>(`/${id}`);if(seq!==generation.current)return;
    if(fileContext&&r.file_id!==fileContext){setError('该工作记录与所选PDF不匹配，请选择当前资料对应的记录或新建。');return;}
    if(!requestedRun){setParams(current=>{const next=visualStageParams(current,visualStageIndex(liveStage.current)??nextVisualStage(r));next.set('run',String(r.id));return next;},{replace:true});return;}
    receive(r);setMaterial(r.file_id);showStep(visualStageIndex(liveStage.current)??nextVisualStage(r),true);
   }else if(fileContext){setNotice('当前PDF还没有图文工作记录，点击“用当前PDF新建”开始；不会打开其他课程。');}
  }catch(e){if(seq===generation.current)setError(errorText(e));}finally{if(seq===generation.current)setBusy('');}})();
  return()=>{generation.current++;};
 },[fileContext,requestedRun,userId]);
 // A stage URL is navigation inside this record. Do not reload data or overwrite editable fields.
 useEffect(()=>{const next=visualStageIndex(requestedStage);if(next!==null)setStep(next);setChecks({});setPrompt(null);setConsent(false);setPdfPrompt(null);setPdfConsent(false);setImageAction(null);setBgOptions(null);setBgPrompt(null);setBgConsent(false);},[requestedStage]);
 useEffect(()=>{if(hasEdits){setPdfPrompt(null);setPdfConsent(false);}},[hasEdits,copy,plan,innerPlan,selected,pdfPagePlan]);
 useEffect(()=>{setPdfPrompt(null);setPdfConsent(false);},[fileContext,requestedRun,userId]);
 useEffect(()=>{
  if(!pdfPickerRequested.current||!productionOptions.includes('remake'))return;
  // Wait for the drawer-free collapse animation before scrolling to its real
  // input. The first animation frame can run before lazy children are mounted.
  const timer=window.setTimeout(()=>{
   const panel=document.querySelector<HTMLElement>('.vd-pdf-pages-panel');
   panel?.querySelector<HTMLInputElement>('input')?.focus({preventScroll:true});
   panel?.scrollIntoView({behavior:'smooth',block:'center'});pdfPickerRequested.current=false;
  },360);
  return()=>window.clearTimeout(timer);
 },[productionOptions,requestedRun,requestedStage,fileContext,userId]);
 useEffect(()=>{
  if(apiImagePlan&&(apiImagePlan.run_id!==run?.id||apiImagePlan.row_version!==run?.row_version||hasEdits)){
   setApiImagePlan(null);setApiImageConsent(false);
  }
 },[apiImagePlan,run?.id,run?.row_version,hasEdits]);
 useEffect(()=>{let live=true;setAccounts([]);setAccount(null);if(!run||entryMode(run.data.entry_mode)!=='xhs-research')return;const seq=generation.current;void fetchAccounts('xhs').then(a=>{if(!live||seq!==generation.current)return;const pc=a.filter(x=>x.sub_type==='pc');setAccounts(pc);setAccount(pc[0]?.id??null);}).catch(()=>{/* Search accounts are optional; PDF analysis must remain available. */});return()=>{live=false;};},[run?.id,run?.data.entry_mode,userId]);
 useEffect(()=>{
  if(!run||!copy||!plan||!innerPlan||userId===undefined||editorReady.current!==run.id||bufferConflict)return;
  if(hasEdits){const ok=writeCourseEditBuffer(editScope(run.id),{copy,plan,innerPlan,innerPagesText,pdfPagePlan,pdfPagesText,selected,pagesText,...legacyCollageBuffer.current,...(briefDirty?{editingId:editing!.id,brief:brief!}:{})},String(run.row_version));setBufferStatus(ok?'修改已缓存在本机，尚未提交保存；刷新后可恢复。':'无法保存本机编辑缓冲，请先保存修改再离开页面。');}
  else if(Object.keys(legacyCollageBuffer.current).length){writeCourseEditBuffer(editScope(run.id),{copy,plan,innerPlan,innerPagesText,pdfPagePlan,pdfPagesText,selected,pagesText,...legacyCollageBuffer.current},String(run.row_version));setBufferStatus('旧拼图选页记录已保留；当前流程使用独立PDF样页。');}
  else{removeCourseEditBuffer(editScope(run.id));setBufferStatus('');}
 },[run,copy,plan,innerPlan,innerPagesText,pdfPagePlan,pdfPagesText,selected,pagesText,editing,brief,hasEdits,briefDirty,userId,bufferConflict]);
 useEffect(()=>{if(!hasEdits||!bufferStatus.startsWith('无法'))return;const warn=(e:BeforeUnloadEvent)=>{e.preventDefault();e.returnValue='';};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[hasEdits,bufferStatus]);
 useEffect(()=>{if(run)setKeyword(run.data.source.course_code);},[run?.id]);
 function changeContext(next:Record<string,string>){if(hasEdits&&bufferStatus.startsWith('无法')){setError('本机缓冲不可用，请保存或明确放弃修改后再切换。');return;}setParams(next);}
 async function chooseRun(id:number){changeContext({run:String(id),...(fileContext?{file_id:String(fileContext)}:{})});setRecordsOpen(false);}
 async function searchMaterials(q:string){const n=++catalogSeq.current;try{const c=await visualWorkflowGet<Catalog>('/catalog',{q});if(n===catalogSeq.current)setCatalog(c);}catch(e){if(!(e instanceof CourseContextChanged))setError(errorText(e));}}
 async function create(){const f=creationMaterials.find(f=>f.id===material);if(!f||!newBrandId||hasEdits||bufferConflict)return;await action('新建',async()=>{const r=await visualWorkflowAction<Run>('',{file_id:f.id,revision_id:f.revision_id,brand_id:newBrandId,request_key:createKey.current,template_id:'magazine-a',entry_mode:newEntryMode});receive(r);setRecordsOpen(false);setNewBrandId('');createKey.current=crypto.randomUUID();setParams({run:String(r.id),file_id:String(r.file_id),stage:'research'});});}
 function chooseNewEntryMode(mode:EntryMode){if(busy||hasEdits||bufferConflict||mode===newEntryMode)return;setNewEntryMode(mode);createKey.current=crypto.randomUUID();}
 async function selectEntryMode(mode:EntryMode){
  if(!run||busy||bufferConflict||run.data.operation?.status==='generating'||entryMode(run.data.entry_mode)===mode)return;
  if(hasEdits){setError('本机修改已保留，请先保存或放弃当前修改，再切换制作入口。');return;}
  await action('切换制作入口',async viewCurrent=>{const r=await visualWorkflowAction<Run>(`/${run.id}/select-entry-mode`,{expected_version:run.row_version,entry_mode:mode});receive(r);if(viewCurrent()){showStep(0);setNotice('制作入口已切换，原文案、方案和图片保留在历史版本。');}await refreshHistoryAfterMutation();});
 }
 async function preparePdfAnalysis(){
  if(!run||busy||bufferConflict||briefDirty||entryMode(run.data.entry_mode)!=='pdf-driven'||run.data.operation?.status==='generating')return;
  if(visualDirty||innerDirty||pdfPagesDirty){setError('请先保存或放弃当前图片方案修改，再准备PDF分析；本机修改仍保留。');return;}
  await action(dirty?'保存文案改动并准备PDF分析':'读取PDF并准备分析',async viewCurrent=>{
   let current=run;
   if(dirty){current=await visualWorkflowAction<Run>(`/${run.id}`,{expected_version:run.row_version,copy,selected_source_ids:selected},'patch');removeCourseEditBuffer(editScope(run.id));receive(current);}
   const result=await visualWorkflowAction<PdfAnalysisPrompt>(`/${current.id}/pdf-analysis-plan`,{expected_version:current.row_version});
   if(viewCurrent()){if(pdfPlanDigest.current!==result.plan_digest){pdfKey.current=crypto.randomUUID();pdfPlanDigest.current=result.plan_digest;}setPdfPromptVersion(current.row_version);setPdfPrompt(result);setPdfConsent(false);}
  });
 }
 async function generateFromPdf(){
  if(!run||!pdfPrompt||!pdfConsent||!pdfPrompt.model?.configured||busy||hasEdits||bufferConflict||entryMode(run.data.entry_mode)!=='pdf-driven'||run.data.operation?.status==='generating')return;
  if(pdfPromptVersion!==run.row_version){setPdfPrompt(null);setPdfConsent(false);setError('当前记录已变化，请重新核对PDF分析范围。');return;}
  const key=pdfKey.current,id=run.id;
  await action('分析PDF并生成待审核内容',async viewCurrent=>{
   try{
    const r=await visualWorkflowAction<Run>(`/${id}/generate-from-pdf`,{expected_version:run.row_version,external_consent:true,plan_digest:pdfPrompt.plan_digest,request_key:key});
    receive(r);pdfKey.current=crypto.randomUUID();if(viewCurrent()){showStep(1);setNotice('PDF分析与推荐文案已保存，4张干货的候选内容也已准备好。请先审核文案；未出图、另存或发布。');}await refreshHistoryAfterMutation();
   }catch(error){
    if(error instanceof CourseContextChanged)throw error;
    try{const latest=await visualWorkflowGet<Run>(`/${id}`);receive(latest);if(latest.data.operation?.key===key&&latest.data.operation.status==='completed'&&latest.data.pdf_analysis){if(viewCurrent()){showStep(1);setNotice('已找回完成的PDF分析，未重复调用模型。请审核当前文案。');}await refreshHistoryAfterMutation();return;}if(latest.data.operation?.key===key&&latest.data.operation.status==='failed')pdfKey.current=crypto.randomUUID();}catch{/* Keep the existing key if the outcome is still ambiguous. */}
    throw error;
   }
  });
 }
 function choosePdfTopic(topic:PdfAnalysis['topic_candidates'][number]){if(busy||bufferConflict||briefDirty)return;changeCopy({topic:topic.topic,takeaway:topic.reader_takeaway});setNotice('已选择新的候选选题；当前正文尚未重写。请点击“保存修改并按当前选题重新生成”，核对外发范围后继续。');chooseStep(1);}
 async function confirmVisualCandidate(){
  if(!run||!plan||!innerPlan||busy||dirty||pdfPagesDirty||briefDirty||bufferConflict||!run.approved.copy||!checks.visualCandidate||run.data.visual_candidate?.status!=='stale')return;
  const issue=innerPlanIssue(innerPlan,plan,run.data.source.page_count);if(issue){setError(issue);return;}
  await action('核对并沿用当前图片内容',async viewCurrent=>{const r=await visualWorkflowAction<Run>(`/${run.id}`,{expected_version:run.row_version,visual_plan:plan,set_plan:innerPlan,visual_candidate_reviewed:true},'patch');removeCourseEditBuffer(editScope(run.id));receive(r);if(viewCurrent())setNotice('当前图片内容已重新核对并绑定文案，可在本机制作；成品仍需审核。');});
 }
 async function forkRun(){if(!run||busy||hasEdits||bufferConflict||run.data.operation?.status==='generating')return;await action('另建优化版本',async viewCurrent=>{const r=await visualWorkflowAction<Run>(`/${run.id}/fork`,{expected_version:run.row_version});if(viewCurrent()){setParams({run:String(r.id),file_id:String(r.file_id),stage:'copy'});setRecordsOpen(false);}else{setNotice(`优化版本 #${r.id} 已创建，原稿保留，可从“资料与工作记录”打开。`);await refreshHistoryAfterMutation();}});}
 async function recoverBundle(id:number,key:string){
  try{const latest=await visualWorkflowGet<Run>(`/${id}`);receive(latest);if(latest.data.operation?.key===key&&latest.data.operation.status==='failed')bundleKey.current=crypto.randomUUID();}
  catch{/* Keep an ambiguous request key: the server may have completed while the response was lost. */}
 }
 async function appendPdfPages(){
  if(!run||busy||bufferConflict||briefDirty||run.data.operation?.status==='generating'||!run.data.images.length)return;
  if(dirty||visualDirty||innerDirty){setError('还有文案或其它图片修改，请先保存或放弃这些修改，再追加样页。');return;}
  if(!run.approved.copy){setError('请先确认当前文案，再追加独立PDF样页。');return;}
  const count=run.data.visual_plan.template_id==='magazine-a'?9:8;const candidate=pdfPagePlan||defaultPdfPagePlan(count),issue=pdfPageIssue(candidate,run.data.source.page_count,count);if(issue){setError(issue);return;}const proposed={pages:[...candidate.pages].sort((a,b)=>a-b)};
  const key=pdfPagesKey.current,beforeDigest=run.digests.set;
  await action(`制作${count}张PDF样页`,async viewCurrent=>{
   try{
    const result=await visualWorkflowAction<Run>(`/${run.id}/append-pdf-pages`,{expected_version:run.row_version,request_key:key,pdf_page_plan:proposed});
    removeCourseEditBuffer(editScope(run.id));receive(result);pdfPagesKey.current=crypto.randomUUID();if(viewCurrent()){showStep(4);setNotice(`${count}张独立PDF样页已放在末尾，原封面和讲解保留。请审核后再另存草稿。`);}await refreshHistoryAfterMutation();
   }catch(error){
    if(!(error instanceof CourseContextChanged))try{
     const latest=await visualWorkflowGet<Run>(`/${run.id}`),pages=latest.data.images.filter(asset=>asset.kind==='pdf-page');
     if(sameVisualEdit(latest.data.pdf_page_plan,proposed)&&pages.length===proposed.pages.length&&pages.every((asset,index)=>asset.source_page===[...proposed.pages].sort((a,b)=>a-b)[index])){removeCourseEditBuffer(editScope(run.id));receive(latest);}
     else if(latest.digests.set===beforeDigest&&latest.data.operation?.key===key&&latest.data.operation.status==='failed'){setRun(latest);pdfPagesKey.current=crypto.randomUUID();}
     else receive(latest);
    }catch{/* Keep the proposed page groups and retry key if the result is uncertain. */}
    throw error;
   }
  });
 }
 function requireCoverSample(){
  if(!run||!plan)return false;
  const issue=coverSampleIssue(plan,run.data.source.page_count);if(!issue)return true;
  setError(issue);showStep(2);
  if(typeof window!=='undefined')window.requestAnimationFrame(()=>{const panel=document.getElementById('vd-cover-sample-picker');panel?.scrollIntoView({behavior:'smooth',block:'center'});panel?.focus({preventScroll:true});});
  return false;
 }
 async function act(path:string,body:Record<string,unknown>,name:string,delivery?:ProductionIntent){if(!run)return;await action(name,async viewCurrent=>{
  let r:Run;
  try{r=await visualWorkflowAction<Run>(`/${run.id}/${path}`,{expected_version:run.row_version,...body});}
  catch(error){
   if(path==='generate-visual-plan'&&!(error instanceof CourseContextChanged))try{
    const latest=await visualWorkflowGet<Run>(`/${run.id}`);receive(latest);
    if(latest.data.operation?.key===body.request_key&&latest.data.operation?.status==='completed'){
     if(viewCurrent()){showStep(2);setNotice('已找回保存的图片内容，未重复调用模型。点击制作即可继续。');}return;
    }
    if(latest.data.operation?.key===body.request_key&&latest.data.operation?.status==='failed')aiKey.current=crypto.randomUUID();
   }catch{/* Retain the key while the paid planning outcome is uncertain. */}
   throw error;
  }
  receive(r);
  if(path==='generate-visual-plan'){
   if(delivery?.mode==='api'){
    // Text planning never authorizes the separate paid image request.
    if(viewCurrent()){
     const prepared=await visualWorkflowAction<ApiImagePlan>(`/${r.id}/api-image-plan`,{expected_version:r.row_version,target:delivery.target});
     if(viewCurrent()){if(prepared.plan_digest!==apiImageDigest.current){apiImageKey.current=crypto.randomUUID();apiImageDigest.current=prepared.plan_digest;}setApiImagePlan(prepared);setApiImageConsent(false);setNotice('4张图的内容已准备好。请核对图片服务商、提示词与计费张数，确认后才生图。');}
    }
   }else try{r=await visualWorkflowAction<Run>(`/${r.id}/render-bundle`,{expected_version:r.row_version,request_key:bundleKey.current});receive(r);bundleKey.current=crypto.randomUUID();}
   catch(e){if(!(e instanceof CourseContextChanged))await recoverBundle(run.id,bundleKey.current);throw e;}
  }
  if(viewCurrent()){if(path==='render')showStep(body.stage==='cover'?2:4);else if(path==='restore')showStep(nextVisualStage(r));else if(path==='export'||path==='generate-visual-plan'&&delivery?.mode!=='api')showStep(4);else if(path==='generate-copy')showStep(1);else if(path==='approve'&&body.stage==='copy')showStep(r.data.images.length?4:2);}
  await refreshHistoryAfterMutation();
 });}

 function changeImageMode(mode:ProductionMode){
  if(busy||bufferConflict||briefDirty)return;
  setPrompt(null);setConsent(false);setApiImagePlan(null);setApiImageConsent(false);
  setParams(current=>{const next=new URLSearchParams(current);next.set('image_mode',mode);return next;},{replace:true});
 }
 async function startProduction(target='bundle',forcePlanning=false){
  if(!run||!copy||!plan||!innerPlan||busy||bufferConflict||briefDirty||run.data.operation?.status==='generating')return;
  if(dirty||!run.approved.copy){setError('请先保存并确认当前文案，再制作图片。');showStep(1);return;}
  const state=productionReadiness(copy,plan,innerPlan,pdfPagePlan);
  if(coverSampleIssue(plan,run.data.source.page_count))setProductionOptions(['options']);
  productionIntent.current={mode:imageMode,target};
  if(forcePlanning||state.needsPlanning||run.data.visual_candidate?.status==='stale'){await showPrompt('visual');return;}
  if(pdfPagesDirty&&run.data.images.length&&!visualDirty&&!innerDirty){await appendPdfPages();return;}
  if(imageMode==='api')await prepareApiImages(target);else await saveAndRender();
 }

 async function saveAndRender(){
  if(!run||!copy||!plan||!innerPlan||busy||bufferConflict||briefDirty||run.data.operation?.status==='generating')return;
  if(dirty||!run.approved.copy){setError('请先保存并确认当前文案，再制作图片。');return;}
  if(run.data.visual_candidate?.status==='stale'){setError('文案已变化，请先重新规划图片，或核对后沿用当前图片内容。');showStep(2);return;}
  if(pdfPagesDirty&&run.data.images.length&&!visualDirty&&!innerDirty){await appendPdfPages();return;}
  if(!requireCoverSample())return;
  const collageIssue=pdfPageIssue(pdfPagePlan,run.data.source.page_count,plan?.template_id==='magazine-a'?9:8);if(collageIssue){setError(collageIssue);return;}
  const issue=innerPlanIssue(innerPlan,plan,run.data.source.page_count);if(issue){setError(issue);return;}
  await action('保存方案并制作整套图片',async viewCurrent=>{
   let current=run;
   if(visualDirty||innerDirty||pdfPagesDirty){
    current=await visualWorkflowAction<Run>(`/${run.id}`,{expected_version:run.row_version,...(visualDirty?{visual_plan:plan}:{}),...(innerDirty?{set_plan:innerPlan}:{}),...(pdfPagesDirty?{pdf_page_plan:pdfPagePlan}:{})},'patch');
    removeCourseEditBuffer(editScope(run.id));receive(current);bundleKey.current=crypto.randomUUID();
   }
   try{
    const result=await visualWorkflowAction<Run>(`/${run.id}/render-bundle`,{expected_version:current.row_version,request_key:bundleKey.current});
    receive(result);bundleKey.current=crypto.randomUUID();if(viewCurrent()){showStep(4);setNotice('整套图片已生成。请在这里检查封面和内页，确认后另存新草稿；旧图均已保留。');}
    await refreshHistoryAfterMutation();
   }catch(e){
    if(!(e instanceof CourseContextChanged))await recoverBundle(run.id,bundleKey.current);
    throw e;
   }
  });
 }
 async function prepareApiImages(target='bundle'){
  if(!run||!plan||!innerPlan||busy||bufferConflict||briefDirty||run.data.operation?.status==='generating')return;
  if(dirty||!run.approved.copy){setError('请先保存并确认当前文案，再准备API生图。');return;}
  if(run.data.visual_candidate?.status==='stale'){setError('文案已变化，请先核对或重新规划图片内容。');chooseStep(2);return;}
  if(plan.template_id!=='magazine-a'){setError('请先选择A杂志讲解版，再使用4张知识图＋9张PDF的完整API制作。');chooseStep(2);return;}
  const issue=innerPlanIssue(innerPlan,plan,run.data.source.page_count)||pdfPageIssue(pdfPagePlan,run.data.source.page_count,9);if(issue){setError(issue);return;}
  setImageAction(null);
  await action('准备API提示词与调用范围',async viewCurrent=>{
   let current=run;
   if(visualDirty||innerDirty||pdfPagesDirty){current=await visualWorkflowAction<Run>(`/${run.id}`,{expected_version:run.row_version,...(visualDirty?{visual_plan:plan}:{}),...(innerDirty?{set_plan:innerPlan}:{}),...(pdfPagesDirty?{pdf_page_plan:pdfPagePlan}:{})},'patch');removeCourseEditBuffer(editScope(run.id));receive(current);}
   const prepared=await visualWorkflowAction<ApiImagePlan>(`/${current.id}/api-image-plan`,{expected_version:current.row_version,target});
   if(viewCurrent()){if(prepared.plan_digest!==apiImageDigest.current){apiImageKey.current=crypto.randomUUID();apiImageDigest.current=prepared.plan_digest;}setApiImagePlan(prepared);setApiImageConsent(false);}
  });
 }
 async function generateApiImages(){
  if(!run||!apiImagePlan||busy||hasEdits||bufferConflict||!apiImageConsent||apiImagePlan.run_id!==run.id||apiImagePlan.row_version!==run.row_version)return;
  const prepared=apiImagePlan,key=apiImageKey.current,id=run.id,seq=generation.current;
  await action('API整张图制作中，请勿重复提交',async viewCurrent=>{
   setApiImageWorking(true);setApiImageProgress('');setApiImagePlan(null);setApiImageConsent(false);
   try{
    const result=await visualWorkflowAction<Run>(`/${id}/generate-api-images`,{expected_version:prepared.row_version,target:prepared.target,external_consent:true,plan_digest:prepared.plan_digest,request_key:key});
    receive(result);if(viewCurrent()){showStep(result.data.images.length?4:2);setNotice('API知识图已另存新版本，大学与课程代码已突出显示。旧图和真实PDF保留，请审核后再另存草稿。');}await refreshHistoryAfterMutation();
   }catch(error){
    if(!(error instanceof CourseContextChanged))try{const latest=await visualWorkflowGet<Run>(`/${id}`);receive(latest);const operation=latest.data.operation;if(operation?.key===key&&operation.status==='completed'){if(viewCurrent()){showStep(latest.data.images.length?4:2);setNotice('已找回完成的API图稿，未重复调用。请核对当前图片。');}await refreshHistoryAfterMutation();return;}}catch{/* Keep the same request key when the paid outcome is uncertain. */}
    throw error;
   }finally{if(seq===generation.current){setApiImageWorking(false);setApiImageProgress('');}}
  });
 }
 async function saveEdits(){if(!run||!copy||!plan||!innerPlan||busy||bufferConflict||briefDirty||run.data.operation?.status==='generating'||(!dirty&&!visualDirty&&!innerDirty&&!pdfPagesDirty))return;if(pdfPagesDirty&&run.data.images.length&&!dirty&&!visualDirty&&!innerDirty){setError(`请点击“追加${plan.template_id==='magazine-a'?9:8}张PDF样页”，直接保留现有图片并制作独立样页。`);return;}const collageIssue=pdfPageIssue(pdfPagePlan,run.data.source.page_count,plan?.template_id==='magazine-a'?9:8);if(collageIssue){setError(collageIssue);return;}if(innerDirty){const issue=innerPlanIssue(innerPlan,plan,run.data.source.page_count,true);if(issue){setError(issue);return;}}const target=dirty?1:2;await action(innerDirty&&!dirty&&!visualDirty?'保存内页扩充':'保存修改',async viewCurrent=>{
  const r=await visualWorkflowAction<Run>(`/${run.id}`,{expected_version:run.row_version,...(dirty?{copy,selected_source_ids:selected}:{}),...(visualDirty?{visual_plan:plan}:{}),...(innerDirty?{set_plan:innerPlan}:{}),...(pdfPagesDirty?{pdf_page_plan:pdfPagePlan}:{})},'patch');
  removeCourseEditBuffer(editScope(run.id));receive(r);if(viewCurrent())showStep(target);await refreshHistoryAfterMutation();if(viewCurrent())setNotice(dirty?'当前修改已保存，请核对并重新确认文案，再继续制作图片。原封面与旧图保留在历史版本。':visualDirty?'视觉方案已保存，可直接制作封面和整套图。原封面与旧图保留在历史版本。':'内页扩充已保存，当前文案与已确认封面保留。请按新计划生成整套图片并重新审核，旧图保留在历史版本。');
 });}
 async function saveCopy(){await saveEdits();}
 async function saveVisual(){await saveEdits();}
 async function saveInner(){if(busy||bufferConflict||briefDirty)return;if(dirty||visualDirty||pdfPagesDirty){setError('还有文案、视觉方案或PDF样页修改，请使用上方“保存当前修改”一并保存；未提交内容仍保留。');return;}await saveEdits();}
 function discardEdits(){if(!run||busy)return;const seq=generation.current,view=navigation.current;Modal.confirm({title:'放弃本机未提交修改？',content:'已保存的工作记录、旧图和草稿保持不变。',okText:'放弃修改',cancelText:'继续编辑',onOk:()=>{if(seq!==generation.current||view!==navigation.current||liveRecord.current?.id!==run.id||liveRecord.current?.row_version!==run.row_version)return;removeCourseEditBuffer(editScope(run.id));receive(run);}});}
 async function showPrompt(purpose:'copy'|'visual'='copy'){
  if(!run||busy||bufferConflict||briefDirty||run.data.operation?.status==='generating')return;
  if(purpose==='visual'&&(dirty||!run.approved.copy)){setError('请先保存并确认当前文案，再规划图片。');return;}
  if(purpose==='visual'&&!requireCoverSample())return;
  if(purpose==='visual'){const issue=pdfPageIssue(pdfPagePlan,run.data.source.page_count,plan?.template_id==='magazine-a'?9:8);if(issue){setError(issue);return;}}
  if(purpose==='visual'&&innerDirty&&innerPlan&&plan){const issue=innerPlanIssue(innerPlan,plan,run.data.source.page_count,true);if(issue){setError(issue);return;}}
  await action('准备生成内容',async viewCurrent=>{
   let current=run;
   if(purpose==='visual'&&(visualDirty||innerDirty||pdfPagesDirty)){
    current=await visualWorkflowAction<Run>(`/${run.id}`,{expected_version:run.row_version,...(visualDirty?{visual_plan:plan}:{}),...(innerDirty?{set_plan:innerPlan}:{}),...(pdfPagesDirty?{pdf_page_plan:pdfPagePlan}:{})},'patch');removeCourseEditBuffer(editScope(run.id));receive(current);bundleKey.current=crypto.randomUUID();
   }
   const result=await visualWorkflowAction<Prompt>(`/${current.id}/prompts?purpose=${purpose}`,{});
   if(viewCurrent()){setPrompt(result);setConsent(false);aiKey.current=crypto.randomUUID();if(purpose==='visual')bundleKey.current=crypto.randomUUID();}
  });
 }

 async function approve(stage:string){if(!run)return;await act('approve',{stage,reviewed:!!checks[stage],...(stage==='set'?{combined_review:true}:{}),limited_sources_reviewed:stage==='copy'&&!!checks.copy&&!!run.data.evidence_review?.limited,digest:run.digests[stage]},'人工确认');}
 async function approveAndExport(){
  if(!run||busy||hasEdits||bufferConflict||!checks.set||!run.data.images.length||!run.approved.copy||run.data.operation?.status==='generating')return;
  await action('审核并另存新草稿',async viewCurrent=>{
   let current=run;
   if(!current.approved.set){current=await visualWorkflowAction<Run>(`/${current.id}/approve`,{expected_version:current.row_version,stage:'set',reviewed:true,combined_review:true,digest:current.digests.set});receive(current);}
   const saved=await visualWorkflowAction<Run>(`/${current.id}/export`,{expected_version:current.row_version,reviewed:true,digest:current.digests.set});
   receive(saved);if(viewCurrent()){showStep(4);setNotice('已审核并另存为一篇新草稿，所有旧稿保留。');}await refreshHistoryAfterMutation();
  });
 }
 function openBackground(slot:string,asset?:Asset){setBgOptions({slot,style:asset?.background?.style||'paper-depth',strength:asset?.background?.strength||'balanced'});setBgPrompt(null);setBgConsent(false);bgKey.current=crypto.randomUUID();}
 function changeBackground(p:Partial<BackgroundOptions>){setBgOptions(v=>v?{...v,...p}:v);setBgPrompt(null);setBgConsent(false);}
 async function refreshAfterBackgroundError(id:number){const seq=generation.current;try{receive(await visualWorkflowGet<Run>(`/${id}`));}catch{if(seq===generation.current)setNotice('暂时无法读取最新请求状态，请刷新工作记录后再继续；已生成的背景不会自动重做。');}}
 async function prepareBackground(){if(!run||!bgOptions)return;await action('整理背景提示词',async viewCurrent=>{try{const result=await visualWorkflowAction<BackgroundPrompt>(`/${run.id}/background-plan`,{expected_version:run.row_version,...bgOptions});if(viewCurrent()){setBgPrompt(result);setBgConsent(false);}}catch(e){if(!(e instanceof CourseContextChanged))await refreshAfterBackgroundError(run.id);throw e;}});}
 async function submitBackground(id:number,body:Record<string,unknown>,slot:string,resuming=false,viewCurrent=()=>true){
  let r:Run;
  try{r=await visualWorkflowAction<Run>(`/${id}/generate-background`,body);}catch(e){if(!(e instanceof CourseContextChanged))await refreshAfterBackgroundError(id);throw e;}
  receive(r);if(viewCurrent())showStep(slot==='cover'?3:4);setNotice(resuming?'已复用保存的背景完成本机合成，未调用图片模型。新图等待人工审核，旧图保留。':'新图已另存，等待人工审核。真实讲义、Logo和文字由本机合成，旧图仍在历史版本中。');await refreshHistoryAfterMutation();
 }
 async function generateBackground(){if(!run||!bgOptions||!bgPrompt)return;await action('生成一张背景并在本机合成，请勿重复提交',viewCurrent=>submitBackground(run.id,{expected_version:run.row_version,...bgOptions,external_consent:bgConsent,plan_digest:bgPrompt.plan_digest,request_key:bgKey.current},bgOptions.slot,false,viewCurrent));}
 async function resumeBackground(key:string,previous:BackgroundRequest){
  if(!run||locked)return;
  await action('复用已生成背景，继续本机合成',async viewCurrent=>{
   const latest=await visualWorkflowGet<Run>(`/${run.id}`);receive(latest);
   const saved=latest.data.background_requests?.[key];
   if(!saved||saved.signature!==previous.signature||saved.status!=='render_failed'||!saved.asset||!saved.consent_digest||!saved.options||saved.asset.request_key!==key){setError('该背景的恢复记录已变化或不完整，请核对最新记录；未调用图片模型。');return;}
   if(latest.data.operation?.status==='generating'){setError('当前内容仍在生成或合成，请完成后刷新；未重复提交。');return;}
   if(saved.input_digest!==latest.digests.set){setError('保存背景后内容已变化，暂不能复用本次合成请求。旧背景和旧图均已保留。');return;}
   if(!(saved.slot==='cover'?latest.approved.copy:latest.approved.cover||latest.data.render_bundle?.status==='ready'&&latest.data.render_bundle.digest===latest.digests.set)){setError('请先确认当前文案，并完成整套图片制作，再继续本机合成。');return;}
   await submitBackground(latest.id,{expected_version:latest.row_version,...saved.options,external_consent:true,plan_digest:saved.consent_digest,request_key:key,local_only:true},saved.slot,true,viewCurrent);
  });
 }
 async function download(a:Asset,source=false){if(!run)return;await action('下载',async()=>{const b=await visualWorkflowImage(run.id,a.id,source),u=URL.createObjectURL(b),link=document.createElement('a');link.href=u;link.download=`${run.data.source.course_code}-${a.slot}.${source?'svg':'png'}`;link.click();URL.revokeObjectURL(u);});}
 function changeCopy(p:Partial<Copy>){if(busy||bufferConflict||briefDirty)return;setCopy(c=>c?{...c,...p}:c);setChecks({});setPrompt(null);}
 async function selectMagazineTemplate(){
  if(!run||busy||bufferConflict||briefDirty||run.data.operation?.status==='generating'||plan?.template_id==='magazine-a')return;
  if(hasEdits){setError('本机修改已保留。请先保存或放弃当前修改，再切换A模板。');return;}
  await action('选择A模板',async viewCurrent=>{
   const result=await visualWorkflowAction<Run>(`/${run.id}/select-template`,{expected_version:run.row_version,template_id:'magazine-a'});
   receive(result);if(viewCurrent()){showStep(2);setNotice('A模板已加入本记录：4张干货＋9张原样PDF预览。填写本篇内容后制作；旧图保留在历史版本。');}await refreshHistoryAfterMutation();
  });
 }
 function changePlan(p:Partial<Plan>){if(busy||bufferConflict||briefDirty)return;setPlan(v=>v?{...v,...p}:v);setChecks({});}
 function changeInner(p:Partial<SetPlan>){if(busy||bufferConflict||briefDirty)return;setInnerPlan(v=>v?{...v,...p}:v);setChecks({});}
 function changeInnerPages(value:string){if(busy||bufferConflict||briefDirty)return;setInnerPagesText(value);changeInner({sample_pages:value.split(/[,，\s]+/).filter(Boolean).map(Number)});}
 function changeExplanation(index:number,p:Partial<Explanation>){if(busy||bufferConflict||briefDirty)return;setInnerPlan(value=>value?{...value,extra_explanations:value.extra_explanations.map((item,i)=>i===index?{...item,...p}:item)}:value);setChecks({});}
 function changePdfPages(value:string){
  if(busy||bufferConflict||briefDirty)return;
  setPdfPagesText(value);setPdfPagePlan(parsePdfPageText(value));setChecks({});pdfPagesKey.current=crypto.randomUUID();
 }
 function normalizePdfPageInput(){if(busy||bufferConflict||briefDirty)return;setPdfPagesText(pdfPageText(pdfPagePlan||parsePdfPageText(pdfPagesText)));}

 function chooseStep(next:number){if(busy)return;if(briefDirty){setError('单张修改已保存在本机。请先继续完成，或放弃本张修改，再编辑其他步骤。');return;}showStep(next);}
 function changeBrief(p:Partial<Brief>){if(busy||bufferConflict)return;setBrief(b=>b?{...b,...p}:b);}
 function discardBrief(){if(!run||busy)return;const seq=generation.current,view=navigation.current;Modal.confirm({title:'放弃这张图的未提交修改？',content:'保留原图片及其他文案和方案修改。',okText:'放弃本张修改',cancelText:'继续编辑',onOk:()=>{if(seq!==generation.current||view!==navigation.current||liveRecord.current?.id!==run.id||liveRecord.current?.row_version!==run.row_version)return;setEditing(null);setBrief(null);setEditOpen(false);}});}
 async function submitRevision(){if(!run||!editing||!brief||busy||dirty||visualDirty||innerDirty||pdfPagesDirty||bufferConflict||run.data.operation?.status==='generating')return;const target=editing.kind==='cover'&&!run.data.images.length?2:4;await action('修改单张并出图',async viewCurrent=>{const r=await visualWorkflowAction<Run>(`/${run.id}/revise`,{expected_version:run.row_version,asset_id:editing.id,brief});removeCourseEditBuffer(editScope(run.id));receive(r);if(viewCurrent())showStep(target);await refreshHistoryAfterMutation();});}
 const locked=!!busy||hasEdits||!!bufferConflict||run?.data.operation?.status==='generating';
 const lockReason=busy?`正在${busy}，完成后可继续。`:bufferConflict?'请先处理上方保留的版本冲突。':briefDirty?'请先继续或放弃当前单张修改。':dirty||visualDirty||innerDirty||pdfPagesDirty?'请先点击当前页面的“保存当前修改”，再继续制作和审核。':run?.data.operation?.status==='generating'?'当前正在制作，请完成后刷新。':'';
 const canEditInner=!!run&&(run.approved.cover||run.data.render_bundle?.status==='ready'&&run.data.render_bundle.digest===run.digests.set);
 const pendingBackgrounds=run?.data.visual_plan.template_id==='magazine-a'?[]:Object.entries(run?.data.background_requests||{}).filter(([,request])=>request.status==='render_failed'&&!!request.asset).sort(([,a],[,b])=>(b.at||'').localeCompare(a.at||''));
 const labels=['选定PDF与研究','文案审核','图片规划与制作','成品审核与另存'];
 const currentEntryMode=entryMode(run?.data.entry_mode);const candidateStale=pdfVisualStale(run?.data.visual_candidate);
 const visibleStep=step>=4?3:step>=2?2:step;
 const templates=catalog?.templates||defaultTemplates,goals=catalog?.writing_goals||defaultGoals,densities=catalog?.densities||defaultDensities;
 const innerTextLimit=!plan?.template_id||plan.template_id==='legacy'||plan.template_id==='magazine-a'?800:plan.density==='compact'?110:200;
 const selectedCoverPage=plan&&run?coverSamplePage(plan,run.data.source.page_count):null;
 const coverSelectionIssue=plan&&run?coverSampleIssue(plan,run.data.source.page_count):'';
 const production=copy&&plan&&innerPlan?productionReadiness(copy,plan,innerPlan,pdfPagePlan):null;
 const plannedCount=production?.plannedCount||0;
 function HistoryGallery({assets}:{assets:Asset[]}){return <div className="vd-gallery">{assets.map(a=><Card key={a.id} size="small" title={a.role}><Picture run={run!.id} asset={a}/><Button disabled={!!busy} style={{marginTop:12}} onClick={()=>void download(a)}>下载旧图</Button>{a.svg_file&&<Collapse size="small" style={{marginTop:10}} items={[{key:"source",label:"高级：旧版源文件",children:<Button disabled={!!busy} onClick={()=>void download(a,true)}>下载 SVG 源文件</Button>} ]}/>}</Card>)}</div>;}
 function reviewGallery(assets:Asset[]){return <ReviewGallery run={run!.id} assets={assets} rawPdf={plan?.template_id==='magazine-a'} locked={!!locked} lockReason={lockReason} busy={!!busy} onEdit={asset=>{if(asset.kind==='pdf-page'&&plan?.template_id==='magazine-a'){pdfPickerRequested.current=true;setProductionOptions(['remake']);}else setImageAction({slot:asset.slot,asset});}} onDownload={(asset,source)=>void download(asset,source)}/>;}
 function editImage(asset:Asset){setImageAction(null);setEditing(asset);setBrief({...asset.brief,nodes:asset.brief.nodes||[]});setEditOpen(true);}
 function pdfPageControls(){if(!run)return null;return <CoursePdfPagesPanel requiredCount={plan?.template_id==='magazine-a'?9:8} raw={plan?.template_id==='magazine-a'} pageCount={run.data.source.page_count} pageText={pdfPagesText} enabled={!!pdfPagePlan} imageCount={run.data.images.length} tailImageCount={run.data.images.filter(asset=>asset.kind==='collage'||asset.kind==='pdf-page').length} hasOldCollages={run.data.images.some(asset=>asset.kind==='collage')} disabled={!!busy||!!bufferConflict||briefDirty||!run.approved.copy||run.data.operation?.status==='generating'} otherEdits={dirty||visualDirty||innerDirty||briefDirty} onChange={changePdfPages} onNormalize={normalizePdfPageInput} onEnable={()=>changePdfPages(pdfPagesText)} onAppend={()=>void appendPdfPages()}/>;}
 function apiImageControls(){
  if(!run||!plan||!production)return null;
  const disabled=!!busy||briefDirty||!!bufferConflict||run.data.operation?.status==='generating';
  const needsPlanning=production.needsPlanning||candidateStale;
  return <section className="vd-production-panel" aria-label="本篇图片制作">
   <div className="vd-production-top"><div><Title level={4}>{run.data.source.university} · {run.data.source.course_code}</Title><Text>本篇计划：{production.knowledgeCount}张干货{production.pdfCount?` ＋ ${production.pdfCount}张真实PDF`:''} · {plannedCount}张</Text></div><Tag>{needsPlanning?'待规划图片内容':'图片内容已就绪'}</Tag></div>
   <div className="vd-production-modes" role="group" aria-label="图片制作方式">
    {plan.template_id==='magazine-a'&&<button type="button" disabled={disabled} className={imageMode==='api'?'selected':''} aria-pressed={imageMode==='api'} onClick={()=>changeImageMode('api')}><strong>API设计整张图</strong><span>知识图按服务商计费，调用前核对提示词和张数</span></button>}
    <button type="button" disabled={disabled} className={imageMode==='local'?'selected':''} aria-pressed={imageMode==='local'} onClick={()=>changeImageMode('local')}><strong>本机模板排版</strong><span>使用已选模板，不调用图片API</span></button>
   </div>
   <div className="vd-production-pages" aria-label="本篇知识图内容">{production.pages.map((page,index)=><div key={page.slot}><Text type="secondary">{index+1} · {page.role}</Text><strong>{page.ready?page.title:'待按当前文案规划'}</strong></div>)}</div>
   <Paragraph type="secondary">大学与课程代码醒目展示，沿用{run?.data.brand.name}真实Logo、白底深蓝橙色。{production.pdfCount}张PDF样页按原页码逐张放在末尾，本机直接导出。</Paragraph>
   {needsPlanning&&<Paragraph>先基于已确认文案规划4张图的具体内容，再按上面选择的方式制作。文本模型调用前会显示摘录和接收方。</Paragraph>}
   <Space wrap className="vd-production-actions"><Button type="primary" icon={<FileImageOutlined/>} disabled={disabled} onClick={()=>void startProduction()}>{!run.approved.copy||dirty?'先核对文案':pdfPagesDirty&&run.data.images.length&&!visualDirty&&!innerDirty?`只更新${production.pdfCount}张PDF样页`:needsPlanning?'规划图片内容，继续制作':imageMode==='api'?(run.data.images.length?'查看API提示词，另做一套':'查看API提示词并制作整套图'):visualDirty||innerDirty||pdfPagesDirty?'保存方案并制作整套图':run.data.images.length?'按当前方案另做一套（本机）':'制作封面和整套图'}</Button>{imageMode==='api'&&!needsPlanning&&<Button disabled={disabled} onClick={()=>void startProduction('cover')}>先试做1张封面</Button>}{run.data.images.length>0&&<Button disabled={disabled} onClick={()=>chooseStep(4)}>审核已有{run.data.images.length}张图</Button>}</Space>
  </section>;
 }

 function newRecordControls(){return <><CourseBrandSelect value={newBrandId} onChange={id=>{setNewBrandId(id);createKey.current=crypto.randomUUID();}} disabled={!!busy} label="新作品的品牌"/><Select aria-label="选择课程PDF" showSearch disabled={!!busy} filterOption={false} onSearch={q=>void searchMaterials(q)} onChange={id=>{createKey.current=crypto.randomUUID();setNewBrandId('');changeContext({file_id:String(id)});}} value={material} placeholder="搜索课程代码或PDF名称" style={{width:'100%'}} options={creationMaterials.map(f=>({value:f.id,label:`${f.university} · ${f.course_code} · ${f.filename}`}))}/><CourseEntryChoices selected={newEntryMode} disabled={!!busy||hasEdits||!!bufferConflict} onSelect={chooseNewEntryMode}/><Button block type="primary" icon={<PlusOutlined/>} disabled={!!busy||!material||!newBrandId||hasEdits||!!bufferConflict} onClick={()=>void create()}>{fileContext?'用当前PDF开始':'用所选PDF开始'}</Button><Paragraph type="secondary" style={{marginTop:12}}>新建待审核工作记录，复用当前PDF版本；原件和旧稿保留，不自动调用AI。</Paragraph></>;}


 return <div className="visual-workbench">
  <div className="vd-heading"><div><Text type="secondary">COURSE VISUAL WORKBENCH</Text><Title level={2}>课程图文工作台</Title><Paragraph type="secondary">选定PDF，确认文案后直接制作整套图；成品审核后另存新草稿。</Paragraph></div><Space wrap><Link to="/platforms/xhs/course-center"><Button>我的课程创作</Button></Link><Button onClick={()=>setRecordsOpen(true)}>资料与工作记录</Button>{run&&<Tooltip title={hasEdits?'先保存当前修改，再另建优化版本':'复制当前文案与方案为待审核的新记录，原稿与旧图保留'}><span><Button disabled={!!busy||hasEdits||!!bufferConflict||run.data.operation?.status==='generating'} onClick={()=>void forkRun()}>另建优化版本，保留本稿</Button></span></Tooltip>}<Button icon={<ReloadOutlined/>} disabled={!!busy||(hasEdits&&bufferStatus.startsWith('无法'))} onClick={()=>void action('刷新',async()=>{await loadHistory();if(run)receive(await visualWorkflowGet<Run>(`/${run.id}`));})}>刷新</Button></Space></div>
  {error&&<Alert type="error" message={error} closable onClose={()=>setError('')} style={{marginBottom:16}}/>}{notice&&<Alert type="success" message={notice} style={{marginBottom:16}}/>}
  {historyNotice&&<Alert type="warning" message={historyNotice} closable onClose={()=>setHistoryNotice('')} style={{marginBottom:16}}/>}
  {bufferStatus&&(!hasEdits||bufferStatus.startsWith('无法'))&&<Alert type={bufferStatus.startsWith('无法')?'warning':'info'} message={bufferStatus} style={{marginBottom:16}}/>}
  {bufferConflict&&run&&<Alert id="vd-buffer-conflict" type="warning" message="检测到较早版本的本机编辑，未自动覆盖最新工作记录。" description={<Space wrap><Button onClick={()=>{const b=bufferConflict.value;if(b.editingId&&!([...(run.data.cover?[run.data.cover]:[]),...run.data.images]).some(a=>a.id===b.editingId)){setError('对应图片已经更新，不能自动应用旧的单张修改；可复制保留内容再人工调整。');return;}applyEditor(run,b);setBufferConflict(null);}}>将保留内容放回编辑器，重新核对</Button><Paragraph copyable={{text:JSON.stringify(bufferConflict.value,null,2)}}>复制保留的修改</Paragraph></Space>} style={{marginBottom:16}}/>}
  <div className="vd-layout">
  <main><Spin spinning={!!busy} tip={busy?`${busy}${apiImageProgress?` · ${apiImageProgress}`:''}`:undefined}>{!run||!copy||!plan||!innerPlan?<Card title="选一份PDF，开始制作课程图文">{newRecordControls()}</Card>:<>
   <Card className="vd-summary"><Space wrap><Tag color="blue">{run.data.source.university} · {run.data.source.course_code}</Tag><Tag>{run.data.brand.name}</Tag><Tag>内容版本 {run.data.revision}</Tag><Tag color="cyan">{currentEntryMode==='pdf-driven'?'PDF直接选题':'小红书问题研究'}</Tag>{currentEntryMode==='pdf-driven'&&step!==0&&<Button size="small" disabled={!!busy||briefDirty} onClick={()=>chooseStep(0)}>查看PDF选题与文案入口</Button>}</Space><Paragraph style={{margin:'12px 0 0'}}>{run.data.source.filename}</Paragraph><Text type="secondary">{run.data.source.page_count} 页 · 只保存本机草稿</Text></Card>
   {!!pendingBackgrounds.length&&<Card title="已保存背景 · 待本机合成"><Paragraph>图片模型已返回背景。可直接继续本机排版，保留原背景和旧图，不再调用图片模型。</Paragraph>{pendingBackgrounds.map(([key,request])=>{const current=request.input_digest===run.digests.set,complete=!!request.consent_digest&&!!request.options&&request.asset?.request_key===key,approved=request.slot==='cover'?run.approved.copy:canEditInner;return <div key={key} style={{marginBottom:12}}><Space wrap><Tag>{request.slot==='cover'?'封面':run.direction.pages.find(p=>p.slot===request.slot)?.title||'内页'}</Tag><Text type="secondary">{request.at}</Text><Button disabled={locked||!current||!complete||!approved} onClick={()=>void resumeBackground(key,request)}>复用已生成背景，继续本机合成</Button></Space>{!complete?<Paragraph type="secondary">这条旧记录缺少原请求信息，无法安全恢复；背景文件已保留，未新建生图请求。</Paragraph>:!current?<Paragraph type="secondary">内容已在保存背景后变化，请先核对版本；当前请求不会自动重做。</Paragraph>:!approved?<Paragraph type="secondary">请先确认文案并完成整套制作，再继续本机合成。</Paragraph>:null}</div>;})}</Card>}
   <Steps current={visibleStep} onChange={index=>chooseStep(index===3?4:index)} size="small" items={labels.map((title,i)=>({title,status:i===1&&run.approved.copy||i===3&&run.approved.set?'finish':i===visibleStep?'process':'wait'}))}/>
   {(hasEdits||bufferConflict)&&<Alert className="vd-pending-actions" type="warning" showIcon
     message={bufferConflict?'先核对保留的版本冲突':briefDirty?(dirty||visualDirty||innerDirty||pdfPagesDirty?'整篇内容与单张图片各有未提交修改':'这张图片还有未提交的修改'):`有未保存的${[dirty?'文案与来源选择':'',visualDirty?'视觉方案':'',innerDirty?'内页扩充':'',pdfPagesDirty?'PDF样页选页':''].filter(Boolean).join('、')}`}
     description={bufferConflict?'上方保留了两份内容，请先选择采用哪份。':pdfPagesDirty&&!dirty&&!visualDirty&&!innerDirty&&!briefDirty?`PDF选页尚未提交。按新选页只制作末尾${plan.template_id==='magazine-a'?9:8}张独立样页，现有封面和讲解保留。`:briefDirty?(dirty||visualDirty||innerDirty||pdfPagesDirty?'两份修改都已保留。请先复制单张修改备份，再放弃本张修改以保存整篇；不会删除原图或旧稿。':'继续单张编辑即可提交新版本，或明确放弃本张修改；当前旧图仍可放大、下载。'):(dirty||visualDirty||pdfPagesDirty?'可直接在这里保存。保存会建立新的制作版本；当前封面与旧图保留在历史版本，需要按新内容重新制作、审核。放大图片、下载和查看制作信息仍可使用。':'内页扩充可直接保存，当前文案和已确认封面保留；按新计划生成整套后重新审核，旧图仍在历史版本。')}
     action={<Space wrap>{!bufferConflict&&(briefDirty?<><Button type="primary" disabled={!!busy} onClick={()=>setEditOpen(true)}>查看单张修改</Button>{(dirty||visualDirty||innerDirty||pdfPagesDirty)&&<Paragraph copyable={{text:JSON.stringify(brief,null,2)}}>复制单张修改备份</Paragraph>}<Button disabled={!!busy} onClick={discardBrief}>{dirty||visualDirty||innerDirty?'保留整篇，放弃本张修改':'放弃本张修改'}</Button></>:<><Button type="primary" icon={<SaveOutlined/>} loading={busy==='保存修改'||busy==='保存内页扩充'} disabled={!!busy||run.data.operation?.status==='generating'} onClick={()=>void (pdfPagesDirty&&!dirty&&!visualDirty&&!innerDirty&&run.data.images.length?appendPdfPages():saveEdits())}>{pdfPagesDirty&&!dirty&&!visualDirty&&!innerDirty&&run.data.images.length?`按新选页制作${plan.template_id==='magazine-a'?9:8}张独立样页`:'保存当前修改'}</Button><Button disabled={!!busy} onClick={()=>chooseStep(dirty?1:visualDirty||pdfPagesDirty?2:4)}>查看修改内容</Button></>)}<Button disabled={!!busy} onClick={discardEdits}>放弃本机修改</Button></Space>}/>}
   {step===0&&<>
    <CourseEntryChoices selected={currentEntryMode} disabled={!!busy||!!bufferConflict||briefDirty} onSelect={mode=>void selectEntryMode(mode)}/>
    {currentEntryMode==='pdf-driven'?<Card title="从PDF提炼痛点和卖点"><Paragraph>读取当前讲义，提炼学生可能卡住的地方、资料能够提供的真实帮助和适合的选题，再生成待审核文案。无需先搜索笔记或选择小红书账号。</Paragraph><Paragraph type="secondary">点击后先在本机读取文字，并显示将发送给哪个文本模型、哪些摘录；你确认同意后才调用AI。分析出的痛点是教学推断，不代表真实评论或购买需求。</Paragraph><Button type="primary" disabled={!!busy||!!bufferConflict||briefDirty||visualDirty||innerDirty||pdfPagesDirty||run.data.operation?.status==='generating'} onClick={()=>void preparePdfAnalysis()}>{dirty?'保存文案改动并准备PDF分析':run.data.pdf_analysis?'重新分析PDF与当前选题':'分析PDF，生成选题与文案'}</Button>{run.data.pdf_analysis&&<><PdfAnalysisReview analysis={run.data.pdf_analysis} disabled={!!busy||!!bufferConflict||briefDirty} onTopic={choosePdfTopic}/><Button style={{marginTop:16}} onClick={()=>chooseStep(1)}>查看已生成的文案</Button></>}</Card>:<>
    <Card title="Spider 课程选题研究"><Space.Compact block><Input aria-label="课程研究关键词" value={keyword} onChange={e=>setKeyword(e.target.value)} placeholder="课程代码或相关主题"/><Select aria-label="搜索排序" value={sort} onChange={setSort} options={[{value:2,label:'最多点赞'},{value:4,label:'最多收藏'},{value:3,label:'最多评论'}]}/><Button type="primary" disabled={locked||!account||!keyword.trim()} onClick={()=>void act('search',{keyword,account_id:account,sort},'Spider搜索')}>搜索笔记</Button></Space.Compact><Select aria-label="小红书PC搜索账号" style={{minWidth:220,marginTop:12}} value={account} onChange={setAccount} options={accounts.map(a=>({value:a.id,label:a.nickname||String(a.id)}))}/><Paragraph type="secondary" style={{marginTop:12}}>搜索与读取由你手动触发。保留来源和日期；历史高互动与资料获取兴趣不代表当前热榜或付费成交。需要官方验证时请手动完成后重试。</Paragraph></Card>
    {run.data.evidence.map(e=><Card key={e.id} size="small"><Space align="start"><Checkbox aria-label={`选用来源 ${e.title}`} disabled={!!busy||!!bufferConflict||briefDirty} checked={selected.includes(e.id)} onChange={x=>setSelected(v=>x.target.checked?[...v,e.id]:v.filter(id=>id!==e.id))}/><div>{e.source_url?<a href={e.source_url} target="_blank" rel="noreferrer">{e.title}</a>:<Text strong>{e.title}</Text>}{e.metrics&&<div className="vd-metrics">赞 {e.metrics.likes??'未知'} · 藏 {e.metrics.collects??'未知'} · 评 {e.metrics.comments??'未知'} · {e.content_status==='detail'?'已读正文':'搜索摘要'}</div>}<Text type="secondary">发布：{e.published_at||'未知'}　观察：{e.observed_at||'未知'}</Text></div></Space><Collapse style={{marginTop:12}} items={[{key:'body',label:'正文与评论',children:<><Paragraph style={{whiteSpace:'pre-wrap'}}>{e.content}</Paragraph>{(e.comments||[]).map(c=><Paragraph key={c.comment_id}><Tag>{c.is_author===true?'作者':c.is_author===false?'非作者，身份未核实':'身份未核实'}</Tag>{c.content}</Paragraph>)}{!e.comments?.length&&<Text type="secondary">未读取到评论；不补造问题。</Text>}</>} ]}/>{e.source_url&&<Button disabled={locked||!account||!run.data.research_id} style={{marginTop:12}} onClick={()=>void act('read',{source_id:e.id,account_id:account},'读取正文与评论')}>读取正文与评论</Button>}</Card>)}
    {!!run.data.analysis?.angles?.length&&<Card title="待判断的选题线索">{run.data.analysis.angles.map((a,i)=><Paragraph key={i}><strong>{a.topic}</strong> · {a.basis}<Button type="link" onClick={()=>{changeCopy({topic:a.topic});chooseStep(1);}}>作为候选</Button></Paragraph>)}</Card>}
    <Button type="primary" onClick={()=>chooseStep(1)}>进入选题与文案</Button>
    </>}
   </>}
   {step===1&&<Card title="选题与文案 · 人工审核节点一" extra={run.approved.copy?<Tag color="success">当前版本已确认</Tag>:<Tag color="gold">待审核</Tag>}>
    {run.data.evidence_review&&<Alert type={run.data.evidence_review.limited?'warning':'info'} showIcon message={run.data.evidence_review.message} style={{marginBottom:14}}/>}
    {currentEntryMode==='pdf-driven'&&run.data.pdf_analysis&&<PdfAnalysisReview analysis={run.data.pdf_analysis} disabled={!!busy||!!bufferConflict||briefDirty} onTopic={choosePdfTopic}/>}
    <fieldset disabled={!!busy||!!bufferConflict||briefDirty} style={{border:0,padding:0,margin:0}}><Alert type="info" showIcon message="先确定这篇给学生什么收获" description="根据学生问题和真实讲义写文案；确认后直接进入图片规划，配图时沿用当前文案。"/><label>文案目标</label><Select aria-label="文案目标" value={copy.goal||'student-question'} onChange={(goal:CopyGoal)=>changeCopy({goal})} style={{width:'100%'}} options={goals.map(item=>({value:item.id,label:item.name}))}/><Paragraph type="secondary" style={{marginTop:8}}>{goals.find(item=>item.id===(copy.goal||'student-question'))?.description}</Paragraph><label>本篇选题</label><Input value={copy.topic} onChange={e=>changeCopy({topic:e.target.value})}/><label>学生看完能做什么</label><Input.TextArea rows={2} value={copy.takeaway} onChange={e=>changeCopy({takeaway:e.target.value})}/><label>标题 · {copy.title.length}/20 字</label><Input value={copy.title} onChange={e=>changeCopy({title:e.target.value})}/><label>正文 · {copy.body.length}/1000 字</label><Input.TextArea rows={13} value={copy.body} onChange={e=>changeCopy({body:e.target.value})}/><label>标签</label><Select mode="tags" style={{width:'100%'}} value={copy.tags} onChange={tags=>changeCopy({tags})}/><Space wrap className="vd-actions"><Button type="primary" disabled={!!busy||!dirty||briefDirty||!!bufferConflict} onClick={()=>void saveCopy()}>保存文案与来源选择</Button>{currentEntryMode==='pdf-driven'?<Button disabled={!!busy||!!bufferConflict||briefDirty||visualDirty||innerDirty||pdfPagesDirty||run.data.operation?.status==='generating'} onClick={()=>void preparePdfAnalysis()}>{dirty?'保存修改并按当前选题重新生成':'按当前选题重新生成文案'}</Button>:<Button disabled={locked||!selected.length} onClick={()=>void showPrompt()}>生成选题与文案</Button>}</Space><Paragraph type="secondary">{currentEntryMode==='pdf-driven'?'文案依据当前讲义生成。学习痛点属于资料分析推断；资料事实仍需人工核对。推荐文案确认后，可直接用候选内容在本机制作4张干货＋9张原样预览。':`已选 ${selected.length} 个来源。可核对外发范围后调用已配置模型；生成后仍需审核。`}</Paragraph>
    <Checkbox checked={!!checks.copy} disabled={locked||run.approved.copy} onChange={e=>setChecks(v=>({...v,copy:e.target.checked}))}>我已核对选题、文案、来源与资料事实。{currentEntryMode==='pdf-driven'?'我已了解学习痛点属于资料分析推断，不代表已验证的评论需求。':run.data.evidence_review?.limited?'我已了解目前只有摘要，不把它当作已验证的学生反馈或热榜依据。':''}</Checkbox><div className="vd-actions"><Button type="primary" icon={<CheckCircleOutlined/>} disabled={locked||!checks.copy||run.approved.copy} onClick={()=>void approve('copy')}>确认文案，进入图片制作</Button>{run.approved.copy&&<Button type="primary" onClick={()=>chooseStep(2)}>继续图片制作</Button>}</div></fieldset>
   </Card>}
   {(step===2||step===3)&&<Card title="图片规划与制作" extra={<Tag>计划 {plannedCount} 张</Tag>}>
    {apiImageControls()}
    {run.data.cover?.api_generated&&!run.data.images.length&&reviewGallery([run.data.cover])}
    {candidateStale&&<Alert type="warning" showIcon message="文案已修改，请核对这4张图的内容是否仍匹配" description={<><Paragraph>可以在下方检查、修改现有图片方案后沿用，不调用AI；也可让AI重新规划。两种方式都不会批准成品，旧稿与旧图保留。</Paragraph><Checkbox checked={!!checks.visualCandidate} disabled={!!busy||dirty||pdfPagesDirty||briefDirty||!!bufferConflict||!run.approved.copy} onChange={e=>setChecks(v=>({...v,visualCandidate:e.target.checked}))}>我已核对当前图片方案与文案一致</Checkbox><Space wrap className="vd-actions"><Button disabled={!!busy||dirty||pdfPagesDirty||briefDirty||!!bufferConflict||!run.approved.copy||!checks.visualCandidate} onClick={()=>void confirmVisualCandidate()}>核对并沿用当前图片方案</Button><Button disabled={locked||!run.approved.copy} onClick={()=>void startProduction('bundle',true)}>用AI重新规划</Button></Space>{!run.approved.copy&&<Button onClick={()=>chooseStep(1)}>先确认修改后的文案</Button>}</>} style={{marginBottom:16}}/>}
    <Collapse className="vd-production-options" activeKey={productionOptions} onChange={keys=>setProductionOptions(Array.isArray(keys)?keys:[keys])} items={[{key:'options',label:'调整模板、图文内容和PDF选页（可选）',children:<>
    {currentEntryMode==='pdf-driven'&&run.data.visual_candidate?.status==='ready'&&<Paragraph type="secondary">已准备与当前文案对应的图片内容，无需再次调用文本模型规划。</Paragraph>}<fieldset disabled={!!busy||!!bufferConflict||briefDirty} style={{border:0,padding:0,margin:0}}><Alert type="info" showIcon message="选版式，再让本篇内容进入模板" description="沿用真实 Logo、白底、深蓝、橙色与完整样张。选好模板和内容后，一次制作封面与内页，再统一审核。"/>{plan.template_id==='magazine-a'?<Paragraph className="vd-magazine-summary">A 杂志讲解版：4张干货＋9张原样PDF预览。知识封面无需选择正文缩略图；原PDF页在末尾逐页展示。</Paragraph>:<section id="vd-cover-sample-picker" className="vd-cover-sample-picker" tabIndex={-1} aria-label="封面正文样张">
     <div className="vd-cover-sample-info"><Title level={5}>封面正文样张</Title><Paragraph>浏览这份PDF的正文，选一页放到封面。第1页不作为正文样张；整套内页的选页保持独立。</Paragraph><Tag color={selectedCoverPage?'blue':coverSelectionIssue?'warning':'default'}>{selectedCoverPage?`当前样张：第 ${selectedCoverPage} 页`:coverSelectionIssue?'尚未选择正文样张':'原版式可使用当前PDF'}</Tag>{selectedCoverPage&&plan.cover_sample_page==null&&<Paragraph type="secondary">沿用这份方案已有的正文样页，也可以重新选。</Paragraph>}{!selectedCoverPage&&coverSelectionIssue&&<Paragraph type="warning">先预览，再点击“用这一页作封面样张”。</Paragraph>}{!selectedCoverPage&&!coverSelectionIssue&&<Paragraph type="secondary">可保留原版式直接制作；切换现代模板时需要正文样张。</Paragraph>}</div>
     {run.data.source.page_count>=2?<CoursePdfInlinePreview key={`${run.id}:${run.data.source.revision_id}`} fileId={run.file_id} revisionId={run.data.source.revision_id} filename={run.data.source.filename} initialPage={selectedCoverPage??2} minPage={2} selectedPage={selectedCoverPage} onSelectPage={page=>changePlan({cover_sample_page:page})} selectionDisabled={!!busy||!!bufferConflict||briefDirty} compact/>:<Alert type={coverSelectionIssue?'warning':'info'} message={coverSelectionIssue?'这份PDF只有封面，现代模板需要正文样张；可保留原版式，或更换包含正文的资料。':'这份PDF只有封面，可保留原版式制作；如需现代模板，请更换包含正文的资料。'}/>}
    </section>}<label>选择模板</label><div className="vd-template-grid" role="group" aria-label="可选视觉模板">{templates.map(template=><button type="button" key={template.id} className={`vd-template-card ${plan.template_id===template.id?'selected':''}`} aria-label={`选择${template.name}模板`} aria-pressed={plan.template_id===template.id} disabled={!!busy||!!bufferConflict||briefDirty} onClick={()=>template.id==='magazine-a'?void selectMagazineTemplate():changePlan({template_id:template.id})}><TemplatePreview template={{...template,preview_available:false}}/><div className="vd-template-description"><strong>{template.name}</strong><p>{template.description}</p><small>适合：{template.suitable_for}</small><span>{plan.template_id===template.id?'已选择':'选择这个模板'}</span></div></button>)}</div>{plan.template_id==='legacy'&&<Paragraph type="secondary">本记录仍保留原版式。选择新模板并保存后才生效，旧封面与旧图会保留在历史版本。</Paragraph>}<label>图内信息标准</label><Select aria-label="图内信息标准" style={{width:'100%'}} value={plan.density||'standard'} onChange={(density:Density)=>changePlan({density})} options={densities.map(item=>({value:item.id,label:item.name}))}/><Paragraph type="secondary" style={{marginTop:8}}>{densities.find(item=>item.id===(plan.density||'standard'))?.description}</Paragraph><Paragraph type="secondary">固定标准：1080×1440、手机阅读优先、醒目的大学和课程代码、真实 Logo 和 PDF、不外加页序。{plan.template_id==='magazine-a'?'A版末尾直接展示原PDF，不加修饰；':'请选正文内容页作样张；'}模板示例仅用于比较版式，不是本篇已生成图片。</Paragraph><Collapse size="small" items={[{key:'style-report',label:'查看本篇视觉判断',children:<div className="vd-style-report">{Object.entries(run.direction.style_report).map(([k,v])=><Paragraph key={k}><Text type="secondary">{{content_type:'内容类型',goal:'目标',emotion:'读者感受',density:'信息密度',primary_style:'主风格',supporting_style:'辅助风格',avoid:'避免',reason:'依据'}[k]||k}：</Text>{v}</Paragraph>)}</div>} ]}/><Paragraph>{run.direction.page_count_reason}</Paragraph><div className="vd-plan-outline">{run.direction.pages.map((page,index)=><div key={page.slot}><Tag>{index+1}</Tag><span>{page.slot.startsWith('sample-')?'真实讲义样张':page.title.replace(/\n/g,' / ')}</span></div>)}</div><Collapse className="vd-plan-details" style={{marginTop:16}} items={[{key:'content',label:'调整图片内容与样张（可选）',children:<><label>原版式构图（仅保留原版式时使用）</label><Select disabled={plan.template_id!=='legacy'} value={plan.style} onChange={style=>changePlan({style})} style={{width:'100%'}} options={[{value:'product-editorial',label:'真实讲义层叠主视觉'},{value:'evidence-editorial',label:'真实封面与样张并列展示'}]}/><label>封面标题（最多两行）</label><Input.TextArea aria-label="封面标题" rows={2} value={plan.cover_lines.join('\n')} onChange={e=>changePlan({cover_lines:cleanLines(e.target.value)})}/><label>封面副标题</label><Input aria-label="封面副标题" value={plan.cover_subtitle||''} onChange={e=>changePlan({cover_subtitle:e.target.value})}/><label>必要的方法说明标题</label><Input aria-label="方法说明标题" value={plan.method_title} onChange={e=>changePlan({method_title:e.target.value})}/><label>{plan.template_id==='magazine-a'?'主讲解正文（4张干货中的第2张）':'方法说明（留空则不生成该页）'}</label><Input.TextArea aria-label="方法说明正文" rows={5} value={plan.method_text} onChange={e=>changePlan({method_text:e.target.value})}/><label>方法页的知识关系</label><Select style={{width:'100%'}} value={plan.method_layout} onChange={method_layout=>changePlan({method_layout})} options={[{value:'editorial',label:'解释与段落层级'},{value:'flow',label:'方法流程与条件'},{value:'comparison',label:'有具体内容的对比'}]}/><Collapse size="small" style={{marginTop:16}} items={[{key:"method-nodes",label:"高级：精细调整图解节点",children:<><Paragraph type="secondary">每行一个节点，用“｜”分隔标题与说明。</Paragraph><Input.TextArea aria-label="图解节点" rows={3} value={plan.method_nodes.join('\n')} onChange={e=>changePlan({method_nodes:cleanLines(e.target.value)})}/></>} ]}/>{plan.template_id!=='magazine-a'&&<><label>使用路线（每行一步）</label><Input.TextArea rows={4} value={plan.usage_steps.join('\n')} onChange={e=>changePlan({usage_steps:cleanLines(e.target.value)})}/><label>了解与购买判断</label><Input.TextArea rows={3} value={plan.cta} onChange={e=>changePlan({cta:e.target.value})}/></>}<Space className="vd-actions"><Button disabled={!!busy||!visualDirty||briefDirty||!!bufferConflict} onClick={()=>void saveVisual()}>仅保存方案</Button></Space></>} ]}/><Collapse items={[{key:'plans',label:'高级：逐张制作说明与提示词',children:run.direction.pages.map(p=><div key={p.slot}><Title level={5}>{p.title}</Title><Paragraph>{p.task} · 布局：{p.layout}</Paragraph><Paragraph copyable={{text:p.prompt}}>复制本张完整视觉提示词</Paragraph></div>)}]}/></fieldset>
    <Collapse className="vd-inner-plan" items={[{key:'inner-plan',label:`内页内容与真实样张 · 计划 ${plannedCount} 张`,children:<fieldset disabled={!!busy||!!bufferConflict||briefDirty} style={{border:0,padding:0,margin:0}}>
     <Paragraph>封面 1 张 · 方法说明 {plan.template_id==='magazine-a'||plan.method_text.trim()?1:0} 张 · 补充干货 {innerPlan.extra_explanations.length} 张{plan.template_id!=='magazine-a'&&<> · 真实样张 {innerPlan.sample_pages.length} 张 · 使用说明 1 张</>}{pdfPagePlan?` · 末尾原样PDF ${pdfPagePlan.pages.length} 张`: ''}</Paragraph>
     <Paragraph type="secondary">仅保存内页扩充会保留当前文案和已确认封面。新增讲解必须有具体内容，样张保留真实原页；重新生成的整套仍需人工审核，旧图不删除。</Paragraph>
     {plan.template_id!=='magazine-a'&&<>
     <label>整套使用的真实 PDF 样页（1至4张）</label><Input aria-label="内页真实PDF样页" value={innerPagesText} onChange={e=>changeInnerPages(e.target.value)} placeholder="例如：4, 6, 9, 12"/>
     <Text type="secondary">页码范围 1–{run.data.source.page_count}，逗号分隔，不重复；选与本篇解释对应的正文页。</Text>
     {innerPlan.sample_pages.map((number,index)=><div className="vd-inner-sample" key={index}><label>样张 {Number.isFinite(number)?number:'待填写'} 的外部说明</label><Input.TextArea aria-label={`样张${index+1}说明`} rows={2} value={innerPlan.sample_instructions[index]||''} onChange={e=>changeInner({sample_instructions:innerPlan.sample_pages.map((_,i)=>i===index?e.target.value:innerPlan.sample_instructions[i]||'')})}/></div>)}
     </>}
     <label>{plan.template_id==='magazine-a'?'补充干货（固定2张）':'补充讲解（最多3张）'}</label>
     {innerPlan.extra_explanations.map((item,index)=><Card size="small" className="vd-inner-explanation" key={index} title={item.title||`待填写的补充讲解 ${index+1}`} extra={plan.template_id!=='magazine-a'&&<Button danger disabled={!!busy||!!bufferConflict||briefDirty} onClick={()=>changeInner({extra_explanations:innerPlan.extra_explanations.filter((_,i)=>i!==index)})}>移除本张计划</Button>}>
      <label>标题</label><Input aria-label={`补充讲解${index+1}标题`} value={item.title} onChange={e=>changeExplanation(index,{title:e.target.value})}/>
      <label>副标题 / 阅读提示</label><Input value={item.subtitle} onChange={e=>changeExplanation(index,{subtitle:e.target.value})}/>
      <label>正文 · {item.text.length}/{innerTextLimit} 字</label><Input.TextArea aria-label={`补充讲解${index+1}正文`} rows={4} value={item.text} onChange={e=>changeExplanation(index,{text:e.target.value})}/>
      {item.text.length>innerTextLimit&&<Text type="danger">超出当前信息标准，请精简后保存；不会自动截断。</Text>}
      <label>内容关系</label><Select style={{width:'100%'}} value={item.layout} onChange={(layout:Explanation['layout'])=>changeExplanation(index,{layout})} options={[{value:'editorial',label:'解释与层级'},{value:'flow',label:'判断流程'},{value:'comparison',label:'具体条件对比'}]}/>
      <label>节点 / 核对点（最多{plan.template_id==='magazine-a'?5:3}条，一行一条）</label><Input.TextArea rows={3} value={item.nodes.join('\n')} onChange={e=>changeExplanation(index,{nodes:cleanLines(e.target.value)})}/>
     </Card>)}
     {plan.template_id!=='magazine-a'&&<Button icon={<PlusOutlined/>} disabled={!!busy||!!bufferConflict||briefDirty||innerPlan.extra_explanations.length>=3} onClick={()=>changeInner({extra_explanations:[...innerPlan.extra_explanations,{title:'',subtitle:'',text:'',layout:'editorial',nodes:[]}]})}>新增补充讲解</Button>}
     {(dirty||visualDirty)&&<Alert type="info" showIcon style={{marginTop:14}} message="同时有文案或视觉方案修改，请使用上方“保存当前修改”一并保存。"/>}
     <Space wrap className="vd-actions"><Button type="primary" loading={busy==='保存内页扩充'} disabled={!!busy||!innerDirty||dirty||visualDirty||briefDirty||!!bufferConflict||run.data.operation?.status==='generating'} onClick={()=>void saveInner()}>保存内页扩充</Button><Text type="secondary">也可直接点击下方“保存方案并制作整套图”，一次完成保存和制作。</Text></Space>
    </fieldset>} ]}/>
    {pdfPageControls()}
    {!run.approved.copy&&<Alert type="info" showIcon message="先确认文案，再制作图片" action={<Button onClick={()=>chooseStep(1)}>返回文案审核</Button>}/>}
    <Space wrap className="vd-actions"><Button disabled={!!busy||dirty||briefDirty||!!bufferConflict||!run.approved.copy} onClick={()=>void startProduction('bundle',true)}>重新规划本篇图片内容</Button></Space>
    </>} ]}/>

   </Card>}
   {step===4&&<Card title="成品审核与另存" extra={!run.data.images.length?<Tag>待生成</Tag>:run.approved.set?<Tag color="success">当前整套已确认</Tag>:<Tag color="gold">待逐张审核</Tag>}>
    <Space wrap className="vd-actions"><Tag>{run.data.images.length} 张实际图片</Tag><Button disabled={!!busy||briefDirty} onClick={()=>chooseStep(2)}>修改图片方案</Button></Space>
    
    {run.data.images.length?<>
     {!run.approved.copy&&<Alert type="info" showIcon message="整套图片已保留，可先逐张预览；修改或另存前请核对文案" action={<Button onClick={()=>chooseStep(1)}>核对当前文案</Button>}/>}
     {reviewGallery(run.data.images)}
     <Paragraph type="secondary">完整样张保留原比例和原页码；细字请打开原图放大查看。任何单张修改都会另存新版本并撤销相应确认。</Paragraph>
     <div className="vd-save">
      {run.data.export?<>
       <Alert type="success" showIcon message={`已另存草稿 #${run.data.export.draft_id}`} description="当前文案与图片已另存，旧稿继续保留。"/>
       <div className="vd-actions">{run.data.export.draft_available===false?<Text type="secondary">原草稿关联暂不可用，文案与图片仍保留在本记录。</Text>:<Link to={`/platforms/xhs/drafts?draft_id=${run.data.export.draft_id}`}>打开这篇草稿</Link>}</div>
      </>:<>
       <Alert type={run.approved.set?'success':'info'} showIcon message={run.approved.set?'成品已确认，可另存新草稿':'请核对封面和全部内页'} description="确认后只另存一篇新草稿，所有旧稿保留。"/>
       <Checkbox checked={!!checks.set} disabled={locked} onChange={e=>setChecks(v=>({...v,set:e.target.checked}))}>我已核对封面及全部内页的文字、公式、真实样张、品牌和整体可读性，同意另存新草稿</Checkbox>
       <Space wrap className="vd-actions"><Button type="primary" disabled={locked||(run.approved.copy&&!checks.set)} onClick={()=>run.approved.copy?void approveAndExport():chooseStep(1)}>{!run.approved.copy?'先核对文案，再确认整套':run.approved.set?'另存为新草稿':'审核通过并另存新草稿'}</Button>{run.approved.copy&&!run.approved.set&&<Button disabled={locked||!checks.set} onClick={()=>void approve('set')}>仅确认成品，暂不另存</Button>}</Space>
      </>}
      <Text type="secondary">{!checks.set&&!run.data.export?'逐张核对后，勾选上方确认项即可启用另存按钮。':''}此处只保存本机草稿，不创建发布任务或开启自动运营。</Text>
     </div>
    </>:<>
     <Alert type="warning" showIcon message="整套图片尚未生成，当前无法审核或另存" description="先完成图片制作；生成后会自动进入这里，逐张审核后另存新草稿。" action={<Button type="primary" disabled={!!busy} onClick={()=>chooseStep(2)}>去制作图片</Button>}/>
     <ol className="vd-set-next-steps"><li>在图片规划中一次制作封面和内页。</li><li>逐张核对文字、公式、品牌与样张，人工确认整套图。</li><li>审核通过后另存一篇新草稿，保留所有旧稿。</li></ol>
     <Text type="secondary">在图片规划中选择API或本机排版，成品统一在这里审核。</Text>
    </>}
    <Collapse activeKey={productionOptions} onChange={keys=>setProductionOptions(Array.isArray(keys)?keys:[keys])} style={{marginTop:20}} items={[{key:'remake',label:'重新制作或调整PDF选页（可选）',children:<>{pdfPageControls()}{apiImageControls()}</>} ]}/>
   </Card>}
   {!!run.data.history.length&&<div id="vd-image-history"><Collapse className="vd-history" activeKey={historyOpen} onChange={keys=>setHistoryOpen(Array.isArray(keys)?keys:[keys])} items={[{key:'history',label:`历史版本与旧图（${run.data.history.length}）`,children:run.data.history.slice().reverse().map(h=><Card key={`${h.revision}-${h.at}`} size="small" title={`内容版本 ${h.revision} · ${h.reason}`} extra={<Button disabled={locked} onClick={()=>void act('restore',{revision:h.revision},'以旧版重新编辑')}>以此版本重新编辑</Button>}><Text type="secondary">{h.at}{h.export?` · 历史草稿 #${h.export.draft_id}`:''}</Text><HistoryGallery assets={h.images.length?h.images:h.cover?[h.cover]:[]}/></Card>)}]}/></div>}
  </>}</Spin></main></div>
  <Drawer title="资料与工作记录" open={recordsOpen} onClose={()=>setRecordsOpen(false)} width={400} className="vd-records-drawer"><Card title="工作记录" size="small">{history.map(h=><button className={`vd-run ${run?.id===h.id?'active':''}`} key={h.id} disabled={!!busy} onClick={()=>void chooseRun(h.id)}><strong>{h.course_code} · #{h.id}</strong><span>{h.title}</span>{h.draft_id&&<small>已另存草稿 #{h.draft_id}</small>}</button>)}{!history.length&&<Empty description={fileContext?"当前PDF暂无工作记录":"从一份真实PDF开始"}/>}</Card><Card title="选择真实资料" size="small">{newRecordControls()}</Card></Drawer>
  <Modal title={imageAction?.asset?'修改当前图片':'制作第一张封面'} open={!!imageAction} onCancel={()=>setImageAction(null)} footer={null} width={580}>
   {imageAction&&<div className="vd-image-options"><Paragraph>选择本次修改方式。所有结果另存新版本，仍需人工审核。</Paragraph>
    {plan?.template_id==='magazine-a'&&['cover','method','method-extra-0','method-extra-1'].includes(imageAction.slot)&&<Card size="small" title="用API重新设计完整图片"><Paragraph>让图片模型重新制作这张知识图。先核对逐字提示词和1次调用范围，其他图片、真实PDF和所有旧图保留。</Paragraph><Button type="primary" disabled={locked||!run?.approved.copy} onClick={()=>void prepareApiImages(imageAction.slot)}>用 API 重新制作这张图</Button></Card>}
    <Card size="small" title={imageAction.asset?.api_generated?'改用本机模板重排 · 保留API旧图':'文字与布局 · 本机处理'}><Paragraph>{imageAction.asset?.api_generated?'用本机模板重新排版当前内容，API原图仍保留。要延续API成图风格，请选上方的API重做。':imageAction.asset?'修改这张图的标题、说明或布局，复用已有背景。':'用真实讲义、Logo 和当前视觉方案制作封面。'}不调用图片模型。</Paragraph><Button type="primary" disabled={locked} onClick={()=>{if(!run?.approved.copy){setImageAction(null);chooseStep(1);return;}if(imageAction.asset)editImage(imageAction.asset);else{setImageAction(null);void act('render',{stage:'cover'},'制作封面');}}}>{!run?.approved.copy?'先核对文案，再修改图片':imageAction.asset?'修改文字与布局':'按当前方案制作封面'}</Button></Card>
    {plan?.template_id!=='magazine-a'&&<>{imageAction.asset?.kind!=='sample'&&imageAction.asset?.kind!=='collage'&&imageAction.asset?.kind!=='pdf-page'&&<Card size="small" title="AI 背景 · 按服务商计费"><Paragraph>只生成背景；真实 PDF、Logo、文字和公式在本机合成。先展示接收方、提示词与外发范围，确认后再调用。</Paragraph><Button disabled={locked||!run?.approved.copy||(imageAction.slot!=='cover'&&!canEditInner)} onClick={()=>{openBackground(imageAction.slot,imageAction.asset);setImageAction(null);}}>设置 AI 背景</Button></Card>}</>}
    <Button type="link" disabled={!!busy||briefDirty} onClick={()=>{setImageAction(null);chooseStep(2);}}>查看整篇视觉方案</Button>
   </div>}
  </Modal>
  <Modal title="AI 背景 · 真实资料在本机合成" open={!!bgOptions&&plan?.template_id!=='magazine-a'} onCancel={()=>{if(!busy){setBgOptions(null);setBgPrompt(null);setBgConsent(false);}}} maskClosable={!busy} closable={!busy} width={760} footer={null}>
   {bgOptions&&<><Paragraph>按 XHS Visual Director 的留白、层级和品牌配色制作背景。真实讲义、中文、课程代码、公式和 Logo 仍由本机排版。每次只制作当前这一张，保留旧图。</Paragraph>
    <label>背景方向</label><Select aria-label="背景方向" disabled={!!busy} style={{width:'100%'}} value={bgOptions.style} onChange={style=>changeBackground({style})} options={[{value:'paper-depth',label:'纸感与光影'},{value:'linear-geometry',label:'轻量几何线条'},{value:'quiet-paper',label:'更简洁的纸感'}]}/>
    <label>装饰强度</label><Select aria-label="装饰强度" disabled={!!busy} style={{width:'100%',marginBottom:16}} value={bgOptions.strength} onChange={strength=>changeBackground({strength})} options={[{value:'balanced',label:'适度，衬托真实讲义'},{value:'light',label:'很轻，留白优先'}]}/>
    <Button disabled={!!busy} onClick={()=>void prepareBackground()}>查看提示词与外发范围</Button>
    {error&&<Alert type="error" message={error} style={{marginTop:16}}/>}
    {bgPrompt&&<><Paragraph style={{marginTop:16}}>接收方：{bgPrompt.model?`${bgPrompt.model.name} · ${bgPrompt.model.model_name} · ${bgPrompt.model.destination}`:'尚未配置默认图片模型'}</Paragraph><Paragraph>{bgPrompt.scope}</Paragraph><Paragraph>生成 1 张背景，{bgPrompt.estimated_cost}。修改已有文字和布局可复用背景，不再次调用图片模型。</Paragraph>
     <Collapse items={[{key:'background-prompt',label:'查看完整背景提示词',children:<pre className="vd-pre">{bgPrompt.prompt}</pre>}]}/>
     {!bgPrompt.supported&&<Alert type="warning" message="请先配置火山方舟北京区 Seedream 5.0 Flash / Pro 图片模型"/>}
     <Checkbox style={{marginTop:16}} disabled={!!busy||!bgPrompt.supported||!bgPrompt.model?.configured} checked={bgConsent} onChange={e=>setBgConsent(e.target.checked)}>同意将上述背景提示词发送给显示的模型，生成一张待审核图片</Checkbox>
     <Button type="primary" loading={!!busy} disabled={!bgConsent||!!busy||!bgPrompt.supported||!bgPrompt.model?.configured} style={{marginTop:16}} onClick={()=>void generateBackground()}>生成一张背景并合成新图</Button>
    </>}
   </>}
  </Modal>
  <PdfAnalysisConsent plan={pdfPrompt} consent={pdfConsent} busy={!!busy} onConsent={setPdfConsent} onCancel={()=>{if(!busy){setPdfPrompt(null);setPdfConsent(false);}}} onGenerate={()=>void generateFromPdf()}/>
  <ApiImageConsent plan={apiImagePlan} consent={apiImageConsent} busy={!!busy} error={error} onConsent={setApiImageConsent} onCancel={()=>{if(!busy){setApiImagePlan(null);setApiImageConsent(false);}}} onGenerate={()=>void generateApiImages()}/>
  <Modal title={prompt?.purpose==='visual'?'规划本篇图片内容':'生成选题与文案'} open={!!prompt} onCancel={()=>setPrompt(null)} width={760} footer={null}>{prompt&&<><Paragraph copyable={{text:prompt.prompt}}>{prompt.purpose==='visual'?productionIntent.current.mode==='api'?'文本模型只规划4张图的内容。随后另行显示图片API提示词和计费张数，经你确认后才生图。':'文本模型规划图片内容后，按所选模板在本机制作整套图，再统一审核。':'依据所选来源与真实讲义生成待审核选题和文案。'}</Paragraph><Collapse items={[{key:'p',label:'查看完整提示词',children:<pre className="vd-pre">{prompt.prompt}</pre>}]}/><Paragraph style={{marginTop:16}}>接收方：{prompt.model?`${prompt.model.name} · ${prompt.model.model_name} · ${prompt.model.destination}`:'尚未配置默认文本模型'}</Paragraph><Paragraph>{prompt.scope}</Paragraph><Checkbox checked={consent} disabled={!prompt.model?.configured||!!busy} onChange={e=>setConsent(e.target.checked)}>我已检查上述内容，同意发送给显示的AI服务生成{prompt.purpose==='visual'?productionIntent.current.mode==='api'?'图片内容方案；本次不调用图片API':'图片内容方案，并在本机制作待审核整套图':'待审核文案'}</Checkbox><Button type="primary" disabled={!consent||!!busy||!prompt.model?.configured} style={{marginTop:16}} onClick={()=>void act(prompt.purpose==='visual'?'generate-visual-plan':'generate-copy',{external_consent:consent,plan_digest:prompt.plan_digest,request_key:aiKey.current},prompt.purpose==='visual'?'规划本篇图片内容':'生成待审核文案',prompt.purpose==='visual'?productionIntent.current:undefined)}>{prompt.purpose==='visual'?(productionIntent.current.mode==='api'?'规划内容，进入API确认':'规划内容并在本机制作'):'生成待审核文案'}</Button></>}</Modal>
  <Drawer title="调整这张图，另存新版本" open={!!editing&&editOpen} onClose={()=>setEditOpen(false)} width={580}>{editing&&brief&&<fieldset disabled={!!busy||!!bufferConflict} style={{border:0,padding:0,margin:0}}><Paragraph>保留当前旧图。标题和布局修改在本机完成，已有AI背景会复用，不再调用生图接口。{editing.kind==='sample'||editing.kind==='collage'||editing.kind==='pdf-page'?'只调整样张外部说明，原PDF正文与公式保持原样。':'修改后需要重新审核相应图稿。'}</Paragraph>{(dirty||visualDirty||innerDirty||pdfPagesDirty)&&<Alert type="warning" message="本机同时保留了整篇修改，请先处理上方修改提示再出图。" description={<Space wrap><Paragraph copyable={{text:JSON.stringify(brief,null,2)}}>复制单张修改备份</Paragraph><Button disabled={!!busy} onClick={discardBrief}>保留整篇，放弃本张修改</Button></Space>}/>}<label>标题</label><Input.TextArea rows={2} value={brief.title} onChange={e=>changeBrief({title:e.target.value})}/><label>副标题 / 样张阅读说明</label><Input.TextArea rows={2} value={brief.subtitle} onChange={e=>changeBrief({subtitle:e.target.value})}/>{editing.kind!=='sample'&&editing.kind!=='collage'&&editing.kind!=='pdf-page'&&<>
   {editing.kind==='cover'&&run?.data.visual_plan.template_id&&run.data.visual_plan.template_id!=='legacy'?<Alert type="info" showIcon message={`当前模板：${templates.find(item=>item.id===run.data.visual_plan.template_id)?.name||run.data.visual_plan.template_id}`} description="此处修改标题与副标题；判断方法图还可修改节点。修改模板请到“模板与标准”，先处理本张未提交修改。"/>:<><label>布局</label><Select style={{width:'100%'}} disabled={!!busy||!!bufferConflict} value={brief.layout} onChange={layout=>changeBrief({layout})} options={editing.kind==='cover'?[{value:'product-hero',label:'讲义层叠主视觉'},{value:'evidence-grid',label:'封面与样张并列'}]:[{value:'editorial',label:'解释与层级'},{value:'flow',label:'方法流程'},{value:'comparison',label:'内容对比'}]}/><label>图内说明</label><Input.TextArea rows={7} value={brief.text} onChange={e=>changeBrief({text:e.target.value})}/></>}
   {(editing.kind!=='cover'||!run?.data.visual_plan.template_id||run.data.visual_plan.template_id==='legacy'||run.data.visual_plan.template_id==='decision-map'||run.data.visual_plan.template_id==='magazine-a')&&<Collapse style={{marginTop:16}} items={[{key:"nodes",label:"高级：节点或步骤",children:<><Paragraph type="secondary">每行一组，用“｜”分隔标题与说明；比较数字也写在对应行。</Paragraph><Input.TextArea aria-label="单图节点或步骤" rows={4} value={brief.nodes.join('\n')} onChange={e=>changeBrief({nodes:cleanLines(e.target.value)})}/></>} ]}/>}</>}<Button type="primary" disabled={!!busy||dirty||visualDirty||innerDirty||pdfPagesDirty||!!bufferConflict} style={{marginTop:20}} onClick={()=>void submitRevision()}>按本次修改生成新版本</Button></fieldset>}</Drawer>
 </div>;
}
