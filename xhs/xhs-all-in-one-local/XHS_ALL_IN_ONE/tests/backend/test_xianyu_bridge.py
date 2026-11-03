"""Synthetic course, isolated Spider DB, mocked local sidecar; no network calls."""
import hashlib
import io
from uuid import uuid4
from PIL import Image
import pytest
from sqlalchemy import select,func
from backend.app.main import app
from backend.app.models import AiDraft,PublishJob,AutoTask
from backend.app.models.course_library_draft import CourseLibraryDraft
from backend.app.services.xianyu_connector import get_xianyu_connector, XianyuConnector
from test_course_library import library,add_pdf,scan,first_file
from test_course_library_drafts import generate


class FakeConnector:
    config={'owner_user_id':1}
    def __init__(self):self.calls=[]
    def request(self,method,path,owner,*,payload=None,content=None,binary=False):
        from fastapi import HTTPException
        if owner!=1:raise HTTPException(403,'not configured')
        self.calls.append((method,path,owner,payload,content))
        if path.startswith('/bridge/assets/'):
            im=Image.open(io.BytesIO(content));return {'sha256':hashlib.sha256(content).hexdigest(),'width':im.width,'height':im.height}
        if path=='/bridge/drafts':return {'id':1,**(payload or {}),'status':'draft','published':False}
        return {'ready':True,'items':[]}


@pytest.fixture
def bridge(library):
    c,h,other,factory,w,s=library
    path=add_pdf(w,'06昆士兰大学/MKTG1501/期末复习讲义/MKTG1501_26S2_Final.pdf');scan(w);row=first_file(factory)
    package,_=generate(c,h,row)
    connector=FakeConnector();app.dependency_overrides[get_xianyu_connector]=lambda:connector
    yield library,path,package,connector
    app.dependency_overrides.pop(get_xianyu_connector,None)


def request(package):return {'package_id':package['id'],'request_key':str(uuid4()),'brand_id':'xingtu'}


def test_private_sample_copy_to_independent_draft_preserves_originals(bridge):
    (c,h,other,factory,w,s),path,p,bridge=bridge
    before=path.read_bytes()
    listed=c.get('/api/platforms/xianyu/materials',headers=h);assert listed.status_code==200 and len(listed.json()['items'])==1
    r=c.post('/api/platforms/xianyu/drafts/from-material',headers=h,json=request(p));assert r.status_code==200,r.text
    assert r.json()['price'] is None and r.json()['status']=='draft' and not r.json()['published']
    assert [(m,u) for m,u,*_ in bridge.calls]==[('PUT','/bridge/assets/'+p['images'][0]['sha256']),('POST','/bridge/drafts')]
    assert all('path' not in i for i in r.json()['images']) and 'relative_path' not in r.json()['source']
    assert path.read_bytes()==before
    with factory() as db:
        assert db.get(CourseLibraryDraft,p['id']).status=='pending'
        for model in [AiDraft,PublishJob,AutoTask]:assert db.scalar(select(func.count()).select_from(model))==0


def test_auth_ownership_brand_and_no_publish_path(bridge):
    (c,h,other,*_),path,p,connector=bridge;url='/api/platforms/xianyu/drafts/from-material'
    assert c.post(url,json=request(p)).status_code==401
    assert c.post(url,headers=other,json=request(p)).status_code==404
    bad=request(p);bad['brand_id']='wenguo';assert c.post(url,headers=h,json=bad).status_code==422
    # API-only mode returns 404; the optional StaticFiles fallback returns 405.
    assert c.post('/api/platforms/xianyu/publish',headers=h,json={}).status_code in {404,405}
    assert not any(getattr(route, 'path', '') == '/api/platforms/xianyu/publish' for route in c.app.routes)
    assert not connector.calls


def test_changed_source_and_tampered_image_fail_before_draft(bridge):
    (c,h,other,factory,w,s),path,p,connector=bridge
    with factory() as db:im=db.get(CourseLibraryDraft,p['id']).images[0]
    image=s.storage_dir/im['path'];original=image.read_bytes();image.write_bytes(b'TAMPERED')
    url='/api/platforms/xianyu/drafts/from-material'
    assert c.post(url,headers=h,json=request(p)).status_code==409
    image.write_bytes(original);path.write_bytes(b'CHANGED PDF')
    assert c.post(url,headers=h,json=request(p)).status_code==409
    assert not connector.calls


def test_transport_rejects_arbitrary_hosts_and_publish_paths(tmp_path):
    from fastapi import HTTPException
    import json
    p=tmp_path/'config.json';p.write_text(json.dumps({'base_url':'https://example.invalid','owner_user_id':1,'bridge_token':'fixture'}))
    with pytest.raises(HTTPException):XianyuConnector(p)
    p.write_text(json.dumps({'base_url':'http://127.0.0.1:18089','owner_user_id':1,'bridge_token':'fixture'}));bridge=XianyuConnector(p)
    for url in ['/api/v1/external/publish','/bridge/drafts/1/../../publish','//evil.test/health']:
        with pytest.raises(HTTPException):bridge.request('POST',url,1,payload={})


def test_manual_publish_requires_auth_and_frozen_preview_confirmation(bridge):
    (c,h,other,*_),path,p,connector=bridge
    base='/api/platforms/xianyu/drafts/1'
    assert c.get(base+'/publish-state').status_code==401
    assert c.get(base+'/publish-state',headers=other).status_code==403
    ticket=str(uuid4())
    assert c.post(base+'/publish',headers=h,json={'preview_id':ticket,'confirmation':'yes'}).status_code==422
    assert c.post(base+'/publish',headers=h,json={'preview_id':ticket,'confirmation':'PUBLISH_THIS_ONE_ITEM','url':'https://example.invalid'}).status_code==422
    assert not connector.calls
    assert c.post(base+'/publish-options',headers=h,json={'row_version':8}).status_code==200
    assert c.post('/api/platforms/xianyu/publish-locations',headers=h,json={'query':'北京'}).status_code==200
    body={'row_version':8,'options_id':str(uuid4()),'category_index':0,'attributes':{},'location_id':str(uuid4())}
    assert c.post(base+'/publish-preview',headers=h,json=body).status_code==200
    assert not any(call[1].endswith('/publish') for call in connector.calls)
    assert c.post(base+'/publish',headers=h,json={'preview_id':ticket,'confirmation':'PUBLISH_THIS_ONE_ITEM'}).status_code==200
    assert connector.calls[-1][:4]==('POST','/bridge/drafts/1/publish',1,{'preview_id':ticket,'confirmation':'PUBLISH_THIS_ONE_ITEM'})
