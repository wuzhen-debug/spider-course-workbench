import type { PdfAnalysis, PdfAnalysisPrompt } from './course-pdf-lane';

export type ResearchLane='pdf'|'xhs';
export function researchLane(params:URLSearchParams):ResearchLane {
  const explicit=params.get('research_lane');
  if(explicit==='pdf'||explicit==='xhs')return explicit;
  return params.has('research_id')||params.has('research_draft_id')?'xhs':'pdf';
}
export function researchLaneParams(params:URLSearchParams,lane:ResearchLane) {
  const next=new URLSearchParams(params);next.set('library_view','research');next.set('research_lane',lane);return next;
}
export type PdfTopicHistory={id:number;file_id:number;revision_id:number;entry_mode?:string;title:string};
export type PdfTopicRun={id:number;file_id:number;row_version:number;data:{entry_mode?:string;
  source:{filename:string;sha256:string;revision_id:number;page_count:number;university:string;course_code:string};
  copy:{topic:string;title:string;body:string;tags:string[];takeaway:string;goal?:string};
  brand:{name:string};pdf_analysis?:PdfAnalysis;operation?:{key?:string;status?:string}}};
export type PdfTopicPreview=PdfAnalysisPrompt&{file_id:number;preview_only?:boolean};
export function pdfTopicHistory(rows:PdfTopicHistory[],fileId:number,revisionId:number) {
  return rows.filter(row=>row.file_id===fileId&&row.revision_id===revisionId&&row.entry_mode==='pdf-driven');
}
export function samePdfTopicScope(a:PdfAnalysisPrompt,b:PdfAnalysisPrompt) {
  return JSON.stringify([a.source,a.model,a.material,a.coverage,a.scope,a.prompt])===JSON.stringify([b.source,b.model,b.material,b.coverage,b.scope,b.prompt]);
}
export function requirePdfTopicRun(run:PdfTopicRun,fileId:number,revisionId:number) {
  if(run.file_id!==fileId||run.data.source.revision_id!==revisionId||run.data.entry_mode!=='pdf-driven')
    throw new Error('这条记录不属于当前PDF的直接选题路线，未混入其他课程或小红书选题。');
}
type TopicTransport={
  create:(payload:unknown)=>Promise<PdfTopicRun>;
  patch:(run:PdfTopicRun,payload:unknown)=>Promise<PdfTopicRun>;
  prepare:(run:PdfTopicRun)=>Promise<PdfAnalysisPrompt>;
  generate:(run:PdfTopicRun,payload:unknown)=>Promise<PdfTopicRun>;
};
export async function generatePdfTopics(input:{fileId:number;revisionId:number;brandId:string;topic:string;goal:string;createKey:string;requestKey:string;preview:PdfTopicPreview},
  transport:TopicTransport,assertCurrent:()=>void,onRun:(run:PdfTopicRun)=>void) {
  assertCurrent();
  if(!input.brandId||input.preview.brand?.id!==input.brandId)throw new Error('请先选择本篇品牌，等待生成范围更新后继续。');
  if(!input.preview.model?.configured||input.preview.file_id!==input.fileId)throw new Error('当前PDF或文本模型尚未就绪。');
  // Every explicit generation starts a new record; existing research and images are never repurposed.
  let run=await transport.create({file_id:input.fileId,revision_id:input.revisionId,brand_id:input.brandId,request_key:input.createKey,template_id:'magazine-a',entry_mode:'pdf-driven'});
  assertCurrent();requirePdfTopicRun(run,input.fileId,input.revisionId);onRun(run);
  if(input.topic||input.goal!=='student-question'){
    run=await transport.patch(run,{expected_version:run.row_version,copy:{...run.data.copy,topic:input.topic,goal:input.goal}});
    assertCurrent();onRun(run);
  }
  const plan=await transport.prepare(run);assertCurrent();
  if(!samePdfTopicScope(input.preview,plan))throw new Error('PDF、模型或文字范围已变化，尚未调用AI。请重新读取范围后再生成。');
  const result=await transport.generate(run,{expected_version:run.row_version,external_consent:true,plan_digest:plan.plan_digest,request_key:input.requestKey});
  assertCurrent();requirePdfTopicRun(result,input.fileId,input.revisionId);onRun(result);return result;
}
