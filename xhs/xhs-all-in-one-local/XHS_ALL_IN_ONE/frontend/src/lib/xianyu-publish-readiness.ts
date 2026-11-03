export function xianyuPreviewBlockReason(value:{enabled:boolean;unavailableReason?:string;dirty:boolean;busy:boolean;accountId:string|null;price:string|null;jobState?:string}):string {
  if(!value.enabled)return value.unavailableReason||'手动发布尚未启用，请刷新核对服务状态。';
  if(value.dirty)return '请先保存修改，再生成发布预览。';
  if(value.busy)return '正在读取发布预览，请稍候。';
  if(!value.accountId)return '请先关联闲鱼账号并保存草稿。';
  if(!value.price||!Number.isFinite(Number(value.price))||Number(value.price)<=0)return '请先填写正数售价并保存草稿。';
  if(['uploading','submitting'].includes(value.jobState??''))return '本次发布正在处理中，请等待结果。';
  if(value.jobState==='unknown')return '请先核对上次发布结果，再决定后续操作。';
  if(['accepted','succeeded'].includes(value.jobState??''))return '这份草稿已有商品编号，请查看上方发布结果，避免重复上架。';
  return '';
}
