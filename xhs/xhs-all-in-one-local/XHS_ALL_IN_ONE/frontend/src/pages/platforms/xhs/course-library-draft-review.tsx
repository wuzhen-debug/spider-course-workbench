import { CheckOutlined, DownloadOutlined, FilePdfOutlined, FormOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Checkbox, Collapse, Image, Input, Modal, Radio, Select, Space, Spin, Steps, Tag, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { approveLibraryDraftReview, fetchLibraryDraftHistory, fetchLibraryDraftImage, fetchLibraryDraftReview, generateLibraryDraft, prepareLibraryDraft, reframeLibraryDraftReview, saveLibraryDraftReview } from "../../../lib/api";
import type { LibraryDetail, LibraryDraftPlan, LibraryDraftRecipe, LibraryDraftReview } from "../../../lib/course-library-types";
import { defaultSamplePages, parseSamplePages, scopedDraftRequest } from "../../../lib/course-library-draft-flow";
import { CourseBrandSelect } from '../../../components/course-brand-select';
const { Text, Paragraph, Title } = Typography;

function errorText(error:unknown) {
  const detail=(error as {response?:{data?:{detail?:unknown}}})?.response?.data?.detail;
  return typeof detail==="string"?detail:"处理未完成，请检查页码与本机服务后重试。已有资料和草稿保持原样。";
}

export function CourseLibraryDraftReview({detail,onClose,initialReviewId}:{detail:LibraryDetail;onClose:()=>void;initialReviewId?:number}) {
  const [searchParams,setSearchParams]=useSearchParams();
  const revision=detail.revisions.find(r=>r.id===detail.file.current_revision_id);
  const [pages,setPages]=useState(defaultSamplePages(revision?.page_count));
  const [mode,setMode]=useState<"local"|"ai">("ai");const [instruction,setInstruction]=useState("");
  const [brandId,setBrandId]=useState('');
  const [plan,setPlan]=useState<LibraryDraftPlan|null>(null);const [preparing,setPreparing]=useState(false);const [planError,setPlanError]=useState("");
  const [prepareRetry,setPrepareRetry]=useState(0);
  const [review,setReview]=useState<LibraryDraftReview|null>(null);const [history,setHistory]=useState<LibraryDraftReview[]>([]);
  const [title,setTitle]=useState("");const [body,setBody]=useState("");const [tags,setTags]=useState<string[]>([]);
  const [images,setImages]=useState<string[]>([]);const [reviewed,setReviewed]=useState(false);
  const [busy,setBusy]=useState("");const [error,setError]=useState("");const [notice,setNotice]=useState("");
  const key=useRef(crypto.randomUUID());const active=useRef(true);
  const reframeKey=useRef(crypto.randomUUID());
  const scope=useRef('');scope.current=`${detail.file.id}:${revision?.id}`;
  useEffect(()=>{
    active.current=true;let cancelled=false;
    setReview(null);setTitle("");setBody("");setTags([]);setHistory([]);setError("");setNotice("");setReviewed(false);setBusy("");
    void fetchLibraryDraftHistory(detail.file.id).then(rows=>{if(!cancelled)setHistory(rows);}).catch(e=>{if(!cancelled)setError(errorText(e));});
    if(initialReviewId){setBusy("正在找回原来的文案与样张");void fetchLibraryDraftReview(initialReviewId).then(next=>{
      if(cancelled)return;
      if(next.file_id!==detail.file.id){setError("指定创作不属于这份 PDF，没有打开其他稿件。");return;}
      useReview(next);
    }).catch(e=>{if(!cancelled)setError(errorText(e));}).finally(()=>{if(!cancelled)setBusy("");});}
    return()=>{cancelled=true;active.current=false;};
  },[detail.file.id,initialReviewId]);
  useEffect(()=>{setPages(defaultSamplePages(revision?.page_count));setMode("ai");setInstruction("");setBrandId('');},[detail.file.id,revision?.id,revision?.page_count]);
  useEffect(()=>{
    let cancelled=false;setPlan(null);setPlanError("");key.current=crypto.randomUUID();
    if(!revision||!brandId){setPreparing(false);return;}
    let payload:LibraryDraftRecipe;
    try{payload={revision_id:revision.id,pages:parseSamplePages(pages,revision.page_count),mode,instruction,brand_id:brandId};}
    catch(e){setPreparing(false);setPlanError(e instanceof Error?e.message:"页码无效");return;}
    setPreparing(true);
    const timer=setTimeout(()=>{
      void prepareLibraryDraft(detail.file.id,payload).then(next=>{if(!cancelled)setPlan(next);})
        .catch(e=>{if(!cancelled)setPlanError(errorText(e));}).finally(()=>{if(!cancelled)setPreparing(false);});
    },300);
    return()=>{cancelled=true;clearTimeout(timer);};
  },[pages,mode,instruction,brandId,detail.file.id,revision?.id,revision?.page_count,prepareRetry]);
  useEffect(()=>{
    if(!review){setImages([]);return;}
    let cancelled=false;const urls:string[]=[];setImages([]);
    void Promise.all(review.images.map((_,i)=>fetchLibraryDraftImage(review.id,i).then(blob=>{const url=URL.createObjectURL(blob);urls.push(url);return url;}))).then(values=>{if(!cancelled)setImages(values);}).catch(e=>{if(!cancelled)setError(errorText(e));}).finally(()=>{if(cancelled)urls.forEach(URL.revokeObjectURL);});
    return()=>{cancelled=true;urls.forEach(URL.revokeObjectURL);};
  },[review?.id]);
  useEffect(()=>{reframeKey.current=crypto.randomUUID();},[review?.id,title,body,tags]);
  function useReview(next:LibraryDraftReview){
    setReview(next);setTitle(next.title);setBody(next.body);setTags(next.tags);setReviewed(false);setNotice("");
    if(searchParams.get("package_id")!==String(next.id)){
      const params=new URLSearchParams(searchParams);params.set("package_id",String(next.id));setSearchParams(params,{replace:true});
    }
  }
  function recipe():LibraryDraftRecipe {
    if(!revision)throw new Error("missing revision");
    const values=parseSamplePages(pages,revision.page_count);
    return {revision_id:revision.id,pages:values,mode,instruction,brand_id:brandId};
  }
  async function generate(){
    if(!plan||busy||preparing)return;const context=scope.current;
    setBusy(mode==="ai"?"正在生成文案并制作真实样张":"正在本机整理文案并制作真实样张");setError("");setNotice("");
    try{const request=scopedDraftRequest(detail.file.id,recipe(),plan,key.current);const next=await generateLibraryDraft(detail.file.id,request);if(active.current&&scope.current===context){useReview(next);const rows=await fetchLibraryDraftHistory(detail.file.id);if(active.current&&scope.current===context)setHistory(rows);}}
    catch(e){if(active.current&&scope.current===context){setError(e instanceof Error&&!('response' in e)?e.message:errorText(e));if((e as {response?:{status?:number}})?.response?.status===409)setPrepareRetry(v=>v+1);}}finally{if(active.current&&scope.current===context)setBusy("");}
  }
  async function save(approve=false){
    if(!review)return;setBusy(approve?"正在保存到草稿工坊":"正在保存审核修改");setError("");
    try{let next=await saveLibraryDraftReview(review.id,{title,body,tags});if(approve)next=await approveLibraryDraftReview(review.id,next.review_digest);setReview(next);setNotice(approve?"已保存到草稿工坊，图片已附上；未创建发布任务。":"审核修改已保存，仍待人工确认。");setHistory(await fetchLibraryDraftHistory(detail.file.id));}
    catch(e){setError(errorText(e));}finally{setBusy("");}
  }
  async function enlargeSamples(){
    if(!review||busy)return;const context=scope.current;
    setBusy("正在本机放大样张，保留旧版");setError("");
    try{
      const next=await reframeLibraryDraftReview(review.id,{title,body,tags,request_key:reframeKey.current});
      if(active.current&&scope.current===context){useReview(next);setNotice("已另存大幅样张，文案沿用，旧版保留；请核对新版图片后审核。");setHistory(await fetchLibraryDraftHistory(detail.file.id));}
    }catch(e){if(active.current&&scope.current===context)setError(errorText(e));}
    finally{if(active.current&&scope.current===context)setBusy("");}
  }
  const saved=review?.status==="saved";const tooLong=title.length>20||body.length>1000;
  return <Modal open title={<Space><FormOutlined/>从 PDF 生成小红书草稿与样张</Space>} width={1160} onCancel={onClose} maskClosable={!busy} closable={!busy} keyboard={!busy} footer={<Button onClick={onClose} disabled={!!busy}>关闭，保留生成结果</Button>} className="library-draft-modal">
    <div className="course-center course-library library-draft-workspace">
      <Steps size="small" current={saved?2:review?1:0} items={[{title:"选择 PDF 与页码"},{title:"生成并编辑"},{title:"人工审核保存"}]} style={{marginBottom:20}}/>
      <Alert type="info" showIcon message="生成结果先保存在本机待审核区；审核通过后只保存草稿，不发布、不启动自动运营。"/>
      <div className="library-draft-source"><FilePdfOutlined/><div><Text strong>{detail.file.filename}</Text><div><Text type="secondary">{[detail.file.university||"大学待确认",detail.file.course_code||"课程待确认",detail.file.material_type||"类型待确认",detail.file.term].join(" / ")}</Text></div></div></div>
      {error&&<Alert type="error" showIcon message={error} closable onClose={()=>setError("")} style={{marginBottom:14}}/>}
      {notice&&<Alert type="success" showIcon message={notice} style={{marginBottom:14}}/>}
      <Spin spinning={!!busy} tip={busy||undefined}><div className="library-draft-layout">
        <div>
          <Card size="small" title="生成范围" className="course-panel">
            <CourseBrandSelect value={brandId} onChange={setBrandId} disabled={!!busy} label="新生成内容的品牌"/>
            <Text>样张页码 {revision?.page_count?`（共 ${revision.page_count} 页）`:""}</Text>
            <Input aria-label="样张页码" value={pages} onChange={e=>setPages(e.target.value)} placeholder="例如：1, 3, 5" style={{margin:"8px 0"}} disabled={!!busy}/>
            <Paragraph type="secondary">默认前9页，按顺序本机导出，使用所选品牌的真实Logo水印。</Paragraph>
            <Radio.Group value={mode} onChange={e=>setMode(e.target.value)} disabled={!!busy} options={[{value:"local",label:"本机初稿"},{value:"ai",label:"AI 文案"}]}/>
            <Paragraph type="secondary" style={{margin:"10px 0"}}>{mode==="local"?"文案和样张均在本机制作。":plan?.model?.configured?`${plan.model.name} · ${plan.model.model_name}`:"使用默认文本模型生成文案，PDF样张在本机制作。"}</Paragraph>
            <Input.TextArea aria-label="笔记生成要求" value={instruction} onChange={e=>setInstruction(e.target.value)} placeholder="可选：希望突出哪一个学习问题或资料特点（AI 模式使用）" rows={2} maxLength={800} disabled={!!busy}/>
            {preparing&&<Text type="secondary" style={{display:"block",marginTop:10}}>正在读取选页…</Text>}
            {planError&&<Alert type="warning" message={planError} action={<Button size="small" onClick={()=>setPrepareRetry(v=>v+1)}>重新读取</Button>} style={{marginTop:10}}/>}
            {plan&&<div style={{marginTop:14}}>
              {plan.warnings.map(w=><Alert type="warning" key={w} message={w} style={{marginTop:10}}/>)}
              {mode==="ai"&&!plan.model?.configured&&<Alert type="warning" message={<>请在<a href="/models" target="_blank" rel="noreferrer">模型配置</a>填写文本API，或选择本机初稿。</>}/>}
              <Collapse size="small" style={{margin:"12px 0"}} items={[{key:"text",label:"选页文字与生成范围",children:<>
                {mode==="ai"&&<Paragraph type="secondary">文案发送至{plan.model?.destination}：仅限这些选页文字、课程信息和生成要求；PDF、图片、Logo和本机路径留在本机。</Paragraph>}
                {plan.pages.map(p=><div key={p.page}><Text strong>第 {p.page} 页{p.truncated?"（文字已截取）":""}</Text><Paragraph className="library-draft-excerpt">{p.text||"未提取到文字"}</Paragraph></div>)}</>}]}/>
            </div>}
            <Button type="primary" block icon={<FormOutlined/>} disabled={!!busy||preparing||!plan||mode==="ai"&&!plan.model?.configured} onClick={()=>void generate()} style={{marginTop:12}}>
              {mode==="ai"?`用${plan?.model?.model_name||"AI"}生成文案与${plan?.pages.length??9}页样张`:`生成文案与${plan?.pages.length??9}页样张`}
            </Button>
          </Card>
          <Card size="small" title="这份 PDF 的生成记录" className="course-panel">
            {history.length?<Select aria-label="选择生成记录" style={{width:"100%"}} value={review?.id} placeholder="选择已有待审核稿" options={history.map(r=>({value:r.id,label:`#${r.id} · ${r.status==="saved"?"已存草稿":"待审核"} · ${r.title}`}))} onChange={id=>{setError("");void fetchLibraryDraftReview(id).then(useReview).catch(e=>setError(errorText(e)));}}/>:<Text type="secondary">尚未生成。记录保留文件版本、页码与样张，关闭后可从这里继续审核。</Text>}
          </Card>
        </div>
        <div>{review?<>
          <Card size="small" className="course-panel" title={<Space>笔记草稿 <Tag>{review.source.preview_brand?.name||'星途留学'}</Tag><Tag color={saved?"green":"gold"}>{saved?"已保存到草稿工坊":"待人工审核"}</Tag></Space>} extra={<Text type="secondary">#{review.id} · {review.generation_mode==="ai"?"AI 生成":"本机摘录初稿"}</Text>}>
            {review.source_stale&&<Alert type="warning" showIcon message="源 PDF 已变化；这份结果保留作参考，请重新生成当前版本后审核保存。" style={{marginBottom:12}}/>}
            {review.warnings.map(w=><Alert key={w} type="warning" message={w} style={{marginBottom:8}}/>)}
            <Text>标题 · {title.length}/20 字</Text><Input aria-label="审核稿标题" value={title} onChange={e=>{setTitle(e.target.value);setReviewed(false);}} disabled={saved} style={{margin:"8px 0 14px"}}/>
            <Text>正文 · {body.length}/1000 字</Text><Input.TextArea aria-label="审核稿正文" value={body} onChange={e=>{setBody(e.target.value);setReviewed(false);}} disabled={saved} autoSize={{minRows:10,maxRows:22}} style={{margin:"8px 0 14px"}}/>
            <Text>标签</Text><Select aria-label="审核稿标签" mode="tags" value={tags} tokenSeparators={[",","，"]} onChange={v=>{setTags(v);setReviewed(false);}} disabled={saved} style={{width:"100%",margin:"8px 0 14px"}}/>
            <Paragraph type="secondary" className="course-ref">来源：{review.source.relative_path}<br/>PDF 内容指纹：{review.source.sha256}<br/>选页：{review.pages.map(p=>p.page).join("、")} / 共 {review.source.page_count} 页</Paragraph>
            {!saved?<><Checkbox checked={reviewed} onChange={e=>setReviewed(e.target.checked)}>我已核对文案、资料归属及预览图，确认可用于本业务</Checkbox><Space wrap style={{marginTop:14}}><Button onClick={()=>void save()} disabled={!!busy}>保存修改，保持待审核</Button><Button type="primary" icon={<CheckOutlined/>} onClick={()=>void save(true)} disabled={!!busy||!reviewed||review.source_stale||tooLong||!title.trim()||!body.trim()}>审核通过，保存到草稿工坊</Button></Space></>:review.draft_available!==false&&review.draft_id?<Link to={`/platforms/xhs/drafts?draft_id=${review.draft_id}`}><Button>打开草稿工坊 · 草稿 #{review.draft_id}</Button></Link>:<Alert type="info" message="原草稿关联暂不可用，原文案与样张仍保留在这里。"/>}
          </Card>
          <Card size="small" className="course-panel" title={`真实资料预览图 · ${review.images.length} 张`} extra={<Space wrap>
            {review.source.preview_layout!=="pdf-full-width-v2"&&<Button size="small" disabled={!!busy||review.source_stale||!title.trim()||!body.trim()} onClick={()=>void enlargeSamples()}>放大样张，保留旧版</Button>}
            <Text type="secondary">{review.source.preview_layout==="pdf-full-width-v2"?"原页比例":"1200 × 1600"} · 点击放大</Text>
          </Space>}>
            <Image.PreviewGroup><div className="library-draft-image-grid">{review.images.map((image,i)=><div key={i}>
              {images[i]?<><Image src={images[i]} alt={`原 PDF 第 ${image.page} 页资料样张`} width="100%"/><a href={images[i]} download={`PDF样张-第${image.page}页.png`}><DownloadOutlined/> 保存第 {image.page} 页样张</a></>:<Spin/>}
            </div>)}</div></Image.PreviewGroup>
            <Paragraph type="secondary" style={{margin:"12px 0 0"}}>点击图片放大，核对公式、中文和原页码；也可单独保存样张。</Paragraph>
          </Card>
        </>:<Card className="course-panel library-draft-empty"><Title level={4}>把资料变成可审核的笔记</Title><Paragraph type="secondary">先在左侧选页并读取范围。生成后，文案与真实样张会一起显示在这里，供你逐项修改、放大检查。</Paragraph><Tag>待审核结果不会进入发布中心</Tag></Card>}</div>
      </div></Spin>
    </div>
  </Modal>;
}
