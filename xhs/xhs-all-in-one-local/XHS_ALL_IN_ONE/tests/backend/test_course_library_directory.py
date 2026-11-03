"""Literal filesystem mirror acceptance; changes only disposable tmp_path fixtures."""
from pathlib import Path
import hashlib
import os
from sqlalchemy import func, select
from test_course_library import library, add_pdf, scan, first_file
from backend.app.models import AiDraft, PublishJob, AutoTask
from backend.app.models.course_library import CourseLibraryFile
from backend.app.models.course_library_draft import CourseLibraryDraft

BASE='/api/course-center/library'


def listing(c,h,path='',**params):
    response=c.get(BASE+'/directory',headers=h,params={'path':path,**params})
    assert response.status_code==200,response.text
    assert 'no-store' in response.headers['cache-control']
    return response.json()


def test_literal_names_levels_empty_directories_and_non_pdf_files_are_preserved(library):
    c,h,_,factory,w,s=library
    pdf=add_pdf(w,'01USYD/本科1/ECON1001/期末复习讲义/版本 A/ECON1001.pdf');scan(w)
    (w.root/'01USYD'/'空文件夹').mkdir();word=pdf.with_suffix('.docx');word.write_bytes(b'WORD fixture')
    (w.root/'.DS_Store').write_bytes(b'OS metadata fixture');(w.root/'.hidden').mkdir()
    before=(pdf.stat().st_mtime_ns,hashlib.sha256(pdf.read_bytes()).hexdigest(),word.read_bytes());row=first_file(factory)
    root=listing(c,h);assert {e['name'] for e in root['items']}=={'01USYD','.DS_Store','.hidden'}
    assert '悉尼大学' not in [e['name'] for e in root['items']]
    first=listing(c,h,'01USYD');assert {e['name'] for e in first['items']}=={'本科1','空文件夹'}
    assert listing(c,h,'01USYD/空文件夹')['items']==[]
    path='01USYD/本科1/ECON1001/期末复习讲义/版本 A';leaf=listing(c,h,path)
    assert leaf['path']==path and leaf['parent_path']=='01USYD/本科1/ECON1001/期末复习讲义'
    assert leaf['folder_count']==0 and leaf['file_count']==2 and leaf['pdf_count']==1
    assert {e['relative_path'] for e in leaf['items']}=={str(f.relative_to(w.root)) for f in [pdf,word]}
    indexed=next(e for e in leaf['items'] if e['is_pdf']);assert indexed['file_id']==row.id and indexed['can_preview']
    assert next(e for e in leaf['items'] if not e['is_pdf'])['file_id'] is None
    assert before==(pdf.stat().st_mtime_ns,hashlib.sha256(pdf.read_bytes()).hexdigest(),word.read_bytes())
    assert first_file(factory).signature==row.signature
    with factory() as db:
        for model in [AiDraft,PublishJob,AutoTask,CourseLibraryDraft]:assert db.scalar(select(func.count()).select_from(model))==0


def test_same_course_under_different_local_branches_is_never_merged(library):
    c,h,_,factory,w,s=library
    paths=['01USYD/本科1/ECON1001/期末复习讲义/a.pdf','01USYD/ECON1001/期末复习讲义/b.pdf','01USYD/研究生/ECON1001/样张/c.pdf']
    for p in paths:add_pdf(w,p)
    scan(w)
    assert {e['name'] for e in listing(c,h,'01USYD')['items']}=={'本科1','ECON1001','研究生'}
    a=listing(c,h,'01USYD/本科1/ECON1001/期末复习讲义')['items'][0]
    b=listing(c,h,'01USYD/ECON1001/期末复习讲义')['items'][0]
    assert a['name']=='a.pdf' and b['name']=='b.pdf' and a['file_id']!=b['file_id']


def test_directory_changes_appear_without_scan_or_reclassification(library):
    c,h,_,factory,w,s=library
    assert listing(c,h)['total_entries']==0
    folder=w.root/'本地新增';folder.mkdir();file=folder/'原名.docx';file.write_bytes(b'first')
    assert listing(c,h)['items'][0]['name']=='本地新增'
    assert listing(c,h,'本地新增')['items'][0]['name']=='原名.docx'
    moved=file.with_name('修改名称.docx');file.rename(moved);moved.write_bytes(b'updated contents')
    current=listing(c,h,'本地新增')['items'];assert len(current)==1 and current[0]['name']=='修改名称.docx' and current[0]['size_bytes']==16
    elsewhere=w.root/'移动目标';elsewhere.mkdir();moved.rename(elsewhere/moved.name)
    assert listing(c,h,'本地新增')['items']==[]
    folder.rename(w.root/'重命名后的空目录')
    assert {e['name'] for e in listing(c,h)['items']}=={'重命名后的空目录','移动目标'}
    assert c.get(BASE+'/directory',headers=h,params={'path':'本地新增'}).status_code==404
    with factory() as db:assert db.scalar(select(func.count()).select_from(CourseLibraryFile))==0


def test_rename_pdf_new_path_shows_before_index_and_old_history_stays(library):
    c,h,_,factory,w,s=library;path=add_pdf(w);scan(w);row=first_file(factory)
    parent=str(path.parent.relative_to(w.root));path.rename(path.with_name('新文件名.pdf'))
    entries=listing(c,h,parent)['items'];assert len(entries)==1 and entries[0]['name']=='新文件名.pdf' and entries[0]['file_id'] is None
    scan(w)
    updated=listing(c,h,parent)['items'][0];assert updated['file_id']!=row.id and updated['can_preview']
    with factory() as db:assert db.get(CourseLibraryFile,row.id).status=='missing' and db.get(CourseLibraryFile,row.id).revision_count==1


def test_path_traversal_symlinks_and_auth_do_not_read_outside_root(library,tmp_path):
    c,h,other,factory,w,s=library
    external=tmp_path/'outside';external.mkdir();(external/'private.txt').write_bytes(b'not exposed')
    (w.root/'linked-folder').symlink_to(external,target_is_directory=True);(w.root/'linked-file.pdf').symlink_to(external/'private.txt')
    entries=listing(c,h)['items'];assert len(entries)==2 and all(e['kind']=='symlink' and not e['can_preview'] for e in entries)
    for path in ['../outside','/tmp','a/../outside','a//b','a/./b','bad\x00name']:
        assert c.get(BASE+'/directory',headers=h,params={'path':path}).status_code==422
    assert c.get(BASE+'/directory',headers=h,params={'path':'linked-folder'}).status_code==404
    assert c.get(BASE+'/files',headers=h,params={'directory_path':'linked-folder'}).status_code==404
    assert c.get(BASE+'/directory').status_code==401
    assert c.get(BASE+'/directory',headers=other).status_code==404
    s.course_library_enabled=False;assert c.get(BASE+'/directory',headers=h).status_code==404


def test_literal_directory_prefix_search_paging_and_no_classification_rewrites(library):
    c,h,_,factory,w,s=library
    for p in ['01USYD/ECON%_1001/a.pdf','01USYD/ECONxx1001/b.pdf','01USYD/ECON%_10010/c.pdf']:
        add_pdf(w,p)
    scan(w)
    files=c.get(BASE+'/files',headers=h,params={'directory_path':'01USYD/ECON%_1001'}).json()
    assert files['total']==1 and files['items'][0]['filename']=='a.pdf'
    for n in range(75):(w.root/f'file{n}.docx').write_bytes(b'fixture')
    root=listing(c,h,page_size=10,page=2);assert root['total']==76 and len(root['items'])==10
    names=[e['name'] for e in listing(c,h,page_size=100)['items']];assert names.index('file2.docx')<names.index('file10.docx')
    match=listing(c,h,q='file20');assert [e['name'] for e in match['items']]==['file20.docx']
    assert listing(c,h,q='%_')['items']==[]
    assert [e['name'] for e in listing(c,h,'01USYD',q='%_')['items']]==['ECON%_1001','ECON%_10010']
    assert c.get(BASE+'/directory',headers=h,params={'page_size':201}).status_code==422


def test_existing_preview_and_review_records_use_the_same_index_id(library):
    from test_course_library_drafts import generate
    c,h,_,factory,w,s=library;path=add_pdf(w,label='Elasticity measures the responsiveness of quantity to price changes.');scan(w);row=first_file(factory)
    review,_=generate(c,h,row)
    result=listing(c,h,str(path.parent.relative_to(w.root)));entry=result['items'][0]
    assert entry['file_id']==row.id and entry['relative_path']==str(path.relative_to(w.root))
    assert c.get(f'{BASE}/files/{entry["file_id"]}/preview',headers=h).status_code==200
    history=c.get(f'{BASE}/files/{entry["file_id"]}/drafts',headers=h).json()['items'];assert history[0]['id']==review['id'] and history[0]['status']=='pending'
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(CourseLibraryDraft))==1
        assert db.scalar(select(func.count()).select_from(PublishJob))==0


def test_offline_root_does_not_expose_stale_directory_but_preserves_index(library):
    c,h,_,factory,w,s=library;add_pdf(w);scan(w);row=first_file(factory)
    offline=w.root.with_name('offline-root');w.root.rename(offline)
    assert c.get(BASE+'/directory',headers=h).status_code==503
    assert db_file_exists(factory,row.id)
    offline.rename(w.root)
    assert listing(c,h)['items'][0]['name']=='01USYD'


def db_file_exists(factory,file_id):
    with factory() as db:return db.get(CourseLibraryFile,file_id) is not None
