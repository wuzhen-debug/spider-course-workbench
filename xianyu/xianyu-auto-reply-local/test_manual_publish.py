"""Publication tests use temporary DB/files and mocked transport exclusively."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import hashlib
import io
import re
from uuid import uuid4

import httpx
from PIL import Image
import pytest
from sqlalchemy import select,update

import draft_service as svc
from manual_gateway import (GatewayError,GoofishGateway,listing_payload,parse_categories,parse_city_location,
    INVALID_MAP_LOCATION,LOCATION_REJECTION_MESSAGE)
from manual_location import verified_location,location_is_valid,LocationError,search_public_locations
from test_draft_service import client,bind

CAP={'mode':'shop','commission':{'commissionTitle':'Synthetic 1.6%','commissionTips':'fixture','percent':'0.016'}}
CAT={'cat_id':'50023914','cat_name':'电子资料','channel_cat_id':'202036301','channel_cat_name':'电子资料','tb_cat_id':'','leaf_id':'','selected':True}
LOC={'label':'北京市 · 东城区（公共城市中心）','dto':{'divisionId':'110101','gps':'39.000000,116.000000','poiId':'SYNTHETIC','poiName':'北京市'},
    'validation':{'version':2,'source':'amap-poi-detail+reverse-geocode','adcode':'110101','poi_id':'SYNTHETIC',
        'poi_district':'东城区','reverse_district':'东城区','poi_location':'116,39'}}


class FakeGateway:
    calls=[];hold=False;failure=None;wrong=False
    def __init__(self,cookie,account_id):self.cookie=cookie;self.account_id=account_id
    async def capability(self):self.calls.append('capability');return deepcopy(CAP)
    async def categories(self,*args):
        return {'categories':[deepcopy(CAT)],'properties':[{'property_id':'p','property_name':'形式','required':True,'multiple':False,
            'options':[{'property_id':'p','property_name':'形式','value_id':'v','value_name':'PDF','properties':'p##形式:v##PDF'}]}],'cards':[],'complete':True}
    async def upload(self,content,name):
        self.calls.append('upload')
        while self.hold:await asyncio.sleep(.01)
        return {'url':'https://img.alicdn.com/fixture.png'}
    async def publish_once(self,snapshot,images,unique_code):
        self.calls.append('publish');assert len(images)==9 and images[0]['major'] and unique_code.isdigit()
        if self.failure:raise self.failure
        return {'data':{'itemId':'123450001'}}
    async def detail(self,item_id):
        self.calls.append('detail')
        return {'itemDO':{'title':'Synthetic MKTG1501','price':'189.00'},'sellerDO':{'sellerId':'wrong' if self.wrong else '123456789'}}


@pytest.fixture
def setup(client,tmp_path,monkeypatch):
    c,h=client
    src=tmp_path/'synthetic.pdf';src.write_bytes(b'%PDF-synthetic source fixture')
    monkeypatch.setitem(svc.CONFIG,'mode','manual_publish');monkeypatch.setitem(svc.CONFIG,'publish_source_pdf',str(src))
    monkeypatch.setattr(svc.manual_publish,'Gateway',FakeGateway)
    monkeypatch.setattr(svc.manual_publish,'submit_lock',asyncio.Lock())
    FakeGateway.calls=[];FakeGateway.hold=False;FakeGateway.failure=None;FakeGateway.wrong=False
    async def search(query):return [deepcopy(LOC)]
    monkeypatch.setattr(svc.manual_publish,'search',search)
    assert bind(client)[0].status_code==200
    images=[]
    for i in range(9):
        b=io.BytesIO();Image.new('RGB',(120,180),(240-i,240,255)).save(b,format='PNG');raw=b.getvalue();sha=hashlib.sha256(raw).hexdigest()
        assert c.put('/bridge/assets/'+sha,headers=h,content=raw).status_code==200
        images.append({'sha256':sha,'page':i+1,'width':120,'height':180})
    payload={'request_key':str(uuid4()),'brand_id':'xingtu','account_id':'123456789','title':'Synthetic MKTG1501',
        'description':'Synthetic learning support','price':'189.00','source':{'university':'昆士兰大学','course_code':'MKTG1501','sha256':hashlib.sha256(src.read_bytes()).hexdigest()},'images':images}
    r=c.post('/bridge/drafts',headers=h,json=payload);assert r.status_code==200,r.text
    d=r.json();base=f'/bridge/drafts/{d["id"]}'
    o=c.post(base+'/publish-options',headers=h,json={'row_version':1});assert o.status_code==200,o.text
    l=c.post('/bridge/publish-locations',headers=h,json={'query':'北京'});assert l.status_code==200,l.text
    preview={'row_version':1,'options_id':o.json()['id'],'category_index':0,'attributes':{'p':[0]},'location_id':l.json()['items'][0]['id']}
    yield c,h,d,base,preview,src
    FakeGateway.hold=False


def freeze(s):
    c,h,d,b,p,src=s;r=c.post(b+'/publish-preview',headers=h,json=p);assert r.status_code==200,r.text;return r.json()


def execute(s,ticket):
    c,h,d,b,p,src=s
    return c.post(b+'/publish',headers=h,json={'preview_id':ticket['id'],'confirmation':'PUBLISH_THIS_ONE_ITEM'})


def drain(c):
    async def finish():
        if svc.manual_publish.tasks:await asyncio.wait_for(asyncio.gather(*list(svc.manual_publish.tasks)),5)
    c.portal.call(finish)


def generic_preview(s,monkeypatch):
    import time
    from manual_source import digest_source,binding_signature
    c,h,legacy,b,p,src=s
    source={**legacy['source'],'origin':'spider-pdf-dual','university':'墨尔本大学','course_code':'ECON10003',
        'file_id':1,'revision_id':2,'platform_pair_id':3,'platform_pair_version':2,'page_count':70,'preview_brand':{'id':'xingtu'}}
    body={'request_key':str(uuid4()),'brand_id':'xingtu','account_id':legacy['account_id'],'title':'Synthetic ECON10003',
        'description':'Synthetic course product','price':'189.00','source':source,'images':legacy['images']}
    response=c.post('/bridge/drafts',headers=h,json=body);assert response.status_code==200,response.text
    draft=response.json();base=f'/bridge/drafts/{draft["id"]}'
    calls=list(FakeGateway.calls)
    blocked=c.post(base+'/publish-options',headers=h,json={'row_version':1})
    assert blocked.status_code==409 and FakeGateway.calls==calls
    binding={'row_version':1,'library_root':str(src.parent),'relative_path':src.name,'source_digest':digest_source(draft),'issued_at':int(time.time()),
        **{k:source[k] for k in ['file_id','revision_id','platform_pair_id','platform_pair_version','sha256']}}
    binding['signature']=binding_signature(svc.CONFIG['bridge_token'],1,draft['id'],binding)
    assert c.put(base+'/publish-source',json=binding).status_code==401
    assert c.put(base+'/publish-source',headers={**h,'X-Spider-User':'2'},json=binding).status_code==403
    response=c.put(base+'/publish-source',headers=h,json=binding);assert response.status_code==200,response.text
    assert FakeGateway.calls==calls and 'library_root' not in response.text
    assert c.get(base,headers=h).json()['publishing_supported']
    options=c.post(base+'/publish-options',headers=h,json={'row_version':1});assert options.status_code==200,options.text
    preview={**p,'options_id':options.json()['id']}
    return c,h,draft,base,preview,src


def test_new_course_preview_checks_registered_pdf_without_uploads_or_submission(setup,monkeypatch):
    s=generic_preview(setup,monkeypatch);ticket=freeze(s)
    assert ticket['snapshot']['draft']['source']['course_code']=='ECON10003'
    assert ticket['snapshot']['draft']['price']=='189.00'
    assert 'publish' not in FakeGateway.calls and 'upload' not in FakeGateway.calls
    assert c_no_jobs(s)
    assert 'library_root' not in str(ticket) and 'relative_path' not in str(ticket)


def c_no_jobs(s):
    c,h,d,b,p,src=s
    return c.get(b+'/publish-state',headers=h).json()['publication'] is None


def test_new_course_source_changed_after_preview_stops_before_any_platform_write(setup,monkeypatch):
    s=generic_preview(setup,monkeypatch);ticket=freeze(s);s[-1].write_bytes(b'%PDF-changed source')
    response=execute(s,ticket)
    assert response.status_code==409,response.text
    assert not any(call in {'publish','upload'} for call in FakeGateway.calls)
    assert c_no_jobs(s)


def test_new_course_still_requires_explicit_confirmation_and_one_submit(setup,monkeypatch):
    s=generic_preview(setup,monkeypatch);c,h,d,b,p,src=s;ticket=freeze(s)
    denied=c.post(b+'/publish',headers=h,json={'preview_id':ticket['id'],'confirmation':'yes'})
    assert denied.status_code==422 and 'upload' not in FakeGateway.calls and 'publish' not in FakeGateway.calls
    result=execute(s,ticket);assert result.status_code==200,result.text;drain(c)
    assert FakeGateway.calls.count('publish')==1 and FakeGateway.calls.count('upload')==9
    assert execute(s,ticket).json()['id']==result.json()['id'] and FakeGateway.calls.count('publish')==1


def test_preview_and_reads_do_not_write_platform(setup):
    c,h,d,b,p,src=setup;t=freeze(setup)
    assert t['snapshot']['settings']['location']==LOC
    assert 'upload' not in FakeGateway.calls and 'publish' not in FakeGateway.calls
    for _ in range(2):assert c.get(b+'/publish-state',headers=h).json()['publication'] is None
    assert c.post(b+'/publish',headers=h,json={'preview_id':t['id'],'confirmation':'yes'}).status_code==422
    assert 'publish' not in FakeGateway.calls
    for key in ['shipping_enabled','auto_reply_enabled','scheduler_running','websocket_running']:assert not c.get('/health').json()[key]


def test_double_click_is_one_submit_and_edits_block_while_busy(setup):
    c,h,d,b,p,src=setup;t=freeze(setup);FakeGateway.hold=True
    with ThreadPoolExecutor(2) as pool:responses=list(pool.map(lambda _:execute(setup,t),range(2)))
    assert all(r.status_code==200 for r in responses)
    assert len({r.json()['id'] for r in responses})==1
    edited={k:d[k] for k in ['row_version','title','description','price','account_id','delivery_note']}
    assert c.patch(b,headers=h,json=edited).status_code==409
    FakeGateway.hold=False;drain(c)
    result=c.get(b+'/publish-state',headers=h).json()['publication']
    assert result['state']=='succeeded' and result['item_url']=='https://www.goofish.com/item?id=123450001'
    assert FakeGateway.calls.count('publish')==1 and FakeGateway.calls.count('upload')==9
    assert execute(setup,t).json()['id']==result['id']
    assert c.post(b+'/publish-preview',headers=h,json=p).status_code==409
    assert c.get(b,headers=h).json()['published']
    async def rows():
        async with svc.engine.connect() as conn:
            return (await conn.execute(select(svc.versions))).mappings().all(),(await conn.execute(select(svc.XYAccount.__table__))).mappings().one()
    history,account=c.portal.call(rows)
    assert len(history)==1 and account['status']=='inactive'
    assert not account['auto_confirm'] and not account['auto_polish'] and not account['scheduled_redelivery']


@pytest.mark.parametrize('change',['draft','expiry','pdf','image'])
def test_preview_cannot_submit_after_change(setup,change):
    c,h,d,b,p,src=setup;t=freeze(setup)
    if change=='draft':
        edit={k:d[k] for k in ['row_version','title','description','price','account_id','delivery_note']};edit['title']+=' changed'
        assert c.patch(b,headers=h,json=edit).status_code==200
    elif change=='expiry':
        async def expire():
            async with svc.engine.begin() as conn:await conn.execute(update(svc.manual_publish.tables['previews']).values(expires_at=svc.now()-timedelta(seconds=1)))
        c.portal.call(expire)
    elif change=='pdf':src.write_bytes(b'changed fixture')
    else:(svc.ASSETS/'1'/(d['images'][0]['sha256']+'.png')).write_bytes(b'changed')
    assert execute(setup,t).status_code==409
    assert FakeGateway.calls.count('publish')==0 and FakeGateway.calls.count('upload')==0


def test_owner_and_platform_options_cannot_be_injected(setup):
    c,h,d,b,p,src=setup
    assert c.post(b+'/publish-preview',headers={**h,'X-Spider-User':'2'},json=p).status_code==403
    assert c.post(b+'/publish-preview',headers=h,json={**p,'location_id':str(uuid4())}).status_code==409
    assert c.post(b+'/publish-preview',headers=h,json={**p,'category_index':500}).status_code==422
    assert c.post(b+'/publish-preview',headers=h,json={**p,'attributes':{}}).status_code==422
    assert c.post(b+'/publish-preview',headers=h,json={**p,'attributes':{'unknown':[0]}}).status_code==422
    assert c.post(b+'/publish-preview',headers=h,json={**p,'attributes':{'p':[9]}}).status_code==422
    t=freeze(setup)
    assert c.post(b+'/publish',headers=h,json={'preview_id':t['id'],'confirmation':'PUBLISH_THIS_ONE_ITEM','url':'https://evil.invalid'}).status_code==422


def test_unknown_result_never_retries_and_needs_verified_receipt(setup):
    c,h,d,b,p,src=setup;t=freeze(setup);FakeGateway.failure=GatewayError('模拟响应中断','NETWORK_ERROR',unknown=True)
    r=execute(setup,t);assert r.status_code==200;drain(c)
    j=c.get(b+'/publish-state',headers=h).json()['publication'];assert j['state']=='unknown' and not j['item_url']
    assert execute(setup,t).json()['id']==j['id'] and FakeGateway.calls.count('publish')==1
    assert c.post(b+'/publish-preview',headers=h,json=p).status_code==409
    FakeGateway.wrong=True
    assert c.post('/bridge/publications/'+j['id']+'/reconcile',headers=h,json={'item_id':'123450001'}).status_code==409
    FakeGateway.wrong=False
    assert c.post('/bridge/publications/'+j['id']+'/reconcile',headers=h,json={'item_id':'123450001'}).json()['state']=='succeeded'
    assert FakeGateway.calls.count('publish')==1


def test_detail_mismatch_is_not_verified_success(setup):
    c,h,d,b,p,src=setup;FakeGateway.wrong=True;execute(setup,freeze(setup));drain(c)
    j=c.get(b+'/publish-state',headers=h).json()['publication']
    assert j['state']=='accepted' and not j['verification']['verified']
    assert j['item_url']


def test_restart_does_not_resume_pending_publication(setup):
    c,h,d,b,p,src=setup;t=freeze(setup)
    async def pending():
        from sqlalchemy import insert
        async with svc.engine.begin() as conn:
            await conn.execute(insert(svc.manual_publish.tables['jobs']).values(id=str(uuid4()),owner_id=1,draft_id=d['id'],draft_version=1,
                preview_id=t['id'],snapshot=t['snapshot'],state='submitting',message='fixture',publish_sent=1,upload_count=9,created_at=svc.now(),updated_at=svc.now()))
        await svc.manual_publish.recover()
    c.portal.call(pending)
    assert c.get(b+'/publish-state',headers=h).json()['publication']['state']=='unknown'
    assert FakeGateway.calls.count('publish')==0


def test_protocol_retains_approved_content_and_disables_services(setup):
    snap=freeze(setup)['snapshot'];images=[{'url':'https://img.alicdn.com/fixture.png'}]*9
    payload=listing_payload(snap,images,'stable')
    assert payload['itemPriceDTO']['priceInCent']=='18900'
    assert payload['itemTextDTO']['title']==snap['draft']['title'] and payload['itemTextDTO']['desc']==snap['draft']['description']
    assert payload['quantity']==1 and payload['itemPostFeeDTO']=={'canFreeShipping':False,'supportFreight':False,'onlyTakeSelf':False}
    assert not any(v.get('enable') for v in payload['userRightsProtocols'])


@pytest.mark.parametrize('failure',['token','timeout'])
def test_transport_never_retries_a_publish_write(monkeypatch,failure):
    count=[];Native=httpx.AsyncClient
    def handler(request):
        count.append(request)
        if failure=='timeout':raise httpx.ReadTimeout('fixture',request=request)
        return httpx.Response(200,json={'ret':['FAIL_SYS_TOKEN_EXOIRED::fixture']})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:Native(**kw,transport=httpx.MockTransport(handler)))
    g=GoofishGateway('unb=123456789; _m_h5_tk=synthetic_1','123456789')
    async def run():
        with pytest.raises(GatewayError) as error:await g._call('mtop.idle.pc.backend.idleitem.publish','1.0',{},seller=True,write=True)
        assert error.value.unknown==(failure=='timeout')
    asyncio.run(run());assert len(count)==1


def test_city_location_preserves_city_scope():
    district={'adcode':'110000','name':'北京市','center':'116.407387,39.904179'}
    station={'id':'station-fixture','name':'北京南站','typecode':'150200','location':'116.378517,39.865246'}
    city={'id':'city-fixture','name':'北京市','typecode':'190102','location':'116.407387,39.904179'}
    assert parse_city_location(district,{'status':'1','pois':[station]}) is None
    result=parse_city_location(district,{'status':'1','pois':[station,city]})
    assert result=={'poi_id':'city-fixture','name':'北京市','location':'116.407387,39.904179','public_city':True}
    assert 'dto' not in result  # A city search code must never become divisionId.


@pytest.mark.parametrize('url',['https://img.alicdn.com/fixture.png','https://evil.invalid/fixture.png'])
def test_upload_uses_real_returned_dimensions_and_fixed_host(monkeypatch,url):
    Native=httpx.AsyncClient;calls=[]
    def handler(request):
        calls.append(request)
        assert request.url.host=='stream-upload.goofish.com' and b'name="file"' in request.content
        filename=re.search(br'filename="([^"]+)"',request.content).group(1)
        assert len(filename)<=32 and filename.endswith(b'.png')
        assert b'\x89PNG\r\n\x1a\n' in request.content
        return httpx.Response(200,json={'success':True,'object':{'url':url,'pix':'60x90'}})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:Native(**kw,transport=httpx.MockTransport(handler)))
    b=io.BytesIO();Image.new('RGB',(120,180),'white').save(b,format='PNG')
    gateway=GoofishGateway('unb=123456789','123456789')
    async def run():
        if 'evil' in url:
            with pytest.raises(GatewayError):await gateway.upload(b.getvalue(),'synthetic.png')
        else:
            image=await gateway.upload(b.getvalue(),'a'*64+'.png');assert (image['widthSize'],image['heightSize'])==(60,90)
    asyncio.run(run());assert len(calls)==1


def test_upload_business_error_keeps_specific_cause_and_never_retries(monkeypatch):
    Native=httpx.AsyncClient;calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json={'total':0,'hasNext':False,'success':False,'status':0,
            'errorCode':'FILE_NAME_LENGTH_IS_OVER_RANGE','message':'文件名称长度过长'})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:Native(**kw,transport=httpx.MockTransport(handler)))
    b=io.BytesIO();Image.new('RGB',(120,180),'white').save(b,format='PNG')
    async def run():
        with pytest.raises(GatewayError) as error:await GoofishGateway('unb=123456789','123456789').upload(b.getvalue(),'a'*64+'.png')
        assert error.value.code=='FILE_NAME_LENGTH_IS_OVER_RANGE'
        assert '文件名过长' in error.value.message and '未提交商品发布' in error.value.message
    asyncio.run(run());assert len(calls)==1
