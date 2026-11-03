import { ArrowUpOutlined, EyeOutlined, FilePdfOutlined, FolderOpenOutlined, ReloadOutlined, SyncOutlined, UnorderedListOutlined } from "@ant-design/icons";
import { Alert, Breadcrumb, Button, Card, Collapse, Descriptions, Drawer, Empty, Input, InputNumber, Select, Space, Spin, Table, Tag, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchLibraryDetail, fetchLibraryFiles, fetchLibraryPreview, fetchLibraryStatus, requestLibraryRescan } from "../../../lib/api";
import type { LibraryDetail, LibraryFile, LibraryStatus } from "../../../lib/course-library-types";
import "./course-center.css";
import { CourseLibraryDraftReview } from "./course-library-draft-review";
import { CoursePlatformDraftReview } from "./course-platform-draft-review";
import { CourseLibraryDirectory } from "./course-library-directory";
import { CourseTopicResearchPage } from "./course-topic-research-page";
import { CourseCreationsPanel } from "../../../components/course-creations-panel";
import { libraryFolderParams, libraryResearchParams, positiveRouteId } from "../../../lib/course-creations";
const {Title,Text,Paragraph}=Typography;
const labels:Record<string,[string,string]>={ready:["已入库","green"],pending:["等待稳定 / 索引","blue"],missing:["原文件未找到","orange"],error:["文件待检查","red"]};
function FileState({value}:{value:string}) { const [label,color]=labels[value]??[value,"default"];return <Tag color={color}>{label}</Tag>; }
function bytes(size:number) { return size>=1024**2?`${(size/1024**2).toFixed(1)} MB`:`${Math.max(1,Math.round(size/1024))} KB`; }
function time(value:string|number|null) { return value ? new Date(typeof value==="number"?value/1e6:value).toLocaleString("zh-CN",{hour12:false}):"尚未完成"; }
function message(error:unknown) { const detail=(error as {response?:{data?:{detail?:unknown}}})?.response?.data?.detail;return typeof detail==="string"?detail:"本机数据暂未加载，请刷新后重试。"; }

export function CourseLibraryPanel() {
  const [status,setStatus]=useState<LibraryStatus|null>(null);const [rows,setRows]=useState<LibraryFile[]>([]);const [total,setTotal]=useState(0);
  const [searchParams,setSearchParams]=useSearchParams();const directory=searchParams.get("library_dir")??"";const path=directory?directory.split("/"):[];
  const listView=searchParams.get("library_view")==="files";
  const researchView=searchParams.get("library_view")==="research";
  const [maintenanceOpen,setMaintenanceOpen]=useState(listView);
  const [query,setQuery]=useState("");const [searchText,setSearchText]=useState("");const [state,setState]=useState("");const [page,setPage]=useState(1);
  const [refreshKey,setRefreshKey]=useState(0);
  const [loading,setLoading]=useState(true);const [error,setError]=useState("");const [notice,setNotice]=useState("");
  const selected=positiveRouteId(searchParams.get("library_file_id"));const packageId=positiveRouteId(searchParams.get("package_id"));
  const [detail,setDetail]=useState<LibraryDetail|null>(null);
  const [draftReviewOpen,setDraftReviewOpen]=useState(false);
  const dualOpen=searchParams.get('dual_drafts')==='1';
  const pairId=positiveRouteId(searchParams.get('platform_pair_id'));
  const sourcePackageId=positiveRouteId(searchParams.get('source_package_id'));
  function openDual(){const next=new URLSearchParams(searchParams);next.delete('package_id');next.set('dual_drafts','1');setSearchParams(next);setDraftReviewOpen(false);}
  function closeDual(){const next=new URLSearchParams(searchParams);for(const key of ['dual_drafts','platform_pair_id','source_package_id'])next.delete(key);setSearchParams(next);}
  function selectDual(id:number){const next=new URLSearchParams(searchParams);next.delete('source_package_id');next.delete('package_id');next.set('dual_drafts','1');next.set('platform_pair_id',String(id));setSearchParams(next);}
  const [detailError,setDetailError]=useState("");
  const [pdfPage,setPdfPage]=useState(1);const [image,setImage]=useState("");const [rendering,setRendering]=useState(false);const [previewError,setPreviewError]=useState("");
  const sequence=useRef(0);const detailSequence=useRef(0);
  function setSelected(id:number|null) {
    const next=new URLSearchParams(searchParams);for(const key of ['package_id','dual_drafts','platform_pair_id','source_package_id'])next.delete(key);
    if(id)next.set("library_file_id",String(id));else next.delete("library_file_id");
    setSearchParams(next);setDraftReviewOpen(false);
  }
  function closeDraftReview(){setDraftReviewOpen(false);if(packageId){const next=new URLSearchParams(searchParams);next.delete("package_id");setSearchParams(next);}}
  async function load(background=false) {
    const request=++sequence.current;if(!background)setLoading(true);
    try {
      const [nextStatus,list]=await Promise.all([fetchLibraryStatus(),listView?fetchLibraryFiles({directory_path:directory,q:query,state,page}):Promise.resolve(null)]);
      if(request!==sequence.current)return;setStatus(nextStatus);setError("");
      if(list){setRows(list.items);setTotal(list.total);}
    } catch(e) {if(request===sequence.current){setError(message(e));setRows([]);setTotal(0);}} finally {if(request===sequence.current)setLoading(false);}
  }
  async function loadDetail(id:number) {
    const request=++detailSequence.current;
    try {const next=await fetchLibraryDetail(id);if(request===detailSequence.current){setDetail(next);setDetailError("");}}catch(e){if(request===detailSequence.current)setDetailError(message(e));}
  }
  useEffect(()=>{void load();const timer=setInterval(()=>void load(true),5000);return()=>{clearInterval(timer);sequence.current++;};},[query,directory,listView,state,page]);
  useEffect(()=>{setPage(1);setQuery("");setSearchText("");setState("");},[directory]);
  useEffect(()=>{if(listView)setMaintenanceOpen(true);},[listView]);
  useEffect(()=>{if(searchParams.has("library_path")){const next=new URLSearchParams(searchParams);next.delete("library_path");setSearchParams(next,{replace:true});}},[searchParams]);
  function navigateFolder(nextPath:string) {
    const next=libraryFolderParams(searchParams,nextPath);
    setQuery("");setSearchText("");setState("");setPage(1);setSearchParams(next);
  }
  function changeView(view:"directory"|"files"|"research") {
    const next=new URLSearchParams(searchParams);if(view!=="directory")next.set("library_view",view);else next.delete("library_view");setPage(1);setQuery("");setSearchText("");setSearchParams(next);
  }
  function researchFile(file:LibraryFile) {
    const next=libraryResearchParams(searchParams,file);
    setDraftReviewOpen(false);setSearchParams(next);
  }
  useEffect(()=>{
    setDetail(null);setPdfPage(1);setPreviewError("");setDetailError("");if(!selected)return;
    void loadDetail(selected);const timer=setInterval(()=>void loadDetail(selected),5000);
    return()=>{clearInterval(timer);detailSequence.current++;};
  },[selected]);
  const current=detail?.revisions.find(r=>r.id===detail.file.current_revision_id);
  useEffect(()=>{setPdfPage(1);},[current?.id]);
  useEffect(()=>{
    setImage("");setPreviewError("");setRendering(false);if(!selected||!current||detail?.file.status!=="ready")return;
    let cancelled=false;let url="";setRendering(true);
    void fetchLibraryPreview(selected,pdfPage,current.id).then(blob=>{
      url=URL.createObjectURL(blob);if(cancelled)URL.revokeObjectURL(url);else {setImage(url);void loadDetail(selected);}
    }).catch(async(e)=>{
      let text=message(e);const blob=(e as {response?:{data?:Blob}})?.response?.data;
      if(blob instanceof Blob)try{text=JSON.parse(await blob.text()).detail??text;}catch{/* keep safe text */}
      if(!cancelled)setPreviewError(text);
    }).finally(()=>{if(!cancelled)setRendering(false);});
    return()=>{cancelled=true;if(url)URL.revokeObjectURL(url);};
  },[selected,pdfPage,current?.id,detail?.file.status]);
  function open(file:LibraryFile) {setSelected(file.id);}
  return <div className="course-center course-library">
    {!researchView&&<div className="library-header">
      <Title level={2}>本地题库</Title>
      <Space wrap><Tag icon={status?.watcher_alive?<SyncOutlined spin/>:<FolderOpenOutlined/>} color={status?.watcher_alive?"green":"default"}>{status?.watcher_alive?"本地监测运行中":"正在连接本地监测"}</Tag>
      <Button icon={<ReloadOutlined/>} loading={loading} onClick={()=>{void load();setRefreshKey(k=>k+1);}}>刷新</Button>
      </Space>
    </div>}
    {error&&<Alert type="error" showIcon message={error} style={{marginTop:12}}/>}
    {notice&&<Alert type="success" showIcon message={notice} closable onClose={()=>setNotice("")} style={{marginTop:12}}/>}
    {status?.root?.last_error&&<Alert type="warning" showIcon message={status.root.last_error} style={{marginTop:12}}/>}
    <div className="library-location-bar">
      <Button icon={<ArrowUpOutlined/>} disabled={!path.length} onClick={()=>navigateFolder(path.slice(0,-1).join("/"))}>上一级</Button>
      <Breadcrumb items={[{title:<button className="library-crumb" onClick={()=>navigateFolder("")}>题库</button>},...path.map((value,index)=>({title:index===path.length-1?<span>{value}</span>:<button className="library-crumb" onClick={()=>navigateFolder(path.slice(0,index+1).join("/"))}>{value}</button>}))]}/>
    </div>
    <div className="library-browser-filters">
      <Space wrap><Button icon={<FolderOpenOutlined/>} type={!listView&&!researchView?"primary":"default"} onClick={()=>changeView("directory")}>本地目录</Button><Button icon={<EyeOutlined/>} type={researchView?"primary":"default"} onClick={()=>changeView("research")}>课程选题研究</Button>{listView&&<Tag>PDF 索引 · 维护视图</Tag>}</Space>
      {listView&&<><Input.Search placeholder="在当前目录及子目录搜索 PDF" aria-label="在当前目录及子目录搜索 PDF" value={searchText} onChange={e=>setSearchText(e.target.value)} allowClear onSearch={q=>{setQuery(q);setPage(1);}} style={{width:300,maxWidth:"100%"}}/>
      <Select value={state} style={{width:190}} onChange={v=>{setState(v);setPage(1);}} options={[{value:"",label:"全部状态"},{value:"products",label:"已关联资料产品"},{value:"needs_confirmation",label:"归属 / 类型待确认"},{value:"pending",label:"等待稳定 / 索引"},{value:"updated",label:"有内容更新"},{value:"missing",label:"原文件未找到"},{value:"error",label:"文件待检查"}]}/></>}
    </div>
    {researchView?<CourseTopicResearchPage directory={directory} onOpenPdf={setSelected}/>:!listView?<CourseLibraryDirectory path={directory} refreshKey={refreshKey} onNavigate={navigateFolder} onOpenPdf={setSelected}/>:<Card className="course-panel" title={<Space wrap><FilePdfOutlined/><span>{query?"PDF 搜索结果":"PDF 索引"}</span><Tag>{total} 份 PDF</Tag><Text type="secondary">包含当前目录的子目录与历史登记</Text></Space>}>
      <Table<LibraryFile> rowKey="id" size="middle" loading={loading} dataSource={rows} scroll={{x:900}} pagination={{current:page,pageSize:20,total,showSizeChanger:false,onChange:setPage,showTotal:n=>`共 ${n} 个 PDF`}} columns={[
        {title:"PDF 产品 / 原目录",key:"filename",width:360,render:(_,f)=><><Button type="link" style={{padding:0,height:"auto",whiteSpace:"normal",wordBreak:"break-word",textAlign:"left"}} onClick={()=>open(f)}>{f.filename}</Button><Paragraph className="course-ref" type="secondary" ellipsis={{rows:2,tooltip:f.relative_path}} style={{marginBottom:4}}>{f.relative_path}</Paragraph><Space wrap><FileState value={f.status}/>{f.product_id?<Tag color="blue">已关联产品 · 未自动上架</Tag>:<Tag>归属 / 类型待确认</Tag>}{f.revision_count>1&&<Tag color="orange">{f.revision_count} 个内容版本</Tag>}</Space></>},
        {title:"课程与资料类型",key:"course",width:225,render:(_,f)=><Space direction="vertical" size={3}><Text>{f.university||"大学待确认"} · {f.course_code||"课程待确认"}</Text><Text type="secondary">{f.material_type||"类型待确认"} · {f.term}</Text></Space>},
        {title:"原文件更新",key:"modified",width:165,render:(_,f)=><><Text>{time(f.mtime_ns)}</Text><div><Text type="secondary">{bytes(f.size_bytes)}</Text></div></>},
        {title:"操作",key:"actions",width:145,render:(_,f)=><Button icon={<EyeOutlined/>} size="small" onClick={()=>open(f)}>查看与预览</Button>},
      ]}/>
    </Card>}
    {!researchView&&<CourseCreationsPanel directory={directory} refreshKey={refreshKey}/>}
    {!researchView&&<Collapse style={{marginTop:12}} activeKey={maintenanceOpen?["maintenance"]:[]} onChange={keys=>setMaintenanceOpen(keys.includes("maintenance"))} items={[{
      key:"maintenance",label:"维护与诊断",children:<Space direction="vertical" size={16} style={{width:"100%"}}>
        <Space wrap>
          <Button icon={<UnorderedListOutlined/>} type={listView?"primary":"default"} onClick={()=>changeView("files")}>查看 PDF 索引（含子目录）</Button>
          <Button icon={<FolderOpenOutlined/>} disabled={!status} onClick={()=>{void requestLibraryRescan().then(()=>{setNotice("已请求重新核对 PDF 索引，目录和登记会自动同步。");setRefreshKey(k=>k+1);}).catch(e=>setError(message(e)));}}>重新核对 PDF 索引</Button>
        </Space>
        <Descriptions size="small" column={{xs:1,sm:2}} items={[
          {key:"root",label:"监测路径",span:2,children:<Text className="course-ref">{status?.root?.path??"等待本机目录连接"}</Text>},
          {key:"scan",label:"上次目录核对",children:time(status?.root?.last_scan_at??null)},
          {key:"heartbeat",label:"监测心跳",children:time(status?.root?.heartbeat_at??null)},
          {key:"total",label:"已登记 PDF",children:status?.total??0},
          {key:"ready",label:"已核对内容指纹",children:status?.counts.ready??0},
          {key:"products",label:"已关联资料产品",children:status?.products??0},
          {key:"updated",label:"有内容更新",children:status?.updated_files??0},
        ]}/>
        <Text type="secondary">目录每 5 秒自动同步，不改变本地文件夹或原文件。文件登记不代表内容质检、使用权确认或上架，不会触发小红书任务。</Text>
      </Space>,
    }]}/>}
    <Drawer className="library-preview-drawer" width={1000} title={<Space><FilePdfOutlined/>PDF 预览</Space>} open={selected!==null} onClose={()=>{setSelected(null);setDraftReviewOpen(false);}} destroyOnClose>
      {detailError&&<Alert type="warning" message={detailError} style={{marginBottom:12}}/>}
      {!detail?<Spin/>:<>
        <Title level={4} className="library-pdf-title">{detail.file.filename}</Title>
        {detail.file.error&&<Alert type="warning" message={detail.file.error} style={{marginBottom:12}}/>}
        {detail.file.status!=="ready"&&!detail.file.error&&<Alert type="warning" message={labels[detail.file.status]?.[0]??"文件暂不可读取"} style={{marginBottom:12}}/>}
        <div className="library-pdf-actions">
          <Button type="primary" disabled={detail.file.status!=="ready"||!current} onClick={openDual}>生成闲鱼＋小红书两版</Button>
          <Button disabled={detail.file.status!=="ready"||!current} onClick={()=>researchFile(detail.file)}>研究选题并制作图文</Button>
          <Button type="link" disabled={detail.file.status!=="ready"||!current} onClick={()=>setDraftReviewOpen(true)}>旧小红书生成记录</Button>
        </div>
        <CourseCreationsPanel key={`file-creations-${detail.file.id}`} fileId={detail.file.id} refreshKey={refreshKey}/>
        <Card size="small" title="原 PDF 页面预览" extra={<Text type="secondary">带预览水印</Text>}>
          <Space wrap style={{marginBottom:12}}><Button disabled={pdfPage<=1||rendering} onClick={()=>setPdfPage(p=>p-1)}>上一页</Button><InputNumber aria-label="PDF 预览页码" min={1} max={current?.page_count??undefined} value={pdfPage} onChange={p=>{if(p)setPdfPage(p);}}/><Text>/ {current?.page_count??"待读取"} 页</Text><Button disabled={!current||rendering||!!current.page_count&&pdfPage>=current.page_count} onClick={()=>setPdfPage(p=>p+1)}>下一页</Button></Space>
          {previewError&&<Alert type="warning" message={previewError} style={{marginBottom:12}}/>}
          <Spin spinning={rendering}><div className="library-pdf-preview">{image?<img src={image} alt={`${detail.file.filename} 第 ${pdfPage} 页，本机水印预览`}/>:<Empty description={detail.file.status==="pending"?"文件稳定并完成指纹登记后可预览":"请选择可读取的当前文件版本"}/>}</div></Spin>
        </Card>
        <Collapse key={`file-details-${detail.file.id}`} className="library-file-details" size="small" defaultActiveKey={[]} items={[{key:"file",label:"文件详情与版本",children:<>
          <Descriptions size="small" column={1} items={[{key:"path",label:"原文件",children:<Text className="course-ref">{detail.source_path}</Text>},
            {key:"course",label:"识别结果",children:`${detail.file.university||"大学待确认"} / ${detail.file.course_code||"课程待确认"} / ${detail.file.material_type||"类型待确认"} / ${detail.file.term}`},
            {key:"reason",label:"依据",children:detail.file.classification_reason},
            {key:"state",label:"文件状态",children:<Space wrap><FileState value={detail.file.status}/><Tag>内容质检另行确认</Tag><Tag>未自动发布或上架</Tag></Space>}]}/>
          <Paragraph type="secondary">{detail.history_note}</Paragraph>
          <Table size="small" rowKey="id" dataSource={detail.revisions} pagination={false} scroll={{x:600}} columns={[
          {title:"内容版本",key:"revision",width:110,render:(_,rev)=><Space direction="vertical"><Text>#{rev.id}</Text>{rev.id===detail.file.current_revision_id&&<Tag color="green">当前内容</Tag>}</Space>},
          {title:"SHA256 / 大小",key:"hash",render:(_,rev)=><><Paragraph copyable className="course-ref" style={{marginBottom:4}}>{rev.sha256}</Paragraph><Text type="secondary">{bytes(rev.size_bytes)}</Text></>},
          {title:"发现时间",dataIndex:"observed_at",width:170,render:value=>time(value)},
          ]}/>
        </>}]}/>
      </>}
    </Drawer>
    {(draftReviewOpen||!!packageId)&&detail&&<CourseLibraryDraftReview detail={detail} initialReviewId={packageId??undefined} onClose={closeDraftReview}/>}
    {(dualOpen||!!pairId||!!sourcePackageId)&&detail&&<CoursePlatformDraftReview key={detail.file.id} detail={detail} initialPairId={pairId??undefined} initialSourcePackageId={sourcePackageId??undefined} onClose={closeDual} onSelectPair={selectDual}/>}
  </div>;
}
