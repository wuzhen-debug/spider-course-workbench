"""Synthetic PDFs, isolated DB/storage, mocked AI; never publish or call external HTTP."""
import hashlib
import io
from uuid import uuid4
import pytest
from PIL import Image
from sqlalchemy import func, select
from test_course_library import library, add_pdf, scan, first_file, pdf_bytes
from backend.app.main import app
from backend.app.api.ai import get_text_ai_client
from backend.app.core.security import encrypt_text
from backend.app.models import AiDraft, DraftAsset, ModelConfig, PublishJob, AutoTask, Task
from backend.app.models.course_library_draft import CourseLibraryDraft

BASE = '/api/course-center/library'


def setup_pdf(library):
    c,h,other,factory,w,settings=library
    path=add_pdf(w,label='Elasticity measures the responsiveness of quantity to price changes.');scan(w)
    return c,h,other,factory,w,settings,path,first_file(factory)


def plan(c,h,row,**changes):
    recipe={'revision_id':row.current_revision_id,'pages':[1],'mode':'local','instruction':'','brand_id':'xingtu',**changes}
    response=c.post(f'{BASE}/files/{row.id}/draft-plan',headers=h,json=recipe)
    assert response.status_code==200,response.text
    return recipe,response.json()


def generate(c,h,row,**changes):
    recipe,prepared=plan(c,h,row,**changes)
    request={**recipe,'plan_digest':prepared['plan_digest'],'request_key':str(uuid4()),'external_consent':False}
    response=c.post(f'{BASE}/files/{row.id}/drafts',headers=h,json=request)
    assert response.status_code==200,response.text
    return response.json(),request


def count(db,model):return db.scalar(select(func.count()).select_from(model))


def test_local_package_has_real_private_page_and_stays_outside_drafts_and_publishing(library):
    c,h,other,factory,w,s,path,row=setup_pdf(library);before=path.read_bytes();mtime=path.stat().st_mtime_ns
    result,request=generate(c,h,row)
    assert result['status']=='pending' and result['draft_id'] is None and result['publishing_enabled'] is False
    assert 'Elasticity' in result['body'] and result['source']['sha256']==hashlib.sha256(before).hexdigest()
    assert result['pages'][0]['page']==1 and 'responsiveness' in result['pages'][0]['text']
    assert len(result['images'])==1 and 'path' not in result['images'][0]
    url=f'{BASE}/draft-reviews/{result["id"]}/images/0'
    image=c.get(url,headers=h);assert image.status_code==200 and 'no-store' in image.headers['cache-control']
    with Image.open(io.BytesIO(image.content)) as rendered:
        assert rendered.width==1200 and rendered.height>1600 and rendered.getpixel((0,0))==(16,31,56)
        assert rendered.getpixel((0,rendered.height-1))==(255,255,255)  # No blue side/footer frame.
    assert c.get(url).status_code==401 and c.get(url,headers=other).status_code==404
    assert c.get(url.replace('/0','/99'),headers=h).status_code==404
    assert path.read_bytes()==before and path.stat().st_mtime_ns==mtime
    with factory() as db:
        assert count(db,CourseLibraryDraft)==1
        for model in [AiDraft,DraftAsset,PublishJob,AutoTask,Task]:assert count(db,model)==0
    assert c.get(f'{BASE}/files/{row.id}/drafts',headers=h).json()['items'][0]['id']==result['id']


def test_retry_same_request_is_idempotent_and_different_payload_conflicts(library):
    c,h,_,factory,_,s,__,row=setup_pdf(library);result,request=generate(c,h,row)
    images=list((s.storage_dir/'course-library-drafts').rglob('preview-*.png'))
    retry=c.post(f'{BASE}/files/{row.id}/drafts',headers=h,json=request)
    assert retry.status_code==200 and retry.json()['id']==result['id']
    assert list((s.storage_dir/'course-library-drafts').rglob('preview-*.png'))==images
    request['plan_digest']='f'*64
    assert c.post(f'{BASE}/files/{row.id}/drafts',headers=h,json=request).status_code==409


def test_manual_review_creates_one_draft_with_verified_images_and_no_job(library):
    c,h,other,factory,w,s,path,row=setup_pdf(library);result,_=generate(c,h,row);url=f'{BASE}/draft-reviews/{result["id"]}'
    assert c.post(url+'/approve',headers=h,json={'reviewed':False}).status_code==422
    edit={'title':'ECON1001弹性学习样张','body':'先看真实资料样张，比较需求变化与价格变化。','tags':['#ECON1001','悉尼大学','ECON1001']}
    assert c.patch(url,headers=other,json=edit).status_code==404
    edited=c.patch(url,headers=h,json=edit).json();assert edited['tags']==['ECON1001','悉尼大学']
    assert c.post(url+'/approve',headers=h,json={'reviewed':True,'review_digest':result['review_digest']}).status_code==409
    saved=c.post(url+'/approve',headers=h,json={'reviewed':True,'review_digest':edited['review_digest']});assert saved.status_code==200,saved.text
    assert saved.json()['status']=='saved' and saved.json()['reviewed_at'] and saved.json()['draft_id']
    assert saved.json()['draft_available'] and saved.json()['source']['draft_binding']['draft_id']==saved.json()['draft_id']
    assert c.post(url+'/approve',headers=h,json={'reviewed':True}).json()['draft_id']==saved.json()['draft_id']
    assert c.patch(url,headers=h,json=edit).status_code==409
    with factory() as db:
        assert count(db,AiDraft)==1 and count(db,DraftAsset)==1 and count(db,PublishJob)==count(db,AutoTask)==count(db,Task)==0
        draft=db.get(AiDraft,saved.json()['draft_id']);assert draft.body==edit['body']
        assert saved.json()['source']['draft_binding']['draft_created_at']==draft.created_at.isoformat()
        asset=db.scalar(select(DraftAsset));image=s.storage_dir/'media'/asset.local_path
        assert image.is_file() and hashlib.sha256(image.read_bytes()).hexdigest()==result['images'][0]['sha256']


def test_changed_pdf_rejects_old_plan_and_blocks_old_review_approval(library):
    c,h,_,factory,w,s,path,row=setup_pdf(library);result,request=generate(c,h,row)
    recipe,prepared=plan(c,h,row);path.write_bytes(pdf_bytes('NEW CONTENT WITH NEW SIGNATURE'))
    assert c.get(f'{BASE}/draft-reviews/{result["id"]}',headers=h).json()['source_stale'] is True
    assert c.post(f'{BASE}/draft-reviews/{result["id"]}/approve',headers=h,json={'reviewed':True,'review_digest':result['review_digest']}).status_code==409
    request['request_key']=str(uuid4())
    assert c.post(f'{BASE}/files/{row.id}/drafts',headers=h,json=request).status_code==409
    scan(w)
    assert c.post(f'{BASE}/files/{row.id}/draft-plan',headers=h,json=recipe).status_code==409
    assert c.get(f'{BASE}/draft-reviews/{result["id"]}/images/0',headers=h).status_code==200
    with factory() as db:assert count(db,AiDraft)==count(db,PublishJob)==0


def test_pages_and_auth_are_bounded_and_plan_never_mutates_inventory(library):
    c,h,other,factory,w,s,path,row=setup_pdf(library);before=path.read_bytes()
    recipe={'revision_id':row.current_revision_id,'pages':[1],'brand_id':'xingtu'};url=f'{BASE}/files/{row.id}/draft-plan'
    assert c.post(url,json=recipe).status_code==401 and c.post(url,headers=other,json=recipe).status_code==404
    for pages in [[],[0],[1,1],list(range(1,8)),[10001],[2]]:
        assert c.post(url,headers=h,json={**recipe,'pages':pages}).status_code==422
    assert c.post(url,headers=h,json={**recipe,'publish':True}).status_code==422
    plan(c,h,row)
    with factory() as db:assert count(db,CourseLibraryDraft)==0
    assert path.read_bytes()==before and first_file(factory).signature==row.signature
    s.course_library_enabled=False
    assert c.post(url,headers=h,json=recipe).status_code==404


def test_nine_pages_real_logo_and_one_explicit_ai_action_stay_pending(library):
    import pypdfium2 as pdfium
    c,h,_,factory,w,s,path,row=setup_pdf(library)
    with pdfium.PdfDocument(pdf_bytes('Nine page course preview: concepts, practice and independent review.')) as source, pdfium.PdfDocument.new() as document:
        document.import_pages(source, pages=[0]*9)
        output=io.BytesIO();document.save(output)
    path.write_bytes(output.getvalue());scan(w);row=first_file(factory)
    before=path.read_bytes();mtime=path.stat().st_mtime_ns
    configure_model(factory);calls=[]
    class Client:
        def generate_note(self,**kwargs):
            calls.append(kwargs)
            return {'title':'ECON1001概念和练习','body':'先读概念，独立做题，再根据解析复盘。'}
    app.dependency_overrides[get_text_ai_client]=lambda:Client()
    try:
        recipe,prepared=plan(c,h,row,mode='ai',pages=list(range(1,10)))
        assert calls==[] and prepared['source']['preview_brand']['name']=='星途留学'
        assert len(prepared['source']['preview_brand']['logo_sha256'])==64
        assert c.post(f'{BASE}/files/{row.id}/draft-plan',headers=h,json={**recipe,'pages':list(range(1,11))}).status_code==422
        request={**recipe,'plan_digest':prepared['plan_digest'],'request_key':str(uuid4()),'external_consent':True}
        response=c.post(f'{BASE}/files/{row.id}/drafts',headers=h,json=request)
        assert response.status_code==200,response.text
        result=response.json()
        assert len(calls)==1 and len(result['images'])==9 and [image['page'] for image in result['images']]==list(range(1,10))
        assert result['status']=='pending' and result['draft_id'] is None
        image=c.get(f'{BASE}/draft-reviews/{result["id"]}/images/0',headers=h)
        with Image.open(io.BytesIO(image.content)) as picture:
            colors=list(picture.crop((1090,20,1174,104)).convert('RGB').getdata())
            assert any(r>190 and 70<g<195 and b<90 for r,g,b in colors)  # Real orange logo pixels.
            assert any(b>100 and r<60 and g<180 for r,g,b in colors)  # Real blue logo pixels.
        repeat=c.post(f'{BASE}/files/{row.id}/drafts',headers=h,json=request)
        assert repeat.json()['id']==result['id'] and len(calls)==1
        assert path.read_bytes()==before and path.stat().st_mtime_ns==mtime
        with factory() as db:
            assert count(db,CourseLibraryDraft)==1
            for model in [AiDraft,DraftAsset,PublishJob,AutoTask,Task]:assert count(db,model)==0
    finally:app.dependency_overrides.pop(get_text_ai_client,None)


def configure_model(factory):
    with factory() as db:
        user=first_file(factory).user_id
        model=ModelConfig(user_id=user,name='Mock DeepSeek',model_type='text',provider='openai-compatible',model_name='fixture-model',base_url='https://example.invalid/v1',encrypted_api_key=encrypt_text('SYNTHETIC-TEST-KEY'),is_default=True)
        db.add(model);db.commit();return model.id


def test_ai_requires_exact_disclosure_and_explicit_consent_before_any_call(library):
    c,h,_,factory,w,s,path,row=setup_pdf(library);configure_model(factory);calls=[]
    class Client:
        def generate_note(self,**kwargs):calls.append(kwargs);return {'title':'ECON1001弹性样张','body':'真实样张展示价格与数量变化的关系。'}
    app.dependency_overrides[get_text_ai_client]=lambda:Client()
    try:
        recipe,prepared=plan(c,h,row,mode='ai',instruction='突出弹性学习问题')
        assert prepared['model']['destination']=='https://example.invalid/v1' and 'api_key' not in str(prepared)
        request={**recipe,'request_key':str(uuid4()),'plan_digest':prepared['plan_digest'],'external_consent':False}
        assert c.post(f'{BASE}/files/{row.id}/drafts',headers=h,json=request).status_code==422 and calls==[]
        request['external_consent']=True
        response=c.post(f'{BASE}/files/{row.id}/drafts',headers=h,json=request);assert response.status_code==200,response.text
        assert len(calls)==1 and 'responsiveness' in calls[0]['reference'] and str(path) not in calls[0]['reference'] and row.filename not in calls[0]['reference']
        assert response.json()['generation_mode']=='ai' and response.json()['status']=='pending'
        assert response.json()['model']['model_name']=='fixture-model'
    finally:app.dependency_overrides.pop(get_text_ai_client,None)


def test_ai_configuration_change_requires_new_consent_plan(library):
    c,h,_,factory,w,s,path,row=setup_pdf(library);model_id=configure_model(factory)
    recipe,prepared=plan(c,h,row,mode='ai')
    with factory() as db:model=db.get(ModelConfig,model_id);model.base_url='https://changed.invalid';db.commit()
    request={**recipe,'request_key':str(uuid4()),'plan_digest':prepared['plan_digest'],'external_consent':True}
    assert c.post(f'{BASE}/files/{row.id}/drafts',headers=h,json=request).status_code==409
    with factory() as db:assert count(db,CourseLibraryDraft)==0


def test_ai_error_is_safe_and_does_not_create_partial_review_or_publish_data(library):
    c,h,_,factory,w,s,path,row=setup_pdf(library);configure_model(factory)
    class Client:
        def generate_note(self,**kwargs):raise RuntimeError('secret provider response must never be shown')
    app.dependency_overrides[get_text_ai_client]=lambda:Client()
    try:
        recipe,prepared=plan(c,h,row,mode='ai');request={**recipe,'request_key':str(uuid4()),'plan_digest':prepared['plan_digest'],'external_consent':True}
        response=c.post(f'{BASE}/files/{row.id}/drafts',headers=h,json=request)
        assert response.status_code==502 and 'secret provider' not in response.text
        with factory() as db:
            for model in [CourseLibraryDraft,AiDraft,PublishJob,Task]:assert count(db,model)==0
    finally:app.dependency_overrides.pop(get_text_ai_client,None)


def test_invalid_or_changed_image_and_unsafe_copy_cannot_be_promoted(library):
    c,h,_,factory,w,s,path,row=setup_pdf(library);result,_=generate(c,h,row);url=f'{BASE}/draft-reviews/{result["id"]}'
    for title,body in [('超'*21,'正常学习资料'),('正常标题','文'*1001),('包过资料','学习资料')]:
        edited=c.patch(url,headers=h,json={'title':title,'body':body,'tags':[]});assert edited.status_code==200
        assert c.post(url+'/approve',headers=h,json={'reviewed':True,'review_digest':edited.json()['review_digest']}).status_code==422
    edited=c.patch(url,headers=h,json={'title':'课程学习样张','body':'正常学习资料介绍','tags':[]}).json()
    with factory() as db:item=db.get(CourseLibraryDraft,result['id']);(s.storage_dir/item.images[0]['path']).write_bytes(b'changed image')
    assert c.post(url+'/approve',headers=h,json={'reviewed':True,'review_digest':edited['review_digest']}).status_code==409
    with factory() as db:assert count(db,AiDraft)==count(db,DraftAsset)==count(db,PublishJob)==0 and db.get(CourseLibraryDraft,result['id']).status=='pending'


def test_no_text_ai_is_blocked_but_local_draft_still_has_manual_review_path(library):
    c,h,_,factory,w,s,path,row=setup_pdf(library);path.write_bytes(pdf_bytes(''));scan(w);row=first_file(factory);configure_model(factory)
    recipe,prepared=plan(c,h,row,mode='ai');assert prepared['warnings']
    request={**recipe,'request_key':str(uuid4()),'plan_digest':prepared['plan_digest'],'external_consent':True}
    assert c.post(f'{BASE}/files/{row.id}/drafts',headers=h,json=request).status_code==422
    result,_=generate(c,h,row);assert result['status']=='pending' and '未读取到足够文字' in result['body']
