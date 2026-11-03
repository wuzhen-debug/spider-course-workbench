"""Cross-brand creation, source preservation and real local watermark checks."""
from copy import deepcopy
from io import BytesIO
import hashlib
from uuid import uuid4

from PIL import Image
import pytest
from sqlalchemy import select

from test_course_library import library
from test_course_library_drafts import BASE as LIBRARY, setup_pdf, plan, generate, count
from test_course_research import research
from test_course_visual_workflow import BASE, call
from test_course_visual_pdf_lane import pdf_run
from backend.app.models import AiDraft, DraftAsset, PublishJob, AutoTask, Task
from backend.app.models.course_visual_workflow import CourseVisualWorkflow
from backend.app.services.course_brands import brands, logo_path, resolve_brand, saved_brand
from backend.app.services.course_draft_images import frame_page, preview_brand


def test_brand_assets_are_distinct_and_legacy_snapshots_still_validate(tmp_path):
    entries=brands()
    assert [(b['id'],b['name']) for b in entries]==[('xingtu','星途留学'),('wenguo','稳过留学')]
    assert entries[0]['logo_sha256']!=entries[1]['logo_sha256']
    old=preview_brand('xingtu');old.pop('id')
    assert saved_brand(old)['id']=='xingtu'
    for value in ['',None,'../xingtu-logo.jpg','unknown']:
        with pytest.raises(Exception) as error:resolve_brand(value)
        assert error.value.status_code==422
    forged={**preview_brand('wenguo'),'logo_sha256':entries[0]['logo_sha256']}
    with pytest.raises(Exception) as error:logo_path(forged)
    assert error.value.status_code==409
    source=tmp_path/'source.png';Image.new('RGB',(240,360),'white').save(source)
    outputs=[]
    for brand in entries:
        output=tmp_path/f"{brand['id']}.png"
        frame_page(source,output,{'university':'测试大学','course_code':'TEST1001','term':'2026S2','material_type':'复习讲义'},1,9,preview_brand(brand['id']))
        with Image.open(output) as image:
            assert image.size==(1200,1924)
            # Both header badge and watermark actually differ, not only metadata.
            outputs.append([hashlib.sha256(image.crop(box).tobytes()).hexdigest() for box in [(1080,12,1184,112),(420,700,780,1200)]])
    assert all(a!=b for a,b in zip(*outputs))


def test_pdf_new_creation_requires_explicit_brand_and_never_rebrands_old(library):
    c,h,_,factory,w,s,path,row=setup_pdf(library);original=path.read_bytes()
    recipe={'revision_id':row.current_revision_id,'pages':[1]}
    assert c.post(f'{LIBRARY}/files/{row.id}/draft-plan',headers=h,json=recipe).status_code==422
    old,_=generate(c,h,row,brand_id='xingtu');frozen=deepcopy(old)
    recipe,prepared=plan(c,h,row,brand_id='wenguo')
    assert prepared['source']['preview_brand']['name']=='稳过留学'
    # A brand change invalidates the prepared scope before any model/image action.
    bad={**recipe,'brand_id':'xingtu','plan_digest':prepared['plan_digest'],'request_key':str(uuid4())}
    assert c.post(f'{LIBRARY}/files/{row.id}/drafts',headers=h,json=bad).status_code==409
    new,request=generate(c,h,row,brand_id='wenguo')
    assert new['status']=='pending' and new['draft_id'] is None
    assert new['source']['preview_brand']['id']=='wenguo' and new['source']['sha256']==old['source']['sha256']
    assert c.get(f'{LIBRARY}/draft-reviews/{old["id"]}',headers=h).json()==frozen
    assert c.get(f'{LIBRARY}/draft-reviews/{old["id"]}/images/0',headers=h).content!=c.get(f'{LIBRARY}/draft-reviews/{new["id"]}/images/0',headers=h).content
    assert path.read_bytes()==original
    with factory() as db:
        assert all(count(db,m)==0 for m in [AiDraft,DraftAsset,PublishJob,AutoTask,Task])


def test_pdf_research_brand_survives_preview_create_reload_and_retry(research):
    star,source=pdf_run(research);c,h,other,factory,*_=research
    before=c.get(f'{BASE}/{star["id"]}',headers=h).json();original=source.read_bytes()
    payload={'file_id':star['file_id'],'revision_id':star['data']['source']['revision_id'],'entry_mode':'pdf-driven','template_id':'magazine-a','request_key':str(uuid4())}
    assert c.post(BASE,headers=h,json=payload).status_code==422
    payload['brand_id']='wenguo'
    preview=c.post(BASE+'/pdf-topic-plan',headers=h,json={k:payload[k] for k in ['file_id','revision_id','brand_id']})
    assert preview.status_code==200,preview.text
    row=c.post(BASE,headers=h,json=payload).json()
    assert row['data']['brand']['name']=='稳过留学' and row['data']['source']['preview_brand']['id']=='wenguo'
    assert row['data']['images']==[] and not any(row['approved'].values())
    p=call(research,row,'pdf-analysis-plan')
    assert p['prompt']==preview.json()['prompt']
    assert '本篇唯一品牌：稳过留学' in p['prompt'] and '本品牌使用真实星途留学Logo' not in p['prompt']
    assert c.post(BASE,headers=h,json=payload).json()['id']==row['id']
    assert c.post(BASE,headers=h,json={**payload,'brand_id':'xingtu'}).status_code==409
    assert c.get(f'{BASE}/{row["id"]}',headers=other).status_code==404
    assert c.get(f'{BASE}/{star["id"]}',headers=h).json()==before and source.read_bytes()==original
    assert c.get(BASE+'/brands').status_code==401
    for brand in brands():
        response=c.get(BASE+'/brand/logo',headers=h,params={'brand_id':brand['id']})
        assert response.status_code==200 and hashlib.sha256(response.content).hexdigest()==brand['logo_sha256']
    with factory() as db:
        assert all(count(db,m)==0 for m in [AiDraft,DraftAsset,PublishJob,AutoTask,Task])


def test_xhs_selected_brand_is_preserved_when_handing_copy_to_visual_workbench(research):
    from test_course_visual_workflow import research_handoff_ready, handoff_plan, handoff_payload
    origin,draft,payload=research_handoff_ready(research,brand='稳过留学')
    prepared=handoff_plan(research,payload)
    assert prepared['brand']['id']=='wenguo' and prepared['source']['preview_brand']['id']=='wenguo'
    request=handoff_payload(payload,prepared,limited_sources_reviewed=True)
    response=research[0].post(BASE+'/from-research',headers=research[1],json=request)
    assert response.status_code==200,response.text
    row=response.json()
    assert row['data']['brand']['name']=='稳过留学' and row['data']['copy']['body']==draft['body']
    assert row['data']['source']['preview_brand']['id']=='wenguo'
    assert row['approved']['copy'] and row['data']['images']==[] and row['data']['export'] is None
    with research[3]() as db:
        assert all(count(db,m)==0 for m in [AiDraft,DraftAsset,PublishJob,AutoTask,Task])
