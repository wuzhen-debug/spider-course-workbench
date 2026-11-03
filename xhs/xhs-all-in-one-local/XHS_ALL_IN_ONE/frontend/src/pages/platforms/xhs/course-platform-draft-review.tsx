import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Checkbox, Collapse, Empty, Image, Input, InputNumber, Modal, Select, Space, Spin, Tabs, Tag, Typography, message } from 'antd';
import { Link } from 'react-router-dom';
import { approveLibraryDraftReview, fetchLibraryDraftHistory, fetchLibraryDraftImage, fetchLibraryDraftReview, pdfPlatformImage, pdfPlatformRequest, prepareLibraryDraft } from '../../../lib/api';
import type { LibraryDetail, LibraryDraftPlan, LibraryDraftRecipe, LibraryDraftReview } from '../../../lib/course-library-types';
import type { PlatformImage, PlatformPair, PlatformPairSummary, XianyuReview } from '../../../lib/course-platform-types';
import './course-platform-draft-review.css';

const {Text,Paragraph}=Typography;
function failure(e:unknown){const d=(e as {response?:{data?:{detail?:unknown}}})?.response?.data?.detail;return typeof d==='string'?d:'本机请求未完成，已保存版本保留，请重试。';}
function pages(value:string){const p=value.split(/[,，、\s]+/).filter(Boolean).map(Number);if(!p.length||p.length>9||p.some(n=>!Number.isInteger(n)||n<1)||new Set(p).size!==p.length)throw Error('请填写 1–9 个不重复的正整数页码');return p;}
function ImageList({images,load,identity}:{images:PlatformImage[];load:(index:number)=>Promise<Blob>;identity:string}){
  const [urls,setUrls]=useState<(string|null)[]>([]);const [busy,setBusy]=useState(false);
  useEffect(()=>{let alive=true;const made:string[]=[];setUrls([]);setBusy(true);
    void Promise.allSettled(images.map((_,i)=>load(i))).then(results=>{const next=results.map(r=>{if(r.status==='rejected')return null;const u=URL.createObjectURL(r.value);made.push(u);return u;});if(alive){setUrls(next);setBusy(false);}else made.forEach(u=>URL.revokeObjectURL(u));});
    return()=>{alive=false;made.forEach(u=>URL.revokeObjectURL(u));};
  },[identity]);
  return <Spin spinning={busy}><Image.PreviewGroup><div className="dual-samples">{images.map((im,i)=><div className="dual-sample" key={`${i}-${im.sha256}`}>
    {urls[i]?<Image src={urls[i]!} alt={`原 PDF 第 ${im.page} 页`} style={{height:180,objectFit:'contain'}} width="100%"/>:<div style={{height:180}}>{busy?'读取样张…':'样张未读到，请重新打开'}</div>}
    <Text>原 PDF 第 {im.page} 页</Text>{urls[i]&&<a href={urls[i]!} download={`PDF样张_第${im.page}页.png`}>下载原图</a>}
  </div>)}</div></Image.PreviewGroup></Spin>;
}

export function CoursePlatformDraftReview({detail,initialPairId,initialSourcePackageId,onClose,onSelectPair}:{detail:LibraryDetail;initialPairId?:number;initialSourcePackageId?:number;onClose:()=>void;onSelectPair:(id:number)=>void}){
  const fileId=detail.file.id;const revision=detail.revisions.find(r=>r.id===detail.file.current_revision_id);
  const defaultPages=Array.from({length:Math.min(revision?.page_count??9,9)},(_,i)=>i+1).join(', ');
  const [brand,setBrand]=useState<string>();const [mode,setMode]=useState<'ai'|'local'>('ai');const [pageInput,setPageInput]=useState(defaultPages);
  const [samePages,setSamePages]=useState(true);const [xyPageInput,setXyPageInput]=useState(defaultPages);const [instruction,setInstruction]=useState('');
  const [plan,setPlan]=useState<LibraryDraftPlan|null>(null);const [planBusy,setPlanBusy]=useState(false);const [planError,setPlanError]=useState('');
  const [createOpen,setCreateOpen]=useState(false);
  const [pair,setPair]=useState<PlatformPair|null>(null);const [history,setHistory]=useState<PlatformPairSummary[]>([]);const [legacy,setLegacy]=useState<LibraryDraftReview[]>([]);const [legacyId,setLegacyId]=useState<number>();
  const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [active,setActive]=useState('xhs');
  const [xs,setXs]=useState({title:'',body:'',tags:'',pages:''});const [xy,setXy]=useState({title:'',description:'',price:null as number|null,delivery_note:'',pages:''});
  const [xsDirty,setXsDirty]=useState(false);const [xyDirty,setXyDirty]=useState(false);const [reviewed,setReviewed]=useState(false);
  const [oldXs,setOldXs]=useState<LibraryDraftReview|null>(null);const [oldXy,setOldXy]=useState<XianyuReview|null>(null);
  const [oldBusy,setOldBusy]=useState(false);const request=useRef(crypto.randomUUID());const saveRequest=useRef(crypto.randomUUID());
  const xsBase=useRef<number|null>(null);const xyBase=useRef<number|null>(null);
  const selection=useRef<number|null>(null);
  const dirty=xsDirty||xyDirty;const dirtyRef=useRef(dirty);dirtyRef.current=dirty;
  function fillXs(data:LibraryDraftReview){xsBase.current=data.id;setXs({title:data.title,body:data.body,tags:data.tags.join('、'),pages:data.images.map(im=>im.page).join(', ')});setXsDirty(false);setReviewed(false);setOldXs(null);saveRequest.current=crypto.randomUUID();}
  function fillXy(data:XianyuReview){xyBase.current=data.row_version;setXy({title:data.title,description:data.description,price:data.price?Number(data.price):null,delivery_note:data.delivery_note,pages:data.images.map(im=>im.page).join(', ')});setXyDirty(false);setOldXy(null);}
  function accept(data:PlatformPair){if(data.file_id!==fileId)throw Error('稿件不属于当前 PDF');selection.current=data.id;setPair(data);fillXs(data.xhs);fillXy(data.xianyu);setCreateOpen(false);setError('');}
  async function refreshHistory(){const [a,b]=await Promise.allSettled([pdfPlatformRequest<{items:PlatformPairSummary[]}>(`/files/${fileId}/platform-drafts`),fetchLibraryDraftHistory(fileId)]);if(a.status==='fulfilled')setHistory(a.value.items);if(b.status==='fulfilled'){setLegacy(b.value);setLegacyId(v=>v??b.value[0]?.id);}}
  useEffect(()=>{if(initialPairId&&selection.current===initialPairId)return;let alive=true;setBusy(true);void (async()=>{
    try{await refreshHistory();let data:PlatformPair|null=null;
      if(initialPairId)data=await pdfPlatformRequest<PlatformPair>(`/platform-drafts/${initialPairId}`);
      else if(initialSourcePackageId)data=await pdfPlatformRequest<PlatformPair>(`/files/${fileId}/platform-drafts/from-existing`,{package_id:initialSourcePackageId},'post');
      else{const list=await pdfPlatformRequest<{items:PlatformPairSummary[]}>(`/files/${fileId}/platform-drafts`);if(list.items[0])data=await pdfPlatformRequest<PlatformPair>(`/platform-drafts/${list.items[0].id}`);}
      if(alive&&data){accept(data);await refreshHistory();}else if(alive)setCreateOpen(true);
    }catch(e){if(alive)setError(failure(e));}finally{if(alive)setBusy(false);}
  })();return()=>{alive=false;};},[fileId,initialPairId,initialSourcePackageId]);
  useEffect(()=>{const handler=(e:BeforeUnloadEvent)=>{if(dirtyRef.current){e.preventDefault();e.returnValue='';}};window.addEventListener('beforeunload',handler);return()=>window.removeEventListener('beforeunload',handler);},[]);
  useEffect(()=>{setPlan(null);setPlanError('');request.current=crypto.randomUUID();if(!brand||!revision)return;
    let alive=true;let selected:number[];try{selected=pages(pageInput);if(!samePages)pages(xyPageInput);}catch(e){setPlanError((e as Error).message);return;}
    setPlanBusy(true);const timer=setTimeout(()=>{const recipe:LibraryDraftRecipe={revision_id:revision.id,pages:selected,mode,instruction,brand_id:brand};void prepareLibraryDraft(fileId,recipe).then(p=>{if(alive)setPlan(p);}).catch(e=>{if(alive)setPlanError(failure(e));}).finally(()=>{if(alive)setPlanBusy(false);});},350);
    return()=>{alive=false;clearTimeout(timer);};
  },[fileId,revision?.id,brand,mode,pageInput,xyPageInput,samePages,instruction]);
  function discardThen(run:()=>void){if(!dirty)run();else Modal.confirm({title:'当前修改尚未保存',content:'继续后会放弃页面上的未保存修改，已保存的两版及历史会保留。',okText:'继续',cancelText:'返回保存',onOk:run});}
  async function openPair(id:number){setBusy(true);try{const value=await pdfPlatformRequest<PlatformPair>(`/platform-drafts/${id}`);accept(value);onSelectPair(value.id);}catch(e){setError(failure(e));}finally{setBusy(false);}}
  async function generate(){if(!plan||!brand||!revision)return;setBusy(true);setError('');try{
    const data=await pdfPlatformRequest<PlatformPair>(`/files/${fileId}/platform-drafts`,{revision_id:revision.id,pages:pages(pageInput),xianyu_pages:pages(samePages?pageInput:xyPageInput),mode,instruction,brand_id:brand,plan_digest:plan.plan_digest,request_key:request.current,external_consent:mode==='ai'},'post');
    accept(data);onSelectPair(data.id);request.current=crypto.randomUUID();await refreshHistory();message.success('两套平台稿已分别保存，等待人工审核');
  }catch(e){setError(failure(e));}finally{setBusy(false);}}
  async function useExisting(){if(!legacyId)return;setBusy(true);try{const value=await pdfPlatformRequest<PlatformPair>(`/files/${fileId}/platform-drafts/from-existing`,{package_id:legacyId},'post');accept(value);onSelectPair(value.id);await refreshHistory();message.success('已保留原稿并补齐双平台工作区');}catch(e){setError(failure(e));}finally{setBusy(false);}}
  async function saveXs(){if(!pair)return;setBusy(true);try{
    const result=await pdfPlatformRequest<PlatformPair>(`/platform-drafts/${pair.id}/xhs/versions`,{package_id:xsBase.current,request_key:saveRequest.current,title:xs.title,body:xs.body,pages:pages(xs.pages),tags:xs.tags.split(/[、,，\n]+/).map(t=>t.replace(/^#/,'').trim()).filter(Boolean)},'post');
    setPair(result);fillXs(result.xhs);if(!xyDirty)fillXy(result.xianyu);await refreshHistory();message.success('小红书版已另存，闲鱼版保持独立');
  }catch(e){setError(failure(e));}finally{setBusy(false);}}
  async function saveXy(){if(!pair)return;setBusy(true);try{
    const result=await pdfPlatformRequest<PlatformPair>(`/platform-drafts/${pair.id}/xianyu`,{row_version:xyBase.current,title:xy.title,description:xy.description,price:xy.price?.toFixed(2)??null,delivery_note:xy.delivery_note,pages:pages(xy.pages)},'patch');
    setPair(result);fillXy(result.xianyu);if(!xsDirty)fillXs(result.xhs);await refreshHistory();message.success('闲鱼版已另存，小红书版保持独立');
  }catch(e){setError(e instanceof Error&&!('response' in e)?e.message:failure(e));}finally{setBusy(false);}}
  async function approveXs(){if(!pair)return;setBusy(true);try{const value=await approveLibraryDraftReview(pair.xhs.id,pair.xhs.review_digest);setPair({...pair,xhs:value});message.success('已加入小红书草稿箱，等待后续人工发布');}catch(e){setError(failure(e));}finally{setBusy(false);}}
  async function exportXy(){if(!pair)return;setBusy(true);try{const value=await pdfPlatformRequest<PlatformPair>(`/platform-drafts/${pair.id}/xianyu/export`,{row_version:pair.xianyu.row_version},'post');setPair(value);fillXy(value.xianyu);await refreshHistory();message.success('已导入本机闲鱼商品草稿，尚未提交平台');}catch(e){setError(failure(e));}finally{setBusy(false);}}
  async function readOld(platform:'xhs'|'xianyu',id:number){if(!pair)return;setOldBusy(true);try{if(platform==='xhs')setOldXs(await fetchLibraryDraftReview(id));else setOldXy(await pdfPlatformRequest<XianyuReview>(`/platform-drafts/${pair.id}/xianyu/versions/${id}`));}catch(e){setError(failure(e));}finally{setOldBusy(false);}}
  const xhsView=oldXs??pair?.xhs;const xyView=oldXy??pair?.xianyu;
  return <Modal open title="PDF 双平台稿 · 小红书＋闲鱼" width={1220} footer={null} onCancel={()=>discardThen(onClose)} maskClosable={false} destroyOnHidden>
    <Spin spinning={busy||oldBusy}><div className="dual-platform-workspace">
      <div className="dual-source"><Text strong>{detail.file.university} · {detail.file.course_code}</Text><Text type="secondary">{detail.file.filename}</Text><Tag>两版分别保存和审核</Tag></div>
      {error&&<Alert type="error" showIcon message={error} closable onClose={()=>setError('')} style={{marginBottom:12}}/>}
      <Collapse activeKey={createOpen?['create']:[]} onChange={keys=>setCreateOpen(keys.includes('create'))} items={[{key:'create',label:'从这份 PDF 生成新的两平台稿',children:<div className="dual-create-grid">
        <label>品牌<Select aria-label="双平台品牌" placeholder="选择这份资料的品牌" value={brand} onChange={setBrand} options={[{value:'xingtu',label:'星途留学'},{value:'wenguo',label:'稳过留学'}]}/></label>
        <label>文案方式<Select aria-label="双平台文案方式" value={mode} onChange={setMode} options={[{value:'ai',label:'AI 小红书文案＋本机闲鱼商品文案'},{value:'local',label:'本机生成两版（不调用 AI）'}]}/></label>
        <label>小红书样张页码<Input aria-label="小红书生成页码" value={pageInput} onChange={e=>setPageInput(e.target.value)}/></label>
        <div className="dual-field"><Text>闲鱼样张页码</Text><Checkbox aria-label="闲鱼初始使用相同选页" checked={samePages} onChange={e=>setSamePages(e.target.checked)}>初始使用相同选页</Checkbox>{!samePages&&<Input aria-label="闲鱼生成页码" value={xyPageInput} onChange={e=>setXyPageInput(e.target.value)}/>}</div>
        <label className="dual-wide">小红书写作要求（可留空）<Input aria-label="小红书写作要求" value={instruction} maxLength={800} onChange={e=>setInstruction(e.target.value)}/></label>
        <div className="dual-wide">{planError&&<Alert type="warning" message={planError}/>}<Paragraph type="secondary" style={{marginBottom:8}}>{mode==='ai'?`点击生成会将所选小红书页的提取文字、课程信息和写作要求发送至 ${plan?.model?.destination??'所配置的模型服务'}（${plan?.model?.model_name??'读取中'}）。闲鱼商品文案由本机从其选页提取，不追加模型调用。`:'两版文案及真实水印样张均在本机生成。'}两平台各自保留标题、正文、选页和历史，生成后均待审核。</Paragraph>
          <Button type="primary" loading={planBusy||busy} disabled={!plan||!brand||!!planError||mode==='ai'&&!plan.model?.configured} onClick={()=>discardThen(()=>void generate())}>生成闲鱼＋小红书两版</Button>
        </div>
      </div>}]}/>
      <Collapse style={{margin:'12px 0'}} items={[{key:'history',label:`双平台记录与旧小红书记录（${history.length} / ${legacy.length}）`,children:<Space direction="vertical" style={{width:'100%'}}>
        <Space wrap><Text>打开双平台稿</Text><Select aria-label="双平台记录" style={{minWidth:320}} value={pair?.id} placeholder="选择已保存的两平台稿" options={history.map(h=>({value:h.id,label:`#${h.id} ${h.brand} · ${h.title}`}))} onChange={id=>discardThen(()=>void openPair(id))}/></Space>
        <Space wrap><Text>复用旧小红书稿</Text><Select aria-label="复用旧小红书稿" style={{minWidth:320}} value={legacyId} options={legacy.map(h=>({value:h.id,label:`#${h.id} ${h.title}`,disabled:h.source_stale}))} onChange={setLegacyId}/><Button disabled={!legacyId} onClick={()=>discardThen(()=>void useExisting())}>保留原稿并补齐两版</Button></Space>
      </Space>}]}/>
      {pair?<><Space wrap><Tag color="blue">双平台稿 #{pair.id}</Tag><Tag>{pair.source.preview_brand?.name}</Tag><Tag color="purple">小红书 #{pair.xhs.id}</Tag><Tag color="gold">闲鱼 v{pair.xianyu.row_version}</Tag><Text type="secondary">{dirty?'有未保存修改':'两版均已保存'}</Text></Space>
        {pair.xhs.source_stale&&<Alert type="warning" message="原 PDF 已变化，旧稿仍保留。请从当前 PDF 重新生成后审核。"/>}
        <Tabs activeKey={active} onChange={setActive} items={[{key:'xhs',label:`小红书版 · #${pair.xhs.id}`,children:<div className="dual-editor">
          <Space wrap><Text>版本记录</Text><Select aria-label="小红书版本" value={oldXs?.id??pair.xhs.id} options={pair.xhs_history.map(id=>({value:id,label:`#${id}${id===pair.xhs.id?' · 当前':' · 历史只读'}`}))} onChange={id=>id===pair.xhs.id?setOldXs(null):void readOld('xhs',id)}/>{oldXs&&<Tag>历史只读</Tag>}</Space>
          <label>小红书标题<Input aria-label="小红书标题" disabled={!!oldXs} maxLength={256} showCount value={oldXs?.title??xs.title} onChange={e=>{setXs({...xs,title:e.target.value});setXsDirty(true);setReviewed(false);saveRequest.current=crypto.randomUUID();}}/></label>
          <label>小红书正文<Input.TextArea aria-label="小红书正文" disabled={!!oldXs} rows={10} maxLength={6000} showCount value={oldXs?.body??xs.body} onChange={e=>{setXs({...xs,body:e.target.value});setXsDirty(true);setReviewed(false);saveRequest.current=crypto.randomUUID();}}/></label>
          <label>小红书标签（顿号分隔）<Input aria-label="小红书标签" disabled={!!oldXs} value={oldXs?.tags.join('、')??xs.tags} onChange={e=>{setXs({...xs,tags:e.target.value});setXsDirty(true);setReviewed(false);saveRequest.current=crypto.randomUUID();}}/></label>
          <label>小红书样张页码<Input aria-label="小红书编辑页码" disabled={!!oldXs} value={oldXs?.images.map(im=>im.page).join(', ')??xs.pages} onChange={e=>{setXs({...xs,pages:e.target.value});setXsDirty(true);setReviewed(false);saveRequest.current=crypto.randomUUID();}}/></label>
          {!oldXs&&<><Space wrap><Button type="primary" disabled={!xsDirty||!xs.title.trim()||!xs.body.trim()} onClick={()=>void saveXs()}>另存小红书版本</Button><Text type="secondary">保存只影响小红书版</Text></Space>
            {pair.xhs.warnings.length>0&&<Alert type="warning" message={pair.xhs.warnings.join('；')}/>}
            {pair.xhs.status==='saved'?<Space><Tag color="green">已人工审核加入草稿箱</Tag><Link to={`/platforms/xhs/drafts${pair.xhs.draft_id?`?draft_id=${pair.xhs.draft_id}`:''}`}>查看小红书草稿箱</Link></Space>:<Space wrap><Checkbox checked={reviewed} onChange={e=>setReviewed(e.target.checked)} disabled={xsDirty}>已核对当前小红书文案、标签和样张</Checkbox><Button disabled={!reviewed||xsDirty||pair.xhs.source_stale||pair.xhs.warnings.length>0} onClick={()=>void approveXs()}>审核后加入小红书草稿箱</Button></Space>}
          </>}
          <Paragraph type="secondary">小红书独立样张：第 {xhsView?.images.map(im=>im.page).join('、')} 页。旧样张与历史版本保留。</Paragraph>
          {xhsView&&<ImageList images={xhsView.images} identity={`xhs:${xhsView.id}`} load={i=>fetchLibraryDraftImage(xhsView.id,i)}/>}
        </div>},{key:'xianyu',label:`闲鱼版 · v${pair.xianyu.row_version}`,children:<div className="dual-editor">
          <Space wrap><Text>版本记录</Text><Select aria-label="闲鱼版本" value={oldXy?.row_version??pair.xianyu.row_version} options={pair.xianyu_history.map(v=>({value:v.row_version,label:`v${v.row_version}${v.row_version===pair.xianyu.row_version?' · 当前':' · 历史只读'}`}))} onChange={id=>id===pair.xianyu.row_version?setOldXy(null):void readOld('xianyu',id)}/>{oldXy&&<Tag>历史只读</Tag>}</Space>
          <label>闲鱼商品标题<Input aria-label="闲鱼商品标题" disabled={!!oldXy} maxLength={200} showCount value={oldXy?.title??xy.title} onChange={e=>{setXy({...xy,title:e.target.value});setXyDirty(true);}}/></label>
          <label>闲鱼商品描述<Input.TextArea aria-label="闲鱼商品描述" disabled={!!oldXy} rows={10} maxLength={1500} showCount value={oldXy?.description??xy.description} onChange={e=>{setXy({...xy,description:e.target.value});setXyDirty(true);}}/></label>
          <div className="dual-create-grid"><label>售价<InputNumber aria-label="闲鱼售价" disabled={!!oldXy} min={0.01} max={9999999999.99} precision={2} prefix="¥" value={oldXy?(oldXy.price?Number(oldXy.price):null):xy.price} onChange={v=>{setXy({...xy,price:v});setXyDirty(true);}}/></label><label>闲鱼样张页码<Input aria-label="闲鱼编辑页码" disabled={!!oldXy} value={oldXy?.images.map(im=>im.page).join(', ')??xy.pages} onChange={e=>{setXy({...xy,pages:e.target.value});setXyDirty(true);}}/></label></div>
          <label>交付说明<Input.TextArea aria-label="闲鱼交付说明" rows={2} maxLength={500} disabled={!!oldXy} value={oldXy?.delivery_note??xy.delivery_note} onChange={e=>{setXy({...xy,delivery_note:e.target.value});setXyDirty(true);}}/></label>
          {!oldXy&&<Space wrap><Button type="primary" disabled={!xyDirty||!xy.title.trim()||!xy.description.trim()} onClick={()=>void saveXy()}>另存闲鱼版本</Button><Text type="secondary">保存只影响闲鱼版；改选页会重新制作本机水印样张</Text></Space>}
          {!oldXy&&(pair.xianyu.service_draft_id?<Space wrap><Tag color="green">已导入闲鱼商品草稿 #{pair.xianyu.service_draft_id}</Tag><Link to={`/platforms/xianyu/dashboard?draft_id=${pair.xianyu.service_draft_id}`}>打开闲鱼商品草稿</Link><Text type="secondary">此后两处分别保存；修改本页会生成新的待审核版本</Text></Space>:<Space wrap><Button disabled={xyDirty||pair.xhs.source_stale} onClick={()=>void exportXy()}>导入为闲鱼商品草稿</Button><Text type="secondary">仅保存至本机独立服务，尚未提交闲鱼平台</Text></Space>)}
          <Paragraph type="secondary">闲鱼独立样张：第 {xyView?.images.map(im=>im.page).join('、')} 页。</Paragraph>
          {xyView&&<ImageList images={xyView.images} identity={`xy:${pair.id}:${xyView.row_version}`} load={i=>pdfPlatformImage(pair.id,i,xyView.row_version)}/>}
        </div>}]}/>
      </>:<Card><Empty description="选择品牌并生成，两套平台稿会同时出现在这里"/></Card>}
      {pair&&<Collapse items={[{key:'source',label:'来源与审核状态',children:<Space direction="vertical"><Text>{pair.source.university} · {pair.source.course_code} · {pair.source.term} · 原 PDF {pair.source.page_count} 页</Text><Text copyable style={{wordBreak:'break-all'}}>SHA-256：{pair.source.sha256}</Text><Text type="secondary">小红书：{pair.xhs.status==='saved'?'已人工加入草稿箱':'待人工审核'}；闲鱼：{pair.xianyu.status==='exported'?'已导入本机商品草稿':'待人工审核'}。审核与后续发布分别操作。</Text></Space>}]}/>}
    </div></Spin>
  </Modal>;
}
