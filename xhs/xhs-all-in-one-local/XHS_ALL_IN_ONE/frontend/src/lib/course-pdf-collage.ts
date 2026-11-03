export type PdfCollagePlan={groups:number[][]};

export const defaultPdfCollagePlan=():PdfCollagePlan=>({groups:[[2,3,4,5],[6,7,8,9]]});
export const pdfCollagePageTexts=(plan:PdfCollagePlan|null|undefined):string[]=>(plan||defaultPdfCollagePlan()).groups.map(group=>group.join(', '));

export function pdfCollageIssue(plan:PdfCollagePlan|null|undefined,pageCount:number):string {
  if(!plan)return '';
  if(pageCount<9)return `这份PDF只有${Math.max(0,pageCount-1)}页可用正文，不足8页，不能重复凑成两张四宫格。`;
  if(plan.groups.length!==2||plan.groups.some(group=>group.length!==4))return '请填写两组页码，每组4页，共8页。';
  const pages=plan.groups.flat();
  if(pages.some(page=>!Number.isInteger(page)||page<2||page>pageCount))return `拼图页码请选择2至${pageCount}之间的正文页，第1页不计入。`;
  return new Set(pages).size!==8?'两张拼图合计需要8个不同的正文页，请去掉重复页码。':'';
}
