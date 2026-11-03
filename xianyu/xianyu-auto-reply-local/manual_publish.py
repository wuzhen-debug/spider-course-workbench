"""Human-only publication: frozen previews, one submit, persisted receipts.

All platform writes originate in execute(), after an authenticated explicit
confirmation of a still-current preview. Startup and polling never submit.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import re
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from PIL import Image
from sqlalchemy import Column, DateTime, Integer, JSON, String, Text, insert, select, update

from manual_gateway import (GatewayError,GoofishGateway,search_locations,location_is_valid,
    INVALID_MAP_LOCATION,LOCATION_REJECTION_MESSAGE)
from manual_source import SourceBinding,load_source,save_source

ACTIVE={'uploading','submitting','unknown','accepted','succeeded'}
BUSY={'uploading','submitting'}


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')


class OptionsRequest(Strict):
    row_version:int=Field(ge=1)
    previous_options_id:UUID|None=None
    category_index:int|None=Field(default=None,ge=0,le=500)


class LocationRequest(Strict):
    query:str=Field(min_length=1,max_length=60)


class PreviewRequest(Strict):
    row_version:int=Field(ge=1)
    options_id:UUID
    category_index:int=Field(ge=0,le=500)
    attributes:dict[str,list[int]]=Field(default_factory=dict)
    location_id:UUID


class ExecuteRequest(Strict):
    preview_id:UUID
    confirmation:str


class ReconcileRequest(Strict):
    item_id:str|None=Field(default=None,pattern=r'^\d{1,32}$')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def id_from_result(value):
    if isinstance(value,dict):
        for key,current in value.items():
            if key.lower() in {'itemid','item_id','idleitemid'} and re.fullmatch(r'\d{1,32}',str(current)):
                return str(current)
        for current in value.values():
            found=id_from_result(current)
            if found:return found
    elif isinstance(value,list):
        for current in value:
            found=id_from_result(current)
            if found:return found
    return None


def detail_matches(detail,snapshot):
    item=detail.get('itemDO') or detail.get('item') or {}
    seller=detail.get('sellerDO') or {}
    d=snapshot['draft']
    seller_id=str(seller.get('sellerId') or item.get('sellerId') or '')
    title=str(item.get('title') or '')
    description=str(item.get('desc') or item.get('description') or '')
    price=item.get('price')
    if isinstance(price,dict):price=price.get('price') or price.get('value')
    try:price_ok=Decimal(str(price))==Decimal(d['price'])
    except Exception:price_ok=False
    text_ok=title==d['title'] or (not title and description.startswith(d['title']))
    return {'seller_matches':seller_id==d['account_id'],'title_matches':text_ok,'price_matches':price_ok,
            'verified':seller_id==d['account_id'] and text_ok and price_ok}


def install(app,s):
    from sqlalchemy import Table
    meta=s['meta']
    options=Table('xy_spider_publish_options',meta,
        Column('id',String(36),primary_key=True),Column('owner_id',Integer,nullable=False),
        Column('draft_id',Integer,nullable=False),Column('row_version',Integer,nullable=False),
        Column('data',JSON,nullable=False),Column('expires_at',DateTime,nullable=False))
    locations=Table('xy_spider_publish_locations',meta,
        Column('id',String(36),primary_key=True),Column('owner_id',Integer,nullable=False),
        Column('data',JSON,nullable=False),Column('expires_at',DateTime,nullable=False))
    previews=Table('xy_spider_publish_previews',meta,
        Column('id',String(36),primary_key=True),Column('owner_id',Integer,nullable=False),
        Column('draft_id',Integer,nullable=False),Column('row_version',Integer,nullable=False),
        Column('draft_digest',String(64),nullable=False),Column('snapshot',JSON,nullable=False),
        Column('created_at',DateTime,nullable=False),Column('expires_at',DateTime,nullable=False),
        Column('job_id',String(36)))
    jobs=Table('xy_spider_publications',meta,
        Column('id',String(36),primary_key=True),Column('owner_id',Integer,nullable=False),
        Column('draft_id',Integer,nullable=False),Column('draft_version',Integer,nullable=False),
        Column('preview_id',String(36),nullable=False,unique=True),Column('snapshot',JSON,nullable=False),
        Column('state',String(30),nullable=False),Column('message',Text,nullable=False),
        Column('publish_sent',Integer,nullable=False,default=0),Column('upload_count',Integer,nullable=False,default=0),
        Column('item_id',String(32)),Column('verification',JSON),
        Column('created_at',DateTime,nullable=False),Column('updated_at',DateTime,nullable=False))
    router=APIRouter(prefix='/bridge',dependencies=[])

    class Controller:
        Gateway=GoofishGateway
        search=staticmethod(search_locations)
        tasks=None

        def __init__(self):self.tasks=set();self.submit_lock=asyncio.Lock()

        def enabled(self):return s['CONFIG'].get('mode')=='manual_publish'

        def guard(self):
            if not self.enabled():raise HTTPException(403,'手动发布尚未启用，草稿仍保留')

        def location(self,value):
            if not location_is_valid(value):raise HTTPException(422,'所在地需要重新检索并核对到区县，请重新打开发布预览')

        async def draft(self,draft_id,owner,connection=None,lock=False):
            query=select(s['drafts']).where(s['drafts'].c.id==draft_id,s['drafts'].c.owner_id==owner)
            if lock:query=query.with_for_update()
            if connection is not None:row=(await connection.execute(query)).mappings().first()
            else:
                async with s['engine'].connect() as conn:row=(await conn.execute(query)).mappings().first()
            if not row:raise HTTPException(404,'商品草稿不存在')
            return s['serialize'](row)

        def source_file(self,draft):
            if draft['source'].get('origin')=='spider-pdf-dual':
                return load_source(s['ASSETS'].parent/'publish-sources',s['CONFIG']['owner_user_id'],s['CONFIG'],draft)
            if draft['source'].get('course_code')!='MKTG1501' or draft['source'].get('university')!='昆士兰大学' or draft['brand_id']!='xingtu':
                raise HTTPException(422,'这份历史草稿未关联已核对的 PDF，请从双平台稿重新导入；原稿保留')
            if len(draft['images'])!=9:raise HTTPException(422,'本轮商品须使用已审核的九张真实样张')
            source=Path(s['CONFIG'].get('publish_source_pdf') or '')
            if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=draft['source']['sha256']:
                raise HTTPException(409,'原资料当前不可读取或已变化，请先核对样张')
            return source

        def files(self,draft,read=False):
            self.source_file(draft)
            result=[]
            for im in draft['images']:
                if not re.fullmatch(r'[a-f0-9]{64}',im['sha256']):raise HTTPException(409,'样张指纹异常')
                path=s['ASSETS']/str(s['CONFIG']['owner_user_id'])/(im['sha256']+'.png')
                if not path.is_file():raise HTTPException(409,'样张文件缺失，请先核对')
                content=path.read_bytes()
                if hashlib.sha256(content).hexdigest()!=im['sha256']:raise HTTPException(409,'样张已变化，请先核对')
                try:
                    with Image.open(io.BytesIO(content)) as png:
                        if png.format!='PNG' or png.size!=(im['width'],im['height']):raise ValueError()
                        png.verify()
                except Exception:raise HTTPException(409,'样张格式或尺寸校验未通过') from None
                if read:result.append(content)
            return result

        async def gateway(self,draft,owner):
            if not draft['account_id']:raise HTTPException(422,'请先关联闲鱼账号并保存')
            async with s['engine'].connect() as conn:
                row=(await conn.execute(select(s['XYAccount'].__table__).where(
                    s['XYAccount'].__table__.c.owner_id==owner,
                    s['XYAccount'].__table__.c.account_id==draft['account_id']))).mappings().first()
            if not row or not row['cookie'].startswith('fernet-v1:'):raise HTTPException(409,'请重新扫码确认账号')
            try:cookie=s['fernet'].decrypt(row['cookie'].split(':',1)[1].encode()).decode()
            except Exception:raise HTTPException(409,'账号凭据无法读取，请重新扫码') from None
            return self.Gateway(cookie,draft['account_id']),row['cookie']

        async def save_cookie(self,gateway,previous,owner):
            # Do not overwrite a concurrent QR re-login; never change automation flags.
            try:old=s['fernet'].decrypt(previous.split(':',1)[1].encode()).decode()
            except Exception:return
            if gateway.cookie==old:return
            table=s['XYAccount'].__table__
            async with s['engine'].begin() as conn:
                row=(await conn.execute(select(table).where(table.c.owner_id==owner,
                    table.c.account_id==gateway.account_id).with_for_update())).mappings().first()
                if not row or row['cookie']!=previous:return
                sealed='fernet-v1:'+s['fernet'].encrypt(gateway.cookie.encode()).decode()
                await conn.execute(update(table).where(table.c.id==row['id']).values(cookie=sealed))
                await conn.execute(insert(s['credentials']).values(account_id=gateway.account_id,
                    ciphertext=sealed,created_at=s['now']()))

        async def last(self,draft_id,owner,conn=None):
            query=select(jobs).where(jobs.c.owner_id==owner,jobs.c.draft_id==draft_id).order_by(jobs.c.created_at.desc())
            if conn is not None:return (await conn.execute(query)).mappings().first()
            async with s['engine'].connect() as c:return (await c.execute(query)).mappings().first()

        def public(self,row):
            if not row:return None
            return {'id':row['id'],'state':row['state'],'message':row['message'],
                'draft_version':row['draft_version'],'upload_count':row['upload_count'],
                'item_id':row['item_id'],'item_url':'https://www.goofish.com/item?id='+row['item_id'] if row['item_id'] else None,
                'verification':row['verification'],'created_at':row['created_at'].isoformat(),
                'updated_at':row['updated_at'].isoformat()}

        async def assert_editable(self,draft_id,owner,conn):
            row=await self.last(draft_id,owner,conn)
            if row and row['state'] in BUSY:raise HTTPException(409,'本次发布正在处理中，请等结果返回后再编辑')

        async def decorate(self,draft,owner):
            row=await self.last(draft['id'],owner)
            supported=False
            try:self.source_file(draft);supported=True
            except HTTPException:pass
            return {**draft,'published':bool(row and row['state'] in {'accepted','succeeded'}),
                'publication':self.public(row),'publishing_supported':supported}

        async def recover(self):
            async with s['engine'].begin() as conn:
                await conn.execute(update(jobs).where(jobs.c.state.in_(list(BUSY))).values(
                    state='unknown',message='服务曾中断，请先到闲鱼核对结果；不会自动重试发布',updated_at=s['now']()))
                rows=(await conn.execute(select(jobs).where(jobs.c.owner_id==s['CONFIG']['owner_user_id'],
                    jobs.c.state=='unknown',jobs.c.item_id.is_(None)).with_for_update())).mappings().all()
                legacy='闲鱼未完成请求（'+INVALID_MAP_LOCATION+'）'
                for row in rows:
                    previous=row['verification'] or {}
                    if row['message']!=legacy:continue
                    if previous.get('failure_code') and previous.get('outcome')!='rejected':continue
                    audit={**previous,'failure_code':INVALID_MAP_LOCATION,'outcome':'rejected','classification_repair':{
                        'previous_state':row['state'],'previous_message':row['message'],
                        'reason':'Explicit platform location rejection, no item id returned; no retry performed',
                        'at':s['now']().isoformat()}}
                    await conn.execute(update(jobs).where(jobs.c.id==row['id']).values(state='failed',
                        message=LOCATION_REJECTION_MESSAGE,verification=audit,updated_at=s['now']()))

        async def shutdown(self):
            for task in list(self.tasks):task.cancel()
            if self.tasks:await asyncio.gather(*list(self.tasks),return_exceptions=True)

        async def update_job(self,jid,**values):
            async with s['engine'].begin() as conn:
                await conn.execute(update(jobs).where(jobs.c.id==jid).values(**values,updated_at=s['now']()))

        async def verify_job(self,row,gateway):
            try:
                detail=await gateway.detail(row['item_id'])
                verification=detail_matches(detail,row['snapshot'])
                state='succeeded' if verification['verified'] else 'accepted'
                message='发布成功，商品账号、标题和售价已回读核对' if verification['verified'] else '平台已返回商品编号；详情尚未完全核对，请打开链接检查'
                await self.update_job(row['id'],state=state,message=message,verification=verification)
            except GatewayError:
                await self.update_job(row['id'],state='accepted',message='平台已返回商品编号，详情暂未读到；请打开商品链接核对')

        async def run(self,jid):
            sent=False;gateway=None;previous=None;owner=None
            try:
                async with s['engine'].connect() as conn:row=(await conn.execute(select(jobs).where(jobs.c.id==jid))).mappings().one()
                owner=row['owner_id'];snapshot=row['snapshot'];draft=snapshot['draft']
                self.location(snapshot['settings']['location'])
                self.guard();contents=self.files(draft,True)
                current=await self.draft(draft['id'],owner)
                if digest(current)!=snapshot['draft_digest']:raise HTTPException(409,'草稿已改变，本次未提交发布')
                gateway,previous=await self.gateway(draft,owner)
                # Refresh/validate token via a read before any image upload or write.
                capability=await gateway.capability()
                if capability['mode']!=snapshot['capability']['mode'] or capability['commission']!=snapshot['capability']['commission']:
                    raise HTTPException(409,'账号类型或平台费用已变化，请重新查看发布预览')
                images=[]
                for index,content in enumerate(contents):
                    image=await gateway.upload(content,draft['images'][index]['sha256']+'.png')
                    image['major']=index==0;images.append(image)
                    await self.update_job(jid,upload_count=len(images),message=f'已上传 {len(images)}/{len(contents)} 张水印样张，尚未提交商品')
                current=await self.draft(draft['id'],owner)
                if digest(current)!=snapshot['draft_digest']:raise HTTPException(409,'草稿已改变，未提交商品发布')
                self.files(draft)
                await self.update_job(jid,state='submitting',publish_sent=1,message='正在向闲鱼提交这一件商品，请勿重复操作')
                sent=True
                result=await gateway.publish_once(snapshot,images,snapshot['platform_unique_code'])
                item_id=id_from_result(result.get('data') or result)
                if not item_id:raise GatewayError('平台已接受请求，但没有返回可核对的商品编号','MISSING_ITEM_ID',unknown=True)
                await self.update_job(jid,state='accepted',item_id=item_id,message='平台已返回商品编号，正在回读商品详情')
                async with s['engine'].connect() as conn:row=(await conn.execute(select(jobs).where(jobs.c.id==jid))).mappings().one()
                await self.verify_job(row,gateway)
            except asyncio.CancelledError:
                await self.update_job(jid,state='unknown' if sent else 'failed',message='发布流程中断，请先核对平台结果；不会自动重试')
                raise
            except GatewayError as error:
                await self.update_job(jid,state='unknown' if error.unknown else 'failed',message=error.message,
                    verification={**(row['verification'] or {}),'failure_code':error.code,
                        'outcome':'unknown' if error.unknown else 'rejected'})
            except HTTPException as error:
                await self.update_job(jid,state='unknown' if sent else 'failed',message=str(error.detail))
            except Exception:
                await self.update_job(jid,state='unknown' if sent else 'failed',message='发布流程未完成，请核对平台结果；不会自动重试')
            finally:
                if gateway is not None and previous is not None and owner is not None:
                    try:await self.save_cookie(gateway,previous,owner)
                    except Exception:pass

    controller=Controller()
    auth=s['authorized']

    @router.get('/drafts/{draft_id}/publish-state')
    async def publish_state(draft_id:int,owner=Depends(auth)):
        draft=await controller.draft(draft_id,owner)
        async with s['engine'].connect() as conn:
            opt=(await conn.execute(select(options).where(options.c.owner_id==owner,
                options.c.draft_id==draft_id,options.c.row_version==draft['row_version'],options.c.expires_at>s['now']()).order_by(options.c.expires_at.desc()))).mappings().first()
            choices=(await conn.execute(select(locations).where(locations.c.owner_id==owner,locations.c.expires_at>s['now']()))).mappings().all()
        return {'enabled':controller.enabled(),'publication':controller.public(await controller.last(draft_id,owner)),
            'options':{**opt['data'],'id':opt['id']} if opt else None,
            'locations':[{'id':row['id'],**row['data']} for row in choices if location_is_valid(row['data'])],
            'preferred_location_query':s['CONFIG'].get('publish_location_query',''),
            'shipping_enabled':False,'auto_reply_enabled':False}

    @router.put('/drafts/{draft_id}/publish-source')
    async def publish_source(draft_id:int,body:SourceBinding,owner=Depends(auth)):
        controller.guard();draft=await controller.draft(draft_id,owner)
        return save_source(s['ASSETS'].parent/'publish-sources',owner,s['CONFIG'],draft,body)

    @router.post('/drafts/{draft_id}/publish-options')
    async def publish_options(draft_id:int,body:OptionsRequest,owner=Depends(auth)):
        controller.guard();draft=await controller.draft(draft_id,owner)
        if draft['row_version']!=body.row_version:raise HTTPException(409,'草稿已更新，请刷新后再准备发布')
        controller.files(draft)
        gateway,previous=await controller.gateway(draft,owner)
        category=None;cards=None
        if body.previous_options_id:
            async with s['engine'].connect() as conn:old=(await conn.execute(select(options).where(
                options.c.id==str(body.previous_options_id),options.c.owner_id==owner,options.c.draft_id==draft_id,
                options.c.row_version==body.row_version,options.c.expires_at>s['now']()))).mappings().first()
            if not old or body.category_index is None or body.category_index>=len(old['data']['categories']):raise HTTPException(409,'类目选项已过期，请重新读取')
            category=old['data']['categories'][body.category_index];cards=old['data']['cards']
        try:
            capability=await gateway.capability()
            data=await gateway.categories(draft,category,cards)
        except GatewayError as error:raise HTTPException(409,error.message) from None
        except ValueError:raise HTTPException(422,'平台类目未匹配，请重新读取选项') from None
        finally:await controller.save_cookie(gateway,previous,owner)
        data['capability']=capability
        if not data['categories']:raise HTTPException(409,'闲鱼未返回可用类目，请先在官方发布页核对')
        oid=str(uuid4())
        async with s['engine'].begin() as conn:await conn.execute(insert(options).values(id=oid,owner_id=owner,
            draft_id=draft_id,row_version=draft['row_version'],data=data,expires_at=s['now']()+timedelta(minutes=15)))
        return {**data,'id':oid}

    @router.post('/publish-locations')
    async def publish_locations(body:LocationRequest,owner=Depends(auth)):
        controller.guard()
        try:items=await controller.search(body.query.strip())
        except GatewayError as error:raise HTTPException(502,error.message) from None
        result=[]
        async with s['engine'].begin() as conn:
            for item in items[:30]:
                if not location_is_valid(item):continue
                lid=str(uuid4());await conn.execute(insert(locations).values(id=lid,owner_id=owner,
                    data=item,expires_at=s['now']()+timedelta(days=7)));result.append({'id':lid,**item})
        return {'items':result}

    @router.post('/drafts/{draft_id}/publish-preview')
    async def publish_preview(draft_id:int,body:PreviewRequest,owner=Depends(auth)):
        controller.guard();draft=await controller.draft(draft_id,owner);controller.files(draft)
        if draft['row_version']!=body.row_version:raise HTTPException(409,'草稿已更新，请重新打开预览')
        if not draft['price'] or Decimal(draft['price'])<=0:raise HTTPException(422,'请先填写正数售价并保存')
        if not draft['account_id']:raise HTTPException(422,'请先关联闲鱼账号并保存')
        if not draft['title'].strip() or not draft['description'].strip():raise HTTPException(422,'请先填写标题和描述')
        if any(w in draft['title']+draft['description'] for w in ['代写','包过','保分','可提交成品','原题答案','直接答案']):
            raise HTTPException(422,'请保留学习支持用途，删除成绩保证或可提交答案等表述')
        latest=await controller.last(draft_id,owner)
        if latest and latest['state'] in ACTIVE:raise HTTPException(409,'这份草稿已有发布记录，请先查看发布结果，不要重复上架')
        async with s['engine'].connect() as conn:
            opt=(await conn.execute(select(options).where(options.c.id==str(body.options_id),
                options.c.owner_id==owner,options.c.draft_id==draft_id,options.c.row_version==draft['row_version'],
                options.c.expires_at>s['now']()))).mappings().first()
            loc=(await conn.execute(select(locations).where(locations.c.id==str(body.location_id),
                locations.c.owner_id==owner,locations.c.expires_at>s['now']()))).mappings().first()
        if not opt or not loc:raise HTTPException(409,'平台选项或所在地已过期，请重新读取')
        controller.location(loc['data'])
        categories=opt['data']['categories']
        if body.category_index>=len(categories):raise HTTPException(422,'请选择平台返回的类目')
        category=categories[body.category_index]
        # Digital-material categories legitimately have no Taobao category/leaf.
        # Preserve the platform's empty optional fields instead of inventing IDs.
        if not all(category.get(key) for key in ['cat_id','channel_cat_id','cat_name']):
            raise HTTPException(422,'所选类目尚缺平台编号，请重新读取这个类目的属性')
        attributes=[];properties=opt['data']['properties'];known={p['property_id'] for p in properties}
        if set(body.attributes)-known:raise HTTPException(422,'存在未由平台返回的属性')
        for prop in properties:
            indexes=body.attributes.get(prop['property_id'],[])
            if prop['required'] and not indexes:raise HTTPException(422,'请填写平台要求的属性：'+prop['property_name'])
            if not prop.get('multiple') and len(indexes)>1:raise HTTPException(422,'该属性只能选择一项：'+prop['property_name'])
            if len(indexes)!=len(set(indexes)) or any(i<0 or i>=len(prop['options']) for i in indexes):raise HTTPException(422,'属性选项无效')
            attributes.extend(prop['options'][i] for i in indexes)
        settings={'category':category,'attributes':attributes,'location':loc['data'],'shipping_method':'none','quantity':1}
        pid=str(uuid4());snapshot={'draft':draft,'draft_digest':digest(draft),'settings':settings,
            'capability':opt['data']['capability'],'auto_reply_enabled':False,'shipping_enabled':False}
        async with s['engine'].begin() as conn:await conn.execute(insert(previews).values(id=pid,owner_id=owner,
            draft_id=draft_id,row_version=draft['row_version'],draft_digest=digest(draft),snapshot=snapshot,
            created_at=s['now'](),expires_at=s['now']()+timedelta(minutes=15)))
        return {'id':pid,'snapshot':snapshot,'expires_at':(s['now']()+timedelta(minutes=15)).isoformat(),
            'notice':f'点击确认后将向闲鱼上传这 {len(draft["images"])} 张水印样张并发布这一件商品。自动回复与自动发货保持关闭。'}

    @router.post('/drafts/{draft_id}/publish')
    async def publish(draft_id:int,body:ExecuteRequest,owner=Depends(auth)):
        async with controller.submit_lock:
            return await submit(draft_id,body,owner)

    async def submit(draft_id,body,owner):
        controller.guard()
        if body.confirmation!='PUBLISH_THIS_ONE_ITEM':raise HTTPException(422,'请本人核对预览并确认发布这一件商品')
        async with s['engine'].begin() as conn:
            draft=await controller.draft(draft_id,owner,conn,True)
            ticket=(await conn.execute(select(previews).where(previews.c.id==str(body.preview_id),
                previews.c.owner_id==owner,previews.c.draft_id==draft_id).with_for_update())).mappings().first()
            if not ticket:raise HTTPException(404,'发布预览不存在')
            if ticket['job_id']:
                previous=(await conn.execute(select(jobs).where(jobs.c.id==ticket['job_id']))).mappings().one()
                return controller.public(previous)
            if ticket['expires_at']<=s['now']() or ticket['draft_digest']!=digest(draft):raise HTTPException(409,'预览已过期或草稿已改变，请重新核对')
            latest=await controller.last(draft_id,owner,conn)
            if latest and latest['state'] in ACTIVE:raise HTTPException(409,'这份草稿已有发布记录，请先核对结果')
            controller.files(draft)
            controller.location(ticket['snapshot']['settings']['location'])
            snapshot={**ticket['snapshot'],'platform_unique_code':str(int(s['now']().timestamp()*1000))+draft['account_id'][-4:]}
            jid=str(uuid4());await conn.execute(insert(jobs).values(id=jid,owner_id=owner,draft_id=draft_id,
                draft_version=draft['row_version'],preview_id=ticket['id'],snapshot=snapshot,
                state='uploading',message='已收到本人确认，准备上传水印样张',publish_sent=0,upload_count=0,
                created_at=s['now'](),updated_at=s['now']()))
            await conn.execute(update(previews).where(previews.c.id==ticket['id']).values(job_id=jid))
            row=(await conn.execute(select(jobs).where(jobs.c.id==jid))).mappings().one()
        task=asyncio.create_task(controller.run(jid));controller.tasks.add(task);task.add_done_callback(controller.tasks.discard)
        return controller.public(row)

    @router.get('/publications/{job_id}')
    async def publication(job_id:UUID,owner=Depends(auth)):
        async with s['engine'].connect() as conn:row=(await conn.execute(select(jobs).where(jobs.c.id==str(job_id),jobs.c.owner_id==owner))).mappings().first()
        if not row:raise HTTPException(404,'发布记录不存在')
        return controller.public(row)

    @router.post('/publications/{job_id}/reconcile')
    async def reconcile(job_id:UUID,body:ReconcileRequest,owner=Depends(auth)):
        async with s['engine'].connect() as conn:row=(await conn.execute(select(jobs).where(jobs.c.id==str(job_id),jobs.c.owner_id==owner))).mappings().first()
        if not row:raise HTTPException(404,'发布记录不存在')
        if row['state'] in BUSY:raise HTTPException(409,'发布仍在处理中，请稍后查看')
        item_id=body.item_id or row['item_id']
        if not item_id:raise HTTPException(422,'请先在闲鱼核对是否已有商品，并填写对应的商品编号')
        draft=row['snapshot']['draft'];gateway,previous=await controller.gateway(draft,owner)
        try:
            detail=await gateway.detail(item_id);verification=detail_matches(detail,row['snapshot'])
        except GatewayError as error:raise HTTPException(409,error.message) from None
        finally:await controller.save_cookie(gateway,previous,owner)
        if not verification['verified']:raise HTTPException(409,'商品账号、标题或售价未匹配，未标记为发布成功')
        await controller.update_job(row['id'],item_id=item_id,state='succeeded',verification=verification,message='商品详情已回读核对，发布成功')
        return await publication(job_id,owner)

    app.include_router(router)
    controller.tables={'options':options,'locations':locations,'previews':previews,'jobs':jobs}
    return controller
