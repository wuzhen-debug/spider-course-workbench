import {Alert,Button,Checkbox,Collapse,Modal,Space,Typography} from 'antd';

const {Paragraph,Text}=Typography;
export type ApiImagePlan={run_id:number;row_version:number;target:string;plan_digest:string;supported:boolean;
 count:number;image_count:number;reused_count:number;pdf_count:number;scope:string;estimated_cost:string;
 model:{name:string;model_name:string;destination:string;configured:boolean}|null;
 local_header:{university:string;course_code:string;brand:string};pages:{slot:string;title:string;prompt:string;will_send:boolean}[]};

export function ApiImageConsent({plan,consent,busy,error,onConsent,onCancel,onGenerate}:{plan:ApiImagePlan|null;consent:boolean;busy:boolean;error:string;onConsent:(v:boolean)=>void;onCancel:()=>void;onGenerate:()=>void}){
 return <Modal title="API制作完整知识图 · 先核对本次范围" open={!!plan} onCancel={onCancel} maskClosable={!busy} closable={!busy} footer={null} width={780}>
  {plan&&<>
   <Paragraph><Text strong>{plan.local_header.university} · {plan.local_header.course_code}</Text> · {plan.local_header.brand}</Paragraph>
   <Paragraph>接收方：{plan.model?`${plan.model.name} · ${plan.model.model_name}`:'尚未配置默认图片模型'}</Paragraph>
   {plan.model&&<Paragraph code>{plan.model.destination}</Paragraph>}
   <Paragraph>本次制作 {plan.image_count} 张完整知识图，新增 {plan.count} 次图片API调用{plan.reused_count>0?`；复用上次已返回的 ${plan.reused_count} 张原图，不再次调用`:''}。{plan.pdf_count>0?`另附 ${plan.pdf_count} 张原样PDF预览，在本机处理。`:''}</Paragraph>
   <Paragraph>{plan.estimated_cost}</Paragraph><Paragraph>{plan.scope}</Paragraph>
   <Collapse items={plan.pages.map(p=>({key:p.slot,label:`${p.title.replace(/\n/g,' / ')} · ${p.will_send?'实际发送的提示词':'复用原图，本次不发送'}`,children:<pre className="vd-pre">{p.prompt}</pre>}))}/>
   <Paragraph type="secondary" style={{marginTop:16}}>API会绘制知识图中的文字与公式，生成后仍需逐张校对。大学、课程代码和真实Logo由本机添加。旧图保留，结果不会自动审核、另存草稿或发布。</Paragraph>
   {!plan.supported&&<Alert type="warning" message="请先在模型配置中选择火山方舟北京区Seedream 5.0 Flash / Pro"/>}
   {plan.supported&&!plan.model?.configured&&<Alert type="warning" message="请先在本机模型配置页面填写图片API Key"/>}
   {error&&<Alert type="error" message={error} style={{marginTop:12}}/>}
   <Checkbox checked={consent} disabled={busy||!plan.supported||!plan.model?.configured} onChange={e=>onConsent(e.target.checked)} style={{marginTop:16}}>{plan.count>0?`同意将上述逐张提示词发送给显示的服务商，调用 ${plan.count} 次图片API`:'确认复用已返回原图，仅在本机合成，不新增图片API调用'}</Checkbox>
   <Space style={{marginTop:16}}><Button type="primary" disabled={busy||!consent||!plan.supported||!plan.model?.configured} loading={busy} onClick={onGenerate}>{plan.count>0?`确认生成 ${plan.image_count} 张待审核知识图`:'复用原图完成本机合成'}</Button><Button disabled={busy} onClick={onCancel}>取消</Button></Space>
  </>}
 </Modal>;
}
