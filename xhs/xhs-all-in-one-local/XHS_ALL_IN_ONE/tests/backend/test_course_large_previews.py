"""Full-page preview regression checks. Local PDF rendering only; no live AI."""
import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import select

from test_course_library import library
from test_course_library_drafts import setup_pdf, generate, BASE, count
from backend.app.api.ai import get_text_ai_client
from backend.app.main import app
from backend.app.models import AiDraft, DraftAsset, PublishJob, AutoTask, Task
from backend.app.models.course_library_draft import CourseLibraryDraft
from backend.app.services.course_draft_images import frame_page, HEADER_HEIGHT, PREVIEW_LAYOUT


def test_full_width_page_retains_all_four_edges_and_original_ratio(tmp_path):
    source=tmp_path/'source.png';output=tmp_path/'preview.png'
    page=Image.new('RGB',(240,360),'white');draw=ImageDraw.Draw(page)
    for box,color in [((0,0,12,12),'red'),((227,0,239,12),'green'),((0,347,12,359),'blue'),((227,347,239,359),'orange')]:draw.rectangle(box,fill=color)
    page.save(source);original=source.read_bytes()
    dimensions=frame_page(source,output,{'university':'昆士兰大学','course_code':'MKTG1501','term':'2026S2','material_type':'期末复习讲义'},1,73)
    with Image.open(output) as image:
        assert image.size==(1200,1800+HEADER_HEIGHT)
        assert dimensions=={'width':1200,'height':image.height}
        for point,color in [((0,HEADER_HEIGHT),(255,0,0)),((1199,HEADER_HEIGHT),(0,128,0)),
            ((0,image.height-1),(0,0,255)),((1199,image.height-1),(255,165,0))]:
            assert image.getpixel(point)==color
    assert source.read_bytes()==original


def test_native_sample_render_has_no_added_footer_or_cropped_page(library,tmp_path):
    import pypdfium2 as pdfium
    from backend.app.services.course_pdf_renderer import render
    *_,path,row=setup_pdf(library)
    before=path.read_bytes();output=tmp_path/'native.png'
    with pdfium.PdfDocument(before) as document:width,height=document[0].get_size()
    with path.open('rb') as source:render(source.fileno(),1,output,frame_source=True)
    with Image.open(output) as image:
        assert abs(image.height-image.width*height/width)<2
        assert image.getpixel((0,image.height-1))==(255,255,255)
    assert path.read_bytes()==before


@pytest.mark.parametrize('saved',[False,True])
def test_reframe_clones_copy_and_images_without_ai_approval_or_publishing(library,saved):
    c,h,other,factory,w,s,path,row=setup_pdf(library)
    old,_=generate(c,h,row)
    if saved:old=c.post(f'{BASE}/draft-reviews/{old["id"]}/approve',headers=h,json={'reviewed':True,'review_digest':old['review_digest']}).json()
    with factory() as db:
        item=db.get(CourseLibraryDraft,old['id']);original_images=list(item.images)
        source={**item.source_snapshot};source.pop('preview_layout',None);item.source_snapshot=source;db.commit()
        before={m.__tablename__:count(db,m) for m in [AiDraft,DraftAsset,PublishJob,AutoTask,Task]}
    old=c.get(f'{BASE}/draft-reviews/{old["id"]}',headers=h).json()
    old_png=(s.storage_dir/original_images[0]['path']).read_bytes();original_pdf=path.read_bytes();mtime=path.stat().st_mtime_ns
    class NoAI:
        def generate_note(self,**kwargs):pytest.fail('Reframing must not call AI')
    app.dependency_overrides[get_text_ai_client]=lambda:NoAI()
    request={'request_key':str(uuid4()),'title':'MKTG1501保留当前编辑','body':old['body'],'tags':['MKTG1501']}
    url=f'{BASE}/draft-reviews/{old["id"]}/reframe'
    try:
        assert c.post(url,json=request).status_code==401
        assert c.post(url,headers=other,json=request).status_code==404
        response=c.post(url,headers=h,json=request);assert response.status_code==200,response.text
        new=response.json()
        assert new['id']!=old['id'] and new['status']=='pending' and new['draft_id'] is None
        assert new['body']==old['body'] and new['title']==request['title']
        assert new['source']['preview_layout']==PREVIEW_LAYOUT and new['source']['preview_parent_package_id']==old['id']
        assert new['source']['sha256']==hashlib.sha256(original_pdf).hexdigest()
        assert [p['page'] for p in new['images']]==[p['page'] for p in old['images']]
        assert c.get(f'{BASE}/draft-reviews/{old["id"]}',headers=h).json()==old
        assert (s.storage_dir/original_images[0]['path']).read_bytes()==old_png
        assert path.read_bytes()==original_pdf and path.stat().st_mtime_ns==mtime
        assert c.post(url,headers=h,json=request).json()['id']==new['id']
        assert c.post(url,headers=h,json={**request,'body':'changed'}).status_code==409
        with factory() as db:
            assert count(db,CourseLibraryDraft)==2
            assert {m.__tablename__:count(db,m) for m in [AiDraft,DraftAsset,PublishJob,AutoTask,Task]}==before
    finally:app.dependency_overrides.pop(get_text_ai_client,None)


def test_changed_original_blocks_reframe_and_keeps_old_preview(library):
    c,h,_,factory,w,s,path,row=setup_pdf(library);old,_=generate(c,h,row)
    path.write_bytes(path.read_bytes()+b'\n% source changed')
    response=c.post(f'{BASE}/draft-reviews/{old["id"]}/reframe',headers=h,json={'request_key':str(uuid4()),'title':old['title'],'body':old['body'],'tags':old['tags']})
    assert response.status_code==409
    assert c.get(f'{BASE}/draft-reviews/{old["id"]}/images/0',headers=h).status_code==200
    with factory() as db:assert count(db,CourseLibraryDraft)==1
