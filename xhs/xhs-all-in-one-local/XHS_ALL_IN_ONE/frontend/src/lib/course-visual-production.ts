export type ProductionMode='api'|'local';
export type ProductionIntent={mode:ProductionMode;target:string};

/** Count planned slots, not filled text fields. Empty placeholders need planning. */
export function productionReadiness(copy:{title:string},plan:{template_id?:string;cover_lines:string[];method_title:string;method_text:string},inner:{sample_pages:number[];extra_explanations:{title:string;text:string}[]},pdf:{pages:number[]}|null){
 const magazine=plan.template_id==='magazine-a';
 const pages=[{slot:'cover',role:'封面 · 课程与学生问题',title:plan.cover_lines.join(' / ')||copy.title,ready:!!(plan.cover_lines.join('')||copy.title).trim()}];
 if(magazine||plan.method_text.trim())pages.push({slot:'method',role:'讲解 · 判断方法',title:plan.method_title,ready:!!plan.method_title.trim()&&!!plan.method_text.trim()});
 for(let i=0;i<(magazine?Math.max(2,inner.extra_explanations.length):inner.extra_explanations.length);i++){
  const page=inner.extra_explanations[i];pages.push({slot:`method-extra-${i}`,role:i===0?'讲解 · 应用与辨析':'讲解 · 练习与资料使用',title:page?.title||'',ready:!!page?.title.trim()&&!!page?.text.trim()});
 }
 const knowledgeCount=pages.length+(magazine?0:1);
 const pdfCount=pdf?.pages.length||0;
 return {pages,needsPlanning:pages.some(page=>!page.ready)||magazine&&inner.extra_explanations.length!==2,
  knowledgeCount,pdfCount,plannedCount:knowledgeCount+pdfCount+(magazine?0:inner.sample_pages.length)};
}
