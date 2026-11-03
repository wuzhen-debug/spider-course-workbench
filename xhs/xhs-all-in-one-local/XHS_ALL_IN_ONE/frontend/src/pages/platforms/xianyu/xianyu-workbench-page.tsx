import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Col, Collapse, Empty, Form, Image, Input, InputNumber, Modal, Row, Select, Space, Spin, Tag, Typography, message } from 'antd';
import { Link, useSearchParams } from 'react-router-dom';
import { QrcodeOutlined, ReloadOutlined, SaveOutlined } from '@ant-design/icons';
import { PageHeader } from '../../../components/layout/app-shell';
import { xianyuRequest, xianyuDraftImage } from '../../../lib/api';
import type { XianyuAccount, XianyuDraft, XianyuLogin, XianyuMaterial, XianyuStatus } from '../../../lib/xianyu-types';
import { XianyuPublishPanel } from './xianyu-publish-panel';

const { Text, Title, Paragraph } = Typography;

function DraftImages({draft}:{draft:XianyuDraft}) {
  const [urls,setUrls]=useState<(string|null)[]>([]);
  const [loading,setLoading]=useState(false);
  const fingerprint=draft.images.map(im=>im.sha256).join(':');
  useEffect(()=>{
    let active=true; const made:string[]=[];setLoading(true);setUrls([]);
    void Promise.allSettled(draft.images.map((_,index)=>xianyuDraftImage(draft.id,index))).then(results=>{
      const next=results.map(r=>{if(r.status!=='fulfilled')return null;const u=URL.createObjectURL(r.value);made.push(u);return u;});
      if(active){setUrls(next);setLoading(false);} else made.forEach(u=>URL.revokeObjectURL(u));
    });
    return ()=>{active=false;made.forEach(u=>URL.revokeObjectURL(u));};
  },[draft.id,fingerprint]);
  function download(index:number){const url=urls[index];if(!url)return;const a=document.createElement('a');a.href=url;a.download=`${draft.source.preview_brand?.name??draft.brand_id}_${draft.source.course_code}_第${draft.images[index].page}页.png`;a.click();}
  return <Spin spinning={loading}><Image.PreviewGroup><Row gutter={[12,16]}>{draft.images.map((im,index)=><Col xs={12} sm={8} lg={6} key={im.sha256}>
    <div style={{border:'1px solid #dbe4ee',borderRadius:8,padding:8,background:'#fff'}}>
      {urls[index]?<Image src={urls[index]!} alt={`${draft.source.course_code} 原 PDF 第 ${im.page} 页`} width="100%" style={{height:190,objectFit:'contain'}}/>:<div style={{height:190,display:'grid',placeItems:'center',color:'#64748b'}}>{loading?'读取样张…':'样张读取失败，请刷新'}</div>}
      <Space style={{width:'100%',justifyContent:'space-between',marginTop:6}}><Text style={{color:'#172f47',fontSize:12}}>原 PDF 第 {im.page} 页</Text><Button type="link" size="small" disabled={!urls[index]} onClick={()=>download(index)}>下载</Button></Space>
    </div></Col>)}</Row></Image.PreviewGroup></Spin>;
}

export function XianyuWorkbenchPage(){
  const [searchParams,setSearchParams]=useSearchParams();
  const wantedDraft=useRef(Number(searchParams.get('draft_id'))||null);
  const [form]=Form.useForm();
  const [status,setStatus]=useState<XianyuStatus|null>(null);
  const [accounts,setAccounts]=useState<XianyuAccount[]>([]);
  const [materials,setMaterials]=useState<XianyuMaterial[]>([]);
  const [drafts,setDrafts]=useState<XianyuDraft[]>([]);
  const [selected,setSelected]=useState<XianyuDraft|null>(null);
  const [packageId,setPackageId]=useState<number>();
  const [loading,setLoading]=useState(true);
  const [saving,setSaving]=useState(false);
  const [dirty,setDirty]=useState(false);
  const [login,setLogin]=useState<XianyuLogin|null>(null);
  const [qrBusy,setQrBusy]=useState(false);
  const [qrError,setQrError]=useState('');
  const [loadError,setLoadError]=useState('');
  const selectedRef=useRef<XianyuDraft|null>(null);
  const dirtyRef=useRef(false);
  selectedRef.current=selected;dirtyRef.current=dirty;

  async function load(){
    setLoading(true);setLoadError('');
    const result=await Promise.allSettled([
      xianyuRequest<XianyuStatus>('/status'),xianyuRequest<{items:XianyuAccount[]}>('/accounts'),
      xianyuRequest<{items:XianyuMaterial[]}>('/materials'),xianyuRequest<{items:XianyuDraft[]}>('/drafts')]);
    if(result[0].status==='fulfilled')setStatus(result[0].value);else{setStatus(null);setLoadError('独立服务暂不可用。已有草稿会保留，恢复服务后可刷新继续。');}
    if(result[1].status==='fulfilled')setAccounts(result[1].value.items);
    if(result[2].status==='fulfilled'){const items=result[2].value.items;setMaterials(items);setPackageId(id=>id??items.find(i=>!i.source_stale)?.package_id);}
    if(result[3].status==='fulfilled'){
      const items=result[3].value.items;setDrafts(items);
      if(!dirtyRef.current){const active=items.find(d=>d.id===(selectedRef.current?.id??wantedDraft.current))??items[0]??null;setSelected(active);}
    }
    if(result.some(r=>r.status==='rejected'))setLoadError(e=>e||'部分内容未读取成功，请刷新重试。');
    setLoading(false);
  }
  useEffect(()=>{void load();},[]);
  useEffect(()=>{
    if(selected){form.setFieldsValue({...selected,price:selected.price?Number(selected.price):null,account_id:selected.account_id??undefined});setDirty(false);}
  },[selected?.id,selected?.row_version]);
  useEffect(()=>{
    const handler=(e:BeforeUnloadEvent)=>{if(dirtyRef.current){e.preventDefault();e.returnValue='';}};
    window.addEventListener('beforeunload',handler);return()=>window.removeEventListener('beforeunload',handler);
  },[]);
  const sessionId=login?.session_id;
  useEffect(()=>{
    if(!sessionId||!['waiting','scanned'].includes(login?.status??''))return;
    let cancelled=false;let timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{
      try{
        const next=await xianyuRequest<XianyuLogin>(`/login/${sessionId}`);
        if(cancelled)return;
        setLogin(prev=>({...prev,...next}));
        if(next.status==='success'){
          message.success('闲鱼账号已绑定，自动运营保持关闭');
          const r=await xianyuRequest<{items:XianyuAccount[]}>('/accounts');if(!cancelled)setAccounts(r.items);
        }else if(['waiting','scanned'].includes(next.status)){timer=setTimeout(poll,2500);}
      }catch{if(!cancelled)setQrError('登录状态暂未读到，请关闭弹窗后重新打开扫码入口核对。');}
    };
    timer=setTimeout(poll,1500);return()=>{cancelled=true;clearTimeout(timer);};
    // The loop handles status transitions. Depending on login.status cancels
    // the successful poll before its account-list request can finish.
  },[sessionId]);

  async function startLogin(){
    setQrBusy(true);setQrError('');
    try{setLogin(await xianyuRequest<XianyuLogin>('/login',{brand_id:'xingtu'},'post'));}
    catch{setQrError('暂未取得闲鱼二维码，请稍后手动重试。');}
    finally{setQrBusy(false);}
  }
  async function save(){
    if(!selected)return;const values=await form.validateFields();setSaving(true);
    try{
      const saved=await xianyuRequest<XianyuDraft>(`/drafts/${selected.id}`,{row_version:selected.row_version,title:values.title,description:values.description,
        price:values.price==null?null:Number(values.price).toFixed(2),account_id:values.account_id??null,delivery_note:values.delivery_note??''},'patch');
      setSelected(saved);setDrafts(items=>items.map(d=>d.id===saved.id?saved:d));setDirty(false);message.success('商品草稿已保存为新版本');
    }finally{setSaving(false);}
  }
  function chooseDraft(id:number){
    const next=drafts.find(d=>d.id===id);if(!next)return;
    const choose=()=>{setDirty(false);setSelected(next);const params=new URLSearchParams(searchParams);params.set('draft_id',String(id));setSearchParams(params);};
    if(dirty){Modal.confirm({title:'当前修改尚未保存',content:'切换草稿将放弃页面上的未保存修改，已保存版本会保留。',okText:'切换草稿',cancelText:'继续编辑',onOk:choose});}
    else choose();
  }
  const material=materials.find(m=>m.package_id===packageId);
  const dualLink=material?`/platforms/xhs/course-center?library_file_id=${material.file_id}&dual_drafts=1&${material.platform_pair_id?`platform_pair_id=${material.platform_pair_id}`:`source_package_id=${material.package_id}`}`:'/platforms/xhs/course-center';
  const publicationText=selected?.publication?({uploading:'正在上传样张',submitting:'正在提交商品',unknown:'发布结果待核对',accepted:'平台已返回商品编号',succeeded:'已回读发布结果',failed:'本次发布未完成'}[selected.publication.state]):'尚未发布';
  return <>
    <PageHeader eyebrow="XIANYU · COURSE MATERIALS" title="闲鱼商品草稿" description="将课程资料与真实样张整理为闲鱼商品介绍，先保存，再人工审核。" action={<Button icon={<ReloadOutlined/>} onClick={()=>void load()} loading={loading}>刷新</Button>}/>
    <Space wrap style={{marginBottom:16}}><Tag color="blue">{selected?.source.preview_brand?.name??status?.brand_name??'课程资料'}</Tag>{selected&&<Tag>{selected.source.university} · {selected.source.course_code}</Tag>}<Tag color={status?.ready?'green':'orange'}>{status?.ready?'独立服务已连接':'服务待连接'}</Tag><Tag>{status?.manual_publish_enabled?'手动发布 · 自动回复与发货关闭':'发布、自动回复与发货关闭'}</Tag><Link to="/platforms/xhs/course-center">PDF 双平台稿</Link></Space>
    {loadError&&<Alert type="warning" showIcon message={loadError} style={{marginBottom:16}}/>}
    <Row gutter={[20,20]}>
      <Col xs={24} lg={8}>
        <Card title="1 · 绑定一个账号" style={{marginBottom:16}}>
          {accounts.length?accounts.map(a=><div key={a.account_id}><Text strong>{a.display_name}</Text><Paragraph type="secondary" style={{margin:'8px 0'}}>闲鱼账号 ID：{a.account_id}<br/>已扫码绑定 · {status?.manual_publish_enabled?'可人工确认发布':'当前仅用于商品草稿'}</Paragraph></div>):<Paragraph type="secondary">请用星途留学对应的闲鱼账号扫码。登录后不会启动自动回复或发货。</Paragraph>}
          <Button icon={<QrcodeOutlined/>} onClick={()=>void startLogin()} loading={qrBusy} disabled={!status?.ready}>{accounts.length?'重新扫码确认账号':'扫码绑定闲鱼账号'}</Button>
          {qrError&&<Alert style={{marginTop:12}} type="warning" message={qrError}/>}
        </Card>
        <Card title="2 · 选择课程资料" style={{marginBottom:16}}>
          <Select style={{width:'100%'}} placeholder="选择现有 PDF 样张记录" value={packageId} options={materials.map(m=>({value:m.package_id,label:`${m.title} · 样张 #${m.package_id}`,disabled:m.source_stale}))} onChange={setPackageId}/>
          {material&&<Paragraph type="secondary" style={{marginTop:12}}>{material.page_count} 页 PDF · {material.image_count} 张真实样张<br/>{material.brand_name} · 原 PDF 第 {material.preview_pages.join('、')} 页</Paragraph>}
          {!material&&!loading&&<Paragraph type="secondary" style={{marginTop:12}}>先从本地题库选择一份 PDF，即可生成两平台稿。</Paragraph>}
          <Link to={dualLink}><Button type="primary" block disabled={dirty||!!material?.source_stale}>{material?'打开这份资料的两平台稿':'选择 PDF 生成两平台稿'}</Button></Link>
          <Text type="secondary" style={{display:'block',marginTop:8,fontSize:12}}>分别生成小红书笔记与闲鱼商品介绍；在双平台页审核后，可导入本机闲鱼商品草稿。</Text>
        </Card>
        <Card title={`已保存的商品草稿（${drafts.length}）`}>
          {drafts.length?<Select style={{width:'100%'}} value={selected?.id} onChange={chooseDraft} options={drafts.map(d=>({value:d.id,label:`#${d.id} ${d.title}`}))}/>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未创建商品草稿"/>}
        </Card>
      </Col>
      <Col xs={24} lg={16}>
        {selected?<Card title={<Space wrap><span>3 · 编辑商品草稿</span><Tag color={selected.published?'green':'orange'}>{selected.publication?publicationText:'待人工审核'}</Tag></Space>} extra={<Text type="secondary">#{selected.id} · 版本 {selected.row_version}</Text>}>
          <Form form={form} layout="vertical" onValuesChange={()=>setDirty(true)} disabled={Boolean(selected.publication&&['uploading','submitting'].includes(selected.publication.state))}>
            <Form.Item label="商品标题" name="title" rules={[{required:true,whitespace:true,message:'请填写商品标题'}]}><Input maxLength={200} showCount/></Form.Item>
            <Form.Item label="商品描述" name="description" rules={[{required:true,whitespace:true,message:'请填写商品描述'}]}><Input.TextArea rows={11} maxLength={1500} showCount/></Form.Item>
            <Row gutter={16}><Col xs={24} sm={9}><Form.Item label="售价（可暂留空）" name="price"><InputNumber min={0.01} max={9999999999.99} precision={2} prefix="¥" placeholder="待填写" style={{width:'100%'}}/></Form.Item></Col><Col xs={24} sm={15}><Form.Item label="关联闲鱼账号" name="account_id"><Select allowClear placeholder="选择同品牌账号，也可暂不绑定" options={accounts.filter(a=>a.brand_id===selected.brand_id).map(a=>({value:a.account_id,label:`${a.display_name} · ${a.account_id}`}))}/></Form.Item></Col></Row>
            <Form.Item label="交付说明" name="delivery_note"><Input.TextArea rows={2} maxLength={500}/></Form.Item>
            <Space wrap style={{marginBottom:20}}><Button type="primary" icon={<SaveOutlined/>} loading={saving} onClick={()=>void save()}>保存商品草稿</Button><Text type="secondary">{dirty?'有未保存修改':'当前版本已保存'} · {publicationText}{selected.publication?`（版本 ${selected.publication.draft_version}）`:''}</Text></Space>
          </Form>
          {selected.source.file_id&&<Paragraph><Link to={`/platforms/xhs/course-center?library_file_id=${selected.source.file_id}&dual_drafts=1&${selected.source.platform_pair_id?`platform_pair_id=${selected.source.platform_pair_id}`:`source_package_id=${selected.source.package_id}`}`}>打开对应的 PDF 双平台稿</Link></Paragraph>}
          <XianyuPublishPanel draft={selected} dirty={dirty} enabled={Boolean(status?.ready&&status.manual_publish_enabled)} unavailableReason={!status?.ready?'独立服务尚未连接，请刷新后重试。':'手动发布尚未启用，草稿仍保留。'} images={<DraftImages draft={selected}/>} onStateChange={()=>void load()}/>
          <Title level={5}>真实 PDF 样张 · {selected.images.length} 张</Title>
          <Paragraph type="secondary">本草稿选页：原 PDF 第 {selected.images.map(im=>im.page).join('、')} 页。点击图片可放大查看，样张保留对应品牌 Logo 和水印。</Paragraph>
          <DraftImages draft={selected}/>
          <Collapse style={{marginTop:20}} items={[{key:'source',label:'资料来源与版本',children:<div><Paragraph>{selected.source.filename}<br/>{selected.source.university} · {selected.source.course_code} · {selected.source.term}<br/>来源样张记录 #{selected.source.package_id} · 原 PDF {selected.source.page_count} 页</Paragraph><Text type="secondary" style={{wordBreak:'break-all'}}>SHA-256：{selected.source.sha256}</Text><Paragraph type="secondary" style={{marginTop:8}}>闲鱼商品文案与小红书原稿分别保存；本草稿仍需人工审核。</Paragraph></div>}]}/>
        </Card>:<Card style={{minHeight:360,display:'grid',placeItems:'center'}}><Empty description="选择课程资料，创建第一篇闲鱼商品草稿"/></Card>}
      </Col>
    </Row>
    <Modal open={Boolean(login)} title="星途留学 · 闲鱼账号扫码绑定" footer={null} onCancel={()=>{setLogin(null);setQrError('');}} destroyOnHidden>
      {login?.status==='success'?<Alert type="success" showIcon message="账号已绑定" description="回到草稿，选择这个账号并保存。发布需人工确认，自动回复与发货保持关闭。"/>:<>
        {login?.qr_code_url&&['waiting','scanned'].includes(login.status)&&<div style={{textAlign:'center'}}><Image src={login.qr_code_url} alt="闲鱼官方登录二维码" preview={false} width={260}/></div>}
        <Paragraph style={{marginTop:16}}>{login?.status==='scanned'?'已扫码，请在闲鱼 App 中确认登录。':login?.status==='waiting'?'请使用闲鱼 App 扫码，并确认这是星途留学对应的账号。':login?.status==='verification_required'?'闲鱼要求本人完成官方验证。':login?.status==='expired'?'二维码已过期，请重新获取。':'登录未完成，请重新获取二维码。'}</Paragraph>
        {login?.verification_url&&<a href={login.verification_url} target="_blank" rel="noreferrer">打开本次闲鱼官方验证页面</a>}
        {['expired','cancelled','not_found','verification_required'].includes(login?.status??'')&&<Button style={{marginTop:12}} onClick={()=>void startLogin()} loading={qrBusy}>重新获取登录二维码</Button>}
        {qrError&&<Alert type="warning" message={qrError}/>}
      </>}
    </Modal>
  </>;
}
