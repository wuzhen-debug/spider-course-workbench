"""Course provenance and non-destructive image variants, isolated database only."""
from copy import deepcopy
from uuid import uuid4
import pytest
from sqlalchemy import select, func
from test_course_research import research
from test_course_library import library
from backend.app.main import app
from backend.app.api.ai import get_image_ai_client
from backend.app.models import AiDraft, DraftAsset, ModelConfig, Task, User
from backend.app.models.course_library import CourseLibraryFile
from backend.app.models.course_library_draft import CourseLibraryDraft
from backend.app.models.course_research import CourseResearch, CourseResearchDraft
from backend.app.models.course_visual_workflow import CourseVisualWorkflow
from backend.app.services.course_draft_origin import draft_binding


@pytest.fixture
def image_guard(research):
    c,h,other,factory,*_=research
    with factory() as db:
        owner=db.scalar(select(User).where(User.username=='pdf-owner'))
        file=db.scalar(select(CourseLibraryFile).where(CourseLibraryFile.user_id==owner.id))
        drafts=[AiDraft(user_id=owner.id,platform='xhs',title=t,body='unchanged') for t in ('workflow','pdf','research','ordinary')]
        db.add_all(drafts);db.flush()
        run=CourseVisualWorkflow(user_id=owner.id,file_id=file.id,request_key=str(uuid4()),data={
            'source':{'course_code':'MAST10007'},'export':None,'history':[{'revision':3,'export':{'draft_id':drafts[0].id,
                'at':drafts[0].created_at.isoformat(),'snapshot':draft_binding(drafts[0])}}]})
        db.add(run)
        db.add(CourseLibraryDraft(user_id=owner.id,file_id=file.id,revision_id=file.current_revision_id,request_key=str(uuid4()),plan_digest='fixture',
            title='pdf',body='unchanged',tags=[],source_snapshot={'draft_binding':draft_binding(drafts[1])},page_texts=[],images=[],generation_mode='template',draft_id=drafts[1].id))
        study=CourseResearch(user_id=owner.id,context={'course_code':'MAST10006','library_directory':'02墨大/MAST10006'})
        db.add(study);db.flush()
        db.add(CourseResearchDraft(user_id=owner.id,research_id=study.id,request_key=str(uuid4()),request_digest='fixture',
            title='research',body='unchanged',tags=[],prompt='',brief={'draft_binding':draft_binding(drafts[2])},draft_id=drafts[2].id))
        assets=[DraftAsset(draft_id=d.id,asset_type='image',local_path=f'ordinary-name-{i}.png',url='',sort_order=0) for i,d in enumerate(drafts)]
        assets.append(DraftAsset(draft_id=drafts[3].id,asset_type='image',url='https://example.test/later.png',sort_order=8))
        db.add_all(assets)
        db.add(ModelConfig(user_id=owner.id,name='fixture',model_type='image',provider='openai-compatible',model_name='fixture',base_url='https://example.test',is_default=True))
        db.commit();ids=[d.id for d in drafts];aids=[a.id for a in assets];runid=run.id
    class Client:
        calls=0
        def generate_image(self,**kwargs):
            self.calls+=1
            return {'url':'https://example.test/generated.png'}
    fake=Client();app.dependency_overrides[get_image_ai_client]=lambda:fake
    yield research,ids,aids,runid,fake
    app.dependency_overrides.pop(get_image_ai_client,None)


def test_readonly_provenance_includes_historical_exports_and_other_course_flows(image_guard):
    r,ids,aids,runid,fake=image_guard;c,h,other,factory,*_=r
    with factory() as db:
        before=deepcopy(db.get(CourseVisualWorkflow,runid).data)
    data={d['id']:d for d in c.get('/api/drafts',headers=h).json()['items']}
    assert data[ids[0]]['course_origin']['href']==f'/platforms/xhs/visual-workbench?run={runid}'
    assert data[ids[0]]['course_origin']['revision']==3
    assert data[ids[1]]['course_origin']['kind']=='pdf_review'
    assert data[ids[2]]['course_origin']['kind']=='course_research'
    assert data[ids[3]]['course_origin'] is None
    assert not c.get('/api/drafts',headers=other).json()['items']
    changed=c.patch(f'/api/drafts/{ids[0]}',headers=h,json={'title':'edited draft'})
    assert changed.json()['course_origin']['workflow_id']==runid
    with factory() as db:
        assert db.get(CourseVisualWorkflow,runid).data==before
        assert db.scalar(select(func.count()).select_from(Task))==0


def test_course_images_are_rejected_before_any_provider_call(image_guard):
    r,ids,aids,runid,fake=image_guard;c,h,other,factory,*_=r
    for i in range(3):
        variants=[{'draft_id':ids[i]}, {'asset_id':aids[i]},
                  {'reference_images':[f'/api/files/media/ordinary-name-{i}.png']},
                  {'reference_images':[f'http://127.0.0.1:8000/api/files/media/ordinary-name-{i}.png?preview=true']}]
        for payload in variants:
            res=c.post('/api/ai/images/generate',headers=h,json={'prompt':'do not send',**payload})
            assert res.status_code==409,res.text
    # Protected export names remain recognized after a removed/renamed draft relationship.
    for ref in ['xhs-asset-u1-workflow-5-old.png','/api/files/media/xhs-asset-u1-pdf-review-8-old.png']:
        assert c.post('/api/ai/images/generate',headers=h,json={'prompt':'do not send','reference_images':[ref]}).status_code==409
    assert c.post('/api/ai/images/generate',headers=other,json={'prompt':'do not send','asset_id':aids[3]}).status_code==404
    assert c.post('/api/ai/images/generate',headers=h,json={'prompt':'do not send','asset_id':aids[0],'draft_id':ids[3]}).status_code==404
    assert fake.calls==0
    with factory() as db:assert db.scalar(select(func.count()).select_from(Task))==0


def test_ordinary_polish_adds_variant_after_original_and_is_idempotent(image_guard):
    r,ids,aids,runid,fake=image_guard;c,h,other,factory,*_=r
    generated=c.post('/api/ai/images/generate',headers=h,json={'prompt':'ordinary image','draft_id':ids[3],'asset_id':aids[3],
        'reference_images':['/api/files/media/ordinary-name-3.png'],'save_to_assets':False})
    assert generated.status_code==200 and fake.calls==1
    endpoint=f'/api/drafts/{ids[3]}/assets/{aids[3]}/variants'
    result=c.post(endpoint,headers=h,json={'url':generated.json()['url']})
    assert result.status_code==200,result.text
    assets=result.json()['items'];assert [a['id'] for a in assets][::2]==[aids[3],aids[4]]
    assert [a['sort_order'] for a in assets]==[0,1,2]
    assert assets[0]['local_path']=='ordinary-name-3.png' and assets[1]['url']==generated.json()['url']
    retry=c.post(endpoint,headers=h,json={'url':generated.json()['url']})
    assert retry.json()==result.json()
    assert c.post(endpoint,headers=other,json={'url':generated.json()['url']}).status_code==404
    assert c.post(f'/api/drafts/{ids[0]}/assets/{aids[0]}/variants',headers=h,json={'url':generated.json()['url']}).status_code==409
    assert c.patch(f'/api/drafts/{ids[0]}/assets/{aids[0]}',headers=h,json={'url':generated.json()['url'],'local_path':''}).status_code==409
    assert c.get(f'/api/drafts/{ids[0]}/assets',headers=h).json()['items'][0]['local_path']=='ordinary-name-0.png'
    assert c.post(endpoint,headers=h,json={'url':'invalid'}).status_code==422
    after=c.get(f'/api/drafts/{ids[3]}/assets',headers=h).json()
    assert after==result.json()
