export class CourseContextChanged extends Error {}

/** A completed request may not write into a different course or account view. */
export async function inCourseContext<T>(request:()=>Promise<T>,epoch:()=>number):Promise<T>{
 const started=epoch();
 try{const result=await request();if(started!==epoch())throw new CourseContextChanged();return result;}
 catch(error){if(started!==epoch())throw new CourseContextChanged();throw error;}
}

export function initialCourseRun(items:{id:number;file_id:number}[],fileId?:number,runId?:number):number|undefined{
 return runId||items.find(item=>fileId===undefined||item.file_id===fileId)?.id;
}
