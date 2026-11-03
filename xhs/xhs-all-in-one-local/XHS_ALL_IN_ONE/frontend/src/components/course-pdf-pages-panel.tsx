import {Alert,Button,Input,Space,Tag,Typography} from 'antd';
import {parsePdfPageText} from '../lib/course-pdf-pages';

type Props={pageCount:number;pageText:string;enabled:boolean;imageCount:number;tailImageCount:number;hasOldCollages:boolean;disabled:boolean;otherEdits:boolean;requiredCount?:8|9;raw?:boolean;onChange:(value:string)=>void;onNormalize:()=>void;onEnable:()=>void;onAppend:()=>void};

export function CoursePdfPagesPanel({pageCount,pageText,enabled,imageCount,tailImageCount,hasOldCollages,disabled,otherEdits,requiredCount=8,raw=false,onChange,onNormalize,onEnable,onAppend}:Props){
 const available=pageCount>=requiredCount+1,pages=parsePdfPageText(pageText).pages;
 return <section className="vd-pdf-pages-panel" aria-label="独立PDF样页">
  <Space wrap><Typography.Text strong>追加{requiredCount}张PDF样页</Typography.Text><Tag>一图一页 · 按原页码升序</Tag>{raw&&<Tag>原比例 · 不加修饰</Tag>}{enabled&&<Tag color="blue">已加入本次方案</Tag>}</Space>
  {available?<>
   <Typography.Paragraph type="secondary">{imageCount?`保留现有${imageCount-tailImageCount}张封面和讲解，末尾展示${requiredCount}张独立样页。`:`原封面和讲解保留，末尾展示${requiredCount}张独立样页。`}{hasOldCollages?'原拼图保留在历史版本。':''}点击图片可放大查看。{raw?'直接从当前PDF原样导出，保留原公式与页码，不调用生图API。':''}</Typography.Paragraph>
   <label className="vd-pdf-pages-input">选择{requiredCount}个不同正文页<Input aria-label={`${requiredCount}张PDF样页的页码`} disabled={disabled} value={pageText} onChange={event=>onChange(event.target.value)} onBlur={onNormalize} placeholder={Array.from({length:requiredCount},(_,index)=>index+2).join(', ')}/></label>
   <Typography.Paragraph type="secondary">实际展示顺序：{pages.length?pages.map(page=>Number.isFinite(page)?page:'待填写').join(' → '):'待选页'}（已选{pages.length}/{requiredCount}页）</Typography.Paragraph>
   {otherEdits&&imageCount>0&&<Typography.Paragraph type="warning">还有文案或其它图片修改，请先保存或放弃这些修改，再追加样页。</Typography.Paragraph>}
   <Space wrap className="vd-actions">{imageCount>0?<Button disabled={disabled||otherEdits} onClick={onAppend}>{hasOldCollages?`改为${requiredCount}张独立样页`:tailImageCount?`按新选页重做${requiredCount}张样页`:`追加${requiredCount}张PDF样页`}</Button>:enabled?<Typography.Text type="secondary">制作整套图时，将在末尾加入这{requiredCount}张独立样页。</Typography.Text>:<Button disabled={disabled} onClick={onEnable}>将{requiredCount}张独立样页加入本次制作</Button>}</Space>
  </>:<Alert type="info" showIcon message={`正文不足${requiredCount}个不同页，暂不能追加${requiredCount}张独立样页（当前${Math.max(0,pageCount-1)}页）。保留原图文，不重复凑页。`}/>}
 </section>;
}
