import { FileOutlined, FilePdfOutlined, FolderFilled, LinkOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Empty, Input, Space, Table, Tag, Tooltip, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { fetchLibraryDirectory } from "../../../lib/api";
import type { LibraryDirectory, LibraryDirectoryEntry } from "../../../lib/course-library-types";
const {Text}=Typography;

function bytes(value:number|null) {
  if(value===null)return "—";
  return value>=1024**2?`${(value/1024**2).toFixed(1)} MB`:value>=1024?`${(value/1024).toFixed(1)} KB`:`${value} B`;
}
function rowState(entry:LibraryDirectoryEntry) {
  if(entry.kind==="directory")return <Text type="secondary">本地文件夹</Text>;
  if(entry.kind==="symlink")return <Tooltip title="显示链接名称，读取范围保持在题库原目录内"><Tag>链接 · 仅展示</Tag></Tooltip>;
  if(!entry.is_pdf||!entry.index_eligible)return <Text type="secondary">仅展示文件位置</Text>;
  if(entry.can_preview)return <Tag color="green">PDF 可预览</Tag>;
  if(entry.index_status==="error")return <Tag color="orange">PDF 待检查</Tag>;
  return <Tag color="blue">PDF 同步中</Tag>;
}

export function CourseLibraryDirectory({path,refreshKey,onNavigate,onOpenPdf}:{path:string;refreshKey:number;onNavigate:(path:string)=>void;onOpenPdf:(id:number)=>void}) {
  const [data,setData]=useState<LibraryDirectory|null>(null);const [loading,setLoading]=useState(true);const [error,setError]=useState("");
  const [text,setText]=useState("");const [query,setQuery]=useState("");const [group,setGroup]=useState("");const request=useRef(0);
  useEffect(()=>{setText("");setQuery("");setGroup("");setData(null);},[path]);
  async function load(background=false){
    const id=++request.current;if(!background)setLoading(true);
    try{const next=await fetchLibraryDirectory({path,q:query,alphabetic:true,group_key:group});if(id===request.current){setData(next);setError("");}}
    catch(e){if(id===request.current){const detail=(e as {response?:{data?:{detail?:unknown}}})?.response?.data?.detail;setError(typeof detail==="string"?detail:"目录暂未读取完成，请稍后重试。");setData(null);}}
    finally{if(id===request.current)setLoading(false);}
  }
  useEffect(()=>{void load();const timer=setInterval(()=>void load(true),5000);return()=>{clearInterval(timer);request.current++;};},[path,query,group,refreshKey]);
  const icon=(entry:LibraryDirectoryEntry)=>entry.kind==="directory"?<FolderFilled className="library-real-folder-icon"/>:entry.kind==="symlink"?<LinkOutlined/>:entry.is_pdf?<FilePdfOutlined className="library-real-pdf-icon"/>:<FileOutlined/>;
  const activeGroup=data?.groups.find(item=>item.key===data.active_group);const virtual=(data?.items.length??0)>120;
  const startsLetter=(entry:LibraryDirectoryEntry,index:number)=>!!entry.course_initial&&(index===0||data?.items[index-1]?.course_initial!==entry.course_initial);
  return <Card className="course-panel library-real-directory" title={<Space wrap><FolderFilled className="library-real-folder-icon"/><span>{path.split("/").pop()||"题库"}</span><Text type="secondary">{data?`${data.folder_count} 个文件夹 · ${data.file_count} 个文件`:loading?"正在读取目录":"目录暂不可用"}</Text></Space>}>
    {error&&<Alert type="warning" showIcon message={error} action={<Button size="small" onClick={()=>onNavigate("")}>返回题库</Button>} style={{marginBottom:16}}/>}
    <div className="library-folder-toolbar"><Text type="secondary">名称与位置来自本地目录 · {data?.pdf_count??0} 份 PDF</Text><Input.Search aria-label="查找当前目录文件或文件夹" placeholder="查找当前目录文件或文件夹" value={text} onChange={e=>setText(e.target.value)} onSearch={value=>{setQuery(value);setGroup("");}} allowClear style={{width:300,maxWidth:"100%"}}/></div>
    {!!data?.groups.length&&<div className="library-alphabet-navigation" aria-label="课程首字母分组">
      <Space wrap size={[8,10]}>{data.groups.map(item=><Tooltip key={item.key} title={item.letters.length?item.letters.map(letter=>`${letter.initial}：${letter.count} 个`).join(" · "):"保留当前目录的其他文件和文件夹"}>
        <Button aria-label={`查看${item.label}组`} type={data.active_group===item.key?"primary":"default"} onClick={()=>setGroup(item.key)}>{item.label}<span className="library-alphabet-count">{item.count}</span></Button>
      </Tooltip>)}<Button aria-label="全部连续浏览" type={data.active_group==="all"?"primary":"default"} onClick={()=>setGroup("all")}>全部连续浏览<span className="library-alphabet-count">{data.total}</span></Button></Space>
      <div className="library-alphabet-caption"><Text strong>{activeGroup?`${activeGroup.label} · ${activeGroup.count} 项`:`全部 · ${data.total} 项`}</Text><Text type="secondary">{activeGroup?.letters.map(letter=>`${letter.initial} 开头 ${letter.count} 个`).join(" · ")||"按名称排序"}</Text></div>
      <Text type="secondary">少量相邻字母合并展示，同一字母保留在一组；组内直接向下滚动。</Text>
    </div>}
    <Table<LibraryDirectoryEntry> rowKey="relative_path" size="middle" loading={loading} dataSource={data?.items??[]} virtual={virtual} scroll={virtual?{x:900,y:600}:{x:900}}
      rowClassName={(entry,index)=>startsLetter(entry,index)?"library-initial-start":""}
      locale={{emptyText:<Empty description={loading?"正在读取本地目录":error?"当前目录不可用":query?"当前目录没有匹配的文件或文件夹":"本地文件夹为空"}/>}}
      pagination={false}
      columns={[
        {title:"名称",key:"name",width:400,render:(_,entry,index)=><div className="library-real-name">{icon(entry)}{entry.kind==="directory"?<button className="library-entry-button" onClick={()=>onNavigate(entry.relative_path)} aria-label={`打开本地文件夹 ${entry.name}`}>{startsLetter(entry,index)&&<Tag color="blue">{entry.course_initial}</Tag>}{entry.name}</button>:entry.file_id?<button className="library-entry-button" onClick={()=>onOpenPdf(entry.file_id!)}>{entry.name}</button>:<span>{entry.name}</span>}</div>},
        {title:"修改时间",key:"modified",width:180,render:(_,entry)=><Text type="secondary">{new Date(entry.mtime_ns/1e6).toLocaleString("zh-CN",{hour12:false})}</Text>},
        {title:"大小",key:"size",width:100,render:(_,entry)=><Text type="secondary">{bytes(entry.size_bytes)}</Text>},
        {title:"状态 / 操作",key:"actions",width:170,render:(_,entry)=><Space direction="vertical" size={3}>{rowState(entry)}{entry.file_id&&<Button size="small" onClick={()=>onOpenPdf(entry.file_id!)}>{entry.can_preview?"预览与研究选题":"查看 PDF 登记"}</Button>}</Space>},
      ]}/>
    <div className="library-directory-footer"><Text type="secondary">{data?`当前显示 ${data.items.length} 项${data.groups.length?` / 当前目录共 ${data.total} 项`:""} · `:""}连续滚动，无需翻页</Text><Text type="secondary">每 5 秒同步{data?` · 本次读取 ${new Date(data.synced_at).toLocaleTimeString("zh-CN",{hour12:false})}`:""}</Text></div>
  </Card>;
}
