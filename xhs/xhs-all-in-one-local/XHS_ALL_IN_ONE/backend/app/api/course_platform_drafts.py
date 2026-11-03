"""One PDF creates two persisted, independently versioned review drafts."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
from threading import Lock
from uuid import UUID,NAMESPACE_URL,uuid4,uuid5

from fastapi import APIRouter,Depends,HTTPException,Query
from fastapi.responses import FileResponse
from pydantic import BaseModel,ConfigDict,Field,field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api import course_library_drafts as xhs
from backend.app.api.ai import get_text_ai_client
from backend.app.api.course_library import require_library,owned_file
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.time import shanghai_now
from backend.app.models import User
from backend.app.models.course_library_draft import CourseLibraryDraft
from backend.app.models.course_platform_pair import CoursePlatformPair
from backend.app.services.course_brands import saved_brand
from backend.app.services.course_platform_copy import product_copy
from backend.app.services.xianyu_connector import get_xianyu_connector

router=APIRouter(prefix='/course-center/library',tags=['pdf-platform-drafts'])
creation_lock=Lock()


class Strict(BaseModel):model_config=ConfigDict(extra='forbid')


class GeneratePair(xhs.GenerateRequest):
    xianyu_pages:list[int]|None=Field(default=None,min_length=1,max_length=9)
    @field_validator('xianyu_pages')
    @classmethod
    def valid_pages(cls,value):return xhs.PlanRequest.page_numbers(value) if value is not None else value


class ExistingPair(Strict):
    package_id:int=Field(gt=0)


class XhsVersion(xhs.ReviewUpdate):
    package_id:int=Field(gt=0)
    request_key:UUID
    pages:list[int]|None=Field(default=None,min_length=1,max_length=9)
    @field_validator('pages')
    @classmethod
    def valid_pages(cls,value):return xhs.PlanRequest.page_numbers(value) if value is not None else value


class XianyuVersion(Strict):
    row_version:int=Field(ge=1)
    title:str=Field(min_length=1,max_length=200)
    description:str=Field(min_length=1,max_length=1500)
    price:Decimal|None=Field(default=None,gt=0,max_digits=12,decimal_places=2)
    delivery_note:str=Field(max_length=500)
    pages:list[int]=Field(min_length=1,max_length=9)
    @field_validator('pages')
    @classmethod
    def valid_pages(cls,value):return xhs.PlanRequest.page_numbers(value)


class ExportVersion(Strict):row_version:int=Field(ge=1)


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def optional_connector():
    try:return get_xianyu_connector()
    except HTTPException as error:
        if error.status_code==503:return None
        raise


def pair_owned(db,user,pair_id,lock=False):
    query=select(CoursePlatformPair).where(CoursePlatformPair.id==pair_id,CoursePlatformPair.user_id==user.id)
    if lock:query=query.with_for_update()
    item=db.scalar(query)
    if not item:raise HTTPException(404,'双平台稿不存在')
    return item


def xy_public(data):
    return {**{k:v for k,v in data.items() if k!='images'},
        'images':[{k:im[k] for k in ['page','sha256','width','height']} for im in data['images']]}


def serialize(db,item,user,settings):
    package=xhs.package_owned(db,user,item.xhs_package_id)
    return {'id':item.id,'file_id':item.file_id,'revision_id':item.revision_id,
        'source':package.source_snapshot,'xhs':xhs.serialize(db,package,user,settings),
        'xhs_history':item.xhs_history,'xianyu':xy_public(item.xianyu),
        'xianyu_history':[{'row_version':v['row_version'],'title':v['title'],'status':v['status'],
            'created_at':v['created_at']} for v in item.xianyu_history],
        'created_at':item.created_at.isoformat(),'updated_at':item.updated_at.isoformat(),
        'publishing_enabled':False,'shipping_enabled':False}


def make_xy(package,images=None,pages=None):
    source=deepcopy(package.source_snapshot);brand=saved_brand(source['preview_brand'])
    copy=product_copy(source,pages if pages is not None else package.page_texts)
    return {**copy,'price':None,'delivery_note':'电子资料；交付方式待人工确认，当前未启用发货。',
        'brand_id':brand['id'],'source':source,'images':deepcopy(images if images is not None else package.images),
        'row_version':1,'status':'pending','service_draft_id':None,'created_at':shanghai_now().isoformat()}


def verified_image_path(settings,user_id,image):
    root=(settings.storage_dir/'course-library-drafts'/str(user_id)).resolve()
    path=(settings.storage_dir/image['path']).resolve()
    if not path.is_relative_to(root) or not path.is_file() or xhs.hash_file(path)!=image['sha256']:
        raise HTTPException(409,'样张文件已变化，旧稿保留，请核对来源')
    return path


def render_xy(db,user,settings,package,pages):
    recipe=xhs.PlanRequest(revision_id=package.revision_id,pages=pages,mode='local',
        brand_id=saved_brand(package.source_snapshot['preview_brand'])['id'])
    plan=xhs.build_plan(db,user,settings,package.file_id,recipe)
    file,root,revision,fd=xhs.stable_source(db,user,settings,package.file_id,package.revision_id)
    try:
        images=xhs.render_samples(settings,user.id,fd,plan['source'],pages);xhs.unchanged(file,root,fd)
        return images,plan['pages']
    finally:os.close(fd)


@router.post('/files/{file_id}/platform-drafts')
def generate_pair(file_id:int,payload:GeneratePair,user:User=Depends(get_current_user),db:Session=Depends(get_db),
    settings=Depends(require_library),ai=Depends(get_text_ai_client)):
    with creation_lock:
        request_digest=digest({'file_id':file_id,**payload.model_dump(mode='json',exclude={'external_consent'})})
        old=db.scalar(select(CoursePlatformPair).where(CoursePlatformPair.user_id==user.id,CoursePlatformPair.request_key==str(payload.request_key)))
        if old:
            if old.request_digest!=request_digest:raise HTTPException(409,'本次双平台请求内容已变化，请重新读取范围；旧稿保留')
            return serialize(db,old,user,settings)
        base=xhs.GenerateRequest(**payload.model_dump(exclude={'xianyu_pages'}))
        result=xhs.generate(file_id,base,user,db,settings,ai)
        package=xhs.package_owned(db,user,result['id'])
        images=None;pages=None
        if payload.xianyu_pages is not None and payload.xianyu_pages!=payload.pages:
            images,pages=render_xy(db,user,settings,package,payload.xianyu_pages)
        data=make_xy(package,images,pages)
        item=CoursePlatformPair(user_id=user.id,file_id=file_id,revision_id=package.revision_id,
            request_key=str(payload.request_key),request_digest=request_digest,xhs_package_id=package.id,
            xhs_history=[package.id],xianyu=data,xianyu_history=[deepcopy(data)])
        db.add(item);db.commit();return serialize(db,item,user,settings)


@router.post('/files/{file_id}/platform-drafts/from-existing')
def from_existing(file_id:int,payload:ExistingPair,user:User=Depends(get_current_user),db:Session=Depends(get_db),settings=Depends(require_library),connector=Depends(optional_connector)):
    with creation_lock:
        package=xhs.package_owned(db,user,payload.package_id)
        if package.file_id!=file_id:raise HTTPException(404,'记录不属于这份 PDF')
        key=str(uuid5(NAMESPACE_URL,f'pdf-platform-existing:{user.id}:{package.id}'))
        old=db.scalar(select(CoursePlatformPair).where(CoursePlatformPair.user_id==user.id,CoursePlatformPair.request_key==key))
        if old:return serialize(db,old,user,settings)
        if xhs.source_stale(db,package,user,settings):raise HTTPException(409,'PDF 已变化，请选择当前版本生成两版；旧稿保留')
        data=make_xy(package)
        # Reuse an already authored product when it comes from this exact XHS
        # package. Only local authenticated reads; offline service is optional.
        try:
            products=connector.request('GET','/bridge/drafts',user.id)['items'] if connector is not None else []
            existing=next((d for d in products if d['source'].get('package_id')==package.id and
                d['source'].get('sha256')==package.source_snapshot['sha256'] and d['brand_id']==data['brand_id']),None)
            if existing:
                directory=settings.storage_dir/'course-library-drafts'/str(user.id)/uuid4().hex
                directory.mkdir(parents=True,mode=0o700);images=[]
                for index,im in enumerate(existing['images']):
                    content=connector.request('GET',f'/bridge/drafts/{existing["id"]}/images/{index}',user.id,binary=True)
                    if hashlib.sha256(content).hexdigest()!=im['sha256']:raise HTTPException(409,'已有闲鱼样张指纹未匹配')
                    path=directory/f'xianyu-{index}.png';path.write_bytes(content);path.chmod(0o600)
                    images.append({**im,'path':str(path.relative_to(settings.storage_dir))})
                data.update(title=existing['title'],description=existing['description'],price=existing['price'],
                    delivery_note=existing['delivery_note'],images=images,status='exported',service_draft_id=existing['id'],
                    service_row_version=existing['row_version'])
        except HTTPException as error:
            if error.status_code not in {403,503}:raise
        item=CoursePlatformPair(user_id=user.id,file_id=file_id,revision_id=package.revision_id,request_key=key,
            request_digest=digest({'package_id':package.id}),xhs_package_id=package.id,xhs_history=[package.id],
            xianyu=data,xianyu_history=[deepcopy(data)])
        db.add(item);db.commit();return serialize(db,item,user,settings)


@router.get('/files/{file_id}/platform-drafts')
def history(file_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db),settings=Depends(require_library)):
    owned_file(db,file_id,user,settings)
    rows=db.scalars(select(CoursePlatformPair).where(CoursePlatformPair.file_id==file_id,
        CoursePlatformPair.user_id==user.id).order_by(CoursePlatformPair.id.desc()).limit(50)).all()
    return {'items':[{'id':r.id,'title':r.xianyu['title'],'brand':r.xianyu['source']['preview_brand']['name'],
        'xhs_package_id':r.xhs_package_id,'xianyu_version':r.xianyu['row_version'],'created_at':r.created_at.isoformat()} for r in rows]}


@router.get('/platform-drafts/{pair_id}')
def read_pair(pair_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db),settings=Depends(require_library)):
    return serialize(db,pair_owned(db,user,pair_id),user,settings)


@router.post('/platform-drafts/{pair_id}/xhs/versions')
def save_xhs(pair_id:int,payload:XhsVersion,user:User=Depends(get_current_user),db:Session=Depends(get_db),settings=Depends(require_library)):
    with creation_lock:
        item=pair_owned(db,user,pair_id,True)
        fingerprint=digest({'pair_id':pair_id,**payload.model_dump(mode='json',exclude={'request_key'})})
        old=db.scalar(select(CourseLibraryDraft).where(CourseLibraryDraft.user_id==user.id,CourseLibraryDraft.request_key==str(payload.request_key)))
        if old:
            if old.plan_digest!=fingerprint:raise HTTPException(409,'保存请求已用于其他内容')
            return serialize(db,item,user,settings)
        if item.xhs_package_id!=payload.package_id:raise HTTPException(409,'小红书版已更新，请刷新后继续')
        previous=xhs.package_owned(db,user,item.xhs_package_id)
        if not payload.title.strip() or not payload.body.strip():raise HTTPException(422,'标题和正文不能为空')
        images=deepcopy(previous.images);page_texts=deepcopy(previous.page_texts)
        if payload.pages is not None and payload.pages!=[im['page'] for im in images]:
            images,page_texts=render_xy(db,user,settings,previous,payload.pages)
        child=CourseLibraryDraft(user_id=user.id,file_id=item.file_id,revision_id=item.revision_id,request_key=str(payload.request_key),
            plan_digest=fingerprint,status='pending',generation_mode=previous.generation_mode,title=payload.title.strip(),body=payload.body.strip(),
            tags=payload.tags,source_snapshot={**{k:deepcopy(v) for k,v in previous.source_snapshot.items() if k!='draft_binding'},'platform_pair_id':item.id,'platform_parent_package_id':previous.id},
            page_texts=page_texts,images=images,model_snapshot=deepcopy(previous.model_snapshot),instruction=previous.instruction)
        db.add(child);db.flush();item.xhs_package_id=child.id;item.xhs_history=[*item.xhs_history,child.id];item.updated_at=shanghai_now()
        db.commit();return serialize(db,item,user,settings)


@router.patch('/platform-drafts/{pair_id}/xianyu')
def save_xianyu(pair_id:int,payload:XianyuVersion,user:User=Depends(get_current_user),db:Session=Depends(get_db),settings=Depends(require_library)):
    with creation_lock:
        item=pair_owned(db,user,pair_id,True);current=item.xianyu
        if current['row_version']!=payload.row_version:raise HTTPException(409,'闲鱼版已更新，请刷新后继续')
        if not payload.title.strip() or not payload.description.strip():raise HTTPException(422,'标题和描述不能为空')
        xhs.PlanRequest(revision_id=item.revision_id,pages=payload.pages)
        images=deepcopy(current['images'])
        if payload.pages!=[im['page'] for im in images]:
            package=xhs.package_owned(db,user,item.xhs_package_id);images,_=render_xy(db,user,settings,package,payload.pages)
        data={**deepcopy(current),'title':payload.title.strip(),'description':payload.description.strip(),
            'price':str(payload.price) if payload.price is not None else None,'delivery_note':payload.delivery_note,
            'images':images,'row_version':current['row_version']+1,'status':'pending','service_draft_id':None,
            'created_at':shanghai_now().isoformat()}
        item.xianyu=data;item.xianyu_history=[*item.xianyu_history,deepcopy(data)];item.updated_at=shanghai_now()
        db.commit();return serialize(db,item,user,settings)


@router.get('/platform-drafts/{pair_id}/xianyu/versions/{version}')
def xy_version(pair_id:int,version:int,user:User=Depends(get_current_user),db:Session=Depends(get_db),settings=Depends(require_library)):
    item=pair_owned(db,user,pair_id)
    data=next((v for v in item.xianyu_history if v['row_version']==version),None)
    if not data:raise HTTPException(404,'闲鱼历史版本不存在')
    return xy_public(data)


@router.get('/platform-drafts/{pair_id}/xianyu/images/{index}')
def xy_image(pair_id:int,index:int,version:int|None=Query(None,ge=1),user:User=Depends(get_current_user),db:Session=Depends(get_db),settings=Depends(require_library)):
    item=pair_owned(db,user,pair_id);data=item.xianyu
    if version is not None:data=next((v for v in item.xianyu_history if v['row_version']==version),None)
    if data is None or index<0 or index>=len(data['images']):raise HTTPException(404,'样张不存在')
    return FileResponse(verified_image_path(settings,user.id,data['images'][index]),media_type='image/png',
        headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})


@router.post('/platform-drafts/{pair_id}/xianyu/export')
def export_xianyu(pair_id:int,payload:ExportVersion,user:User=Depends(get_current_user),db:Session=Depends(get_db),settings=Depends(require_library),connector=Depends(get_xianyu_connector)):
    with creation_lock:
        item=pair_owned(db,user,pair_id,True);data=item.xianyu
        if data.get('service_draft_id') and (payload.row_version==data['row_version'] or data.get('exported_from_version')==payload.row_version):
            return serialize(db,item,user,settings)
        if data['row_version']!=payload.row_version:raise HTTPException(409,'闲鱼版已更新，请先刷新')
        package=xhs.package_owned(db,user,item.xhs_package_id)
        if xhs.source_stale(db,package,user,settings):raise HTTPException(409,'源 PDF 已变化，不能导入旧版')
        file,root,revision,fd=xhs.stable_source(db,user,settings,item.file_id,item.revision_id)
        os.close(fd)
        if any(w in data['title']+data['description'] for w in ['代写','包过','保分','可提交成品','原题答案','直接答案']):raise HTTPException(422,'请保留学习支持用途，删除成绩保证或可提交答案等表述')
        images=[]
        for im in data['images']:
            result=connector.request('PUT','/bridge/assets/'+im['sha256'],user.id,content=verified_image_path(settings,user.id,im).read_bytes())
            if any(result[k]!=im[k] for k in ['sha256','width','height']):raise HTTPException(409,'样张接入校验未通过')
            images.append({k:im[k] for k in ['page','sha256','width','height']})
        source={k:data['source'].get(k) for k in ['filename','university','course_code','term','material_type','sha256','page_count','revision_id','preview_layout','preview_brand']}
        source.update(file_id=item.file_id,package_id=item.xhs_package_id,platform_pair_id=item.id,platform_pair_version=data['row_version'],origin='spider-pdf-dual')
        request_key=str(uuid5(NAMESPACE_URL,f'pdf-pair-export:{user.id}:{item.id}:{data["row_version"]}'))
        if xhs.source_stale(db,package,user,settings):raise HTTPException(409,'复制样张期间原 PDF 已变化，请重新核对')
        result=connector.request('POST','/bridge/drafts',user.id,payload={'request_key':request_key,'brand_id':data['brand_id'],
            'account_id':None,'title':data['title'],'description':data['description'],'price':data['price'],
            'delivery_note':data['delivery_note'],'source':source,'images':images})
        next_data={**deepcopy(data),'status':'exported','service_draft_id':result['id'],'service_row_version':result['row_version'],
            'exported_from_version':data['row_version'],'row_version':data['row_version']+1,'created_at':shanghai_now().isoformat()}
        item.xianyu=next_data;item.xianyu_history=[*item.xianyu_history,deepcopy(next_data)];item.updated_at=shanghai_now()
        db.commit();return serialize(db,item,user,settings)
