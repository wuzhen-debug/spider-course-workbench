"""Alphabetic browsing keeps literal paths and whole letters; no manual pagination."""
from pathlib import Path
import json
from sqlalchemy import func, select
from test_course_library import library
from backend.app.models.course_library import CourseLibraryFile
from backend.app.services.course_library_directory import alphabetic_groups, course_initial

BASE='/api/course-center/library/directory'


def entries(counts):
    return [{'kind':'directory','name':f'{letter}CODE{n:04}','relative_path':f'01USYD/{letter}CODE{n:04}'} for letter,count in counts.items() for n in range(count)]


def make_folders(root,counts):
    parent=root/'01USYD';parent.mkdir(exist_ok=True)
    for entry in entries(counts):(root/entry['relative_path']).mkdir(exist_ok=True)
    return parent


def get(c,h,**params):
    response=c.get(BASE,headers=h,params={'path':'01USYD','alphabetic':True,**params})
    assert response.status_code==200,response.text
    assert 'no-store' in response.headers['cache-control']
    return response.json()


def test_sparse_adjacent_letters_pack_near_target_without_splitting_or_mutating():
    original=entries({'A':28,'B':31,'C':31,'D':6,'E':74,'F':17,'G':13,'H':9,'I':22,'J':2,'K':1,'L':17,'M':43,'N':2,'O':17,'P':27,'Q':10,'S':15,'W':7})
    before=json.dumps(original,sort_keys=True);groups=alphabetic_groups(original)
    assert [(g['key'],g['count']) for g in groups]==[('A-B',59),('C-D',37),('E',74),('F-I',61),('J-M',63),('N-W',78)]
    flattened=[entry['relative_path'] for group in groups for entry in group['items']]
    assert len(flattened)==len(set(flattened))==len(original) and set(flattened)=={e['relative_path'] for e in original}
    assert json.dumps(original,sort_keys=True)==before
    for letter in 'ABCDEFGHIJKLMNOPSQW':
        matching=[group for group in groups if any(item['initial']==letter for item in group['letters'])]
        assert len(matching)==1


def test_small_and_large_letters_and_non_course_entries_keep_every_path():
    sparse=alphabetic_groups(entries({'A':3,'B':4,'C':5}));assert [(g['key'],g['count']) for g in sparse]==[('A-C',12)]
    source=entries({'A':125,'B':20,'C':2})+[{'kind':'file','name':'guide.pdf','relative_path':'01USYD/guide.pdf'},{'kind':'directory','name':'说明','relative_path':'01USYD/说明'}]
    groups=alphabetic_groups(source)
    assert [(g['key'],g['count']) for g in groups]==[('A',125),('B-C',22),('other',2)]
    assert len(groups[0]['items'])==125  # A is never split into conventional pages.
    assert course_initial({'kind':'directory','name':'amme1802'})=='A'
    assert course_initial({'kind':'directory','name':'BANK 3012'})=='B'
    assert course_initial({'kind':'file','name':'ACCT1006.pdf'}) is None
    assert alphabetic_groups(entries({'A':5})+[{'kind':'file','name':'a.pdf'}])==[]


def test_api_combined_group_and_all_mode_are_complete_and_read_only(library):
    c,h,_,factory,w,s=library;parent=make_folders(w.root,{'A':28,'B':31,'C':31,'D':6,'E':74})
    (parent/'notes').mkdir();document=parent/'说明.docx';document.write_bytes(b'fixture')
    before={p.name:(p.stat().st_ino,p.stat().st_mtime_ns) for p in parent.iterdir()}
    first=get(c,h);assert first['active_group']=='A-B' and len(first['items'])==59 and first['total']==172
    assert [e['name'][0] for e in first['items']]==['A']*28+['B']*31
    assert [g['key'] for g in first['groups']]==['A-B','C-D','E','other']
    cd=get(c,h,group_key='C-D');assert cd['active_group']=='C-D' and len(cd['items'])==37
    e=get(c,h,group_key='E',page_size=1,page=3);assert e['active_group']=='E' and len(e['items'])==74 and e['page']==1
    other=get(c,h,group_key='other');assert {e['name'] for e in other['items']}=={'notes','说明.docx'}
    all_items=get(c,h,group_key='all');assert all_items['active_group']=='all' and len(all_items['items'])==172
    assert {e['name'] for e in all_items['items']}=={p.name for p in parent.iterdir()}
    assert before=={p.name:(p.stat().st_ino,p.stat().st_mtime_ns) for p in parent.iterdir()}
    with factory() as db:assert db.scalar(select(func.count()).select_from(CourseLibraryFile))==0


def test_selection_follows_initial_if_automatic_group_boundaries_change(library):
    c,h,_,__,w,s=library;make_folders(w.root,{'A':90,'B':31,'C':31,'D':6,'E':74})
    result=get(c,h,group_key='C-D')
    assert result['active_group']=='B-C' and len(result['items'])==62
    assert 'C' in {letter['initial'] for group in result['groups'] if group['key']==result['active_group'] for letter in group['letters']}
    assert get(c,h,group_key='all')['active_group']=='all'


def test_leaf_and_single_initial_directories_return_all_files_without_paging(library):
    c,h,_,factory,w,s=library;parent=w.root/'leaf';parent.mkdir()
    for n in range(205):(parent/f'notes{n}.docx').write_bytes(b'fixture')
    (parent/'ECON1001').mkdir()
    result=get(c,h,path='leaf');assert result['groups']==[] and len(result['items'])==206 and result['total']==206
    legacy=c.get(BASE,headers=h,params={'path':'leaf','page_size':200}).json();assert len(legacy['items'])==200
    empty=parent/'空目录';empty.mkdir()
    assert get(c,h,path='leaf/空目录')['items']==[]


def test_search_spans_groups_and_new_mode_keeps_auth_and_path_boundaries(library):
    c,h,other,_,w,s=library;make_folders(w.root,{'A':28,'B':31,'C':31})
    result=get(c,h,group_key='A-B',q='CCODE');assert result['total']==31 and len(result['items'])==31 and all(e['name'].startswith('C') for e in result['items'])
    assert get(c,h,group_key='A-B',q='not-there')['items']==[]
    params={'path':'01USYD','alphabetic':True,'group_key':'all'}
    assert c.get(BASE,params=params).status_code==401
    assert c.get(BASE,headers=other,params=params).status_code==404
    assert c.get(BASE,headers=h,params={**params,'path':'../outside'}).status_code==422
