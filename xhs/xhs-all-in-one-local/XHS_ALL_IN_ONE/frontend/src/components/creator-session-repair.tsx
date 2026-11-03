import {Alert,Button,Card,Drawer,Space,Typography} from 'antd';
import {useEffect,useRef,useState} from 'react';
import {checkCreatorPublishSession,repairCreatorPublishSession,type CreatorSessionCheck} from '../lib/api';
import {QrLoginPanel} from './account/qr-login-panel';

/** Repair authentication only; this component has no publish transport. */
export function CreatorSessionRepair({accountId,onState,onUpdated}:{accountId:number;onState?:(state:CreatorSessionCheck)=>void;onUpdated?:()=>void}){
 const [result,setResult]=useState<CreatorSessionCheck|null>(null);const [busy,setBusy]=useState(false);
 const [loginOpen,setLoginOpen]=useState(false);const [error,setError]=useState('');
 const current=useRef(accountId);current.current=accountId;const callbacks=useRef({onState,onUpdated});callbacks.current={onState,onUpdated};
 function accept(next:CreatorSessionCheck){if(current.current!==next.account_id)return;setResult(next);callbacks.current.onState?.(next);}
 useEffect(()=>{let active=true;setResult(null);setLoginOpen(false);setError('');setBusy(true);
  void checkCreatorPublishSession(accountId).then(next=>{if(active)accept(next);}).catch(()=>{if(active)setError('会话检查未完成，请稍后重新检查。');}).finally(()=>{if(active)setBusy(false);});
  return()=>{active=false;};
 },[accountId]);
 async function check(){const id=accountId;setBusy(true);setError('');try{const next=await checkCreatorPublishSession(id);accept(next);if(next.session_ok)callbacks.current.onUpdated?.();}catch{if(current.current===id)setError('检查未完成，未提交任何笔记。');}finally{if(current.current===id)setBusy(false);}}
 async function repair(){const id=accountId;setBusy(true);setError('');try{
  const next=await repairCreatorPublishSession(id);if(current.current!==id)return;accept(next);
  if(next.session_ok)callbacks.current.onUpdated?.();else if(next.repair?.requires_pc_login)setLoginOpen(true);
 }catch(caught){if(current.current===id){const detail=(caught as {response?:{data?:{detail?:unknown}}})?.response?.data?.detail;setError(typeof detail==='string'?detail:'同步未完成，现有会话和草稿保留。');}}
 finally{if(current.current===id)setBusy(false);}}
 const name=result?.account_name||'当前发布账号';
 return <Card size="small" title={`${name} · 发布登录`}>
  <Space direction="vertical" style={{width:'100%'}}>
   <Typography.Text>{result?.session_ok?'同账号发布会话的只读检查已通过。':'创作中心登录和跨站发布会话分别检查；补全同一账号的PC登录后再同步。'}</Typography.Text>
   {result&&<Alert type={result.session_ok?'success':'warning'} message={result.message} showIcon/>}
   {error&&<Alert type="error" message={error} showIcon/>}
   <Space wrap>{!result?.session_ok&&<Button type="primary" loading={busy} onClick={()=>void repair()}>{result?.repair?.matching_pc_account_id?'同步同账号登录':'扫码补全发布登录'}</Button>}
    <Button disabled={busy} onClick={()=>void check()}>只检查会话，不发布</Button></Space>
   <Typography.Text type="secondary">保留原稿与历史失败记录；这里只处理登录，不上传或重试发布。</Typography.Text>
  </Space>
  <Drawer title={`补全「${name}」发布登录`} open={loginOpen} onClose={()=>setLoginOpen(false)} width={420} destroyOnHidden>
   <Alert type="info" showIcon message={`请使用小红书 App 中的「${name}」账号扫码，并在手机确认。`} description="仅补全PC登录并同步当前Creator账号。账号不一致时停止保存；完成后只做会话检查。" style={{marginBottom:16}}/>
   {loginOpen&&<QrLoginPanel key={accountId} accountType="pc" targetCreatorAccountId={accountId} onConfirmed={()=>{setLoginOpen(false);callbacks.current.onUpdated?.();void check();}}/>}
  </Drawer>
 </Card>;
}
