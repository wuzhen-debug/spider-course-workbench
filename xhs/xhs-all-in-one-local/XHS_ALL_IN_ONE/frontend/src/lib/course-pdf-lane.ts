export type EntryMode='pdf-driven'|'xhs-research';
export const entryMode=(value:unknown):EntryMode=>value==='pdf-driven'?'pdf-driven':'xhs-research';
export type PdfCoverage={total_pages:number;read_pages:number[];local_chars:number;local_truncated:boolean;excerpt_pages:number[];sent_chars:number};
export type PdfAnalysis={
 pain_points:{pain:string;basis:'teaching-inference';pdf_pages:number[];quote:string}[];
 product_facts:{fact:string;pdf_pages:number[];quote:string}[];
 topic_candidates:{id:string;topic:string;reader_takeaway:string;rationale:string;pdf_pages:number[]}[];
 recommended_topic_id:string;coverage:PdfCoverage;status:'pending_review';
};
export type VisualCandidate={status:'ready'|'stale';copy_digest:string;source_sha256:string;revision_id:number};
export type PdfAnalysisPrompt={purpose:'pdf-analysis';brand?:{id:string;name:string};source:{filename:string;sha256:string;revision_id:number;page_count:number};model:{name:string;model_name:string;destination:string;configured:boolean}|null;scope:string;prompt:string;plan_digest:string;coverage:PdfCoverage;material:{page_count:number;pages:{page:number;text:string;truncated:boolean}[]};allowed_pages:number[]};
export function coverageSummary(coverage:PdfCoverage):{local:string;external:string}{
 const read=coverage.read_pages?.length||0,total=coverage.total_pages||0;
 return {local:`本机读取 ${read}/${total} 页文字，共 ${coverage.local_chars||0} 字${coverage.local_truncated?'；存在截断或未读取部分':'。'}`,
  external:`发送 ${coverage.excerpt_pages?.length||0} 页的文字摘录，共 ${coverage.sent_chars||0} 字；AI依据这些摘录分析，不接收完整PDF文件。`};
}
export const pdfVisualStale=(candidate:VisualCandidate|undefined)=>candidate?.status==='stale';
