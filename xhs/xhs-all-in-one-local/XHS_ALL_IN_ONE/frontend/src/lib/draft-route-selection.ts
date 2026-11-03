import type {Draft} from '../types';

export type DraftEditorValue={title:string;body:string;tags:{id:string;name:string}[]};
export function draftEditorValue(draft:Draft):DraftEditorValue{
 return {title:draft.title,body:draft.body,tags:(draft.tags||[]).map(t=>typeof t==='string'?{id:'',name:t}:{id:t.id||'',name:t.name||''})};
}
export function draftEditorKey(value:DraftEditorValue):string{return JSON.stringify(value);}
export function parseRequestedDraft(value:string|null):number|null{
 if(value===null)return null;
 if(!/^[1-9]\d*$/.test(value)||!Number.isSafeInteger(Number(value)))throw new Error('草稿链接中的 draft_id 无效，请重新选择草稿。');
 return Number(value);
}
export async function resolveRequestedDraft(raw:string|null,items:Draft[],currentId:number|null,get:(id:number)=>Promise<Draft>):Promise<Draft|null>{
 const id=parseRequestedDraft(raw);
 if(id!==null)return get(id); // Explicit IDs never silently fall back to another draft.
 return items.find(d=>d.id===currentId)||items[0]||null;
}
