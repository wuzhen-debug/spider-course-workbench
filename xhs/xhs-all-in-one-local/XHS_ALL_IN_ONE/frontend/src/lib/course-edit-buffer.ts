/** Local editor recovery only. Callers must pass editable fields, never credentials,
 * external-transfer consent, review approval, or generated request keys. */
export type CourseEditScope={userId:string|number;feature:string;recordId:string;context?:string};
export type CourseEditBuffer<T>={value:T;savedAt:string;baseVersion?:string};
const PREFIX='spider-course-edit:v1:';
const MAX_BYTES=1_000_000;

export function courseEditBufferKey(scope:CourseEditScope):string{
  return PREFIX+JSON.stringify([String(scope.userId),scope.feature,scope.recordId,scope.context||'']);
}
export function hasCourseEditStorage():boolean{
  try{const key=PREFIX+'probe';localStorage.setItem(key,'1');localStorage.removeItem(key);return true;}catch{return false;}
}
export function readCourseEditBuffer<T>(scope:CourseEditScope):CourseEditBuffer<T>|null{
  try{
    const raw=localStorage.getItem(courseEditBufferKey(scope));
    if(!raw||raw.length>MAX_BYTES)return null;
    const result=JSON.parse(raw) as CourseEditBuffer<T>;
    return result&&typeof result==='object'&&typeof result.savedAt==='string'&&'value' in result&&
      (result.baseVersion===undefined||typeof result.baseVersion==='string')?result:null;
  }catch{return null;}
}
export function writeCourseEditBuffer<T>(scope:CourseEditScope,value:T,baseVersion?:string):boolean{
  try{
    const raw=JSON.stringify({value,savedAt:new Date().toISOString(),...(baseVersion===undefined?{}:{baseVersion})});
    if(raw.length>MAX_BYTES)return false;
    localStorage.setItem(courseEditBufferKey(scope),raw);return true;
  }catch{return false;}
}
export function removeCourseEditBuffer(scope:CourseEditScope):boolean{
  try{localStorage.removeItem(courseEditBufferKey(scope));return true;}catch{return false;}
}
