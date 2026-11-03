import type { LibraryDraftPlan, LibraryDraftRecipe } from './course-library-types';

export const MAX_SAMPLE_PAGES = 9;

export function defaultSamplePages(pageCount?: number | null) {
  return Array.from({length:Math.min(MAX_SAMPLE_PAGES, Math.max(1,pageCount??MAX_SAMPLE_PAGES))},(_,i)=>i+1).join(', ');
}

export function parseSamplePages(value:string, pageCount?:number|null) {
  const pages=value.replace(/[，、\s]+/g,',').split(',').filter(Boolean).map(Number);
  if(!pages.length||pages.length>MAX_SAMPLE_PAGES||pages.some(n=>!Number.isInteger(n)||n<1||n>(pageCount??10000))||new Set(pages).size!==pages.length)
    throw new Error('请输入1至9个不重复且在PDF范围内的页码，用逗号分隔。');
  return pages;
}

export function scopedDraftRequest(fileId:number, recipe:LibraryDraftRecipe, plan:LibraryDraftPlan, requestKey:string) {
  if(!recipe.brand_id||plan.source.preview_brand?.id!==recipe.brand_id)throw new Error('请先选择本篇品牌，等待生成范围更新后继续。');
  if(plan.file_id!==fileId||plan.source.revision_id!==recipe.revision_id||plan.mode!==recipe.mode||plan.instruction!==recipe.instruction||JSON.stringify(plan.pages.map(p=>p.page))!==JSON.stringify(recipe.pages))
    throw new Error('生成范围已变化，正在重新读取；请稍后点击生成。');
  if(recipe.mode==='ai'&&!plan.model?.configured)throw new Error('请先配置可用的文本模型。');
  // The scoped Generate button is the user's explicit action, rather than a second checkbox.
  return {...recipe,request_key:requestKey,plan_digest:plan.plan_digest,external_consent:recipe.mode==='ai'};
}
