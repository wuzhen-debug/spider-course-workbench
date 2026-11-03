export type PdfPagePlan={pages:number[]};

export const defaultPdfPagePlan=(count:8|9=8):PdfPagePlan=>({pages:Array.from({length:count},(_,index)=>index+2)});
export const pdfPageText=(plan:PdfPagePlan|null|undefined):string=>(plan||defaultPdfPagePlan()).pages.join(', ');
export const parsePdfPageText=(text:string):PdfPagePlan=>({pages:[...new Set(text.split(/[,，\s]+/).filter(Boolean).map(Number))].sort((a,b)=>a-b)});

export function pdfPageIssue(plan:PdfPagePlan|null|undefined,pageCount:number,requiredCount:8|9=8):string {
  if(!plan)return '';
  if(pageCount<requiredCount+1)return `这份PDF只有${Math.max(0,pageCount-1)}页可用正文，不足${requiredCount}页，不重复凑页。`;
  if(plan.pages.length!==requiredCount||new Set(plan.pages).size!==requiredCount)return `请选择${requiredCount}个不同的PDF正文页，每张图对应一页。`;
  return plan.pages.some(page=>!Number.isInteger(page)||page<2||page>pageCount)?`样页请选择2至${pageCount}之间的正文页，第1页不计入。`:'';
}
