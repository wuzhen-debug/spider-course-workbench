import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url), ts = require('../../frontend/node_modules/typescript');
const compile = source => ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const from = source => import('data:text/javascript;base64,'+Buffer.from(compile(source)).toString('base64'));
const helpers = await from(fs.readFileSync(new URL('../../frontend/src/lib/auth-feedback.ts',import.meta.url),'utf8'));
const apiSource = fs.readFileSync(new URL('../../frontend/src/lib/api.ts',import.meta.url),'utf8');
const source = apiSource.slice(apiSource.indexOf('const REFRESH_TOKEN_KEY'),apiSource.indexOf('export async function fetchPlatforms'));
const {make} = await from(`export function make(runtime){const {http,message,window,authFailureMessage,isAuthRejected,isCredentialEndpoint}=runtime;${source.replace(/export /g,'')}return {login,register,logout,refreshAccessToken,clearAuthTokens,getAccessToken,getAuthSessionRevision,bootstrapAuth,hasRefreshToken};}`);
const tick = () => new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const tests=[];async function test(name,check){await check();tests.push(name);}
function setup(token='old-refresh-fixture') {
  const values=new Map(token?[['spider_xhs_refresh_token',token]]:[]),calls=[],retries=[],toasts=[];let errorHandler,post=async()=>({data:{access_token:'refresh-fixture'}});
  const http=async config=>{retries.push(config);return {data:{ok:true}};};
  http.interceptors={request:{use(){}},response:{use(_ok,fail){errorHandler=fail;}}};
  http.post=(...args)=>{calls.push(args);return post(...args);};http.get=async()=>({data:{id:1,username:'fixture-user'}});
  const runtime={...helpers,http,message:{error:value=>toasts.push(value)},window:{localStorage:{getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)}}};
  const api=make(runtime);
  return {api,values,calls,retries,toasts,setPost:fn=>{post=fn;},error:(url,status=401,silent=false)=>errorHandler({response:{status,data:{detail:'fixture failure'}},config:{url,headers:{},_silent:silent}})};
}
await test('network, timeout, server error and actual invalid credentials have different messages',()=>{
  assert.match(helpers.authFailureMessage({isAxiosError:true,code:'ERR_NETWORK'},'fallback'),/无法连接本机服务/);
  assert.match(helpers.authFailureMessage({code:'ECONNABORTED'},'fallback'),/超时/);
  assert.match(helpers.authFailureMessage({response:{status:503,data:{}}},'fallback'),/服务暂时异常/);
  assert.match(helpers.authFailureMessage({response:{status:401,data:{detail:'Invalid username or password'}}},'fallback'),/密码错误/);
  assert.equal(helpers.authFailureMessage(new Error('unrelated internal fixture'),'登录未完成'),'登录未完成');
});
await test('only explicit authentication rejection is grounds to discard a refresh token',()=>{
  for(const status of [401,403]) assert.equal(helpers.isAuthRejected({response:{status}}),true);
  for(const error of [{code:'ERR_NETWORK'},{code:'ECONNABORTED'},{response:{status:503}},{response:{status:429}}])assert.equal(helpers.isAuthRejected(error),false);
});
await test('credential endpoints never refresh recursively; protected identity reading still can',async()=>{
  const h=setup();
  for(const path of ['/auth/login','/auth/register','/auth/refresh','/auth/logout'])await assert.rejects(h.error(path,401,true));
  assert.equal(h.calls.length,0);
  await h.error('/auth/me');assert.equal(h.calls.length,1);assert.equal(h.retries.length,1);
});
await test('concurrent protected 401 responses share one refresh request',async()=>{
  const h=setup(),pending=deferred();h.setPost(()=>pending.promise);
  const a=h.error('/accounts'),b=h.error('/drafts');assert.equal(h.calls.length,1);
  pending.resolve({data:{access_token:'new-access-fixture'}});await Promise.all([a,b]);
  assert.equal(h.retries.length,2);assert.equal(h.api.getAccessToken(),'new-access-fixture');
});
await test('failed refresh neither recurses nor erases a token for a temporarily offline service',async()=>{
  for(const failure of [{isAxiosError:true,code:'ERR_NETWORK'},{code:'ECONNABORTED'},{response:{status:503}}]){
    const h=setup();h.setPost(async()=>{throw failure;});await assert.rejects(h.error('/accounts'));
    assert.equal(h.calls.length,1);assert.equal(h.api.hasRefreshToken(),true);assert.match(h.toasts[0],/本机/);
  }
});
await test('explicit invalid refresh clears once and reports expired without recursive requests',async()=>{
  const h=setup(),pending=deferred();h.setPost(()=>pending.promise);
  const a=h.error('/accounts'),b=h.error('/drafts');pending.reject({response:{status:401}});await Promise.allSettled([a,b]);
  assert.equal(h.calls.length,1);assert.equal(h.api.hasRefreshToken(),false);assert.equal(h.toasts.length,1);
});
await test('late refresh failure or success cannot clear or overwrite a newer login',async()=>{
  for(const success of [true,false]){
    const h=setup(),pending=deferred();h.setPost(url=>url==='/auth/refresh'?pending.promise:Promise.resolve({data:{access_token:'login-B',refresh_token:'refresh-B',user:{id:2}}}));
    const old=h.error('/accounts');const settled=old.catch(()=>{});await h.api.login({username:'fixture-B',password:'synthetic-only'});
    if(success)pending.resolve({data:{access_token:'old-late'}});else pending.reject({response:{status:401}});
    await settled;assert.equal(h.api.getAccessToken(),'login-B');assert.equal(h.values.get('spider_xhs_refresh_token'),'refresh-B');assert.equal(h.retries.length,0);
  }
});
await test('logout finishing after a newer login cannot clear that newer login',async()=>{
  const h=setup(),pending=deferred();h.setPost(url=>url==='/auth/logout'?pending.promise:Promise.resolve({data:{access_token:'login-B',refresh_token:'refresh-B',user:{id:2}}}));
  const old=h.api.logout();await h.api.login({username:'fixture-B',password:'synthetic-only'});pending.resolve({data:{status:'ok'}});await old;
  assert.equal(h.api.getAccessToken(),'login-B');assert.equal(h.api.hasRefreshToken(),true);
});
await test('new login refresh does not join a previous account refresh promise',async()=>{
  const h=setup(),a=deferred(),b=deferred();let refreshes=0;
  h.setPost(url=>url==='/auth/refresh'?(++refreshes===1?a.promise:b.promise):Promise.resolve({data:{access_token:'login-B',refresh_token:'refresh-B',user:{id:2}}}));
  const first=h.error('/old-accounts');const firstSettled=first.catch(()=>{});
  await h.api.login({username:'fixture-B',password:'synthetic-only'});
  const second=h.error('/new-accounts');assert.equal(refreshes,2);
  a.reject({response:{status:401}});await firstSettled;
  assert.equal(h.api.getAccessToken(),'login-B');assert.equal(h.api.hasRefreshToken(),true);
  b.resolve({data:{access_token:'renewed-B'}});await second;
  assert.equal(h.api.getAccessToken(),'renewed-B');assert.equal(h.values.get('spider_xhs_refresh_token'),'refresh-B');assert.equal(h.retries.length,1);
});
await test('login completing after an explicit logout does not restore the old session',async()=>{
  const h=setup(),pending=deferred();h.setPost(url=>url==='/auth/login'?pending.promise:Promise.resolve({data:{status:'ok'}}));
  const old=h.api.login({username:'fixture',password:'synthetic-only'});const settled=old.catch(()=>{});await h.api.logout();pending.resolve({data:{access_token:'late',refresh_token:'late',user:{id:2}}});await settled;
  assert.equal(h.api.getAccessToken(),null);assert.equal(h.api.hasRefreshToken(),false);
});
await test('FormData uses silent password-manager autofill instead of stale React values',()=>{
  const native=new Map([['username','visible-fixture'],['password','autofill-fixture'],['confirmPassword','confirm-fixture']]);
  assert.deepEqual(helpers.authFormFields({get:key=>native.get(key)??null},{username:'stale',password:'stale',confirmPassword:''}),{username:'visible-fixture',password:'autofill-fixture',confirmPassword:'confirm-fixture'});
  assert.equal(helpers.authFormFields({get:()=>''},{username:'stale',password:'stale',confirmPassword:'stale'}).password,'');
});
// Run the real login submit handler with synthetic native form data. No UI,
// browser credentials, local storage from the user, network or DB is accessed.
const loginSource=fs.readFileSync(new URL('../../frontend/src/pages/login/login-page.tsx',import.meta.url),'utf8');
const tree=ts.createSourceFile('login.tsx',loginSource,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);let submit;
function walk(node){if(ts.isFunctionDeclaration(node)&&node.name?.text==='handleSubmit')submit=node.getText(tree);ts.forEachChild(node,walk);}walk(tree);
const {submitter}=await from(`export function submitter(runtime){const {setError,credentialsSchema,formRef,FormData,authFormFields,username,password,confirmPassword,setUsername,setPassword,setConfirmPassword,mode,setIsSubmitting,auth,location,navigate,errorMessage}=runtime;${submit};return handleSubmit;}`);
await test('real submit sends current autofilled fields and register compares current confirmation',async()=>{
  const {z}=require('../../frontend/node_modules/zod');
  for(const mode of ['login','register']){
    const sent=[],errors=[],form=new Map([['username','fixture'],['password','synthetic-autofill'],['confirmPassword','synthetic-autofill']]);
    const runtime={...helpers,setError:value=>errors.push(value),credentialsSchema:z.object({username:z.string().trim().min(3),password:z.string().min(6)}),formRef:{current:form},FormData:class{constructor(value){this.value=value;}get(key){return this.value.get(key)??null;}},username:'',password:'',confirmPassword:'',setUsername(){},setPassword(){},setConfirmPassword(){},mode,setIsSubmitting(){},auth:{login:value=>sent.push(value),register:value=>sent.push(value)},location:{state:null},navigate(){},errorMessage:(_error,fallback)=>fallback};
    await submitter(runtime)();assert.deepEqual(sent,[{username:'fixture',password:'synthetic-autofill'}]);assert.deepEqual(errors,[null]);
  }
  for(const name of ['username','password','confirmPassword'])assert.match(loginSource,new RegExp(`name="${name}"`));
});
const hookSource=fs.readFileSync(new URL('../../frontend/src/hooks/use-auth.ts',import.meta.url),'utf8');
const hookTree=ts.createSourceFile('auth.ts',hookSource,ts.ScriptTarget.Latest,true);
const declarations=hookTree.statements.filter(n=>!ts.isImportDeclaration(n)).map(n=>n.getText(hookTree).replace(/^export /,'')).join('\n');
const {hookFactory}=await from(`export function hookFactory(runtime){const {api,authFailureMessage,isAuthRejected}=runtime;const useEffect=()=>{},useSyncExternalStore=()=>{};${declarations};return {bootstrap,login,logout,getSnapshot};}`);
await test('late bootstrap rejection cannot replace a new authenticated login',async()=>{
  const pending=deferred();let revision=0,cleared=0;
  const api={hasRefreshToken:()=>true,getAuthSessionRevision:()=>revision,bootstrapAuth:()=>pending.promise,clearAuthTokens(){cleared++;revision++;},login:async()=>{revision++;return {user:{id:2,username:'fixture-B'}};}};
  const h=hookFactory({...helpers,api});const old=h.bootstrap();await h.login({username:'fixture-B',password:'synthetic-only'});pending.reject({response:{status:401}});await old;
  assert.equal(cleared,0);assert.equal(h.getSnapshot().status,'authenticated');assert.equal(h.getSnapshot().user.id,2);
});
await test('bootstrap preserves a token on temporary outage but clears explicitly rejected token',async()=>{
  for(const rejected of [false,true]){
    let cleared=0,revision=0;
    const api={hasRefreshToken:()=>cleared===0,getAuthSessionRevision:()=>revision,bootstrapAuth:async()=>{throw rejected?{response:{status:401}}:{isAxiosError:true,code:'ERR_NETWORK'};},clearAuthTokens(){cleared++;revision++;}};
    const h=hookFactory({...helpers,api});await h.bootstrap();assert.equal(cleared,rejected?1:0);assert.equal(h.getSnapshot().status,'anonymous');assert.match(h.getSnapshot().error,rejected?/过期/:/无法连接/);
  }
});
console.log(JSON.stringify({passed:tests.length,tests},null,2));
