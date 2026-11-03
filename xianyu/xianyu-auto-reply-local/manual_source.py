"""Private PDF bindings for manual publication; no platform transport."""
import hashlib
import hmac
import json
import os
from pathlib import Path,PurePosixPath
import tempfile
import time
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field


class SourceBinding(BaseModel):
    model_config=ConfigDict(extra='forbid')
    row_version:int=Field(ge=1)
    file_id:int=Field(gt=0)
    revision_id:int=Field(gt=0)
    platform_pair_id:int=Field(gt=0)
    platform_pair_version:int=Field(gt=0)
    source_digest:str=Field(pattern=r'^[a-f0-9]{64}$')
    sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    library_root:str=Field(min_length=1,max_length=2000)
    relative_path:str=Field(min_length=1,max_length=2000)
    issued_at:int=Field(gt=0)
    signature:str=Field(pattern=r'^[a-f0-9]{64}$')


def binding_signature(secret,owner,draft_id,binding):
    data={k:v for k,v in binding.items() if k!='signature'}
    proof=json.dumps({'owner':owner,'draft_id':draft_id,'binding':data},sort_keys=True,ensure_ascii=False).encode()
    return hmac.new(secret.encode(),proof,hashlib.sha256).hexdigest()


def digest_source(draft):
    value={k:draft[k] for k in ['brand_id','source','images']}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def checked_pdf(config,binding,draft):
    """Only this signed owner/draft/file reference; no directory-wide grant."""
    expected=binding_signature(config['bridge_token'],config['owner_user_id'],draft['id'],binding)
    if not hmac.compare_digest(binding.get('signature',''),expected):
        raise HTTPException(409,'PDF 来源签名未匹配，请从工作台重新核对当前商品')
    source=draft['source']
    if source.get('origin')!='spider-pdf-dual' or binding['source_digest']!=digest_source(draft):
        raise HTTPException(409,'PDF 来源与商品样张已变化，请重新打开预览核对')
    if any(binding[k]!=source.get(k) for k in ['file_id','revision_id','platform_pair_id','platform_pair_version','sha256']):
        raise HTTPException(409,'PDF 来源记录与商品不一致')
    if source.get('preview_brand',{}).get('id')!=draft['brand_id'] or draft['brand_id'] not in {'xingtu','wenguo'}:
        raise HTTPException(409,'样张品牌与商品品牌不一致')
    root=Path(binding['library_root'])
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise HTTPException(409,'PDF 来源目录无效')
    relative=binding['relative_path'];parts=relative.split('/')
    if PurePosixPath(relative).is_absolute() or any(p in {'','.','..'} for p in parts) or '\\' in relative or '\x00' in relative:
        raise HTTPException(409,'PDF 来源路径无效')
    current=root
    for part in parts:
        current=current/part
        if current.is_symlink():raise HTTPException(409,'PDF 来源不能使用符号链接')
    if current.suffix.lower()!='.pdf':raise HTTPException(409,'商品来源须为 PDF')
    try:
        fd=os.open(current,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
        try:
            start=os.fstat(fd)
            if start.st_size>200*1024*1024 or os.read(fd,5)!=b'%PDF-':raise HTTPException(409,'PDF 来源格式或大小未通过校验')
            os.lseek(fd,0,0);hasher=hashlib.sha256()
            while chunk:=os.read(fd,1024*1024):hasher.update(chunk)
            end=os.fstat(fd);present=current.stat()
            signature=lambda st:(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)
            if signature(start)!=signature(end) or signature(start)!=signature(present) or hasher.hexdigest()!=binding['sha256']:
                raise HTTPException(409,'原 PDF 已变化，请重新核对当前资料版本')
        finally:os.close(fd)
    except OSError:raise HTTPException(409,'原 PDF 当前无法读取，请核对题库来源') from None
    if not 1<=len(draft['images'])<=9 or len({im['page'] for im in draft['images']})!=len(draft['images']):
        raise HTTPException(422,'商品须使用 1 至 9 张不重复的真实样张')
    if not isinstance(source.get('page_count'),int) or any(not 1<=im['page']<=source['page_count'] for im in draft['images']):
        raise HTTPException(409,'样张页码不在原 PDF 范围内')
    return current


def record_path(storage,owner,draft):return storage/str(owner)/str(draft['id'])/'current.json'


def load_source(storage,owner,config,draft):
    try:binding=json.loads(record_path(storage,owner,draft).read_text())
    except (OSError,ValueError):raise HTTPException(409,'请先打开发布前预览，核对这份商品的原 PDF 来源') from None
    return checked_pdf(config,binding,draft)


def save_source(storage,owner,config,draft,binding):
    data=binding.model_dump()
    if owner!=config['owner_user_id']:raise HTTPException(403,'PDF 来源不属于当前用户')
    if data['row_version']!=draft['row_version']:raise HTTPException(409,'草稿已更新，请重新打开预览')
    if not -60<=time.time()-data['issued_at']<=300:raise HTTPException(409,'PDF 来源核验已过期，请重新打开预览')
    checked_pdf(config,data,draft)
    path=record_path(storage,owner,draft);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    raw=json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
    # Keep previous verifications as private evidence, outside frozen drafts.
    history=path.parent/(hashlib.sha256(raw.encode()).hexdigest()+'.json')
    if not history.exists():
        with history.open('x') as f:f.write(raw)
        history.chmod(0o600)
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,prefix='.binding-',delete=False) as f:
        f.write(raw);temporary=Path(f.name)
    temporary.chmod(0o600);os.replace(temporary,path)
    return {'ready':True,'draft_id':draft['id'],'source_sha256':data['sha256']}
