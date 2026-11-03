import { Alert, Select } from 'antd';
import { useEffect, useState } from 'react';
import { visualWorkflowGet, visualWorkflowLogo } from '../lib/api';

export type CourseBrand={id:string;name:string;logo_sha256:string};

/** A new piece starts blank. Resuming a saved piece keeps its own identity. */
export function CourseBrandSelect({value,onChange,disabled=false,label='本篇品牌'}:{value:string;onChange:(id:string)=>void;disabled?:boolean;label?:string}){
 const [choices,setChoices]=useState<CourseBrand[]>([]);const [logos,setLogos]=useState<Record<string,string>>({});const [error,setError]=useState(false);
 useEffect(()=>{let live=true;const urls:string[]=[];
  void visualWorkflowGet<{items:CourseBrand[]}>('/brands').then(async result=>{
   if(!live)return;setChoices(result.items);
   const images=await Promise.all(result.items.map(async b=>{const url=URL.createObjectURL(await visualWorkflowLogo(b.id));urls.push(url);return [b.id,url];}));
   if(live)setLogos(Object.fromEntries(images));else urls.forEach(URL.revokeObjectURL);
  }).catch(()=>{if(live)setError(true);});
  return()=>{live=false;urls.forEach(URL.revokeObjectURL);};
 },[]);
 const selected=choices.find(b=>b.id===value||b.name===value);
 return <div className="course-brand-select" style={{marginBottom:12}}>
  <div style={{marginBottom:6}}>{label}</div>
  <Select aria-label={label} style={{width:'100%'}} value={selected?.id} placeholder="请选择：星途留学 / 稳过留学" disabled={disabled} loading={!choices.length&&!error} onChange={onChange}
   options={choices.map(b=>({value:b.id,label:<span style={{display:'inline-flex',alignItems:'center',gap:10}}>{logos[b.id]&&<img src={logos[b.id]} alt={`${b.name} Logo`} style={{width:28,height:28,objectFit:'contain',background:'white',borderRadius:3}}/>}{b.name}</span>}))}/>
  {error&&<Alert type="error" message="品牌读取失败，请刷新页面；未替换为其他品牌。" style={{marginTop:6}}/>}
 </div>;
}
