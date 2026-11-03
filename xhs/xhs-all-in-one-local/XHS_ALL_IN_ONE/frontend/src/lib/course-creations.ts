export type CourseCreation = {
  id:string;kind:'research'|'visual'|'pdf';title:string;university:string;course_code:string;
  filename:string;relative_path:string;file_id:number|null;revision_id:number|null;updated_at:string;
  status:string;image_count:number;draft_id:number|null;draft_available:boolean;
  primary_label:string;primary_url:string;source_url:string|null;
};
export type CourseCreationList = {items:CourseCreation[];total:number;limit:number;offset:number};

// File preview and research selection are separate URL states. A different folder or
// source must never carry an old course's research IDs into the new course.
export function libraryFolderParams(current:URLSearchParams,directory:string):URLSearchParams {
  const next=new URLSearchParams(current);
  for(const key of ['library_path','library_view','file_id','research_id','research_draft_id','library_file_id','package_id','research_lane','pdf_run','dual_drafts','platform_pair_id','source_package_id'])next.delete(key);
  if(directory)next.set('library_dir',directory);else next.delete('library_dir');
  return next;
}
export function libraryResearchParams(current:URLSearchParams,file:{id:number;relative_path:string}):URLSearchParams {
  const next=libraryFolderParams(current,file.relative_path.split('/').slice(0,-1).join('/'));
  next.set('library_view','research');next.set('file_id',String(file.id));return next;
}
export function positiveRouteId(value:string|null):number|null {
  if(!value||!/^\d+$/.test(value))return null;
  const id=Number(value);return Number.isSafeInteger(id)&&id>0?id:null;
}
export function researchEntryMatches(directory:{university:string;course_code:string},record?:{university:string;course_code:string}):boolean {
  return !!record&&(['university','course_code'] as const).every(key=>!directory[key]||directory[key]===record[key]);
}
