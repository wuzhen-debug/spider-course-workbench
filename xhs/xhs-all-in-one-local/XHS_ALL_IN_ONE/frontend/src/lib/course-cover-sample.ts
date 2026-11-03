type CoverPlan={cover_sample_page?:number|null;sample_pages:number[];template_id?:string};

/** Keep legacy sample choices effective without adding a new field to old plans. */
export function coverSamplePage(plan:CoverPlan,pageCount:number):number|null {
  const valid=(page:number)=>Number.isInteger(page)&&page>=2&&page<=pageCount;
  if(plan.cover_sample_page!==undefined&&plan.cover_sample_page!==null)return valid(plan.cover_sample_page)?plan.cover_sample_page:null;
  return plan.sample_pages.find(valid)??null;
}

export function coverSampleIssue(plan:CoverPlan,pageCount:number):string {
  if(!plan.template_id||plan.template_id==='legacy'||plan.template_id==='magazine-a')return '';
  if(pageCount<2)return '这份PDF没有可选的正文页，请更换包含正文的资料后制作。';
  return coverSamplePage(plan,pageCount)===null?'请先在“封面正文样张”中浏览真实PDF，点击“用这一页作封面样张”，再制作整套图。':'';
}
