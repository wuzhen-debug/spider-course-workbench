"""District mapping/rejection regressions: no live upload or publish requests."""
import asyncio
from copy import deepcopy
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import insert,select,update

import draft_service as svc
from manual_gateway import GatewayError,GoofishGateway,INVALID_MAP_LOCATION,LOCATION_REJECTION_MESSAGE
from manual_location import verified_location,location_is_valid,LocationError,search_public_locations
from test_manual_publish import setup,freeze,execute,drain,FakeGateway,LOC
from test_draft_service import client

POI={'id':'B000ABCR66','name':'北京市','adname':'东城区','location':'116.407387,39.904179','typecode':'190102'}
REVERSE={'status':'1','regeocode':{'addressComponent':{'province':'北京市','city':[],'district':'东城区','adcode':'110101'}}}


def test_city_poi_uses_its_real_district_not_province_code():
    result=verified_location(POI['id'],POI,REVERSE,True)
    assert result['dto']=={'divisionId':'110101','gps':'39.904179,116.407387','poiId':POI['id'],'poiName':'北京市'}
    assert result['label']=='北京市 · 东城区（公共城市中心）' and location_is_valid(result)


@pytest.mark.parametrize('change',['province','city','district_mismatch','poi_adcode_mismatch'])
def test_location_metadata_disagreement_fails_closed(change):
    poi=deepcopy(POI);reverse=deepcopy(REVERSE);component=reverse['regeocode']['addressComponent']
    if change=='province':component['adcode']='110000'
    elif change=='city':component['adcode']='110100'
    elif change=='district_mismatch':component['district']='海淀区'
    else:poi['adcode']='110108'
    with pytest.raises(LocationError):verified_location(poi['id'],poi,reverse,True)


def test_mismatched_coordinates_and_unverified_cache_are_rejected():
    assert location_is_valid(LOC)
    changed=deepcopy(LOC);changed['dto']['gps']='116,39'
    assert not location_is_valid(changed)
    legacy={'label':'北京市（城市级）','dto':{'divisionId':'110000','gps':'39.904179,116.407387','poiId':POI['id'],'poiName':'北京市'}}
    assert not location_is_valid(legacy)


def test_city_search_cross_checks_public_poi_and_reverse_geocode(monkeypatch):
    Native=httpx.AsyncClient;paths=[]
    def handler(request):
        assert request.method=='GET' and request.url.host=='restapi.amap.com' and 'Cookie' not in request.headers
        path=request.url.path;paths.append(path)
        if path.endswith('config/district'):data={'status':'1','districts':[{'name':'北京市','level':'province','adcode':'110000','center':POI['location']}]}
        elif path.endswith('place/text'):data={'status':'1','pois':[POI]}
        elif path.endswith('place/detail'):data={'status':'1','pois':[POI]};assert request.url.params['id']==POI['id']
        else:
            assert path.endswith('geocode/regeo') and request.url.params['location']==POI['location'];data=REVERSE
        return httpx.Response(200,json=data)
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:Native(**kw,transport=httpx.MockTransport(handler)))
    result=asyncio.run(search_public_locations('北京'))
    assert len(paths)==4 and result[0]['dto']['divisionId']=='110101' and location_is_valid(result[0])


def test_cached_city_location_cannot_be_previewed_or_selected(setup):
    c,h,d,b,p,src=setup
    async def downgrade():
        table=svc.manual_publish.tables['locations']
        async with svc.engine.begin() as conn:
            await conn.execute(update(table).where(table.c.id==p['location_id']).values(data={'label':'北京市（城市级）',
                'dto':{'divisionId':'110000','gps':'39,116','poiId':'SYNTHETIC','poiName':'北京市'}}))
    c.portal.call(downgrade)
    assert c.get(b+'/publish-state',headers=h).json()['locations']==[]
    assert c.post(b+'/publish-preview',headers=h,json=p).status_code==422
    assert 'upload' not in FakeGateway.calls and 'publish' not in FakeGateway.calls


def test_old_preview_is_blocked_before_any_upload(setup):
    c,h,d,b,p,src=setup;t=freeze(setup)
    async def legacy_ticket():
        table=svc.manual_publish.tables['previews'];snapshot=deepcopy(t['snapshot'])
        snapshot['settings']['location']={'label':'北京市（城市级）','dto':{'divisionId':'110000','gps':'39,116','poiId':'SYNTHETIC','poiName':'北京市'}}
        async with svc.engine.begin() as conn:await conn.execute(update(table).where(table.c.id==t['id']).values(snapshot=snapshot))
    c.portal.call(legacy_ticket)
    assert execute(setup,t).status_code==422
    assert c.get(b+'/publish-state',headers=h).json()['publication'] is None
    assert 'upload' not in FakeGateway.calls and 'publish' not in FakeGateway.calls


@pytest.mark.parametrize('item_reference',[None,{'itemId':'123450001'},{'result':{'item_id':'123450001'}}])
def test_explicit_map_rejection_is_definite_without_item_id(monkeypatch,item_reference):
    Native=httpx.AsyncClient;calls=[]
    def handler(request):
        calls.append(request);return httpx.Response(200,json={'ret':[INVALID_MAP_LOCATION+'::所在地无效'],'data':item_reference or {}})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:Native(**kw,transport=httpx.MockTransport(handler)))
    gateway=GoofishGateway('unb=123456789','123456789')
    async def run():
        with pytest.raises(GatewayError) as error:await gateway._call('mtop.idle.pc.backend.idleitem.publish','1.0',{},seller=True,write=True)
        assert error.value.unknown==bool(item_reference) and error.value.code==INVALID_MAP_LOCATION
        if not item_reference:assert error.value.message==LOCATION_REJECTION_MESSAGE
    asyncio.run(run());assert len(calls)==1


def test_definite_rejection_allows_new_review_but_never_auto_retries(setup):
    c,h,d,b,p,src=setup;FakeGateway.failure=GatewayError(LOCATION_REJECTION_MESSAGE,INVALID_MAP_LOCATION)
    t=freeze(setup);execute(setup,t);drain(c)
    job=c.get(b+'/publish-state',headers=h).json()['publication']
    assert job['state']=='failed' and job['upload_count']==9 and job['verification']['failure_code']==INVALID_MAP_LOCATION
    assert c.post(b+'/publish-preview',headers=h,json=p).status_code==200
    assert execute(setup,t).json()['id']==job['id'] and FakeGateway.calls.count('publish')==1


def test_recovery_repairs_only_known_rejection_and_preserves_original_receipt(setup):
    c,h,d,b,p,src=setup;t=freeze(setup);ids=[str(uuid4()) for _ in range(4)]
    legacy='闲鱼未完成请求（'+INVALID_MAP_LOCATION+'）'
    async def check():
        table=svc.manual_publish.tables['jobs']
        async with svc.engine.begin() as conn:
            for index,jid in enumerate(ids):
                await conn.execute(insert(table).values(id=jid,owner_id=1,draft_id=d['id'],draft_version=1,preview_id=str(uuid4()),
                    snapshot=t['snapshot'],state='unknown',message='网络超时' if index==1 else legacy,
                    publish_sent=1,upload_count=9,item_id='123450001' if index==2 else None,
                    verification={'failure_code':INVALID_MAP_LOCATION,'outcome':'unknown'} if index==3 else None,
                    created_at=svc.now(),updated_at=svc.now()))
        await svc.manual_publish.recover()
        async with svc.engine.connect() as conn:return {r['id']:dict(r) for r in (await conn.execute(select(table))).mappings()}
    rows=c.portal.call(check)
    first=rows[ids[0]]
    assert first['state']=='failed' and first['publish_sent']==1 and first['upload_count']==9
    assert first['snapshot']==t['snapshot'] and first['verification']['classification_repair']['previous_message']==legacy
    assert rows[ids[1]]['state']=='unknown' and rows[ids[2]]['state']=='unknown'
    assert rows[ids[3]]['state']=='unknown'
    assert 'upload' not in FakeGateway.calls and 'publish' not in FakeGateway.calls
