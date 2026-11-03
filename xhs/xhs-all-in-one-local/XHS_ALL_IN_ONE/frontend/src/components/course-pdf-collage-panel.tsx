import {Alert,Button,Input,Space,Tag,Typography} from 'antd';

type Props={pageCount:number;pageTexts:string[];enabled:boolean;imageCount:number;collageCount:number;disabled:boolean;otherEdits:boolean;onChange:(index:number,value:string)=>void;onEnable:()=>void;onAppend:()=>void};

/** This editor only chooses local PDF pages; rendering is an explicit action. */
export function CoursePdfCollagePanel({pageCount,pageTexts,enabled,imageCount,collageCount,disabled,otherEdits,onChange,onEnable,onAppend}:Props){
 const available=pageCount>=9;
 return <section className="vd-collage-panel" aria-label="PDF四宫格样张">
  <Space wrap><Typography.Text strong>追加两张PDF样张拼图</Typography.Text><Tag>每张四宫格 · 共8个正文页</Tag>{enabled&&<Tag color="blue">已加入本次方案</Tag>}</Space>
  {available?<>
   <Typography.Paragraph type="secondary">{imageCount?`保留现有${imageCount-collageCount}张封面和讲解，只制作末尾两张拼图。`:'两张拼图放在原图文末尾，保留封面和讲解。'}正文页保持原比例和公式，点击成品可放大查看。</Typography.Paragraph>
   <div className="vd-collage-inputs">{[0,1].map(index=><label key={index}>拼图{index+1} · 4个正文页<Input aria-label={`拼图${index+1}的PDF页码`} disabled={disabled} value={pageTexts[index]||''} onChange={event=>onChange(index,event.target.value)} placeholder={index?'6, 7, 8, 9':'2, 3, 4, 5'}/></label>)}</div>
   {otherEdits&&imageCount>0&&<Typography.Paragraph type="warning">还有文案或其它图片修改，请先保存或放弃这些修改，再追加拼图。</Typography.Paragraph>}
   <Space wrap className="vd-actions">{imageCount>0?<Button disabled={disabled||otherEdits} onClick={onAppend}>{collageCount?'按新选页重做两张拼图':'追加两张PDF样张拼图'}</Button>:enabled?<Typography.Text type="secondary">制作整套图时，将在末尾加入这两张拼图。</Typography.Text>:<Button disabled={disabled} onClick={onEnable}>将两张拼图加入本次制作</Button>}</Space>
  </>:<Alert type="info" showIcon message={`正文不足8个不同页，暂不拼图（当前${Math.max(0,pageCount-1)}页）。保留原图文，不重复凑页。`}/>}
 </section>;
}
