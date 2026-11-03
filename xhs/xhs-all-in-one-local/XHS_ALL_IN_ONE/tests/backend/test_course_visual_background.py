"""Real local composition, mocked external image API; never publishes."""
from io import BytesIO
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4
import base64
import pytest
from PIL import Image
from sqlalchemy import select, func
from test_course_visual_workflow import research, copy_ready, approve, call, BASE
from test_course_library import library
from backend.app.main import app
from backend.app.models import ModelConfig, User, AiDraft, PublishJob, AutoTask
from backend.app.models.course_visual_workflow import CourseVisualWorkflow
from backend.app.core.security import encrypt_text
from backend.app.services import course_visual_background as bg
from backend.app.api import course_visual_workflow as api


@pytest.fixture
def setup(research):
    c,h,other,factory,w,*_=research
    with factory() as db:
        owner=db.scalar(select(User).where(User.username=='pdf-owner'))
        db.add(ModelConfig(user_id=owner.id,name='Seedream fixture',model_type='image',provider='openai-compatible',model_name='doubao-seedream-5-0-flash-260915',base_url='https://ark.cn-beijing.volces.com/api/v3',encrypted_api_key=encrypt_text('fixture-key'),is_default=True));db.commit()
    class Client:
        calls=0;fail=False
        def generate(self,**kwargs):
            self.calls+=1
            assert 'MAST10007' not in kwargs['prompt'] and 'DO_NOT_SEND_TO_AI' not in kwargs['prompt'] and 'fixture-key' not in kwargs['prompt']
            if self.fail:raise RuntimeError('credential fixture-key must never be exposed')
            stream=BytesIO();Image.new('RGB',(768,1024),'#f0f5fa').save(stream,format='PNG');return stream.getvalue()
    client=Client();app.dependency_overrides[bg.get_background_client]=lambda:client
    return research,client


def prepared(r,row,slot='cover'):
    options={'slot':slot,'style':'paper-depth','strength':'balanced'}
    p=call(r,row,'background-plan',options)
    return {**options,'external_consent':True,'plan_digest':p['plan_digest'],'request_key':str(uuid4())}


def test_consent_owner_and_copy_gates(setup):
    r,client=setup;c,h,other,*_=r;row=copy_ready(r)
    call(r,row,'background-plan',{'slot':'cover'},409)
    row=approve(r,row,'copy');payload=prepared(r,row)
    assert c.post(f'{BASE}/{row["id"]}/background-plan',headers=other,json={'expected_version':row['row_version']}).status_code==404
    call(r,row,'generate-background',{**payload,'external_consent':False},422)
    call(r,row,'generate-background',{**payload,'plan_digest':'stale'},422)
    call(r,row,'background-plan',{'slot':'sample-0'},422)
    assert client.calls==0


def test_real_composition_local_edits_reuse_background_and_preserve_review(setup):
    r,client=setup;c,h,other,factory,w,*_=r
    row=approve(r,copy_ready(r),'copy');row=call(r,row,'render',{'stage':'cover'});old=row['data']['cover'];original_copy=row['data']['copy']
    payload=prepared(r,row);result=call(r,row,'generate-background',payload)
    assert client.calls==1 and result['approved']['copy'] and not result['approved']['cover'] and not result['data']['images']
    assert result['data']['copy']==original_copy and result['data']['cover']['background']['ai_generated']
    assert c.get(f'{BASE}/{row["id"]}/images/{old["id"]}',headers=h).status_code==200
    png=c.get(f'{BASE}/{row["id"]}/images/{result["data"]["cover"]["id"]}',headers=h).content
    with Image.open(BytesIO(png)) as image:assert image.size==(1080,1440) and image.getpixel((10,10))[:3]==(240,245,250)
    retry=call(r,row,'generate-background',payload)
    assert retry['data']['cover']['id']==result['data']['cover']['id'] and client.calls==1
    current=result['data']['cover'];edited=call(r,result,'revise',{'asset_id':current['id'],'brief':{**current['brief'],'subtitle':'先确认条件，再独立练习'}})
    assert client.calls==1 and edited['data']['cover']['background']['sha256']==current['background']['sha256']
    assert not edited['approved']['cover']
    # A later inner page can use the same feature; original PDF sample pages cannot.
    row=approve(r,edited,'cover');row=call(r,row,'render',{'stage':'set'})
    row=call(r,row,'generate-background',prepared(r,row,'method'))
    assert client.calls==2 and row['approved']['cover'] and not row['approved']['set']
    assert next(a for a in row['data']['images'] if a['slot']=='method')['background']['ai_generated']
    with factory() as db:
        for model in [AiDraft,PublishJob,AutoTask]:assert db.scalar(select(func.count()).select_from(model))==0


def test_failure_is_not_recharged_or_exposed_and_cached_composition_can_resume(setup,monkeypatch):
    r,client=setup;c,h,*_=r;row=approve(r,copy_ready(r),'copy');payload=prepared(r,row)
    client.fail=True;error=call(r,row,'generate-background',payload,502)
    assert 'fixture-key' not in str(error)
    call(r,row,'generate-background',payload,409);assert client.calls==1
    row=c.get(f'{BASE}/{row["id"]}',headers=h).json();client.fail=False;payload=prepared(r,row)
    real=api.render_assets
    def fail(*a,**kw):raise ValueError('local renderer unavailable')
    monkeypatch.setattr(api,'render_assets',fail)
    call(r,row,'generate-background',payload,422);assert client.calls==2
    monkeypatch.setattr(api,'render_assets',real)
    result=call(r,row,'generate-background',payload)
    assert client.calls==2 and result['data']['cover'] and not result['approved']['cover']


def test_background_tamper_and_source_change_block_local_render(setup):
    r,client=setup;c,h,_,factory,w,*_=r;row=approve(r,copy_ready(r),'copy')
    row=call(r,row,'generate-background',prepared(r,row));old=row['data']['cover']
    with factory() as db:
        model=db.get(CourseVisualWorkflow,row['id']);owner=db.get(User,model.user_id)
        path=api.directory(SimpleNamespace(storage_dir=w.root.parent/'storage'),owner,model)/model.data['backgrounds']['cover']['path']
        path.write_bytes(b'corrupt')
    call(r,row,'render',{'stage':'cover'},409)
    after=c.get(f'{BASE}/{row["id"]}',headers=h).json()
    assert after['data']['cover']['id']==old['id'] and client.calls==1


def test_cached_resume_is_local_only_and_respects_concurrent_operation(setup,monkeypatch):
    r,client=setup;c,h,_,factory,*_=r
    row=approve(r,copy_ready(r),'copy');payload=prepared(r,row)
    # A lost request key must never create a fresh paid request through recovery.
    call(r,row,'generate-background',{**payload,'local_only':True},409)
    assert client.calls==0
    real=api.render_assets
    def fail(*a,**kw):raise ValueError('local renderer unavailable')
    monkeypatch.setattr(api,'render_assets',fail)
    call(r,row,'generate-background',payload,422)
    current=c.get(f'{BASE}/{row["id"]}',headers=h).json()
    saved=current['data']['background_requests'][payload['request_key']]
    assert saved['consent_digest']==payload['plan_digest']
    assert saved['options']=={k:payload[k] for k in ('slot','style','strength')}
    # Simulate a different in-flight operation; a stale retry must not clear its lock.
    with factory() as db:
        model=db.get(CourseVisualWorkflow,row['id']);d=deepcopy(model.data)
        d['operation']={'key':'other-request','status':'generating','kind':'background'}
        model.data=d;db.commit()
    call(r,row,'generate-background',{**payload,'local_only':True},409)
    after=c.get(f'{BASE}/{row["id"]}',headers=h).json()
    assert after['data']['operation']['status']=='generating'
    assert after['data']['background_requests'][payload['request_key']]['status']=='render_failed'
    with factory() as db:
        model=db.get(CourseVisualWorkflow,row['id']);d=deepcopy(model.data)
        d['operation']['status']='failed';model.data=d;db.commit()
    def check_lock(*args,**kwargs):
        with factory() as db:
            model=db.get(CourseVisualWorkflow,row['id'])
            assert model.data['operation']=={**model.data['operation'],'key':payload['request_key'],'status':'generating'}
            assert model.data['background_requests'][payload['request_key']]['status']=='rendering'
        return real(*args,**kwargs)
    monkeypatch.setattr(api,'render_assets',check_lock)
    # Reconstruct exactly what the reopened frontend can persistently recover.
    resumed=call(r,after,'generate-background',{**saved['options'],'external_consent':True,
        'plan_digest':saved['consent_digest'],'request_key':payload['request_key'],'local_only':True})
    assert client.calls==1 and resumed['data']['background_requests'][payload['request_key']]['status']=='completed'


def test_seedream_wire_payload_is_text_only_and_single_call(monkeypatch):
    stream=BytesIO();Image.new('RGB',(768,1024),'white').save(stream,format='PNG')
    calls=[]
    def post(url,**kwargs):
        calls.append(kwargs)
        assert url=='https://ark.cn-beijing.volces.com/api/v3/images/generations'
        assert set(kwargs['json'])=={'model','prompt','size','response_format','watermark'}
        assert kwargs['json']['size']=='1536x2048' and kwargs['json']['response_format']=='b64_json'
        return SimpleNamespace(status_code=200,json=lambda:{'data':[{'b64_json':base64.b64encode(stream.getvalue()).decode()}]})
    monkeypatch.setattr(bg.requests,'post',post)
    out=bg.SeedreamBackgroundClient().generate(model=SimpleNamespace(base_url='https://ark.cn-beijing.volces.com/api/v3',model_name='doubao-seedream-5-0-flash-260915'),api_key='fixture-key',prompt='Only abstract background')
    assert out.startswith(b'\x89PNG') and len(calls)==1
