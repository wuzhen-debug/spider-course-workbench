/** Compare editor JSON values without treating object insertion order as an edit.
 * Array order and exact scalar values remain meaningful, including text spaces.
 */
export function sameVisualEdit(left:unknown,right:unknown):boolean {
  if(left===right)return true;
  if(left===null||right===null||typeof left!=='object'||typeof right!=='object')return false;
  const leftArray=Array.isArray(left),rightArray=Array.isArray(right);
  if(leftArray||rightArray){
    return leftArray&&rightArray&&left.length===right.length&&left.every((value,index)=>sameVisualEdit(value,right[index]));
  }
  // Editor values come from JSON. Do not confuse non-JSON objects with empty maps.
  const plain=(value:object)=>Object.getPrototypeOf(value)===Object.prototype||Object.getPrototypeOf(value)===null;
  if(!plain(left)||!plain(right))return false;
  const leftKeys=Object.keys(left),rightKeys=Object.keys(right);
  if(leftKeys.length!==rightKeys.length)return false;
  const a=left as Record<string,unknown>,b=right as Record<string,unknown>;
  return leftKeys.every(key=>Object.prototype.hasOwnProperty.call(b,key)&&sameVisualEdit(a[key],b[key]));
}
