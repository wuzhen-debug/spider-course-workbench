/** A step is navigation within one work record, not a new record/data scope. */
export const visualStageNames=['research','copy','visual','cover','set'] as const;

export function visualStageIndex(stage:string|null):number|null {
  if(stage===null)return null;
  const aliases:Record<string,number>={plan:2,images:4,preview:3};
  const index=visualStageNames.indexOf(stage as typeof visualStageNames[number]);
  return index>=0?index:Object.prototype.hasOwnProperty.call(aliases,stage)?aliases[stage]:null;
}

export function visualStageParams(current:URLSearchParams,step:number):URLSearchParams {
  if(!Number.isInteger(step)||step<0||step>=visualStageNames.length)throw new RangeError('Unknown visual workflow step');
  const next=new URLSearchParams(current);
  next.set('stage',visualStageNames[step]);
  return next;
}

type VisualProgress={
  approved:Record<string,boolean>;
  data:{copy?:{title?:string;body?:string};cover?:unknown;images?:unknown[];export?:unknown};
};

/** Choose an actionable stage only when the URL did not explicitly choose one.
 * Generated assets remain reviewable even before their approval. A saved export
 * is never treated as evidence that missing content or approvals are complete.
 */
export function nextVisualStage(run:VisualProgress):number {
  const data=run.data;
  if(data.images?.length)return 4;
  if(data.cover)return 2;
  if(run.approved.copy)return 2;
  if(data.copy?.title?.trim()&&data.copy.body?.trim())return 1;
  return 0;
}
