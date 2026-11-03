"""Isolated HTTP/storage tests: temporary SQLite, fake Redis and synthetic QR.

No production DB, real account, platform request, AI or publishing operation.
"""
import hashlib
import io
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import BigInteger, select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.compiler import compiles

import draft_service as svc


@compiles(BigInteger, 'sqlite')
def sqlite_bigint(element, compiler, **kw): return 'INTEGER'


class FakeRedis:
    def __init__(self):self.data={}
    async def get(self,key):return self.data.get(key)
    async def set(self,key,value,ex=None):self.data[key]=value
    async def ping(self):return True
    async def aclose(self):pass


class FakeQR:
    def __init__(self):self.sessions={};self.statuses={};self.generated=0
    def cleanup_expired_sessions(self):pass
    async def generate_qr_code(self):
        self.generated+=1;sid=str(uuid4());self.sessions[sid]=SimpleNamespace(status='waiting',is_expired=lambda:False,qr_code_url='data:image/png;base64,fixture')
        self.statuses[sid]={'status':'waiting'}
        return {'success':True,'session_id':sid,'qr_code_url':'data:image/png;base64,fixture'}
    def get_session_status(self,sid):return self.statuses.get(sid,{'status':'not_found'})


@pytest.fixture
def client(tmp_path,monkeypatch):
    engine=create_async_engine(f'sqlite+aiosqlite:///{tmp_path}/db.sqlite')
    config={**svc.CONFIG,'bridge_token':'isolated-test-token','owner_user_id':1,'mode':'draft_only'}
    monkeypatch.setattr(svc,'CONFIG',config);monkeypatch.setattr(svc,'engine',engine)
    monkeypatch.setattr(svc,'redis',FakeRedis());monkeypatch.setattr(svc,'qr',FakeQR())
    monkeypatch.setattr(svc,'qr_lock',__import__('asyncio').Lock())
    monkeypatch.setattr(svc,'ASSETS',tmp_path/'assets')
    with TestClient(svc.app) as c:yield c,{'Authorization':'Bearer isolated-test-token','X-Spider-User':'1'}


def asset(client,page=1):
    c,h=client;b=io.BytesIO();Image.new('RGB',(120,180),'white').save(b,format='PNG');data=b.getvalue();sha=hashlib.sha256(data).hexdigest()
    r=c.put('/bridge/assets/'+sha,headers=h,content=data);assert r.status_code==200,r.text
    return {'sha256':sha,'page':page,'width':120,'height':180}


def payload(client):
    return {'request_key':str(uuid4()),'brand_id':'xingtu','title':'MKTG1501 TEST','description':'Synthetic local learning support fixture',
        'price':None,'source':{'university':'昆士兰大学','course_code':'MKTG1501','sha256':'a'*64},'images':[asset(client)]}


def bind(client,unb='123456789'):
    c,h=client;r=c.post('/bridge/login',headers=h,json={'brand_id':'xingtu'});assert r.status_code==200
    sid=r.json()['session_id'];svc.qr.statuses[sid]={'status':'success','unb':unb,'cookies':'unb='+unb+'; cookie2=SYNTHETIC-PRIVATE'}
    r=c.get('/bridge/login/'+sid,headers=h);return r,sid


def test_auth_and_dangerous_routes_fail_closed(client):
    c,h=client
    assert c.get('/bridge/accounts').status_code==401
    assert c.get('/bridge/accounts',headers={**h,'X-Spider-User':'2'}).status_code==403
    for path in ['/api/v1/external/publish/single','/api/v1/messages/send','/api/v1/qr-login/cookie/abc','/internal/accounts/a/start','/api/v1/product-publish/publish','/api/v1/auto-delivery','/bridge/publish']:
        r=c.post(path,headers=h,json={});assert r.status_code in {403,404}
    health=c.get('/health').json()
    assert health['ready'] and not any(health[k] for k in ['publishing_enabled','shipping_enabled','auto_reply_enabled','scheduler_running','websocket_running'])


def test_qr_owner_dedup_and_credentials_are_encrypted(client):
    c,h=client
    first=c.post('/bridge/login',headers=h,json={'brand_id':'xingtu'}).json()
    second=c.post('/bridge/login',headers=h,json={'brand_id':'xingtu'}).json()
    assert first==second and svc.qr.generated==1
    assert c.get('/bridge/login/'+first['session_id'],headers={**h,'X-Spider-User':'2'}).status_code==403
    r,sid=bind(client);assert r.status_code==200 and r.json()['status']=='success'
    assert c.get('/bridge/login/'+sid,headers=h).json()==r.json()
    accounts=c.get('/bridge/accounts',headers=h)
    assert 'cookie' not in accounts.text.lower() and 'SYNTHETIC-PRIVATE' not in accounts.text
    async def read():
        async with svc.engine.connect() as conn:
            return (await conn.execute(select(svc.XYAccount.__table__))).mappings().one(),(await conn.execute(select(svc.credentials))).mappings().all()
    row,history=c.portal.call(read)
    assert row['cookie'].startswith('fernet-v1:') and row['status']=='inactive'
    assert 'SYNTHETIC-PRIVATE' not in row['cookie'] and len(history)==1
    assert not row['auto_confirm'] and not row['auto_polish'] and not row['scheduled_redelivery']
    assert svc.fernet.decrypt(row['cookie'].split(':',1)[1].encode()).decode().endswith('SYNTHETIC-PRIVATE')


def test_only_one_account_and_verified_identity(client):
    c,h=client
    assert bind(client)[0].status_code==200
    assert bind(client,'999999999')[0].status_code==409
    assert len(c.get('/bridge/accounts',headers=h).json()['items'])==1


def test_draft_roundtrip_retry_versions_and_account_binding(client):
    c,h=client;p=payload(client)
    r=c.post('/bridge/drafts',headers=h,json=p);assert r.status_code==200,r.text
    d=r.json();assert d['price'] is None and d['review_required'] and not d['published']
    assert c.post('/bridge/drafts',headers=h,json=p).json()['id']==d['id']
    p['title']='changed';assert c.post('/bridge/drafts',headers=h,json=p).status_code==409
    assert c.get(f'/bridge/drafts/{d["id"]}/images/0',headers=h).status_code==200
    assert c.get(f'/bridge/drafts/{d["id"]}/images/0').status_code==401
    assert c.get(f'/bridge/drafts/{d["id"]}/images/9',headers=h).status_code==404
    update={k:d[k] for k in ['row_version','title','description','price','account_id','delivery_note']}
    update['account_id']='123456789'
    assert c.patch(f'/bridge/drafts/{d["id"]}',headers=h,json=update).status_code==422
    assert bind(client)[0].status_code==200
    update['price']='199.00'
    edited=c.patch(f'/bridge/drafts/{d["id"]}',headers=h,json=update);assert edited.status_code==200,edited.text
    assert edited.json()['row_version']==2 and edited.json()['account_id']=='123456789'
    assert c.patch(f'/bridge/drafts/{d["id"]}',headers=h,json=update).status_code==409
    assert c.get('/bridge/drafts',headers=h).json()['items'][0]['id']==d['id']
    async def history():
        async with svc.engine.connect() as conn:return (await conn.execute(select(svc.versions))).mappings().all()
    saved=c.portal.call(history);assert len(saved)==2 and saved[0]['snapshot']['price'] is None


def test_invalid_assets_limits_brand_and_missing_source(client):
    c,h=client
    assert c.put('/bridge/assets/'+'a'*64,headers=h,content=b'not png').status_code==409
    p=payload(client);p['images']*=10
    assert c.post('/bridge/drafts',headers=h,json=p).status_code==422
    p=payload(client);p['brand_id']='wenguo'
    assert c.post('/bridge/drafts',headers=h,json=p).status_code==422
    p=payload(client);p['images'][0]['sha256']='b'*64
    assert c.post('/bridge/drafts',headers=h,json=p).status_code==409
    p=payload(client);p['source']['course_code']='ECON1001'
    assert c.post('/bridge/drafts',headers=h,json=p).status_code==422


def test_manual_verification_url_is_official_only():
    assert svc.official_verification_url('https://passport.goofish.com/verify?a=1')
    for url in ['http://passport.goofish.com/','https://goofish.com.evil.test/','javascript:alert(1)','https://user@passport.goofish.com/']:
        assert svc.official_verification_url(url) is None


def test_dual_platform_other_course_and_brand_can_save_without_expanding_publishing(client):
    c,h=client;p=payload(client)
    p['brand_id']='wenguo';p['title']='ECON1001 local product review'
    p['source'].update(origin='spider-pdf-dual',university='悉尼大学',course_code='ECON1001',
        preview_brand={'id':'wenguo','name':'稳过留学'},file_id=1,revision_id=2,platform_pair_id=3,platform_pair_version=1)
    r=c.post('/bridge/drafts',headers=h,json=p);assert r.status_code==200,r.text
    d=c.get('/bridge/drafts/'+str(r.json()['id']),headers=h).json()
    assert d['brand_id']=='wenguo' and d['account_id'] is None and not d['published'] and not d['publishing_supported']
    assert c.get('/bridge/drafts',headers=h).json()['items'][0]['id']==d['id']
    assert bind(client)[0].status_code==200
    update={k:d[k] for k in ['row_version','title','description','price','account_id','delivery_note']};update['account_id']='123456789'
    assert c.patch('/bridge/drafts/'+str(d['id']),headers=h,json=update).status_code==422
    health=c.get('/health').json();assert not health['auto_reply_enabled'] and not health['shipping_enabled']


def test_dual_platform_requires_matching_brand_and_source_identity(client):
    c,h=client;p=payload(client);p['source'].update(origin='spider-pdf-dual',preview_brand={'id':'wenguo'})
    assert c.post('/bridge/drafts',headers=h,json=p).status_code==422
    p['source']['preview_brand']['id']='xingtu'
    assert c.post('/bridge/drafts',headers=h,json=p).status_code==422
