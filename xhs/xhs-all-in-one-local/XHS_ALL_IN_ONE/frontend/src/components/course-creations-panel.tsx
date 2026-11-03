import { FileImageOutlined, FileTextOutlined, FolderOpenOutlined, ReloadOutlined } from '@ant-design/icons';
import { Alert, Button, Collapse, Empty, Input, Space, Spin, Tag, Typography } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../hooks/use-auth';
import { fetchCourseCreations } from '../lib/api';
import type { CourseCreationList } from '../lib/course-creations';

const {Text}=Typography;
const stages:Record<string,[string,string]>={
  copy_pending:['文案待审核','gold'],copy_saved:['文案已保存','blue'],visual_planned:['待制作封面','blue'],
  cover_pending:['封面待审核','gold'],cover_reviewed:['待制作内页','blue'],images_pending:['整套待审核','gold'],
  images_reviewed:['待另存草稿','blue'],draft_saved:['已另存草稿','green'],processing:['处理中','blue'],failed:['上次处理未完成','orange'],
};
function errorText(error:unknown){const d=(error as {response?:{data?:{detail?:unknown}}})?.response?.data?.detail;return typeof d==='string'?d:'课程创作记录暂未加载，请重试。';}

export function CourseCreationsPanel({directory='',fileId,refreshKey=0}:{directory?:string;fileId?:number;refreshKey?:number}){
  const {user}=useAuth();const owner=user?.id;
  const [search,setSearch]=useState('');const [query,setQuery]=useState('');const [allCourses,setAllCourses]=useState(false);
  const [limit,setLimit]=useState(fileId?4:2);const [reload,setReload]=useState(0);
  const [result,setResult]=useState<{key:string;data:CourseCreationList}|null>(null);
  const [error,setError]=useState<{key:string;text:string}|null>(null);const [loading,setLoading]=useState(false);
  const scope=fileId?'':allCourses?'':directory;
  const requestKey=JSON.stringify([owner,scope,fileId,query,limit,reload,refreshKey]);
  const liveKey=useRef(requestKey);liveKey.current=requestKey;
  useEffect(()=>{
    if(owner===undefined)return;
    let active=true;setLoading(true);setError(null);
    void fetchCourseCreations({directory:scope,file_id:fileId,q:query,limit}).then(data=>{if(active)setResult({key:requestKey,data});})
      .catch(e=>{if(active)setError({key:requestKey,text:errorText(e)});}).finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[requestKey]);
  useEffect(()=>{setSearch('');setQuery('');setLimit(fileId?4:2);setAllCourses(false);},[directory,fileId,owner]);
  const current=result?.key===requestKey?result.data:null;
  async function loadMore(){
    if(!current||loading)return;const key=requestKey;setLoading(true);
    try{
      const next=await fetchCourseCreations({directory:scope,file_id:fileId,q:query,limit:6,offset:current.items.length});
      if(liveKey.current!==key)return;
      const ids=new Set(current.items.map(i=>i.id));
      setResult({key,data:{...next,items:[...current.items,...next.items.filter(i=>!ids.has(i.id))]}});
    }catch(e){if(liveKey.current===key)setError({key,text:errorText(e)});}
    finally{if(liveKey.current===key)setLoading(false);}
  }
  return <Collapse className="course-creations" size="small" defaultActiveKey={[]} items={[{
    key:'creations',
    label:<Space><FolderOpenOutlined/><span>{fileId?'这份讲义的创作':'我的课程创作'}</span>{current&&<Tag>{current.total}</Tag>}</Space>,
    extra:<Button aria-label="刷新课程创作" size="small" icon={<ReloadOutlined/>} loading={loading} onClick={event=>{event.stopPropagation();setReload(v=>v+1);}}>刷新</Button>,
    children:<>
    <div className="creation-toolbar">
      <Space wrap>
        {!fileId&&directory&&<Button size="small" onClick={()=>{setAllCourses(v=>!v);setLimit(2);}}>{allCourses?'只看当前目录':'查看全部课程'}</Button>}
        <Input.Search aria-label={fileId?'搜索这份讲义的创作':'搜索课程创作'} placeholder="课程代码、大学或作品标题" value={search} allowClear
          onChange={e=>{setSearch(e.target.value);if(!e.target.value){setQuery('');setLimit(fileId?4:2);}}}
          onSearch={value=>{setQuery(value.trim());setLimit(6);}} style={{width:270,maxWidth:'100%'}}/>
      </Space>
    </div>
    {error?.key===requestKey?<Alert type="warning" showIcon message={error.text} action={<Button onClick={()=>setReload(v=>v+1)}>重试</Button>}/>:!current?<Spin/>:!current.items.length?
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={query?'没有找到匹配的创作，请换一个课程代码或标题。':fileId?'这份讲义还没有保存的创作记录。':'这里会显示已保存的研究文案和图文制作记录。'}/>:<>
      <div className="creation-list">{current.items.map(item=>{
        const [label,color]=stages[item.status]??['待继续','default'];
        return <article className="creation-entry" key={item.id}>
          <div className="creation-summary" title={item.relative_path||item.filename}>
          <Space wrap size={[4,6]}><Tag>{item.university||'大学待确认'} · {item.course_code||'课程待确认'}</Tag><Tag color={color}>{label}</Tag><Text type="secondary">{{research:'研究文案',visual:'图文制作',pdf:'PDF 样张'}[item.kind]}</Text></Space>
          <Link className="creation-title" to={item.primary_url}>{item.title||item.filename||'未命名创作'}</Link>
          <Space wrap size={[12,4]} className="creation-progress">
            <Text type="secondary">{item.image_count>0?<><FileImageOutlined/> {item.image_count} 张图</>:<><FileTextOutlined/> {item.kind==='research'?'文案':'暂无图片'}</>}</Text>
            <Text type="secondary">{item.updated_at?new Date(item.updated_at).toLocaleString('zh-CN',{hour12:false}):''}</Text>
          </Space>
          {!item.draft_available&&item.draft_id&&<Text type="secondary">原草稿关联暂不可用，原制作记录仍保留。</Text>}
          </div>
          <Space wrap className="creation-actions">
            {item.draft_available&&item.draft_id&&<Link to={`/platforms/xhs/drafts?draft_id=${item.draft_id}`}><Button type="primary" size="small">打开草稿</Button></Link>}
            <Link to={item.primary_url}><Button type={item.draft_available?'default':'primary'} size="small">{item.primary_label}</Button></Link>
            {!fileId&&item.source_url&&<Link to={item.source_url}>查看讲义</Link>}
          </Space>
        </article>;
      })}</div>
      {current.items.length<current.total&&<Button className="creation-more" onClick={()=>void loadMore()} loading={loading}>继续显示更多创作（已显示 {current.items.length} / {current.total}）</Button>}
    </>}
    </>,
  }]}/>;
}
