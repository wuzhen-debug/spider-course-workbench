"""Authenticated course-to-Xianyu draft bridge. Leaves all XHS records untouched."""
import hashlib
import os
from pathlib import Path
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.course_library import require_library
from backend.app.api.course_library_drafts import package_owned, stable_source, unchanged, source_stale
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import User
from backend.app.models.course_library_draft import CourseLibraryDraft
from backend.app.models.course_platform_pair import CoursePlatformPair
from backend.app.services.course_platform_copy import product_copy as independent_product_copy
from backend.app.services.course_brands import saved_brand
from backend.app.services.xianyu_connector import get_xianyu_connector

router=APIRouter(prefix='/platforms/xianyu',tags=['xianyu-drafts'])


class StrictModel(BaseModel):
    model_config=ConfigDict(extra='forbid')


class CreateFromMaterial(StrictModel):
    package_id:int=Field(gt=0)
    request_key:UUID
    brand_id:str
    account_id:str|None=Field(default=None,max_length=80)


class LoginRequest(StrictModel):
    brand_id:str


class EditDraft(StrictModel):
    row_version:int=Field(ge=1)
    title:str=Field(min_length=1,max_length=200)
    description:str=Field(min_length=1,max_length=1500)
    price:str|None=None
    account_id:str|None=Field(default=None,max_length=80)
    delivery_note:str=Field(max_length=500)


class PublishOptions(StrictModel):
    row_version:int=Field(ge=1)
    previous_options_id:UUID|None=None
    category_index:int|None=Field(default=None,ge=0,le=500)


class PublishLocation(StrictModel):
    query:str=Field(min_length=1,max_length=60)


class PublishPreview(StrictModel):
    row_version:int=Field(ge=1)
    options_id:UUID
    category_index:int=Field(ge=0,le=500)
    attributes:dict[str,list[int]]=Field(default_factory=dict)
    location_id:UUID


class PublishOne(StrictModel):
    preview_id:UUID
    confirmation:Literal['PUBLISH_THIS_ONE_ITEM']


class ReconcilePublication(StrictModel):
    item_id:str|None=Field(default=None,pattern=r'^\d{1,32}$')


def source_allowed(item):
    s=item.source_snapshot or {}
    return s.get('university')=='昆士兰大学' and s.get('course_code')=='MKTG1501' and s.get('preview_layout')=='pdf-full-width-v2' and s.get('preview_brand',{}).get('name')=='星途留学'


@router.get('/status')
def status(user:User=Depends(get_current_user),connector=Depends(get_xianyu_connector)):
    result=connector.request('GET','/health',user.id)
    return {**result,'brand_id':'xingtu','brand_name':'星途留学','scope':'昆士兰大学 MKTG1501'}


@router.get('/accounts')
def accounts(user:User=Depends(get_current_user),connector=Depends(get_xianyu_connector)):
    return connector.request('GET','/bridge/accounts',user.id)


@router.post('/login')
def login(payload:LoginRequest,user:User=Depends(get_current_user),connector=Depends(get_xianyu_connector)):
    return connector.request('POST','/bridge/login',user.id,payload=payload.model_dump())


@router.get('/login/{session_id}')
def login_status(session_id:UUID,user:User=Depends(get_current_user),connector=Depends(get_xianyu_connector)):
    return connector.request('GET','/bridge/login/'+str(session_id),user.id)


@router.get('/materials')
def materials(user:User=Depends(get_current_user),db:Session=Depends(get_db),settings=Depends(require_library),connector=Depends(get_xianyu_connector)):
    if user.id!=connector.config['owner_user_id']: raise HTTPException(403,'当前用户尚未配置闲鱼工作台')
    rows=db.scalars(select(CourseLibraryDraft).where(CourseLibraryDraft.user_id==user.id).order_by(CourseLibraryDraft.id.desc()).limit(200)).all()
    pairs=db.scalars(select(CoursePlatformPair).where(CoursePlatformPair.user_id==user.id).order_by(CoursePlatformPair.id)).all()
    paired={package_id:pair.id for pair in pairs for package_id in pair.xhs_history}
    items=[]
    for row in rows:
        if not source_allowed(row) and row.id not in paired: continue
        s=row.source_snapshot
        items.append({'package_id':row.id,'file_id':row.file_id,'platform_pair_id':paired.get(row.id),'title':s['filename'],'university':s['university'],'course_code':s['course_code'],
            'term':s['term'],'material_type':s['material_type'],'page_count':s['page_count'],
            'preview_pages':[im['page'] for im in row.images],'image_count':len(row.images),'brand_name':s['preview_brand']['name'],
            'source_stale':source_stale(db,row,user,settings),'source_status':row.status,'sha256':s['sha256']})
    return {'items':items}


@router.get('/drafts')
def list_drafts(user:User=Depends(get_current_user),connector=Depends(get_xianyu_connector)):
    return connector.request('GET','/bridge/drafts',user.id)


def product_copy(item):
    copy=independent_product_copy(item.source_snapshot,item.page_texts)
    return copy['title'],copy['description']


@router.post('/drafts/from-material')
def create_from_material(payload:CreateFromMaterial,user:User=Depends(get_current_user),db:Session=Depends(get_db),settings=Depends(require_library),connector=Depends(get_xianyu_connector)):
    if payload.brand_id!='xingtu': raise HTTPException(422,'本轮品牌为星途留学，不能更换原样张品牌')
    if user.id!=connector.config['owner_user_id']: raise HTTPException(403,'当前用户尚未配置闲鱼工作台')
    item=package_owned(db,user,payload.package_id)
    if not source_allowed(item): raise HTTPException(422,'请选择星途留学的 MKTG1501 新版 PDF 样张')
    brand=saved_brand(item.source_snapshot['preview_brand'])
    if brand['id']!=payload.brand_id: raise HTTPException(409,'资料品牌与所选品牌不一致')
    if not 1<=len(item.images)<=9: raise HTTPException(422,'闲鱼商品草稿须使用 1 至 9 张样张')
    file,root,revision,fd=stable_source(db,user,settings,item.file_id,item.revision_id)
    try:
        images=[]
        allowed_root=(settings.storage_dir/'course-library-drafts'/str(user.id)).resolve()
        for im in item.images:
            path=(settings.storage_dir/im['path']).resolve()
            if not path.is_relative_to(allowed_root) or not path.is_file(): raise HTTPException(409,'来源样张当前不可读取')
            content=path.read_bytes()
            if hashlib.sha256(content).hexdigest()!=im['sha256']: raise HTTPException(409,'来源样张已变化，未替换旧稿')
            uploaded=connector.request('PUT','/bridge/assets/'+im['sha256'],user.id,content=content)
            if uploaded['sha256']!=im['sha256'] or any(uploaded[k]!=im[k] for k in ['width','height']): raise HTTPException(409,'样张接入校验未通过')
            images.append({k:im[k] for k in ['page','sha256','width','height']})
        unchanged(file,root,fd)
        db.refresh(file)
        if file.current_revision_id!=item.revision_id: raise HTTPException(409,'原资料版本已变化，请刷新后再创建')
        title,description=product_copy(item)
        s=item.source_snapshot
        source={k:s[k] for k in ['filename','university','course_code','term','material_type','sha256','page_count','revision_id']}
        source.update(package_id=item.id,file_id=item.file_id,preview_layout=s['preview_layout'],
                      preview_brand=s['preview_brand'],source_status=item.status)
        return connector.request('POST','/bridge/drafts',user.id,payload={'request_key':str(payload.request_key),
            'brand_id':payload.brand_id,'account_id':payload.account_id,'title':title,'description':description,
            'price':None,'source':source,'images':images,'delivery_note':'电子资料；交付方式待人工确认，当前未启用发货。'})
    finally: os.close(fd)


@router.get('/drafts/{draft_id}')
def read_draft(draft_id:int,user:User=Depends(get_current_user),connector=Depends(get_xianyu_connector)):
    return connector.request('GET',f'/bridge/drafts/{draft_id}',user.id)


@router.patch('/drafts/{draft_id}')
def edit_draft(draft_id:int,payload:EditDraft,user:User=Depends(get_current_user),connector=Depends(get_xianyu_connector)):
    if any(w in payload.title+payload.description for w in ['代写','包过','保分','可提交成品','原题答案','直接答案']):
        raise HTTPException(422,'请保留学习支持用途，删除代写、成绩保证或可提交答案等表述')
    return connector.request('PATCH',f'/bridge/drafts/{draft_id}',user.id,payload=payload.model_dump())


@router.get('/drafts/{draft_id}/images/{index}')
def image(draft_id:int,index:int,user:User=Depends(get_current_user),connector=Depends(get_xianyu_connector)):
    if draft_id<1 or index<0 or index>=9: raise HTTPException(404,'样张不存在')
    content=connector.request('GET',f'/bridge/drafts/{draft_id}/images/{index}',user.id,binary=True)
    return Response(content,media_type='image/png',headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})


@router.get('/drafts/{draft_id}/publish-state')
def publish_state(draft_id:int,user:User=Depends(get_current_user),connector=Depends(get_xianyu_connector)):
    return connector.request('GET',f'/bridge/drafts/{draft_id}/publish-state',user.id)


@router.post('/drafts/{draft_id}/publish-source')
def publish_source(draft_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db),settings=Depends(require_library),connector=Depends(get_xianyu_connector)):
    from backend.app.services.xianyu_publish_source import prepare_publish_source
    return prepare_publish_source(draft_id,user,db,settings,connector)


@router.post('/drafts/{draft_id}/publish-options')
def publish_options(draft_id:int,payload:PublishOptions,user:User=Depends(get_current_user),connector=Depends(get_xianyu_connector)):
    return connector.request('POST',f'/bridge/drafts/{draft_id}/publish-options',user.id,payload=payload.model_dump(mode='json'))


@router.post('/publish-locations')
def publish_locations(payload:PublishLocation,user:User=Depends(get_current_user),connector=Depends(get_xianyu_connector)):
    return connector.request('POST','/bridge/publish-locations',user.id,payload=payload.model_dump())


@router.post('/drafts/{draft_id}/publish-preview')
def publish_preview(draft_id:int,payload:PublishPreview,user:User=Depends(get_current_user),connector=Depends(get_xianyu_connector)):
    return connector.request('POST',f'/bridge/drafts/{draft_id}/publish-preview',user.id,payload=payload.model_dump(mode='json'))


@router.post('/drafts/{draft_id}/publish')
def publish_one(draft_id:int,payload:PublishOne,user:User=Depends(get_current_user),connector=Depends(get_xianyu_connector)):
    return connector.request('POST',f'/bridge/drafts/{draft_id}/publish',user.id,payload=payload.model_dump(mode='json'))


@router.get('/publications/{job_id}')
def publication(job_id:UUID,user:User=Depends(get_current_user),connector=Depends(get_xianyu_connector)):
    return connector.request('GET',f'/bridge/publications/{job_id}',user.id)


@router.post('/publications/{job_id}/reconcile')
def reconcile_publication(job_id:UUID,payload:ReconcilePublication,user:User=Depends(get_current_user),connector=Depends(get_xianyu_connector)):
    return connector.request('POST',f'/bridge/publications/{job_id}/reconcile',user.id,payload=payload.model_dump())
