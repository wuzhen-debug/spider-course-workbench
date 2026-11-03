// Measured, content-preserving soft wrapping. Authored hard breaks are kept.
// This module is renderer-independent so boundary cases can be tested without
// PDF access, image production, or a business database.
const segmenter = new Intl.Segmenter('und', {granularity:'grapheme'});
const glyphs = value => Array.from(segmenter.segment(value), part => part.segment);
const SPACE = /^\s+$/u;
const CLOSE = /^[,.;:!?%％‰°℃）)\]｝}〉》」』】〕〗〙〛、。，．：；？！‼⁇⁈⁉”’»›]/u;
const OPEN = /[（(\[｛{〈《「『【〔〖〘〚“‘«‹]$/u;
const WORD = /^[\p{Script=Latin}][\p{Script=Latin}\p{Number}\p{M}]*(?:[.'’_\-][\p{Script=Latin}\p{Number}\p{M}]+)*/u;
const NUMBER = /^(?:[+\-−]?\s*[$¥￥€£]\s*|[$¥￥€£]\s*[+\-−]?\s*|[+\-−]?)\d+(?:[,.\u202f]\d+)*(?:[%％‰])?/u;

function fallbackUnits(token) {
 const parts=glyphs(token),prefix=token.match(/^[+\-−$¥￥€£\s]*\d/u)?.[0];
 // When an amount itself is too wide, retain its sign/currency with the first
 // digit. A separated negative sign can change how a financial example reads.
 if(prefix&&prefix.length>1&&NUMBER.exec(token)?.[0]===token) {
  return [prefix,...glyphs(token.slice(prefix.length))];
 }
 return parts;
}

function tokensOf(text) {
 const tokens=[];
 for(let i=0;i<text.length;) {
  const rest=text.slice(i),match=rest.match(WORD)||rest.match(NUMBER)||rest.match(/^\s+/u);
  const token=match?match[0]:segmenter.segment(rest)[Symbol.iterator]().next().value.segment;
  tokens.push(token);i+=token.length;
 }
 return tokens;
}
function legalBoundary(tokens,end) {
 const left=tokens.slice(0,end).join('').trimEnd();
 const right=tokens.slice(end).join('').trimStart();
 return !OPEN.test(left)&&!CLOSE.test(right);
}

async function hardLine(text,width,measure) {
 if(!text.trim())return [''];
 const tokens=tokensOf(text),lines=[];
 let start=0;
 while(start<tokens.length) {
  while(start<tokens.length&&SPACE.test(tokens[start]))start++;
  if(start===tokens.length)break;
  let best=-1,overflow=tokens.length;
  for(let end=start+1;end<=tokens.length;end++) {
   const value=tokens.slice(start,end).join('').trimEnd();
   if(await measure(value)>width) {overflow=end;break;}
   // A closing mark stays with preceding text; an opening mark stays with
   // following text. A source hard break is an intentional exception.
   if(end===tokens.length||legalBoundary(tokens,end))best=end;
  }
  if(best>start) {
   lines.push({start,end:best,text:tokens.slice(start,best).join('').trim()});
   start=best;continue;
  }
  // Keep normal English words, course codes and grouped amounts intact. Only
  // an otherwise impossible line falls back to grapheme boundaries (including
  // a word that fits alone but cannot fit its adjacent required punctuation).
  let split=-1,parts;
  for(let i=start;i<overflow;i++) {
   const candidate=fallbackUnits(tokens[i]);
   if(candidate.length>1&&!SPACE.test(tokens[i])) {split=i;parts=candidate;break;}
  }
  if(split<0)throw Error('当前字号下，文字或不可拆的标点组合超出区域宽度；请调整布局，旧图保留');
  tokens.splice(split,1,...parts);
 }
 // Keep the earlier renderer's useful short-tail balancing, but it is purely
 // optional and may never turn a valid whole-paragraph flow into an error.
 if(lines.length>1&&await measure(lines.at(-1).text)<width*.22) {
  const previous=lines.at(-2),last=lines.at(-1),choices=[];
  for(let end=previous.start+1;end<last.end;end++) {
   if(!legalBoundary(tokens,end))continue;
   const a=tokens.slice(previous.start,end).join('').trim();
   const b=tokens.slice(end,last.end).join('').trim();
   if(!a||!b)continue;
   const wa=await measure(a),wb=await measure(b);
   if(wa<=width&&wb<=width)choices.push({a,b,score:Math.abs(wa-wb),clause:/[，；：。！？,;:]$/u.test(a)});
  }
  const clauses=choices.filter(value=>value.clause);
  const best=(clauses.length?clauses:choices).sort((a,b)=>a.score-b.score)[0];
  if(best) {previous.text=best.a;last.text=best.b;}
 }
 return lines.map(line=>line.text);
}

export async function wrapMeasuredText(value,width,measure) {
 if(!Number.isFinite(width)||width<=0)throw Error('文字区域宽度必须大于零');
 const text=String(value).replace(/\r\n?|[\u2028\u2029]/gu,'\n');
 if(!text)return [];
 const segments=text.split('\n');
 // A terminating newline ends the authored line; it does not add an extra one.
 if(segments.at(-1)==='')segments.pop();
 const rows=[];
 for(const segment of segments)rows.push(...await hardLine(segment,width,measure));
 return rows;
}
