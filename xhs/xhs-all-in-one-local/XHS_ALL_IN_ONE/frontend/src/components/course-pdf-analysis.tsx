import {Alert,Button,Checkbox,Collapse,Modal,Space,Tag,Typography} from 'antd';
import {coverageSummary,type EntryMode,type PdfAnalysis,type PdfAnalysisPrompt} from '../lib/course-pdf-lane';
const {Paragraph,Text}=Typography;

export function CourseEntryChoices({selected,disabled,onSelect}:{selected:EntryMode;disabled:boolean;onSelect:(mode:EntryMode)=>void}){
 return <div className="vd-entry-choices" aria-label="选择图文制作入口">
  <button type="button" aria-label="从PDF提炼痛点和卖点" aria-pressed={selected==='pdf-driven'} disabled={disabled} className={`vd-entry-choice ${selected==='pdf-driven'?'selected':''}`} onClick={()=>onSelect('pdf-driven')}><strong>从PDF提炼痛点和卖点</strong><span>读取资料，提炼学习难点、真实卖点和选题，生成待审核文案。</span></button>
  <button type="button" aria-label="先搜小红书学生问题" aria-pressed={selected==='xhs-research'} disabled={disabled} className={`vd-entry-choice ${selected==='xhs-research'?'selected':''}`} onClick={()=>onSelect('xhs-research')}><strong>先搜小红书学生问题</strong><span>搜索笔记与评论，保留来源，再用讲义回答学生的问题。</span></button>
 </div>;
}

export function PdfAnalysisReview({analysis,disabled,onTopic,showCandidates=true}:{analysis:PdfAnalysis;disabled:boolean;onTopic:(topic:PdfAnalysis['topic_candidates'][number])=>void;showCandidates?:boolean}){
 return <Collapse className="vd-pdf-analysis-review" items={[{key:'pdf-analysis',label:showCandidates?'查看PDF分析：学习痛点、资料卖点与备选选题':'查看PDF依据：学习痛点、资料卖点与引文',children:<>
  <Paragraph type="secondary">以下痛点是依据资料内容作出的教学推断，不是小红书评论中已验证的需求。资料事实和引文仍需人工核对。</Paragraph>
  <Text strong>学习痛点</Text>{(analysis.pain_points||[]).map((item,i)=><div className="vd-pdf-finding" key={`p${i}`}><Paragraph>{item.pain}</Paragraph><Text type="secondary">讲义依据：{(item.pdf_pages||[]).join('、')}　“{item.quote}”</Text></div>)}
  <Text strong>资料的真实支持</Text>{(analysis.product_facts||[]).map((item,i)=><div className="vd-pdf-finding" key={`f${i}`}><Paragraph>{item.fact}</Paragraph><Text type="secondary">讲义依据：{(item.pdf_pages||[]).join('、')}　“{item.quote}”</Text></div>)}
  {showCandidates&&<><Text strong>备选选题</Text>{(analysis.topic_candidates||[]).map(item=><div className="vd-pdf-finding" key={item.id}><Space wrap><Text strong>{item.topic}</Text>{item.id===analysis.recommended_topic_id&&<Tag color="blue">本次推荐</Tag>}</Space><Paragraph>{item.reader_takeaway}</Paragraph><Paragraph type="secondary">{item.rationale}</Paragraph><Button disabled={disabled} onClick={()=>onTopic(item)}>选用这个题目</Button><Text type="secondary"> 只选择题目，正文需重新生成并审核。</Text></div>)}</>}
 </>} ]}/>;
}

export function PdfAnalysisConsent({plan,consent,busy,onConsent,onCancel,onGenerate}:{plan:PdfAnalysisPrompt|null;consent:boolean;busy:boolean;onConsent:(checked:boolean)=>void;onCancel:()=>void;onGenerate:()=>void}){
 const summary=plan?coverageSummary(plan.coverage):null;
 return <Modal title="从PDF生成选题与文案" open={!!plan} onCancel={onCancel} maskClosable={!busy} closable={!busy} width={760} footer={null}>
  {plan&&summary&&<>
   <Paragraph>接收方：{plan.model?`${plan.model.name} · ${plan.model.model_name} · ${plan.model.destination}`:'尚未配置默认文本模型'}</Paragraph>
   <Paragraph>{summary.local}</Paragraph><Paragraph>{summary.external}</Paragraph><Paragraph>{plan.scope}</Paragraph>
   <Alert type="info" showIcon message="先生成待审核内容，再由你确认" description="AI会整理学习痛点、真实资料卖点、候选选题、文案和4张干货图的候选内容。此处不会出图、批准文案、另存草稿或发布。"/>
   <Collapse style={{marginTop:16}} items={[{key:'excerpts',label:`查看实际发送的文字摘录（${plan.coverage.excerpt_pages.length}页）`,children:plan.material.pages.map(page=><div className="vd-pdf-excerpt" key={page.page}><Text strong>讲义来源 {page.page}{page.truncated?' · 摘录已截断':''}</Text><pre className="vd-pre">{page.text}</pre></div>)},{key:'prompt',label:'高级：查看本次完整分析要求',children:<pre className="vd-pre">{plan.prompt}</pre>}]}/>
   <Checkbox style={{marginTop:18}} disabled={busy||!plan.model?.configured} checked={consent} onChange={e=>onConsent(e.target.checked)}>我已核对接收方和上述文字范围，同意发送这些摘录生成待审核内容</Checkbox>
   <Button type="primary" disabled={busy||!consent||!plan.model?.configured} loading={busy} style={{marginTop:18}} onClick={onGenerate}>分析PDF并生成待审核文案</Button>
  </>}
 </Modal>;
}
