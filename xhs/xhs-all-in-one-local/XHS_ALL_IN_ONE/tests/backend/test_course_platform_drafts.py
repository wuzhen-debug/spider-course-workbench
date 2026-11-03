"""Two real local PDF samples, independent persistence, no external providers."""
from copy import deepcopy
import hashlib
import io
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from test_course_library import library, add_pdf, scan, first_file, pdf_bytes
from test_course_library_drafts import plan, generate, configure_model
from backend.app.main import app
from backend.app.api import course_platform_drafts as api
from backend.app.api.ai import get_text_ai_client
from backend.app.models import AiDraft, AutoTask, DraftAsset, PublishJob, Task
from backend.app.models.course_library_draft import CourseLibraryDraft
from backend.app.models.course_platform_pair import CoursePlatformPair
from backend.app.services.xianyu_connector import get_xianyu_connector

BASE='/api/course-center/library'


def multipage_pdf(labels):
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',
        f'<< /Type /Pages /Kids [{" ".join(f"{3+i*3} 0 R" for i in range(len(labels)))}] /Count {len(labels)} >>'.encode()]
    for i,label in enumerate(labels):
        font=4+i*3;content=5+i*3;stream=f'BT /F1 24 Tf 60 700 Td ({label}) Tj ET'.encode()
        objects.extend([f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font} 0 R >> >> /Contents {content} 0 R >>'.encode(),
            b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream'])
    data=b'%PDF-1.4\n';offsets=[]
    for n,obj in enumerate(objects,1):offsets.append(len(data));data+=f'{n} 0 obj\n'.encode()+obj+b'\nendobj\n'
    start=len(data);data+=f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode()
    data+=b''.join(f'{o:010} 00000 n \n'.encode() for o in offsets)
    return data+f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()


@pytest.fixture
def paired(library):
    c,h,other,factory,w,s=library
    path=add_pdf(w);path.write_bytes(multipage_pdf(['Elasticity measures price responsiveness.','Demand changes under substitute prices.','Worked example evaluates revenue changes.']))
    scan(w);row=first_file(factory)
    app.dependency_overrides[api.optional_connector]=lambda:None
    yield c,h,other,factory,w,s,path,row
    app.dependency_overrides.pop(api.optional_connector,None)
    app.dependency_overrides.pop(get_xianyu_connector,None)


def create(paired,**changes):
    c,h,_,__,___,____,_____,row=paired
    recipe,prepared=plan(c,h,row,pages=changes.pop('pages',[1,2]))
    body={**recipe,'plan_digest':prepared['plan_digest'],'request_key':str(uuid4()),'external_consent':False,'xianyu_pages':[2,3],**changes}
    response=c.post(f'{BASE}/files/{row.id}/platform-drafts',headers=h,json=body)
    assert response.status_code==200,response.text
    return response.json(),body


def xy_edit(pair,**changes):
    data=pair['xianyu']
    return {**{k:data[k] for k in ['row_version','title','description','price','delivery_note']},'pages':[im['page'] for im in data['images']],**changes}


def test_one_pdf_creates_two_independent_saved_reviews_and_retry_is_idempotent(paired):
    c,h,_,factory,__,s,path,row=paired;before=(path.read_bytes(),path.stat().st_mtime_ns)
    pair,body=create(paired)
    assert pair['xhs']['title']!=pair['xianyu']['title'] and pair['xhs']['body']!=pair['xianyu']['description']
    assert [im['page'] for im in pair['xhs']['images']]==[1,2]
    assert [im['page'] for im in pair['xianyu']['images']]==[2,3]
    assert pair['xianyu']['source']['sha256']==pair['source']['sha256']==hashlib.sha256(before[0]).hexdigest()
    assert 'Demand changes' in pair['xianyu']['description'] and pair['xianyu']['service_draft_id'] is None
    assert 'path' not in pair['xianyu']['images'][0] and pair['xhs']['status']=='pending'
    again=c.post(f'{BASE}/files/{row.id}/platform-drafts',headers=h,json=body)
    assert again.status_code==200 and again.json()['id']==pair['id']
    body['xianyu_pages']=[1]
    assert c.post(f'{BASE}/files/{row.id}/platform-drafts',headers=h,json=body).status_code==409
    assert before==(path.read_bytes(),path.stat().st_mtime_ns)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(CourseLibraryDraft))==1
        assert db.scalar(select(func.count()).select_from(CoursePlatformPair))==1
        for model in [AiDraft,DraftAsset,PublishJob,AutoTask,Task]:assert db.scalar(select(func.count()).select_from(model))==0
    assert c.get(f'{BASE}/files/{row.id}/platform-drafts',headers=h).json()['items'][0]['id']==pair['id']


def test_edit_either_platform_keeps_other_and_immutable_history_and_selection(paired):
    c,h,_,factory,__,s,path,row=paired;pair,_=create(paired);url=f'{BASE}/platform-drafts/{pair["id"]}'
    old_xhs=deepcopy(pair['xhs']);old_xy=deepcopy(pair['xianyu'])
    payload={'package_id':old_xhs['id'],'request_key':str(uuid4()),'title':'ECON1001价格变化怎么看','body':'从真实选页比较需求与价格的变化。','tags':['ECON1001'],'pages':[1,3]}
    response=c.post(url+'/xhs/versions',headers=h,json=payload);assert response.status_code==200,response.text
    changed=response.json();assert changed['xhs']['id']!=old_xhs['id'] and changed['xianyu']==old_xy
    assert changed['xhs_history']==[old_xhs['id'],changed['xhs']['id']]
    assert [im['page'] for im in changed['xhs']['images']]==[1,3]
    assert c.post(url+'/xhs/versions',headers=h,json=payload).json()['xhs']['id']==changed['xhs']['id']
    assert c.get(f'{BASE}/draft-reviews/{old_xhs["id"]}',headers=h).json()==old_xhs
    assert c.patch(f'{BASE}/draft-reviews/{old_xhs["id"]}',headers=h,json={'title':'overwrite','body':'no','tags':[]}).status_code==409
    r=c.patch(url+'/xianyu',headers=h,json=xy_edit(changed,title='悉尼大学 ECON1001 PDF复习资料',description='独立商品介绍，按真实 PDF 样张核对范围。',price='189.00',pages=[3]));assert r.status_code==200,r.text
    saved=r.json();assert saved['xhs']==changed['xhs'] and saved['xianyu']['row_version']==2 and saved['xianyu']['price']=='189.00'
    assert [im['page'] for im in saved['xianyu']['images']]==[3]
    assert c.get(url+'/xianyu/versions/1',headers=h).json()==old_xy
    assert c.get(url,headers=h).json()==saved
    assert c.patch(url+'/xianyu',headers=h,json=xy_edit(changed)).status_code==409
    payload['request_key']=str(uuid4())
    assert c.post(url+'/xhs/versions',headers=h,json=payload).status_code==409


def test_private_pair_history_and_images_and_tamper_checks(paired):
    c,h,other,factory,_,s,__,row=paired;pair,_=create(paired);url=f'{BASE}/platform-drafts/{pair["id"]}'
    for path in [url,url+'/xianyu/versions/1',url+'/xianyu/images/0',f'{BASE}/files/{row.id}/platform-drafts']:
        assert c.get(path).status_code==401 and c.get(path,headers=other).status_code==404
    image=c.get(url+'/xianyu/images/0?version=1',headers=h)
    assert image.status_code==200 and 'no-store' in image.headers['cache-control']
    assert hashlib.sha256(image.content).hexdigest()==pair['xianyu']['images'][0]['sha256']
    assert c.get(url+'/xianyu/images/99',headers=h).status_code==404
    assert c.get(url+'/xianyu/images/0?version=99',headers=h).status_code==404
    with factory() as db:path=s.storage_dir/db.get(CoursePlatformPair,pair['id']).xianyu['images'][0]['path']
    path.write_bytes(b'changed fixture')
    assert c.get(url+'/xianyu/images/0',headers=h).status_code==409


class LocalConnector:
    config={'owner_user_id':1}
    def __init__(self):self.calls=[];self.products={};self.fail_once=False
    def request(self,method,path,owner,**kwargs):
        self.calls.append((method,path,deepcopy(kwargs)))
        if method=='PUT':
            from PIL import Image
            with Image.open(io.BytesIO(kwargs['content'])) as im:return {'sha256':hashlib.sha256(kwargs['content']).hexdigest(),'width':im.width,'height':im.height}
        if method=='POST' and path=='/bridge/drafts':
            data=kwargs['payload'];key=data['request_key'];self.products.setdefault(key,{**data,'id':500+len(self.products),'row_version':1})
            if self.fail_once:self.fail_once=False;raise HTTPException(503,'synthetic lost response after local storage')
            return self.products[key]
        raise AssertionError((method,path))


def test_local_service_export_uses_only_xianyu_copy_and_is_retry_safe(paired):
    c,h,_,__,___,____,_____,row=paired;pair,_=create(paired);url=f'{BASE}/platform-drafts/{pair["id"]}'
    connector=LocalConnector();connector.fail_once=True;app.dependency_overrides[get_xianyu_connector]=lambda:connector
    r=c.post(url+'/xianyu/export',headers=h,json={'row_version':1});assert r.status_code==503
    assert c.get(url,headers=h).json()['xianyu']['row_version']==1
    r=c.post(url+'/xianyu/export',headers=h,json={'row_version':1});assert r.status_code==200,r.text
    saved=r.json();assert saved['xianyu']['service_draft_id']==500 and saved['xianyu']['row_version']==2
    assert len(connector.products)==1 and saved['xhs']==pair['xhs']
    payload=next(iter(connector.products.values()))
    assert payload['description']==pair['xianyu']['description'] and payload['description']!=pair['xhs']['body']
    assert payload['source']['origin']=='spider-pdf-dual' and payload['account_id'] is None
    calls=len(connector.calls)
    assert c.post(url+'/xianyu/export',headers=h,json={'row_version':1}).status_code==200 and len(connector.calls)==calls
    assert c.post(url+'/xianyu/export',headers=h,json={'row_version':2}).status_code==200 and len(connector.calls)==calls
    # Editing the exported local review preserves the old native product and
    # starts a fresh pending review instead of silently syncing the service.
    r=c.patch(url+'/xianyu',headers=h,json=xy_edit(saved,description='New independent product review.'))
    assert r.status_code==200 and r.json()['xianyu']['service_draft_id'] is None and len(connector.calls)==calls
    assert c.get(url+'/xianyu/versions/2',headers=h).json()['service_draft_id']==500
    assert all(path.startswith('/bridge/assets/') or path=='/bridge/drafts' for _,path,_ in connector.calls)


def test_stale_source_blocks_export_before_any_service_writes(paired):
    c,h,_,__,___,____,path,row=paired;pair,_=create(paired);connector=LocalConnector();app.dependency_overrides[get_xianyu_connector]=lambda:connector
    path.write_bytes(pdf_bytes('NEW VERSION'))
    r=c.post(f'{BASE}/platform-drafts/{pair["id"]}/xianyu/export',headers=h,json={'row_version':1})
    assert r.status_code==409 and not connector.calls
    assert c.get(f'{BASE}/platform-drafts/{pair["id"]}',headers=h).json()['xhs']['source_stale']


def test_partial_creation_retry_reuses_xhs_and_existing_adoption_preserves_old(paired,monkeypatch):
    c,h,_,factory,__,___,____,row=paired;original=api.make_xy
    def fail(*args,**kwargs):raise HTTPException(503,'Synthetic interrupted pair creation')
    monkeypatch.setattr(api,'make_xy',fail)
    recipe,prepared=plan(c,h,row,pages=[1]);request={**recipe,'plan_digest':prepared['plan_digest'],'request_key':str(uuid4())}
    url=f'{BASE}/files/{row.id}/platform-drafts'
    assert c.post(url,headers=h,json=request).status_code==503
    with factory() as db:assert db.scalar(select(func.count()).select_from(CourseLibraryDraft))==1
    monkeypatch.setattr(api,'make_xy',original)
    assert c.post(url,headers=h,json=request).status_code==200
    with factory() as db:assert db.scalar(select(func.count()).select_from(CourseLibraryDraft))==1
    result=c.post(url+'/from-existing',headers=h,json={'package_id':1});assert result.status_code==200,result.text
    assert c.post(url+'/from-existing',headers=h,json={'package_id':1}).json()['id']==result.json()['id']
    assert result.json()['xhs']['id']==1 and result.json()['xianyu']['service_draft_id'] is None


def test_validation_bad_pages_missing_ai_consent_and_cross_owner(paired):
    c,h,other,_,__,___,____,row=paired;recipe,p=plan(c,h,row,pages=[1]);body={**recipe,'plan_digest':p['plan_digest'],'request_key':str(uuid4()),'xianyu_pages':[2,2]}
    url=f'{BASE}/files/{row.id}/platform-drafts'
    assert c.post(url,headers=h,json=body).status_code==422
    body['xianyu_pages']=[99]
    assert c.post(url,headers=h,json=body).status_code in {409,422}
    assert c.post(url,headers=other,json={**body,'xianyu_pages':[1]}).status_code==404
    assert c.post(url+'/from-existing',headers=other,json={'package_id':1}).status_code==404


def test_ai_is_called_once_for_xhs_only_with_explicit_disclosure_and_no_repeat(paired):
    c,h,_,factory,__,___,____,row=paired;configure_model(factory);calls=[]
    class AI:
        def generate_note(self,**kwargs):calls.append(kwargs);return {'title':'ECON1001看懂价格弹性','body':'先比较需求量与价格变化，再检查真实样张中的例题。'}
    app.dependency_overrides[get_text_ai_client]=lambda:AI()
    try:
        recipe,p=plan(c,h,row,mode='ai',pages=[1]);url=f'{BASE}/files/{row.id}/platform-drafts'
        body={**recipe,'plan_digest':p['plan_digest'],'request_key':str(uuid4()),'external_consent':False,'xianyu_pages':[3]}
        assert p['model']['destination']=='https://example.invalid/v1'
        assert c.post(url,headers=h,json=body).status_code==422 and calls==[]
        body['external_consent']=True;r=c.post(url,headers=h,json=body);assert r.status_code==200,r.text
        pair=r.json();assert len(calls)==1 and 'price responsiveness' in calls[0]['reference']
        assert 'Worked example' not in calls[0]['reference'] and 'Worked example' in pair['xianyu']['description']
        assert pair['xhs']['body']!=pair['xianyu']['description']
        assert c.post(url,headers=h,json=body).json()['id']==pair['id'] and len(calls)==1
    finally:app.dependency_overrides.pop(get_text_ai_client,None)


def test_adopting_existing_native_draft_is_read_only_and_keeps_approved_copy_price_and_pages(paired):
    c,h,_,factory,__,s,___,row=paired;package,_=generate(c,h,row)
    with factory() as db:image=deepcopy(db.get(CourseLibraryDraft,package['id']).images[0])
    raw=(s.storage_dir/image['path']).read_bytes();calls=[]
    native={'id':42,'row_version':11,'brand_id':'xingtu','source':{**package['source'],'package_id':package['id']},
        'title':'Approved native product','description':'This already authored copy must remain unchanged.','price':'189.00',
        'delivery_note':'Manually confirmed delivery','images':[{k:image[k] for k in ['page','sha256','width','height']}]}
    class ReadOnly:
        def request(self,method,path,*args,**kwargs):
            assert method=='GET';calls.append(path)
            return {'items':[deepcopy(native)]} if path=='/bridge/drafts' else raw
    app.dependency_overrides[api.optional_connector]=lambda:ReadOnly()
    response=c.post(f'{BASE}/files/{row.id}/platform-drafts/from-existing',headers=h,json={'package_id':package['id']})
    assert response.status_code==200,response.text
    pair=response.json();assert pair['xhs']==package and pair['xianyu']['service_draft_id']==42
    assert pair['xianyu']['description']==native['description'] and pair['xianyu']['price']=='189.00'
    assert calls==['/bridge/drafts','/bridge/drafts/42/images/0']
    assert c.get(f'{BASE}/draft-reviews/{package["id"]}',headers=h).json()==package


def test_creations_reopen_paired_records_in_dual_editor(paired):
    c,h,_,__,___,____,_____,row=paired;pair,_=create(paired)
    listing=c.get('/api/course-center/creations',headers=h,params={'file_id':row.id}).json()
    item=next(r for r in listing['items'] if r['id']==f'pdf:{pair["xhs"]["id"]}')
    from urllib.parse import parse_qs,urlsplit
    query=parse_qs(urlsplit(item['primary_url']).query)
    assert query['platform_pair_id']==[str(pair['id'])] and query['dual_drafts']==['1']
    assert 'package_id' not in query and item['primary_label']=='查看两平台稿与历史'
