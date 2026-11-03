import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Alert, Button, Checkbox, Descriptions, Divider, Input, Modal, Select, Space, Spin, Tag, Typography } from 'antd';
import { SendOutlined } from '@ant-design/icons';
import { xianyuRequest } from '../../../lib/api';
import { xianyuPreviewBlockReason } from '../../../lib/xianyu-publish-readiness';
import type { XianyuDraft, XianyuLocation, XianyuPublication, XianyuPublishOptions, XianyuPublishPreview, XianyuPublishState } from '../../../lib/xianyu-types';

const { Paragraph, Text, Title }=Typography;
const busyStates=['uploading','submitting'];
const blockedStates=[...busyStates,'unknown','accepted','succeeded'];
function errorText(error:unknown){
  const e=error as {response?:{data?:{detail?:unknown}}};
  return typeof e.response?.data?.detail==='string'?e.response.data.detail:'读取未完成，请稍后重新核对。';
}
function selectedIndex(options:XianyuPublishOptions){return Math.max(0,options.categories.findIndex(c=>c.selected));}

export function XianyuPublishPanel({draft,dirty,enabled,unavailableReason,images,onStateChange}:{draft:XianyuDraft;dirty:boolean;enabled:boolean;unavailableReason?:string;images:ReactNode;onStateChange:()=>void}){
  const [job,setJob]=useState<XianyuPublication|null>(draft.publication??null);
  const [open,setOpen]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [options,setOptions]=useState<XianyuPublishOptions|null>(null);
  const [category,setCategory]=useState(0);
  const [attributes,setAttributes]=useState<Record<string,number[]>>({});
  const [locations,setLocations]=useState<XianyuLocation[]>([]);
  const [location,setLocation]=useState<string>();
  const [query,setQuery]=useState('北京');
  const [preview,setPreview]=useState<XianyuPublishPreview|null>(null);
  const [confirmed,setConfirmed]=useState(false);
  const [itemId,setItemId]=useState('');
  const callback=useRef(onStateChange);callback.current=onStateChange;
  const base=`/drafts/${draft.id}`;

  useEffect(()=>{setJob(draft.publication??null);},[draft.publication?.id,draft.publication?.state,draft.publication?.updated_at]);

  useEffect(()=>{
    let active=true;
    setOpen(false);setPreview(null);setConfirmed(false);setError('');setJob(draft.publication??null);
    setOptions(null);setAttributes({});setLocations([]);setLocation(undefined);
    void xianyuRequest<XianyuPublishState>(base+'/publish-state').then(r=>{
      if(active)setJob(r.publication);
    }).catch(e=>{if(active)setError(errorText(e));});
    return()=>{active=false;};
  },[draft.id,draft.row_version]);
  useEffect(()=>{
    if(!job||!busyStates.includes(job.state))return;
    let active=true;let timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{
      try{
        const next=await xianyuRequest<XianyuPublication>('/publications/'+job.id);
        if(!active)return;setJob(next);setError('');
        if(busyStates.includes(next.state))timer=setTimeout(poll,2000);
        else callback.current();
      }catch(e){if(active){setError(errorText(e)+' 发布状态会继续核对，请勿重复提交。');timer=setTimeout(poll,5000);}}
    };
    timer=setTimeout(poll,1500);return()=>{active=false;clearTimeout(timer);};
  },[job?.id,job?.state]);

  async function readOptions(previous?:XianyuPublishOptions,index?:number){
    const next=await xianyuRequest<XianyuPublishOptions>(base+'/publish-options',{
      row_version:draft.row_version,...(previous?{previous_options_id:previous.id,category_index:index}:{})},'post');
    setOptions(next);setAttributes({});
    const old=previous?.categories[index??0];
    const match=old?next.categories.findIndex(c=>c.channel_cat_id===old.channel_cat_id&&c.tb_cat_id===old.tb_cat_id):-1;
    setCategory(match>=0?match:selectedIndex(next));return next;
  }
  function chooseDefaultLocation(items:XianyuLocation[]){
    const exact=items.find(i=>['北京','北京市'].includes(i.dto.poiName));
    setLocation(exact?.id);
  }
  async function searchLocation(searchQuery=query){
    const r=await xianyuRequest<{items:XianyuLocation[]}>('/publish-locations',{query:searchQuery},'post');
    setLocations(r.items);chooseDefaultLocation(r.items);
    if(!r.items.length)setError('未查到可用地点，请输入城市或公共地点重新检索。');
  }
  async function begin(){
    setOpen(true);setBusy(true);setError('');setPreview(null);setConfirmed(false);
    try{
      const r=await xianyuRequest<XianyuPublishState>(base+'/publish-state');setJob(r.publication);
      if(r.publication&&blockedStates.includes(r.publication.state))return;
      await xianyuRequest(base+'/publish-source',{},'post');
      if(r.options){setOptions(r.options);setCategory(selectedIndex(r.options));setAttributes({});}
      else await readOptions();
      const q=r.preferred_location_query||'北京';setQuery(q);
      if(r.locations.length){setLocations(r.locations);chooseDefaultLocation(r.locations);}
      else await searchLocation(q);
    }catch(e){setError(errorText(e));}finally{setBusy(false);}
  }
  async function changeCategory(index:number){
    if(!options)return;setBusy(true);setError('');
    try{await readOptions(options,index);}catch(e){setError(errorText(e));}finally{setBusy(false);}
  }
  async function freezePreview(){
    if(!options||!location)return;setBusy(true);setError('');setConfirmed(false);
    try{setPreview(await xianyuRequest<XianyuPublishPreview>(base+'/publish-preview',{
      row_version:draft.row_version,options_id:options.id,category_index:category,attributes,location_id:location},'post'));}
    catch(e){setError(errorText(e));}finally{setBusy(false);}
  }
  async function publish(){
    if(!preview||!confirmed||dirty||busy)return;
    setBusy(true);setError('');
    try{
      const result=await xianyuRequest<XianyuPublication>(base+'/publish',{
        preview_id:preview.id,confirmation:'PUBLISH_THIS_ONE_ITEM'},'post');
      setJob(result);setOpen(false);setPreview(null);setConfirmed(false);callback.current();
    }catch(e){
      setError(errorText(e)+' 如确认请求曾超时，请关闭预览并刷新发布状态。');
      try{const r=await xianyuRequest<XianyuPublishState>(base+'/publish-state');setJob(r.publication);if(r.publication)setOpen(false);}catch{/* Same preview remains idempotent. */}
    }finally{setBusy(false);}
  }
  async function reconcile(){
    if(!job)return;setBusy(true);setError('');
    try{setJob(await xianyuRequest<XianyuPublication>('/publications/'+job.id+'/reconcile',itemId?{item_id:itemId}:{},'post'));callback.current();}
    catch(e){setError(errorText(e));}finally{setBusy(false);}
  }
  const blocked=Boolean(job&&blockedStates.includes(job.state));
  const hasRequired=options?.properties.every(p=>!p.required||attributes[p.property_id]?.length);
  const selectedCategory=options?.categories[category];
  const completeCategory=Boolean(selectedCategory?.cat_id&&selectedCategory?.channel_cat_id);
  const shown=preview?.snapshot.draft??draft;
  const capability=preview?.snapshot.capability??options?.capability;
  const blockReason=xianyuPreviewBlockReason({enabled,unavailableReason,dirty,busy,accountId:draft.account_id,price:draft.price,jobState:job?.state});
  return <div style={{border:'1px solid #375b88',borderRadius:8,padding:16,margin:'4px 0 24px'}}>
    <Space wrap style={{width:'100%',justifyContent:'space-between'}}>
      <Title level={5} style={{margin:0}}>4 · 人工发布</Title><Tag color="blue">自动回复与发货关闭</Tag>
    </Space>
    <Paragraph type="secondary" style={{marginTop:8}}>先核对发布预览，再由你确认上架这一件商品。旧草稿版本会保留。</Paragraph>
    {job&&<Alert showIcon type={job.state==='succeeded'?'success':job.state==='failed'?'error':'info'} message={job.message}
      description={<Space direction="vertical"><Text>对应草稿版本 {job.draft_version} · 已上传 {job.upload_count}/{draft.images.length} 张样张</Text>
        {job.item_url&&<a href={job.item_url} target="_blank" rel="noreferrer">打开闲鱼商品 · {job.item_id}</a>}
        {job.state==='unknown'&&<><Text>请先在闲鱼 App 核对是否已有商品，填写商品链接中的 id 后只回读核验。</Text><Input value={itemId} onChange={e=>setItemId(e.target.value.replace(/\D/g,''))} maxLength={32} placeholder="已有商品编号"/></>}
        {['unknown','accepted'].includes(job.state)&&<Button loading={busy} onClick={()=>void reconcile()} disabled={job.state==='unknown'&&!itemId&&!job.item_id}>回读商品结果</Button>}
      </Space>} style={{marginBottom:12}}/>}
    {error&&!open&&<Alert type="warning" showIcon message={error} style={{marginBottom:12}}/>}
    <Button type="primary" icon={<SendOutlined/>} onClick={()=>void begin()} disabled={!!blockReason}>发布前预览</Button>
    {blockReason&&<Text type="secondary" style={{marginLeft:12}}>{blockReason}</Text>}
    <Modal open={open} width={920} style={{top:24}} styles={{body:{maxHeight:'calc(100vh - 200px)',overflowY:'auto',paddingRight:8}}} title={preview?`确认发布 · ${draft.source.preview_brand?.name??draft.brand_id} ${draft.source.course_code}`:'发布前预览 · 设置类目与所在地'}
      onCancel={()=>{if(!busy){setOpen(false);setConfirmed(false);}}} destroyOnHidden maskClosable={false}
      footer={preview?<Space wrap><Button disabled={busy} onClick={()=>{setPreview(null);setConfirmed(false);}}>返回调整选项</Button>
        <Button type="primary" loading={busy} disabled={!confirmed||dirty||blocked} onClick={()=>void publish()}>确认发布这 1 件商品</Button></Space>:
        <Button type="primary" loading={busy} disabled={!options||!location||!hasRequired||!completeCategory||blocked||dirty} onClick={()=>void freezePreview()}>核对最终发布预览</Button>}>
      <Spin spinning={busy}>
        {error&&<Alert type="warning" showIcon message={error} style={{marginBottom:16}}/>}
        <Descriptions size="small" column={2} bordered items={[
          {key:'account',label:'闲鱼账号',children:shown.account_id},
          {key:'version',label:'草稿版本',children:`#${shown.id} · 版本 ${shown.row_version}`},
          {key:'price',label:'售价',children:<Text strong>¥{Number(shown.price).toFixed(2)}</Text>},
          {key:'shipping',label:'交付设置',children:'电子资料 · 无需邮寄 · 自动发货关闭'},
        ]}/>
        {capability&&<Alert type="info" showIcon style={{margin:'16px 0'}} message={capability.commission.commissionTitle||'平台服务费'}
          description={<div style={{whiteSpace:'pre-wrap'}}>{capability.commission.commissionTips}</div>}/>}
        {!preview?<Space direction="vertical" size={12} style={{width:'100%',marginTop:16}}>
          <Text strong>闲鱼返回的商品类目</Text>
          <Space.Compact style={{width:'100%'}}><Select style={{flex:1}} value={options?category:undefined} disabled={busy} placeholder="读取平台类目后选择"
            options={options?.categories.map((c,i)=>({value:i,label:c.cat_name}))} onChange={i=>void changeCategory(i)}/>
            <Button disabled={busy} onClick={()=>{setBusy(true);setError('');void readOptions().catch(e=>setError(errorText(e))).finally(()=>setBusy(false));}}>重新读取</Button></Space.Compact>
          {!completeCategory&&options&&<Text type="warning">所选类目缺少平台编号，请选择这个类目以读取完整属性。</Text>}
          {options?.properties.map(p=><div key={p.property_id}><Text>{p.property_name}{p.required?'（必填）':''}</Text>
            <Select style={{width:'100%',marginTop:4}} allowClear mode={p.multiple?'multiple':undefined}
              value={p.multiple?(attributes[p.property_id]??[]):attributes[p.property_id]?.[0]}
              options={p.options.map((v,i)=>({value:i,label:v.value_name}))} placeholder={'选择'+p.property_name}
              onChange={(v:number|number[]|undefined)=>setAttributes(a=>({...a,[p.property_id]:v===undefined?[]:Array.isArray(v)?v:[v]}))}/></div>)}
          <Text strong>商品所在地</Text><Text type="secondary">地点检索使用高德。输入城市或公共地点，所选名称会显示在商品中。</Text>
          <Space.Compact style={{width:'100%'}}><Input value={query} onChange={e=>setQuery(e.target.value)} maxLength={60}/><Button disabled={busy||!query.trim()} onClick={()=>{setBusy(true);setError('');void searchLocation().catch(e=>setError(errorText(e))).finally(()=>setBusy(false));}}>检索所在地</Button></Space.Compact>
          <Select style={{width:'100%'}} placeholder="请选择实际显示的所在地" value={location} options={locations.map(l=>({value:l.id,label:l.label}))} onChange={setLocation}/>
        </Space>:<>
          <Paragraph style={{marginTop:16}}><Text strong>类目：</Text>{preview.snapshot.settings.category.cat_name}<br/><Text strong>所在地：</Text>{preview.snapshot.settings.location.label}<br/>
            {preview.snapshot.settings.attributes.map(a=><span key={a.property_name+a.value_name}>{a.property_name}：{a.value_name}　</span>)}</Paragraph>
          <Divider/>
          <Title level={5}>{shown.title}</Title><Paragraph style={{whiteSpace:'pre-wrap'}}>{shown.description}</Paragraph>
          <Text type="secondary">{shown.description.length} 字 · 样张为原 PDF 第 {shown.images.map(i=>i.page).join('、')} 页</Text>
          <div style={{marginTop:16}}>{images}</div>
          <Alert type="warning" showIcon message={preview.notice} style={{margin:'16px 0'}}/>
          <Checkbox checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}>我已核对账号、内容、售价、类目和所在地，确认向闲鱼发布这一件商品。</Checkbox>
          <Paragraph type="secondary" style={{marginTop:8}}>此预览在 {new Date(preview.expires_at).toLocaleTimeString('zh-CN')} 前有效；内容变更后需重新核对。</Paragraph>
        </>}
        <Paragraph type="secondary" style={{marginTop:16,marginBottom:0}}>本轮仅上架 1 件课程 PDF 商品；发货方式待人工处理。</Paragraph>
      </Spin>
    </Modal>
  </div>;
}
