"""Local course drafts with an explicit, single-item human publication flow.

Upstream websocket, scheduler, chat and fulfilment routers are not imported.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import quote_plus, urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from loguru import logger
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator
from redis.asyncio import Redis
from sqlalchemy import (Column, DateTime, Integer, JSON, MetaData, Numeric,
                        String, Table, Text, UniqueConstraint, insert, select, text, update)
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.exc import IntegrityError

from app.services.qr_login import manager as qr_module
from common.models.user import User
from common.models.xy_account import XYAccount
from common.models.product_material import ProductMaterial

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT/'private/config.json').read_text())
ASSETS = ROOT/'data/assets'
fernet = Fernet(CONFIG['fernet_key'].encode())
engine = create_async_engine(
    'mysql+asyncmy://spider_xianyu:'+quote_plus(CONFIG['mysql_password'])+'@127.0.0.1:33079/spider_xianyu',
    pool_size=3, max_overflow=2, pool_pre_ping=True, echo=False)
redis = Redis(host='127.0.0.1', port=16379, password=CONFIG['redis_password'], decode_responses=True)
meta = MetaData()
drafts = Table('xy_spider_product_drafts', meta,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('owner_id', Integer, nullable=False),
    Column('request_key', String(36), nullable=False),
    Column('request_digest', String(64), nullable=False),
    Column('account_id', String(80)), Column('brand_id', String(30), nullable=False),
    Column('title', String(200), nullable=False), Column('description', Text, nullable=False),
    Column('price', Numeric(12,2)), Column('delivery_note', String(500), nullable=False),
    Column('source', JSON, nullable=False), Column('images', JSON, nullable=False),
    Column('row_version', Integer, nullable=False, default=1),
    Column('created_at', DateTime, nullable=False), Column('updated_at', DateTime, nullable=False),
    UniqueConstraint('owner_id','request_key',name='uq_spider_draft_request'))
versions = Table('xy_spider_product_draft_versions', meta,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('draft_id', Integer, nullable=False), Column('row_version', Integer, nullable=False),
    Column('snapshot', JSON, nullable=False), Column('created_at', DateTime, nullable=False),
    UniqueConstraint('draft_id','row_version',name='uq_spider_draft_version'))
credentials = Table('xy_spider_credential_versions', meta,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('account_id', String(80), nullable=False), Column('ciphertext', Text, nullable=False),
    Column('created_at', DateTime, nullable=False))
qr = qr_module.qr_login_manager
qr_lock = asyncio.Lock()
draft_create_lock = asyncio.Lock()
ready = False
# Upstream QR diagnostics may include session URLs/response bodies. Do not log them.
logger.disable('app')


async def manual_verification(manager, session_id, url):
    """Keep the official challenge for its owner; do not automate a challenge."""
    session = manager.sessions.get(session_id)
    if session: session.status = 'verification_required'


qr_module.run_face_verification = manual_verification


def now(): return datetime.now(ZoneInfo('Asia/Shanghai')).replace(tzinfo=None)


@asynccontextmanager
async def lifespan(app):
    global ready
    async with engine.begin() as conn:
        for table in [User.__table__, XYAccount.__table__, ProductMaterial.__table__]:
            await conn.run_sync(lambda sync, t=table: t.create(sync, checkfirst=True))
        await conn.run_sync(meta.create_all)
        owner = (await conn.execute(select(User.__table__.c.id).where(User.__table__.c.id==CONFIG['owner_user_id']))).first()
        if not owner:
            await conn.execute(insert(User.__table__).values(id=CONFIG['owner_user_id'], username='spider_local',
                email='spider-local@localhost.invalid', password_hash='!disabled-interactive-login',
                status='ACTIVE', role='MEMBER', account_limit=1))
    await redis.ping()
    await manual_publish.recover()
    ready = True
    try: yield
    finally:
        ready = False
        await manual_publish.shutdown()
        qr.sessions.clear()
        await redis.aclose()
        await engine.dispose()


app = FastAPI(title='闲鱼课程商品草稿服务', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware('http')
async def restrict_surface(request, call_next):
    # All unknown upstream APIs fail closed, including direct calls to publish,
    # chat, account enablement, fulfilment, Cookie export and task routes.
    if request.url.path not in {'/','/health'} and not request.url.path.startswith('/bridge/'):
        return JSONResponse({'detail':'本安装仅开放账号、草稿和人工确认发布；消息发送与发货未启用'}, status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


def authorized(authorization: str = Header(default=''), x_spider_user: str = Header(default='')):
    if not secrets.compare_digest(authorization, 'Bearer '+CONFIG['bridge_token']):
        raise HTTPException(401, '连接凭据无效')
    if x_spider_user != str(CONFIG['owner_user_id']): raise HTTPException(403, '未为此用户配置闲鱼连接')
    return CONFIG['owner_user_id']


@app.get('/')
def home():
    return HTMLResponse('''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>闲鱼课程商品草稿服务</title><body style="font:17px system-ui;max-width:640px;margin:12vh auto;padding:24px;color:#172f47"><h1>闲鱼课程商品草稿服务</h1><p>独立服务已启动。当前开放账号扫码绑定、课程商品草稿与人工发布预览。</p><p>发布须在工作台核对预览并人工确认；自动回复、发货和定时任务均未启用。</p><p><a href="http://127.0.0.1:8000/platforms/xianyu/dashboard">进入 Spider 闲鱼工作台 →</a></p><p style="font-size:13px;color:#64748b">基于 zhinianboke/xianyu-auto-reply · AGPL-3.0<br>上游源码与本地扩展保存在本安装目录。</p></body></html>''')


@app.get('/health')
async def health():
    try:
        async with engine.connect() as conn: await conn.execute(text('SELECT 1'))
        await redis.ping()
        ok = ready
    except Exception: ok = False
    enabled=manual_publish.enabled()
    return {'ready':ok,'service':'xianyu-course-workbench','mode':'manual_publish' if enabled else 'draft_only',
            'publishing_enabled':enabled,'manual_publish_enabled':enabled,'shipping_enabled':False,'auto_reply_enabled':False,
            'scheduler_running':False,'websocket_running':False,'upstream_ref':CONFIG['upstream_ref']}


def account_public(row):
    return {'account_id':row['account_id'],'display_name':row['display_name'] or ('闲鱼账号 · '+row['account_id'][-4:]),
            'brand_id':'xingtu','login_confirmed_at':row['last_login_at'].isoformat() if row['last_login_at'] else None,
            'connection_status':'manual_publish' if manual_publish.enabled() else 'draft_only','automation_enabled':False}


@app.get('/bridge/accounts')
async def accounts(owner=Depends(authorized)):
    async with engine.connect() as conn:
        rows = (await conn.execute(select(XYAccount.__table__).where(XYAccount.__table__.c.owner_id==owner))).mappings().all()
    return {'items':[account_public(r) for r in rows]}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class LoginRequest(StrictModel):
    brand_id: str = 'xingtu'


@app.post('/bridge/login')
async def start_login(payload: LoginRequest, owner=Depends(authorized)):
    if payload.brand_id != 'xingtu': raise HTTPException(422,'本轮账号绑定的品牌为星途留学')
    async with qr_lock:
        qr.cleanup_expired_sessions()
        previous = await redis.get('spider:active-login:'+str(owner))
        if previous:
            previous_session = qr.sessions.get(previous)
            if previous_session and not previous_session.is_expired() and previous_session.status in {'waiting','scanned'}:
                return {'session_id':previous, 'status':previous_session.status,'qr_code_url':previous_session.qr_code_url}
        result = await qr.generate_qr_code()
        if not result.get('success'): raise HTTPException(502,'闲鱼登录二维码暂未获取成功，请稍后手动重试')
        sid = result['session_id']
        await redis.set('spider:login:'+sid, json.dumps({'owner':owner,'brand_id':payload.brand_id}), ex=900)
        await redis.set('spider:active-login:'+str(owner), sid, ex=300)
        return {'session_id':sid, 'qr_code_url':result['qr_code_url'],'status':'waiting'}


def official_verification_url(value):
    p = urlsplit(value or '')
    if p.scheme=='https' and not p.username and p.hostname and any(p.hostname==h or p.hostname.endswith('.'+h) for h in ['goofish.com','taobao.com','alipay.com']): return value
    return None


@app.get('/bridge/login/{session_id}')
async def login_status(session_id: UUID, owner=Depends(authorized)):
    sid = str(session_id)
    saved = await redis.get('spider:login:'+sid)
    if not saved or json.loads(saved)['owner'] != owner: raise HTTPException(404,'登录会话不存在或已过期')
    previous = await redis.get('spider:login-done:'+sid)
    if previous: return json.loads(previous)
    async with qr_lock:
        previous = await redis.get('spider:login-done:'+sid)
        if previous: return json.loads(previous)
        status = qr.get_session_status(sid)
        if status['status']=='success':
            unb = str(status.get('unb') or '')
            cookie = status.get('cookies') or ''
            if not re.fullmatch(r'\d{1,64}',unb) or not cookie:
                raise HTTPException(409,'扫码已确认，但未取得完整账号身份；请重新扫码')
            sealed = 'fernet-v1:'+fernet.encrypt(cookie.encode()).decode()
            async with engine.begin() as conn:
                all_rows = (await conn.execute(select(XYAccount.__table__).where(XYAccount.__table__.c.owner_id==owner).with_for_update())).mappings().all()
                if any(r['account_id']!=unb for r in all_rows): raise HTTPException(409,'本轮已绑定另一账号，请使用原账号重新扫码')
                values = {'cookie':sealed,'unb':unb,'status':'inactive','login_method':'qr_scan',
                          'last_login_at':now(),'auto_confirm':False,'auto_polish':False,
                          'scheduled_redelivery':False,'scheduled_rate':False,'auto_red_flower':False,
                          'disable_reason':'Spider 首轮商品草稿模式',
                          'metadata':{'spider_draft_only':True,'brand_id':'xingtu','credential_storage':'fernet-v1','ai_reply_settings':{'ai_enabled':False}}}
                if all_rows:
                    await conn.execute(update(XYAccount.__table__).where(XYAccount.__table__.c.id==all_rows[0]['id']).values(**values))
                else:
                    await conn.execute(insert(XYAccount.__table__).values(owner_id=owner,account_id=unb,display_name='星途留学闲鱼账号',show_browser=False,**values))
                await conn.execute(insert(credentials).values(account_id=unb,ciphertext=sealed,created_at=now()))
            result = {'status':'success','account_id':unb,'automation_enabled':False,'brand_id':'xingtu'}
            await redis.set('spider:login-done:'+sid,json.dumps(result),ex=900)
            qr.sessions.pop(sid,None)
            return result
        result = {'status':status['status']}
        if status['status']=='verification_required':
            result.update(message='请本人完成闲鱼官方验证；本工具不会代办验证。',verification_url=official_verification_url(status.get('verification_url')))
        return result


SHA = r'^[a-f0-9]{64}$'


@app.put('/bridge/assets/{sha256}')
async def put_asset(sha256: str, request: Request, owner=Depends(authorized)):
    if not re.fullmatch(SHA,sha256): raise HTTPException(422,'图片指纹无效')
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content)>15*1024*1024: raise HTTPException(413,'单张样张不得超过 15 MB')
    if hashlib.sha256(content).hexdigest()!=sha256: raise HTTPException(409,'图片指纹不一致')
    try:
        with Image.open(io.BytesIO(content)) as im:
            if im.format!='PNG' or im.width*im.height>30_000_000: raise ValueError()
            width,height=im.size; im.verify()
    except Exception: raise HTTPException(422,'需要有效的 PNG 样张')
    folder=ASSETS/str(owner);folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    target=folder/(sha256+'.png')
    if not target.exists():
        with target.open('xb') as f: f.write(content)
        target.chmod(0o600)
    elif hashlib.sha256(target.read_bytes()).hexdigest()!=sha256: raise HTTPException(409,'已有图片校验失败')
    return {'sha256':sha256,'width':width,'height':height}


class DraftImage(StrictModel):
    sha256: str = Field(pattern=SHA)
    page: int = Field(ge=1,le=10000)
    width: int = Field(gt=0,le=20000)
    height: int = Field(gt=0,le=20000)


class DraftCreate(StrictModel):
    request_key: UUID
    brand_id: str
    title: str = Field(min_length=1,max_length=200)
    description: str = Field(min_length=1,max_length=1500)
    price: Decimal | None = Field(default=None,gt=0,max_digits=12,decimal_places=2)
    account_id: str | None = Field(default=None,max_length=80)
    delivery_note: str = Field(default='电子资料，具体交付方式待人工确认。',max_length=500)
    source: dict
    images: list[DraftImage] = Field(min_length=1,max_length=9)

    @field_validator('title','description')
    @classmethod
    def non_blank(cls,v):
        if not v.strip(): raise ValueError('内容不能为空')
        return v.strip()


class DraftUpdate(StrictModel):
    row_version: int = Field(ge=1)
    title: str = Field(min_length=1,max_length=200)
    description: str = Field(min_length=1,max_length=1500)
    price: Decimal | None = Field(default=None,gt=0,max_digits=12,decimal_places=2)
    account_id: str | None = Field(default=None,max_length=80)
    delivery_note: str = Field(max_length=500)


def serialize(row):
    d=dict(row)
    d.pop('request_digest',None);d.pop('owner_id',None)
    d['price']=str(d['price']) if d['price'] is not None else None
    for k in ['created_at','updated_at']: d[k]=d[k].isoformat()
    return {**d,'status':'draft','published':False,'shipping_enabled':False,'review_required':True}


async def check_account(conn, owner, account_id,brand_id='xingtu'):
    if not account_id: return
    if brand_id!='xingtu':raise HTTPException(422,'当前绑定的是星途留学账号，请先配置对应品牌账号；草稿可以不关联账号保存')
    r=(await conn.execute(select(XYAccount.__table__.c.id).where(XYAccount.__table__.c.owner_id==owner,XYAccount.__table__.c.account_id==account_id))).first()
    if not r: raise HTTPException(422,'请先绑定这个闲鱼账号')


@app.get('/bridge/drafts')
async def list_drafts(owner=Depends(authorized)):
    async with engine.connect() as conn:
        rows=(await conn.execute(select(drafts).where(drafts.c.owner_id==owner).order_by(drafts.c.id.desc()).limit(100))).mappings().all()
    return {'items':[await manual_publish.decorate(serialize(r),owner) for r in rows]}


@app.post('/bridge/drafts')
async def create_draft(payload:DraftCreate,owner=Depends(authorized)):
    # This deployment has one API process; serialize initial insertion so retrying
    # an interrupted create cannot race the original request into a duplicate.
    async with draft_create_lock:
        return await _create_draft(payload,owner)


async def _create_draft(payload,owner):
    if payload.source.get('origin')=='spider-pdf-dual':
        if payload.brand_id not in {'xingtu','wenguo'} or payload.source.get('preview_brand',{}).get('id')!=payload.brand_id:
            raise HTTPException(422,'双平台稿的品牌与样张未匹配')
        if not all(isinstance(payload.source.get(k),int) and payload.source[k]>0 for k in ['file_id','revision_id','platform_pair_id','platform_pair_version']):
            raise HTTPException(422,'双平台稿缺少已核对的资料来源')
    else:
        if payload.brand_id!='xingtu': raise HTTPException(422,'本轮商品品牌为星途留学')
        if payload.source.get('course_code')!='MKTG1501' or payload.source.get('university')!='昆士兰大学':
            raise HTTPException(422,'首轮范围为昆士兰大学 MKTG1501')
    if not re.fullmatch(SHA,str(payload.source.get('sha256',''))): raise HTTPException(422,'缺少原资料指纹')
    if len({im.page for im in payload.images})!=len(payload.images): raise HTTPException(422,'样张页码不可重复')
    for im in payload.images:
        path=ASSETS/str(owner)/(im.sha256+'.png')
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=im.sha256:
            raise HTTPException(409,'样张尚未完整接入，请重试创建草稿')
    body=payload.model_dump(mode='json')
    digest=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    async with engine.begin() as conn:
        previous=(await conn.execute(select(drafts).where(drafts.c.owner_id==owner,drafts.c.request_key==str(payload.request_key)))).mappings().first()
        if previous:
            if previous['request_digest']!=digest: raise HTTPException(409,'重复请求与原草稿内容不一致')
            return serialize(previous)
        await check_account(conn,owner,payload.account_id,payload.brand_id)
        result=await conn.execute(insert(drafts).values(owner_id=owner,request_digest=digest,row_version=1,created_at=now(),updated_at=now(),**body))
        row=(await conn.execute(select(drafts).where(drafts.c.id==result.inserted_primary_key[0]))).mappings().one()
        public=serialize(row)
        await conn.execute(insert(versions).values(draft_id=row['id'],row_version=1,snapshot=public,created_at=now()))
    return public


@app.get('/bridge/drafts/{draft_id}')
async def read_draft(draft_id:int,owner=Depends(authorized)):
    async with engine.connect() as conn:
        row=(await conn.execute(select(drafts).where(drafts.c.id==draft_id,drafts.c.owner_id==owner))).mappings().first()
    if not row: raise HTTPException(404,'商品草稿不存在')
    return await manual_publish.decorate(serialize(row),owner)


@app.patch('/bridge/drafts/{draft_id}')
async def edit_draft(draft_id:int,payload:DraftUpdate,owner=Depends(authorized)):
    if not payload.title.strip() or not payload.description.strip(): raise HTTPException(422,'标题和商品描述不能为空')
    async with engine.begin() as conn:
        row=(await conn.execute(select(drafts).where(drafts.c.id==draft_id,drafts.c.owner_id==owner).with_for_update())).mappings().first()
        if not row: raise HTTPException(404,'商品草稿不存在')
        if row['row_version']!=payload.row_version: raise HTTPException(409,'草稿已更新，请刷新后继续编辑')
        await manual_publish.assert_editable(draft_id,owner,conn)
        await check_account(conn,owner,payload.account_id,row['brand_id'])
        values=payload.model_dump(mode='json');values['row_version']+=1
        await conn.execute(update(drafts).where(drafts.c.id==draft_id).values(**values,updated_at=now()))
        row=(await conn.execute(select(drafts).where(drafts.c.id==draft_id))).mappings().one();public=serialize(row)
        await conn.execute(insert(versions).values(draft_id=draft_id,row_version=row['row_version'],snapshot=public,created_at=now()))
    return await manual_publish.decorate(public,owner)


@app.get('/bridge/drafts/{draft_id}/images/{index}')
async def draft_image(draft_id:int,index:int,owner=Depends(authorized)):
    d=await read_draft(draft_id,owner)
    if index<0 or index>=len(d['images']): raise HTTPException(404,'样张不存在')
    sha=d['images'][index]['sha256'];path=ASSETS/str(owner)/(sha+'.png')
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=sha: raise HTTPException(409,'样张校验失败')
    return FileResponse(path,media_type='image/png',filename=f'{d["source"].get("course_code") or "课程资料"}_原PDF第{d["images"][index]["page"]}页.png')


from manual_publish import install
manual_publish=install(app,globals())
