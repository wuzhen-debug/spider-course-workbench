"""Only the owned, exported PDF review can register a private preview source."""
from copy import deepcopy
import pytest
from fastapi import HTTPException
from test_course_library import library
from test_course_platform_drafts import paired,create,LocalConnector
from backend.app.main import app
from backend.app.services.xianyu_connector import get_xianyu_connector
from backend.app.models.course_platform_pair import CoursePlatformPair


class BindingConnector(LocalConnector):
    config={'owner_user_id':1,'bridge_token':'synthetic-source-signature-key'}
    def __init__(self):super().__init__();self.native=None;self.bindings=[]
    def request(self,method,path,owner,**kwargs):
        if owner!=self.config['owner_user_id']:raise HTTPException(403,'owner')
        if method=='GET' and path=='/bridge/drafts/500':return deepcopy(self.native)
        if method=='PUT' and path=='/bridge/drafts/500/publish-source':
            self.bindings.append(deepcopy(kwargs['payload']))
            return {'ready':True,'draft_id':500,'source_sha256':kwargs['payload']['sha256']}
        return super().request(method,path,owner,**kwargs)


@pytest.fixture
def exported(paired):
    c,h,other,factory,w,s,path,row=paired;pair,_=create(paired);bridge=BindingConnector()
    app.dependency_overrides[get_xianyu_connector]=lambda:bridge
    response=c.post(f'/api/course-center/library/platform-drafts/{pair["id"]}/xianyu/export',headers=h,json={'row_version':1})
    assert response.status_code==200,response.text
    bridge.native=deepcopy(next(iter(bridge.products.values())));bridge.native['row_version']=4
    yield paired,response.json(),bridge


def test_source_registration_preserves_draft_and_returns_no_private_paths(exported):
    (c,h,_,factory,__,s,path,row),pair,bridge=exported;before=deepcopy(bridge.native)
    r=c.post('/api/platforms/xianyu/drafts/500/publish-source',headers=h,json={});assert r.status_code==200,r.text
    binding=bridge.bindings[0]
    assert binding['file_id']==row.id and binding['row_version']==4 and binding['platform_pair_id']==pair['id']
    assert binding['relative_path']==row.relative_path and binding['sha256']==pair['source']['sha256']
    assert binding['library_root']==str(path.parents[4])  # fixture root / school / level / code / type / PDF
    import hmac,hashlib,json
    expected=hmac.new(bridge.config['bridge_token'].encode(),json.dumps({'owner':1,'draft_id':500,'binding':{k:v for k,v in binding.items() if k!='signature'}},sort_keys=True,ensure_ascii=False).encode(),hashlib.sha256).hexdigest()
    assert binding['signature']==expected
    assert bridge.native==before and 'relative_path' not in r.text and str(path.parent) not in r.text
    assert not any(call[1].endswith('/publish') for call in bridge.calls)


@pytest.mark.parametrize('change',['course','brand','image','file','export_record','pdf'])
def test_mismatch_rejected_before_registering_source(exported,change):
    (c,h,_,factory,__,s,path,row),pair,bridge=exported
    if change=='course':bridge.native['source']['course_code']='WRONG1001'
    elif change=='brand':bridge.native['brand_id']='wenguo'
    elif change=='image':bridge.native['images'][0]['sha256']='f'*64
    elif change=='file':bridge.native['source']['file_id']+=1
    elif change=='pdf':path.write_bytes(b'%PDF-changed fixture')
    else:
        with factory() as db:
            model=db.get(CoursePlatformPair,pair['id']);model.xianyu_history=[v for v in model.xianyu_history if not v.get('service_draft_id')];db.commit()
    r=c.post('/api/platforms/xianyu/drafts/500/publish-source',headers=h,json={})
    assert r.status_code==409,r.text
    assert bridge.bindings==[]


def test_source_registration_owner_and_login_required(exported):
    (c,h,other,*_),pair,bridge=exported;url='/api/platforms/xianyu/drafts/500/publish-source'
    assert c.post(url,json={}).status_code==401
    assert c.post(url,headers=other,json={}).status_code==404
    assert bridge.bindings==[]


def test_transport_allows_only_explicit_local_source_route(tmp_path):
    import json
    from backend.app.services.xianyu_connector import XianyuConnector,ALLOWED
    assert ALLOWED.fullmatch('/bridge/drafts/2/publish-source')
    for path in ['/bridge/drafts/2/publish-source/../../private','/bridge/drafts/no/publish-source','https://evil.invalid/bridge/drafts/2/publish-source']:
        assert not ALLOWED.fullmatch(path)
