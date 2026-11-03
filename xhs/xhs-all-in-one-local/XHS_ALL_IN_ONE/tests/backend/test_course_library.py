"""Local PDF watcher acceptance. All mutations are in disposable tmp_path roots."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import importlib
import os
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from backend.app.main import app
from backend.app.core.database import Base, get_db
from backend.app.models import User, AiDraft, PublishJob, AutoTask
from backend.app.models.course_center import CourseMaterialProduct, CourseMaterialVersion
from backend.app.models.course_library import CourseLibraryFile, CourseLibraryRevision
from backend.app.services.course_library_service import CourseLibraryWatcher
from backend.app.services.course_library_paths import classify, safe_path


def pdf_bytes(label='SYNTHETIC LOCAL TEST'):
    """Tiny valid test protocol fixture, not a user/course deliverable."""
    stream=f'BT /F1 24 Tf 60 700 Td ({label}) Tj ET'.encode()
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    data=b'%PDF-1.4\n';offsets=[]
    for n,obj in enumerate(objects,1):offsets.append(len(data));data+=f'{n} 0 obj\n'.encode()+obj+b'\nendobj\n'
    start=len(data);data+=f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode()
    data+=b''.join(f'{o:010} 00000 n \n'.encode() for o in offsets)
    return data+f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()


@pytest.fixture
def library(tmp_path,monkeypatch):
    from backend.app.api import course_library
    main=importlib.import_module('backend.app.main')
    monkeypatch.setattr(main,'init_db',lambda:None)
    monkeypatch.setattr(main,'start_course_library',lambda:None)
    engine=create_engine(f'sqlite:///{tmp_path/"test.db"}',connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine);factory=sessionmaker(bind=engine)
    def override():
        with factory() as db:yield db
    app.dependency_overrides[get_db]=override
    root=tmp_path/'题库';root.mkdir()
    with TestClient(app) as client:
        h={'Authorization':'Bearer '+client.post('/api/auth/register',json={'username':'pdf-owner','password':'secret123'}).json()['access_token']}
        other={'Authorization':'Bearer '+client.post('/api/auth/register',json={'username':'pdf-other','password':'secret123'}).json()['access_token']}
        with factory() as db:owner=db.scalar(select(User.id).where(User.username=='pdf-owner'))
        settings=SimpleNamespace(course_center_enabled=True,course_library_enabled=True,course_library_owner_id=owner,course_library_root=str(root),
            course_library_stable_seconds=0,course_library_reconcile_seconds=5,storage_dir=tmp_path/'storage')
        monkeypatch.setattr(course_library,'get_settings',lambda:settings)
        watcher=CourseLibraryWatcher(root,owner,factory,stable_seconds=0,reconcile_seconds=5);watcher.initialize()
        yield client,h,other,factory,watcher,settings
    app.dependency_overrides.pop(get_db,None);engine.dispose()


def add_pdf(watcher,relative='01USYD/本科1/ECON1001/期末复习讲义/ECON1001_26S2_Final.pdf',label='SYNTHETIC LOCAL TEST'):
    path=watcher.root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(pdf_bytes(label));return path


def scan(watcher):
    watcher.full_scan()
    for _ in range(10):
        if not watcher.process_ready(100):break


def first_file(factory):
    with factory() as db:return db.scalar(select(CourseLibraryFile))


def test_initial_index_and_course_product_are_read_only_and_separate_from_xhs(library):
    c,h,_,factory,w,_=library;path=add_pdf(w);before=(path.stat().st_mtime_ns,hashlib.sha256(path.read_bytes()).hexdigest());scan(w)
    row=first_file(factory);assert row.status=='ready' and row.course_code=='ECON1001' and row.university=='悉尼大学' and row.term=='2026S2'
    with factory() as db:
        product=db.get(CourseMaterialProduct,row.product_id);version=db.scalar(select(CourseMaterialVersion))
        assert product.listing_status=='not_listed' and version.qa_status=='pending' and version.file_status=='verified'
        assert version.source_reference.startswith('library://')
        for model in (AiDraft,PublishJob,AutoTask):assert db.scalar(select(func.count()).select_from(model))==0
    assert before==(path.stat().st_mtime_ns,hashlib.sha256(path.read_bytes()).hexdigest())
    assert c.get('/api/course-center/library/status',headers=h).json()['products']==1


def test_updates_keep_product_and_revisions_touch_is_not_duplicate_and_restart_resumes(library):
    _,__,___,factory,w,_=library;path=add_pdf(w);scan(w);before=first_file(factory)
    path.write_bytes(pdf_bytes('SECOND CONTENT VERSION'));scan(w);after=first_file(factory)
    assert after.product_id==before.product_id and after.revision_count==2 and after.current_revision_id!=before.current_revision_id
    os.utime(path,None);scan(w);assert first_file(factory).revision_count==2
    restarted=CourseLibraryWatcher(w.root,w.owner_id,factory,stable_seconds=0);restarted.initialize();scan(restarted)
    assert first_file(factory).revision_count==2
    path.write_bytes(pdf_bytes());scan(w)
    reverted=first_file(factory);assert reverted.current_revision_id==before.current_revision_id and reverted.revision_count==2
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(CourseMaterialVersion))==2


def test_wait_for_stable_write_and_file_changed_during_read_is_retried(library):
    _,__,___,factory,w,_=library;path=add_pdf(w);w.stable_seconds=15;w.full_scan()
    assert w.process_ready()==0 and first_file(factory).status=='pending'
    w.stable_seconds=0;w.pending={str(path.relative_to(w.root)):(0,0,0)}
    path.write_bytes(pdf_bytes('CHANGED AFTER OBSERVATION'))
    w.process_ready();assert first_file(factory).revision_count==0 and w.dirty
    w.observe(str(path.relative_to(w.root)));w.process_ready();assert first_file(factory).status=='ready'


def test_unclear_school_stays_pending_and_symlinks_hidden_and_non_pdf_are_ignored(library,tmp_path):
    _,__,___,factory,w,_=library
    add_pdf(w,'bism3101/notes.pdf');outside=tmp_path/'outside.pdf';outside.write_bytes(pdf_bytes())
    (w.root/'linked.pdf').symlink_to(outside);add_pdf(w,'.hidden/hidden.pdf');(w.root/'notes.docx').write_text('fixture')
    scan(w);row=first_file(factory)
    with factory() as db:assert db.scalar(select(func.count()).select_from(CourseLibraryFile))==1
    assert row.product_id is None and row.university=='' and row.classification_status=='needs_confirmation'
    for rel in ['../outside.pdf',str(outside),'linked.pdf','.hidden/hidden.pdf']:
        with pytest.raises(ValueError):safe_path(w.root,rel)


def test_missing_or_offline_keeps_index_and_history(library):
    _,__,___,factory,w,_=library;path=add_pdf(w);scan(w)
    moved=w.root.parent/'offline-root';w.root.rename(moved)
    assert w.full_scan() is False and first_file(factory).status=='ready'
    moved.rename(w.root);path.rename(path.with_suffix('.gone'))
    scan(w);assert first_file(factory).status=='missing' and first_file(factory).revision_count==1
    path.with_suffix('.gone').rename(path);scan(w);assert first_file(factory).status=='ready' and first_file(factory).revision_count==1


def test_auth_owner_and_disabled_scope_and_no_raw_pdf_endpoint(library):
    c,h,other,factory,w,s=library;add_pdf(w);scan(w);row=first_file(factory)
    assert c.get('/api/course-center/library/status').status_code==401
    assert c.get('/api/course-center/library/files',headers=other).status_code==404
    assert c.get(f'/api/course-center/library/files/{row.id}',headers=other).status_code==404
    assert c.get(f'/api/course-center/library/files/{row.id}/preview',headers=other).status_code==404
    assert c.get(f'/api/course-center/library/files/{row.id}/download',headers=h).status_code==404
    s.course_library_enabled=False
    assert c.get('/api/course-center/library/files',headers=h).status_code==404
    assert first_file(factory).status=='ready'


def test_private_watermarked_preview_and_page_limits_do_not_change_original(library):
    from PIL import Image
    import io
    c,h,_,factory,w,_=library;path=add_pdf(w);scan(w);row=first_file(factory);before=path.read_bytes()
    response=c.get(f'/api/course-center/library/files/{row.id}/preview',headers=h)
    assert response.status_code==200,response.text
    assert response.headers['content-type']=='image/png' and 'no-store' in response.headers['cache-control']
    image=Image.open(io.BytesIO(response.content));assert image.width>500 and image.height>700
    bottom=image.getpixel((5,image.height-5));assert bottom[2]>bottom[0]
    detail=c.get(f'/api/course-center/library/files/{row.id}',headers=h).json()
    assert detail['revisions'][0]['page_count']==1 and path.read_bytes()==before
    assert c.get(f'/api/course-center/library/files/{row.id}/preview?page=2',headers=h).status_code==400
    duplicate=add_pdf(w,'01USYD/ECON1001/期末复习讲义/same-content-copy.pdf');scan(w)
    with factory() as db:copy=db.scalar(select(CourseLibraryFile).where(CourseLibraryFile.filename==duplicate.name))
    assert c.get(f'/api/course-center/library/files/{copy.id}/preview',headers=h).status_code==200
    assert c.get(f'/api/course-center/library/files/{copy.id}',headers=h).json()['revisions'][0]['page_count']==1


def test_cached_preview_refuses_changed_file_and_old_version(library):
    c,h,_,factory,w,_=library;path=add_pdf(w);scan(w);row=first_file(factory)
    assert c.get(f'/api/course-center/library/files/{row.id}/preview',headers=h).status_code==200
    path.write_bytes(pdf_bytes('UPDATED FILE'))
    assert c.get(f'/api/course-center/library/files/{row.id}/preview',headers=h).status_code==409
    scan(w)
    assert c.get(f'/api/course-center/library/files/{row.id}/preview?revision_id={row.current_revision_id}',headers=h).status_code==409
    assert c.get(f'/api/course-center/library/files/{row.id}/preview',headers=h).status_code==200


def test_invalid_pdf_visible_and_can_recover_after_update(library):
    c,h,_,factory,w,_=library;path=add_pdf(w);path.write_bytes(b'not a pdf');scan(w)
    row=first_file(factory);assert row.status=='error' and row.revision_count==0
    path.write_bytes(b'%PDF-1.4 invalid structure');scan(w)
    row=first_file(factory);assert c.get(f'/api/course-center/library/files/{row.id}/preview',headers=h).status_code==422
    path.write_bytes(pdf_bytes());scan(w);assert first_file(factory).status=='ready'
    assert c.get(f'/api/course-center/library/files/{row.id}/preview',headers=h).status_code==200


def test_real_local_watcher_detects_new_and_updated_pdf_without_scheduler(library):
    _,__,___,factory,w,_=library
    def wait_for(predicate):
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            if predicate():return
            time.sleep(.05)
        raise AssertionError('Local watcher did not observe the fixture within 10 seconds')
    w.start()
    try:
        path=add_pdf(w)
        wait_for(lambda:(r:=first_file(factory)) is not None and r.status=='ready')
        path.write_bytes(pdf_bytes('LIVE UPDATE EVENT'))
        wait_for(lambda:first_file(factory).revision_count==2)
        with factory() as db:assert db.scalar(select(func.count()).select_from(AutoTask))==0
    finally:w.stop()


def test_directory_classification_does_not_guess_from_course_code_or_final_name():
    assert classify('bism3101/FINM1415_FINAL.pdf')['university']==''
    assert classify('01USYD/ECON1001/ECON1001_FINAL.pdf')['material_type']==''
    assert classify('000英国/1.曼彻斯特大学/BMAN10001 Economic Principles/期末模拟卷/paper.pdf')['course_code']=='BMAN10001'
    assert classify('01USYD/MATH2088-2988/期末模拟卷/paper.pdf')['course_code']==''
    assert classify('LSE/EC1A3/期末模拟卷/LSE_EC1A3_26AT_FinalMock.pdf')['course_code']=='EC1A3'
    assert classify('LSE/MA100/03_期末复习讲义/_LSE_MA100_26-27FY_FinalRevision.pdf')['term']=='2026-27FY'
    assert classify('LSE/MA100/03_期末复习讲义/_LSE_MA100_26-27FY_FinalRevision.pdf')['material_type']=='期末复习讲义'
    assert classify('06昆士兰大学/ECON1011/期末复习讲义/P26S2-UQ__ECON1011__FinalRevision.pdf')['term']=='2026S2'
def test_folder_hierarchy_counts_and_scoped_files_do_not_mix_schools(library):
    c,h,_,factory,w,_=library
    add_pdf(w,'01USYD/ECON1001/期末复习讲义/a.pdf')
    add_pdf(w,'01USYD/ECON1001/期末模拟卷/b.pdf')
    add_pdf(w,'02墨大/ECON1001/期末复习讲义/c.pdf')
    scan(w)
    before=first_file(factory)
    root=c.get('/api/course-center/library/folders',headers=h).json()
    assert root['depth']==0 and root['total']==2 and root['total_files']==3
    assert sum(folder['file_count'] for folder in root['items'])==3
    uni={'scope_university':'悉尼大学'}
    courses=c.get('/api/course-center/library/folders',headers=h,params=uni).json()
    assert courses['depth']==1 and [(f['value'],f['file_count']) for f in courses['items']]==[('ECON1001',2)]
    course={**uni,'scope_course':'ECON1001'}
    types=c.get('/api/course-center/library/folders',headers=h,params=course).json()
    assert types['depth']==2 and {f['value'] for f in types['items']}=={'期末复习讲义','期末模拟卷'}
    leaf={**course,'scope_type':'期末复习讲义'}
    files=c.get('/api/course-center/library/files',headers=h,params=leaf).json()
    assert files['total']==1 and files['items'][0]['filename']=='a.pdf'
    assert c.get('/api/course-center/library/folders',headers=h,params=leaf).json()['depth']==3
    assert first_file(factory).signature==before.signature and first_file(factory).revision_count==before.revision_count


def test_pending_folder_empty_value_is_an_exact_scope_not_all_files(library):
    c,h,_,__,w,_=library
    add_pdf(w,'unclear/notes.pdf');add_pdf(w,'01USYD/ECON1001/untyped.pdf');add_pdf(w)
    scan(w)
    root=c.get('/api/course-center/library/folders',headers=h).json()
    pending=next(f for f in root['items'] if f['pending'])
    assert pending['value']=='' and pending['file_count']==1 and pending['label']=='大学待确认'
    assert c.get('/api/course-center/library/files',headers=h,params={'scope_university':''}).json()['total']==1
    course={'scope_university':'悉尼大学','scope_course':'ECON1001'}
    types=c.get('/api/course-center/library/folders',headers=h,params=course).json()
    assert next(f for f in types['items'] if f['pending'])['file_count']==1
    leaf=c.get('/api/course-center/library/files',headers=h,params={**course,'scope_type':''}).json()
    assert leaf['total']==1 and leaf['items'][0]['filename']=='untyped.pdf'


def test_folder_search_filter_pagination_and_access_are_bounded(library):
    c,h,other,_,w,_=library
    add_pdf(w);add_pdf(w,'02墨大/ECON1001/期末复习讲义/other.pdf');scan(w)
    response=c.get('/api/course-center/library/folders',headers=h,params={'page_size':1}).json()
    assert response['total']==2 and len(response['items'])==1
    assert c.get('/api/course-center/library/folders',headers=h,params={'folder_q':'悉尼'}).json()['items'][0]['value']=='悉尼大学'
    assert c.get('/api/course-center/library/folders',headers=h,params={'state':'error'}).json()['total']==0
    assert c.get('/api/course-center/library/folders').status_code==401
    assert c.get('/api/course-center/library/folders',headers=other).status_code==404
    assert c.get('/api/course-center/library/folders',headers=h,params={'scope_course':'ECON1001'}).status_code==422
    assert c.get('/api/course-center/library/files',headers=h,params={'scope_type':'期末复习讲义'}).status_code==422
    assert c.get('/api/course-center/library/folders',headers=h,params={'page_size':1000}).status_code==422

