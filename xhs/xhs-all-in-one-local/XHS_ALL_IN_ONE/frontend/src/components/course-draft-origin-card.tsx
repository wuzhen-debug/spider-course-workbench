import {Alert,Button,Collapse,Input,Space,Tag,Typography} from 'antd';
import {Link} from 'react-router-dom';
import type {CourseDraftOrigin} from '../types';
import {formatShanghaiTime} from '../lib/time';
import type {DraftEditorValue} from '../lib/draft-route-selection';
const {Paragraph}=Typography;
export function DraftRecoveryNotice({value,onResolve}:{value:DraftEditorValue;onResolve:(useBuffer:boolean)=>void}){
 return <Alert type="warning" showIcon message="服务器草稿已变化，本机还有未保存副本" description={<Space direction="vertical" style={{width:'100%'}}>
  <span>下方编辑器显示服务器版本。请先核对并选择，未选择前不能修改、调用 AI 或保存；两份内容不会自动合并。</span>
  <Input.TextArea readOnly rows={6} value={`${value.title}\n\n${value.body}\n\n${value.tags.map(t=>t.name).join('、')}`} aria-label="本机未保存草稿副本"/>
  <Space wrap><Button onClick={()=>onResolve(true)}>恢复本机副本，继续核对</Button><Button onClick={()=>onResolve(false)}>采用服务器版本，放弃本机副本</Button></Space>
 </Space>}/>;
}
export function CourseDraftOriginCard({origin}:{origin:CourseDraftOrigin}){
 const source=origin.source||{};const changed=origin.comparison?.status==='modified';
 return <Collapse size="small" style={{marginBottom:12}} items={[{key:'origin-details',label:<Space>来源与版本{origin.brand_name&&<Tag>{origin.brand_name}</Tag>}</Space>,children:<div>
   <Space wrap style={{marginBottom:8}}><strong>{source.university||'大学未记录'} · {source.course_code||origin.course_code||'课程未记录'}</strong><Tag color={changed?'orange':origin.comparison?.status==='unchanged'?'green':'default'}>{changed?'已在草稿工坊修改':origin.comparison?.status==='unchanged'?'与导出快照一致':'旧稿未记录完整快照'}</Tag></Space>
   <Paragraph style={{marginBottom:6}} ellipsis={{rows:2,tooltip:source.filename}}>资料：{source.filename||'旧稿未记录文件名'}</Paragraph>
   <Paragraph type="secondary" style={{marginBottom:8}}>{source.revision_id?`PDF 版本 #${source.revision_id}`:'PDF 版本未记录'}{origin.workflow_revision?` · 图文版本 ${origin.workflow_revision}`:''}</Paragraph>
   {changed&&<Paragraph style={{marginBottom:8}}>已改动{origin.comparison?.changed_fields.join('、')}，当前改稿需重新审核，原制作记录保持不变。</Paragraph>}
   <Link to={origin.href}><Button size="small">返回{origin.label}{origin.kind==='visual_workflow'?'（当前版本）':''}</Button></Link>
    <Paragraph style={{marginTop:12}}>来源：{origin.label}{origin.workflow_id?` #${origin.workflow_id}`:''}{origin.research_id?` · 研究 #${origin.research_id}`:''}{source.term?` · ${source.term}`:''}{origin.exported_at?` · 另存于 ${formatShanghaiTime(origin.exported_at)}`:''}</Paragraph>
    {source.sha256&&<Paragraph type="secondary" copyable={{text:source.sha256}} style={{overflowWrap:'anywhere'}}>文件指纹 {source.sha256}</Paragraph>}
    <Space wrap>{(['copy','cover','set'] as const).map(stage=>{const item=origin.review_snapshot?.[stage];return <Tag key={stage}>{({copy:'文案',cover:'封面',set:'整套'})[stage]}：{item?.status==='confirmed'?`导出时已审核${item.at?` · ${formatShanghaiTime(item.at)}`:''}`:item?.status==='not_applicable'?'本来源未制作':'未记录'}</Tag>;})}</Space>
    <Paragraph type="secondary" style={{marginTop:8,marginBottom:6}}>{origin.snapshot_note}。这些记录属于来源版本，不代表后续改稿已审核。</Paragraph>
    <Paragraph type="secondary" style={{marginBottom:6}}>真实讲义、公式和 Logo 请返回制作入口修改并另存。{origin.kind==='visual_workflow'?'返回后显示工作台当前版本，可在历史记录中查看旧版。':''}</Paragraph>
  </div>} ]}/>;
}
