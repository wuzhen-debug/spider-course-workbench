import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url), ts = require('../../frontend/node_modules/typescript');
const compile = source => ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React } }).outputText;
const from = source => import('data:text/javascript;base64,' + Buffer.from(compile(source)).toString('base64'));
const helpers = await from(fs.readFileSync(new URL('../../frontend/src/components/account/login-state.ts', import.meta.url), 'utf8'));
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => { resolve=a;reject=b; }); return {promise,resolve,reject}; };
const tests=[]; async function test(name, check) { await check(); tests.push(name); }
function clock() {
  let serial=0, now=0; const tasks=new Map(), delays=[];
  return { schedule(callback, delay) { delays.push(delay);tasks.set(++serial,{callback,at:now+delay});return serial; }, unschedule(id) { tasks.delete(id); },
    async next() { const entry=[...tasks.entries()].sort((a,b)=>a[1].at-b[1].at)[0]; assert.ok(entry,'A timer should be queued'); tasks.delete(entry[0]);now=entry[1].at;entry[1].callback();await tick(); },
    get size(){return tasks.size;}, delays };
}
function hookRuntime(extra={}) {
  const slots=[],writes=[],pendingEffects=[]; let cursor=0;const time=clock();
  const runtime={...helpers, helpers, window:{setTimeout:time.schedule,clearTimeout:time.unschedule},
    pollLoginSequentially:options=>helpers.pollLoginSequentially({...options,schedule:time.schedule,unschedule:time.unschedule}),
    useState(initial){const i=cursor++;if(!slots[i])slots[i]={value:initial};return [slots[i].value, value=>{slots[i].value=typeof value==='function'?value(slots[i].value):value;writes.push([i,slots[i].value]);}];},
    useRef(initial){const i=cursor++;if(!slots[i])slots[i]={current:initial};return slots[i];},
    useEffect(effect,deps){const i=cursor++,previous=slots[i];if(!previous||deps.some((d,n)=>d!==previous.deps[n])){pendingEffects.push(()=>{previous?.cleanup?.();slots[i]={deps,cleanup:effect()};});}},
    useCallback(fn){return fn;}, ...extra};
  return {runtime,time,writes,reset(){cursor=0;},flushEffects(){pendingEffects.splice(0).forEach(effect=>effect());},unmount(){slots.forEach(slot=>slot?.cleanup?.());pendingEffects.length=0;}};
}
function nodes(root) {const all=[];function walk(node){if(!node||typeof node!=='object')return;if(Array.isArray(node)){node.forEach(walk);return;}all.push(node);walk(node.children);}walk(root);return all;}
const text = node => typeof node==='string'||typeof node==='number'?String(node):Array.isArray(node)?node.map(text).join(''):node&&typeof node==='object'?text(node.children):'';
async function panel(name, props={}, api={}) {
  const source=fs.readFileSync(new URL(`../../frontend/src/components/account/${name}-login-panel.tsx`,import.meta.url),'utf8');
  const tree=ts.createSourceFile('panel.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  const declarations=tree.statements.filter(node=>!ts.isImportDeclaration(node)).map(node=>node.getText(tree).replace(/^export /,'')).join('\n');
  const component=name==='phone'?'PhoneLoginPanel':'QrLoginPanel', bound=[];
  const hooks=hookRuntime({sendXhsPhoneCode:async()=>({session_id:2,status:'pending',message:'sent'}),confirmXhsPhoneLogin:async()=>({session_id:2,status:'confirmed',account:{id:11}}),
    createXhsPcQrLoginSession:async()=>({session_id:2,status:'pending',qr_url:'https://example.test/qr2',qr_image_data_url:'data:image/png;base64,TEST2'}),
    createXhsCreatorQrLoginSession:async()=>({session_id:3,status:'pending',qr_url:'https://example.test/qr3',qr_image_data_url:'data:image/png;base64,TEST3'}),
    pollXhsLoginSession:async id=>({session_id:id,status:'pending',qr_url:'https://example.test/qr'}),...api});
  const {make}=await from(`export function make(runtime){const {useEffect,useRef,useState,useCallback,sendXhsPhoneCode,confirmXhsPhoneLogin,createXhsPcQrLoginSession,createXhsCreatorQrLoginSession,pollXhsLoginSession,loginErrorMessage,loginErrorStatus,pollLoginSequentially,window}=runtime;
    const React={createElement:(type,props,...children)=>({type,props:props||{},children})};const [Alert,Button,Card,Checkbox,Form,Input,Space,MessageOutlined,CheckCircleOutlined,ReloadOutlined]=['Alert','Button','Card','Checkbox','Form','Input','Space','MessageOutlined','CheckCircleOutlined','ReloadOutlined'];const Typography={Text:'Text',Link:'AntLink'};
    ${declarations};return ${component};}`);
  const Component=make(hooks.runtime);let root;
  const fullProps={accountType:'creator',onConfirmed:account=>bound.push(account),...props};
  const h={...hooks,bound,render(flush=true){hooks.reset();root=Component(fullProps);if(flush)hooks.flushEffects();return root;},get root(){return root;},
    button(label){const found=nodes(root).find(n=>n.type==='Button'&&text(n).includes(label));assert.ok(found,label);return found;},
    input(placeholder){const found=nodes(root).find(n=>n.type==='Input'&&n.props.placeholder===placeholder);assert.ok(found,placeholder);return found;},
    get alerts(){return nodes(root).filter(n=>n.type==='Alert').map(n=>n.props.message);}};
  h.render();await tick();h.render();return h;
}

await test('safe backend reason is retained instead of labelling every failure as a bad SMS code',()=>{
  assert.equal(helpers.loginErrorMessage({response:{status:502,data:{detail:'登录已通过，但平台账号资料读取失败，请稍后重试。'}}},'fallback'),'登录已通过，但平台账号资料读取失败，请稍后重试。');
  assert.equal(helpers.loginErrorMessage({response:{status:400,data:{detail:{message:'请在官方页面完成验证'}}}},'fallback'),'请在官方页面完成验证');
  const secret='synthetic-secret-not-to-display';assert.equal(helpers.loginErrorMessage({response:{status:422,data:{detail:[{input:secret,msg:'bad'}]}}},'fallback'),'fallback');
  assert.equal(helpers.loginErrorMessage({code:'ERR_NETWORK'},'fallback'),'无法连接本机登录服务，请检查后台是否运行后重试。');
});
await test('sequential QR polling never overlaps slow requests and cancel ignores a late confirmation',async()=>{
  const time=clock(),pending=deferred(),results=[];let calls=0;
  const stop=helpers.pollLoginSequentially({load:()=>{calls++;return pending.promise;},onResult:result=>{results.push(result);return false;},onError:()=>false,schedule:time.schedule,unschedule:time.unschedule});
  await time.next();assert.equal(calls,1);assert.equal(time.size,0);stop();pending.resolve({status:'confirmed'});await tick();assert.deepEqual(results,[]);assert.equal(time.size,0);
});
await test('transient QR failure backs off and successful poll clears failure count',async()=>{
  const time=clock(),events=[];let calls=0;
  const stop=helpers.pollLoginSequentially({load:async()=>{if(++calls===1)throw Error('temporary');return {status:calls===3?'confirmed':'pending'};},onResult:result=>{events.push(result.status);return result.status!=='confirmed';},onError:(_error,failures)=>{events.push(failures);return true;},schedule:time.schedule,unschedule:time.unschedule});
  await time.next();await time.next();await time.next();assert.deepEqual(events,[1,'pending','confirmed']);assert.deepEqual(time.delays,[2000,4000,2000]);assert.equal(time.size,0);stop();
});
await test('SMS send surfaces the concrete network/session failure and does not claim success',async()=>{
  const h=await panel('phone',{}, {sendXhsPhoneCode:async()=>{throw {response:{status:502,data:{detail:'平台登录会话初始化失败，请稍后重试。'}}};}});
  h.input('请输入手机号').props.onChange({target:{value:'13800138000'}});h.render();await h.button('发送验证码').props.onClick();h.render();assert.deepEqual(h.alerts,['平台登录会话初始化失败，请稍后重试。']);assert.ok(h.button('确认绑定').props.disabled);h.unmount();
});
await test('double click sends one SMS and editing the number invalidates its session and code',async()=>{
  const pending=deferred(),calls=[];const h=await panel('phone',{}, {sendXhsPhoneCode:payload=>{calls.push(payload);return pending.promise;}});
  h.input('请输入手机号').props.onChange({target:{value:'13800138000'}});h.render();const click=h.button('发送验证码').props.onClick;const sent=click();await click();assert.equal(calls.length,1);
  h.render();assert.equal(h.input('请输入手机号').props.disabled,true);pending.resolve({session_id:24,status:'pending'});await sent;h.render();
  h.input('请输入验证码').props.onChange({target:{value:'123456'}});h.render();assert.equal(h.button('确认绑定').props.disabled,false);
  h.input('请输入手机号').props.onChange({target:{value:'13900139000'}});h.render();assert.equal(h.input('请输入验证码').props.value,'');assert.equal(h.button('确认绑定').props.disabled,true);h.unmount();
});
await test('SMS confirmation preserves a post-login profile error without falsely declaring code expiry',async()=>{
  const h=await panel('phone',{}, {confirmXhsPhoneLogin:async()=>{throw {response:{status:502,data:{detail:'登录凭证已取得，但账号资料读取失败；请稍后重试。'}}};}});
  h.input('请输入手机号').props.onChange({target:{value:'13800138000'}});h.render();await h.button('发送验证码').props.onClick();h.render();h.input('请输入验证码').props.onChange({target:{value:'123456'}});h.render();await h.button('确认绑定').props.onClick();h.render();
  assert.deepEqual(h.alerts,['登录凭证已取得，但账号资料读取失败；请稍后重试。']);assert.deepEqual(h.bound,[]);h.unmount();
});
await test('SMS expiry clears obsolete session and successful binding clears the secret code',async()=>{
  for(const expired of [true,false]){const h=await panel('phone',{}, {confirmXhsPhoneLogin:async()=>{if(expired)throw {response:{status:410,data:{detail:'会话已过期，请重新发送。'}}};return {session_id:2,status:'confirmed',account:{id:31}};}});
    h.input('请输入手机号').props.onChange({target:{value:'13800138000'}});h.render();await h.button('发送验证码').props.onClick();h.render();h.input('请输入验证码').props.onChange({target:{value:'123456'}});h.render();await h.button('确认绑定').props.onClick();h.render();
    assert.equal(h.input('请输入验证码').props.value,'');assert.equal(h.button('确认绑定').props.disabled,true);assert.equal(h.bound.length,expired?0:1);h.unmount();}
});
await test('closing/switching the SMS panel ignores an in-flight send result',async()=>{
  const pending=deferred(),h=await panel('phone',{}, {sendXhsPhoneCode:()=>pending.promise});h.input('请输入手机号').props.onChange({target:{value:'13800138000'}});h.render();const work=h.button('发送验证码').props.onClick();h.unmount();const writes=h.writes.length;pending.resolve({session_id:33,status:'pending'});await work;assert.equal(h.writes.length,writes);assert.deepEqual(h.bound,[]);
});
await test('closing an in-flight QR creation prevents its result from reaching a new credential panel',async()=>{
  const pending=deferred(),h=await panel('qr',{}, {createXhsCreatorQrLoginSession:()=>pending.promise});h.unmount();const writes=h.writes.length;
  const next=await panel('qr',{accountType:'pc'});pending.resolve({session_id:34,status:'pending',qr_url:'https://example.test/old',qr_image_data_url:'OLD'});await tick();
  assert.equal(h.writes.length,writes);assert.equal(nodes(next.root).find(n=>n.type==='img').props.src,'data:image/png;base64,TEST2');assert.deepEqual(h.bound,[]);next.unmount();
});
await test('refresh cancels old QR polling and a late confirmation cannot bind or replace the new QR',async()=>{
  const pending=deferred();let created=0,polls=0;
  const h=await panel('qr',{}, {createXhsCreatorQrLoginSession:async()=>({session_id:++created,status:'pending',qr_url:'https://example.test/qr',qr_image_data_url:'QR'+created}),pollXhsLoginSession:()=>{polls++;return pending.promise;}});
  await h.time.next();assert.equal(polls,1);await h.button('刷新二维码').props.onClick();h.render();pending.resolve({session_id:1,status:'confirmed',account:{id:41}});await tick();h.render();assert.deepEqual(h.bound,[]);assert.equal(nodes(h.root).find(n=>n.type==='img').props.src,'QR2');h.unmount();
});
await test('QR confirmed response binds exactly once and stops polling',async()=>{
  const h=await panel('qr',{}, {pollXhsLoginSession:async id=>({session_id:id,status:'confirmed',account:{id:42}})});await h.time.next();h.render();assert.deepEqual(h.bound,[{id:42}]);assert.equal(h.time.size,0);assert.equal(nodes(h.root).some(n=>n.type==='img'),false);h.unmount();
});
await test('missing account after QR confirmation is not presented as successful binding',async()=>{
  const h=await panel('qr',{}, {pollXhsLoginSession:async id=>({session_id:id,status:'confirmed',account:null})});await h.time.next();h.render();assert.equal(h.bound.length,0);assert.match(h.alerts[0],/尚未返回/);assert.equal(h.time.size,0);h.unmount();
});
await test('QR platform rejection stops immediately, reports its detail and hides the unusable QR',async()=>{
  const h=await panel('qr',{}, {pollXhsLoginSession:async()=>{throw {response:{status:403,data:{detail:'请先在官方创作中心完成验证。'}}};}});await h.time.next();h.render();assert.match(h.alerts[0],/官方创作中心完成验证/);assert.equal(h.time.size,0);assert.equal(nodes(h.root).some(n=>n.type==='img'),false);h.unmount();
});
await test('QR transient error disappears on a later successful poll and retries are bounded',async()=>{
  let calls=0;const h=await panel('qr',{}, {pollXhsLoginSession:async id=>{if(++calls===1)throw Error('temporary');return {session_id:id,status:'scanned',qr_url:'https://example.test/qr'};}});
  await h.time.next();h.render();assert.equal(h.alerts.length,1);await h.time.next();h.render();assert.equal(h.alerts.length,0);assert.match(text(h.root),/已扫码/);h.unmount();
  const fail=await panel('qr',{}, {pollXhsLoginSession:async()=>{throw Error('offline');}});await fail.time.next();await fail.time.next();await fail.time.next();fail.render();assert.equal(fail.time.size,0);assert.match(fail.alerts[0],/轮询已暂停/);fail.unmount();
});
await test('switching account subtypes remounts all three credential panels',()=>{
  const source=fs.readFileSync(new URL('../../frontend/src/components/account/add-account-drawer.tsx',import.meta.url),'utf8');
  for(const method of ['qr','phone','cookie'])assert.ok(source.includes('key={`'+method+'-${accountType}`}'));
});
await test('all login API calls silence only the global toast while retaining the rejected promise for inline handling',async()=>{
  const source=fs.readFileSync(new URL('../../frontend/src/lib/api.ts',import.meta.url),'utf8'),tree=ts.createSourceFile('api.ts',source,ts.ScriptTarget.Latest,true);
  const functions=['createXhsPcQrLoginSession','createXhsCreatorQrLoginSession','pollXhsLoginSession','sendXhsPhoneCode','confirmXhsPhoneLogin'];
  const declarations=functions.map(name=>tree.statements.find(node=>ts.isFunctionDeclaration(node)&&node.name?.text===name).getText(tree)).join('\n');
  const code=await from(`export function bind(http){${declarations.replaceAll('export async function','async function')};return {${functions.join(',')}};}`),calls=[],error={response:{status:400,data:{detail:'specific reason'}}};
  const http={get:async(...args)=>{calls.push(args);throw error;},post:async(...args)=>{calls.push(args);throw error;}};
  const api=code.bind(http);for(const name of functions){await assert.rejects(api[name](name==='pollXhsLoginSession'?3:{sub_type:'creator',phone:'13800138000',code:'123456',session_id:3}),caught=>caught===error);}
  assert.equal(calls.length,5);for(const args of calls)assert.equal(args.at(-1)._silent,true);
});
console.log(JSON.stringify({passed:tests.length,tests,network_calls:0,sms_sent:0,real_account_writes:0},null,2));
