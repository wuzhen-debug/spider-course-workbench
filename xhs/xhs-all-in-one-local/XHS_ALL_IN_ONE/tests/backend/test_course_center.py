"""P0/P1 acceptance on isolated SQLite databases, no external services."""
from pathlib import Path
from types import SimpleNamespace
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import sessionmaker

from backend.app.main import app
from backend.app.core.config import get_settings
from backend.app.core.database import Base, get_db
from backend.app.models import AiDraft, Note, PublishJob, PlatformAccount
from backend.app.models.course_center import CourseContentLink, CourseDemoContent, CourseOffering, CourseMaterialProduct


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path/'course-test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    def override_db():
        with factory() as db: yield db
    app.dependency_overrides[get_db] = override_db
    settings = get_settings()
    monkeypatch.setattr(settings, "course_center_enabled", True)
    monkeypatch.setattr(settings, "course_center_demo_only", True)
    from backend.app.services import course_demo_service
    from backend.app.api import course_center
    monkeypatch.setattr(course_demo_service, "get_settings", lambda: SimpleNamespace(storage_dir=tmp_path/'storage'))
    monkeypatch.setattr(course_center, "_demo_dir", lambda: tmp_path/'storage/course-center-demo')
    with TestClient(app, raise_server_exceptions=True) as client:
        # TestClient lifespan initializes the configured DB; override the lifespan
        # init function below so application data is never used in this fixture.
        token = client.post('/api/auth/register', json={'username':'course-owner','password':'secret123'}).json()['access_token']
        token2 = client.post('/api/auth/register', json={'username':'course-other','password':'secret123'}).json()['access_token']
        yield client, {'Authorization':f'Bearer {token}'}, {'Authorization':f'Bearer {token2}'}, factory, settings
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


@pytest.fixture(autouse=True)
def no_runtime_database_initialization(monkeypatch):
    import importlib
    main = importlib.import_module('backend.app.main')
    monkeypatch.setattr(main, 'init_db', lambda: None)
    monkeypatch.setattr(main, 'start_due_publish_scheduler', lambda *a: (_ for _ in ()).throw(AssertionError('No scheduler may be started in course acceptance')))


def seed(client, headers):
    response = client.post('/api/course-center/demo/seed', headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def course_payload(**kw):
    return {'university':'演示大学 C（虚构）','course_code':'DEMO2000','course_name':'新课程登记演示','term':'2026S2','is_demo':True,**kw}


def test_seed_is_isolated_idempotent_and_does_not_overwrite_edits(workspace):
    client, headers, _, factory, _ = workspace
    with factory() as db:
        before = {t: db.connection().exec_driver_sql(f'SELECT COUNT(*) FROM {t}').scalar() for t in ['ai_drafts','publish_jobs','publish_assets','auto_tasks','notes','tasks','account_cookie_versions']}
    result = seed(client, headers)
    assert result['created_total'] == 10
    data = client.get(f"/api/course-center/courses/{result['course_id']}",headers=headers).json()
    assert len(data['products']) == 1 and len(data['versions']) == 2 and len(data['assets']) == 2 and len(data['links']) == 1
    course = data['course']
    edited = course_payload(university=course['university'],course_code=course['course_code'],term=course['term'],course_name='保留这项演示编辑')
    assert client.put(f"/api/course-center/courses/{course['id']}",headers=headers,json=edited).status_code == 200
    version = data['versions'][0]
    assert client.put(f"/api/course-center/versions/{version['id']}", headers=headers,
        json={'version': 'v-renamed', 'language': '中文', 'source_reference': 'demo://edited-reference', 'qa_status': 'changes_required'}).status_code == 200
    assert seed(client,headers)['created_total'] == 0
    after = client.get(f"/api/course-center/courses/{course['id']}",headers=headers).json()
    assert after['course']['course_name'] == '保留这项演示编辑'
    assert len(after['versions']) == 2 and any(v['version'] == 'v-renamed' and v['source_reference'] == 'demo://edited-reference' for v in after['versions'])
    with factory() as db:
        assert before == {t:db.connection().exec_driver_sql(f'SELECT COUNT(*) FROM {t}').scalar() for t in before}
        assert db.scalar(select(CourseDemoContent)).body.startswith('这是独立演示草稿')


def test_same_code_is_separate_by_university_and_term_and_normalized_duplicates_conflict(workspace):
    client,h,_,_,_=workspace
    seed(client,h)
    courses=client.get('/api/course-center/courses',headers=h).json()['items']
    assert len(courses)==3 and len({(c['university'],c['term']) for c in courses})==3
    c=courses[0]
    duplicate=course_payload(university=c['university'],course_code='demo 1000',term='2026s2')
    assert client.post('/api/course-center/courses',headers=h,json=duplicate).status_code==409
    found=client.get('/api/course-center/courses',headers=h,params={'q':'同码不同校'}).json()
    assert found['total']==1 and found['items'][0]['university']=='演示大学 B（虚构）'


def test_feature_off_preserves_data_and_old_routes(workspace):
    client,h,_,_,settings=workspace
    result=seed(client,h)
    settings.course_center_enabled=False
    caps=client.get('/api/course-center/capabilities',headers=h).json()
    assert caps['enabled'] is False and caps['can_publish'] is False and caps['can_run_automation'] is False
    assert client.get('/api/course-center/courses',headers=h).status_code==404
    assert client.post('/api/course-center/demo/seed',headers=h).status_code==404
    assert client.get('/api/health').status_code==200
    assert client.get('/api/drafts',headers=h).status_code==200
    assert client.get('/api/publish/jobs',headers=h).status_code==200
    settings.course_center_enabled=True
    assert client.get(f"/api/course-center/courses/{result['course_id']}",headers=h).status_code==200


def test_authentication_ownership_and_demo_scope_are_enforced(workspace):
    client,h,other,_,_=workspace
    assert client.get('/api/course-center/capabilities').status_code==401
    assert client.get('/api/course-center/courses').status_code==401
    result=seed(client,h);cid=result['course_id']
    assert client.get('/api/course-center/courses',headers=other).json()['total']==0
    assert client.get(f'/api/course-center/courses/{cid}',headers=other).status_code==404
    assert client.put(f'/api/course-center/courses/{cid}',headers=other,json=course_payload()).status_code==404
    assert client.post('/api/course-center/courses',headers=h,json=course_payload(is_demo=False)).status_code==403
    assert client.post('/api/course-center/courses',headers=h,json=course_payload(user_id=2)).status_code==422
    data=client.get(f'/api/course-center/courses/{cid}',headers=h).json()
    pid=data['products'][0]['id']
    assert client.put(f'/api/course-center/products/{pid}',headers=other,json={'title':'x','material_type':'练习'}).status_code==404


def test_versions_file_status_qa_and_listing_remain_independent(workspace):
    client,h,_,_,_=workspace
    cid=seed(client,h)['course_id'];data=client.get(f'/api/course-center/courses/{cid}',headers=h).json()
    v=next(v for v in data['versions'] if v['version']=='v1.0')
    checked=client.post(f"/api/course-center/versions/{v['id']}/check-file",headers=h).json()
    assert checked['file_status']=='verified' and len(checked['sha256'])==64 and checked['qa_status']=='pending'
    assert data['products'][0]['listing_status']=='not_listed'
    missing=next(v for v in data['versions'] if v['version']=='v0.9')
    assert client.post(f"/api/course-center/versions/{missing['id']}/check-file",headers=h).json()['file_status']=='missing'
    payload={'version':'v1.0','source_reference':'/etc/hosts','qa_status':'passed','sha256':''}
    assert client.put(f"/api/course-center/versions/{v['id']}",headers=h,json=payload).status_code==200
    assert client.post(f"/api/course-center/versions/{v['id']}/check-file",headers=h).status_code==400
    refreshed=client.get(f'/api/course-center/courses/{cid}',headers=h).json()
    assert next(r for r in refreshed['versions'] if r['id']==v['id'])['file_status']=='registered'
    assert client.put(f"/api/course-center/versions/{v['id']}",headers=h,json={**payload,'file_status':'verified'}).status_code==422
    assert client.post(f"/api/course-center/products/{data['products'][0]['id']}/versions",headers=h,json={'version':'v1.0'}).status_code==409


def test_sample_approval_requires_watermark_and_rights_and_version_belongs_to_course(workspace):
    client,h,_,_,_=workspace
    cid=seed(client,h)['course_id'];data=client.get(f'/api/course-center/courses/{cid}',headers=h).json()
    payload={'title':'新样张','asset_kind':'sample','usage_status':'approved','rights_confirmed':True,'watermarked':False}
    assert client.post(f'/api/course-center/courses/{cid}/assets',headers=h,json=payload).status_code==400
    payload['watermarked']=True
    assert client.post(f'/api/course-center/courses/{cid}/assets',headers=h,json=payload).status_code==200
    second=client.post('/api/course-center/courses',headers=h,json=course_payload()).json()['id']
    assert client.post(f'/api/course-center/courses/{second}/assets',headers=h,json={**payload,'version_id':data['versions'][0]['id']}).status_code==400


def test_archive_detach_and_reattach_preserve_records(workspace):
    client,h,_,factory,_=workspace
    cid=seed(client,h)['course_id'];data=client.get(f'/api/course-center/courses/{cid}',headers=h).json();link=data['links'][0]
    assert client.post(f"/api/course-center/links/{link['id']}/detach",headers=h).json()['history_retained'] is True
    assert client.get(f'/api/course-center/courses/{cid}',headers=h).json()['links']==[]
    payload={'target_kind':link['target_kind'],'target_id':link['target_id'],'target_is_demo':True}
    assert client.post(f'/api/course-center/courses/{cid}/links',headers=h,json=payload).json()['id']==link['id']
    assert client.patch(f'/api/course-center/courses/{cid}/archive',headers=h,json={'archived':True}).status_code==200
    assert client.get('/api/course-center/courses',headers=h).json()['total']==2
    assert client.get('/api/course-center/courses',headers=h,params={'include_archived':True}).json()['total']==3
    assert client.patch(f'/api/course-center/courses/{cid}/archive',headers=h,json={'archived':False}).status_code==200
    with factory() as db:
        assert db.query(CourseContentLink).count()==1 and db.query(CourseMaterialProduct).count()==1


def test_demo_and_real_content_are_isolated_and_deleted_source_history_is_visible(workspace):
    client,h,_,factory,settings=workspace
    cid=seed(client,h)['course_id']
    with factory() as db:
        user_id=db.scalar(select(CourseOffering.user_id).where(CourseOffering.id==cid))
        account=PlatformAccount(user_id=user_id,platform='xhs',sub_type='creator',nickname='fixture')
        db.add(account);db.flush()
        job=PublishJob(user_id=user_id,platform='xhs',platform_account_id=account.id,source_draft_id=999,title='保留的发布历史',status='published',external_note_id='fixture-note')
        db.add(job);db.commit();job_id=job.id
    candidates=client.get('/api/course-center/content-candidates',headers=h,params={'demo':False}).json()
    assert candidates['can_associate'] is False
    view=next(v for v in candidates['items'] if v['id']==job_id and v['target_kind']=='publish_job')
    assert view['source_available'] is False and '保留发布快照' in view['source_hint']
    assert client.post(f'/api/course-center/courses/{cid}/links',headers=h,json={'target_kind':'publish_job','target_id':job_id,'target_is_demo':False}).status_code==400
    assert client.get('/api/drafts',headers=h).json()['items']==[]
    # A later registration mode can link legacy records through the new join
    # table, without recreating the missing draft or changing the job snapshot.
    settings.course_center_demo_only=False
    real=client.post('/api/course-center/courses',headers=h,json=course_payload(is_demo=False)).json()
    assert client.post(f"/api/course-center/courses/{real['id']}/links",headers=h,
        json={'target_kind':'publish_job','target_id':job_id,'target_is_demo':False}).status_code==200
    linked=client.get(f"/api/course-center/courses/{real['id']}",headers=h).json()['links'][0]['content']
    assert linked['title']=='保留的发布历史' and linked['source_available'] is False
    with factory() as db:
        job=db.get(PublishJob,job_id)
        assert job.status=='published' and job.source_draft_id==999 and job.external_note_id=='fixture-note'
        assert db.scalar(select(func.count()).select_from(AiDraft))==0


def test_demo_preview_is_authenticated_and_has_no_arbitrary_file_route(workspace):
    client,h,_,_,_=workspace
    seed(client,h)
    assert client.get('/api/course-center/demo-assets/sample-watermarked.svg').status_code==401
    response=client.get('/api/course-center/demo-assets/sample-watermarked.svg',headers=h)
    assert response.status_code==200 and 'sandbox' in response.headers['content-security-policy']
    assert '演示样张' in response.text
    assert client.get('/api/course-center/demo-assets/handout.txt',headers=h).status_code==404


def test_additive_migration_preserves_legacy_rows(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    url=f"sqlite:///{tmp_path/'migration.db'}"
    monkeypatch.setenv('DATABASE_URL',url)
    cfg=Config('backend/alembic.ini');cfg.set_main_option('sqlalchemy.url',url)
    command.upgrade(cfg,'60cd5c95fde1')
    engine=create_engine(url)
    with engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO users (id,username,password_hash,created_at) VALUES (1,'fixture','fixture','2026-10-28 09:00:00')")
        connection.exec_driver_sql("INSERT INTO ai_drafts (id,user_id,platform,title,body,created_at) VALUES (1,1,'xhs','保留标题','保留正文','2026-10-28 09:00:00')")
    command.upgrade(cfg,'head')
    command.upgrade(cfg,'head')
    with engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT title,body FROM ai_drafts WHERE id=1').one()==('保留标题','保留正文')
        assert len([t for t in inspect(connection).get_table_names() if t.startswith('course_')])==13
        assert connection.exec_driver_sql('SELECT count(*) FROM course_visual_workflows').scalar()==0
        assert connection.exec_driver_sql('SELECT COUNT(*) FROM course_library_drafts').scalar_one()==0
        assert connection.exec_driver_sql('SELECT COUNT(*) FROM course_research').scalar_one()==0
        assert connection.exec_driver_sql('SELECT COUNT(*) FROM course_research_drafts').scalar_one()==0
    with pytest.raises(RuntimeError,match='功能开关回退'):
        command.downgrade(cfg,'60cd5c95fde1')
    assert 'course_offerings' in inspect(engine).get_table_names()
    engine.dispose()
