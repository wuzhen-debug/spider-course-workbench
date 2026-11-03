import { Alert, Button, Image, InputNumber, Space, Spin, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { fetchLibraryDetail, fetchLibraryPreview } from '../lib/api';
import type { LibraryDetail, LibraryRevision } from '../lib/course-library-types';

type Props={fileId:number;revisionId:number;filename:string;initialPage?:number;minPage?:number;selectedPage?:number|null;onSelectPage?:(page:number)=>void;selectionDisabled?:boolean;compact?:boolean};

async function previewError(error:unknown):Promise<string>{
  let data=(error as {response?:{data?:unknown}})?.response?.data;
  if(data instanceof Blob){try{data=JSON.parse(await data.text());}catch{/* Keep the local fallback. */}}
  const detail=(data as {detail?:unknown}|undefined)?.detail;
  return typeof detail==='string'?detail:error instanceof Error?error.message:'PDF 页面暂未读取成功，请重试。';
}

function selectedRevision(detail:LibraryDetail,fileId:number,revisionId:number):LibraryRevision{
  const revision=detail.revisions.find(item=>item.id===revisionId&&item.file_id===fileId);
  if(detail.file.id!==fileId||!revision)throw new Error('所选 PDF 版本不存在，未改为显示其他资料。请返回文案核对页重新读取版本。');
  if(detail.file.current_revision_id!==revisionId)throw new Error('这份 PDF 已更新。请返回文案核对页重新读取当前版本，再查看预览。');
  if(detail.file.status!=='ready')throw new Error(detail.file.error||'原 PDF 当前不可读取，请核对本地文件后重试。');
  return revision;
}

function PdfPages({fileId,revisionId,filename,initialPage,minPage=1,selectedPage,onSelectPage,selectionDisabled=false,compact=false}:Props){
  const [page,setPage]=useState(typeof initialPage==='number'&&Number.isInteger(initialPage)&&initialPage>=minPage?initialPage:minPage),[count,setCount]=useState<number|null>(null);
  const [src,setSrc]=useState(''),[loadedPage,setLoadedPage]=useState<number|null>(null),[busy,setBusy]=useState(true),[error,setError]=useState('');
  const [retry,setRetry]=useState(0);
  useEffect(()=>{
    let active=true,objectUrl='';setBusy(true);setSrc('');setLoadedPage(null);setError('');
    void (async()=>{
      try{
        const detail=await fetchLibraryDetail(fileId);if(!active)return;
        const revision=selectedRevision(detail,fileId,revisionId);setCount(revision.page_count);
        if(revision.page_count&&page>revision.page_count)throw new Error('所选页码超过这份 PDF 的页数，请选择有效页码。');
        const blob=await fetchLibraryPreview(fileId,page,revisionId);if(!active)return;
        // The first render may discover the page count. Re-read only the same
        // revision; a changed source is never silently substituted.
        if(!revision.page_count){
          const updated=await fetchLibraryDetail(fileId);if(!active)return;
          setCount(selectedRevision(updated,fileId,revisionId).page_count);
        }
        objectUrl=URL.createObjectURL(blob);
        if(active){setSrc(objectUrl);setLoadedPage(page);}else URL.revokeObjectURL(objectUrl);
      }catch(e){
        const text=await previewError(e);if(active)setError(text);
      }finally{if(active)setBusy(false);}
    })();
    return()=>{active=false;if(objectUrl)URL.revokeObjectURL(objectUrl);};
  },[fileId,revisionId,page,retry]);
  function selectCurrentPage(){
    if(!onSelectPage||busy||!!error||!src||loadedPage!==page||selectionDisabled||!count||page<minPage||page>count)return;
    onSelectPage(page);
  }
  return <div aria-label="原 PDF 分页预览">
    {!compact&&<Typography.Paragraph type="secondary" style={{marginBottom:10,overflowWrap:'anywhere'}}>{filename} · PDF 版本 #{revisionId}</Typography.Paragraph>}
    <Space wrap style={{marginBottom:12}}>
      <Button disabled={busy||page<=minPage} onClick={()=>setPage(p=>p-1)}>上一页</Button>
      <InputNumber aria-label={onSelectPage?"封面正文样张预览页码":"原 PDF 预览页码"} min={minPage} max={count??undefined} precision={0} value={page} disabled={busy}
        style={{width:80}} onChange={value=>{if(typeof value==='number'&&Number.isInteger(value)&&value>=minPage&&(!count||value<=count))setPage(value);}}/>
      <Typography.Text>/ {count??'待读取'} 页</Typography.Text>
      <Button disabled={busy||!count||page>=count} onClick={()=>setPage(p=>p+1)}>下一页</Button>
      {onSelectPage&&<Button type="primary" disabled={busy||!!error||!src||loadedPage!==page||selectionDisabled||!count||page<minPage||page>count} onClick={selectCurrentPage}>{selectedPage===page?'已选为封面样张':'用这一页作封面样张'}</Button>}
    </Space>
    {error&&<Alert type="warning" showIcon message={error} action={<Button size="small" onClick={()=>setRetry(v=>v+1)} disabled={busy}>重试</Button>} style={{marginBottom:12}}/>}
    <Spin spinning={busy}>
      <div style={{width:'100%',maxWidth:compact?240:420,minHeight:200,margin:'0 auto',padding:8,background:'#e9edf3',borderRadius:8,boxSizing:'border-box'}}>
        {src?<Image src={src} width="100%" alt={`${filename} 原 PDF 第 ${page} 页，本机水印预览`} style={{display:'block'}}/>:
          <div style={{minHeight:200,display:'flex',alignItems:'center',justifyContent:'center',color:'#566374'}}>{busy?'正在读取原 PDF 页面…':'暂无页面预览'}</div>}
      </div>
    </Spin>
    <Typography.Paragraph type="secondary" style={{margin:'10px 0 0'}}>点击图片放大。仅在本机按页预览，不修改原 PDF。</Typography.Paragraph>
  </div>;
}

export function CoursePdfInlinePreview(props:Props){
  // A different source/version owns a fresh page cursor and request lifecycle.
  // This also prevents one render of the previous file while effects reset.
  return <PdfPages key={`${props.fileId}:${props.revisionId}`} {...props}/>;
}
