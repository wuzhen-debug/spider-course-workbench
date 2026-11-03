"""Isolated API, actual local render and human-review gates; no live AI/publish."""
from uuid import uuid4
from copy import deepcopy
from datetime import timedelta
import hashlib
import pytest
from sqlalchemy import select, func
from test_course_research import research, FakePC
from test_course_library import library
from backend.app.main import app
from backend.app.api.ai import get_text_ai_client
from backend.app.models import AiDraft, PublishJob, AutoTask, DraftAsset
from backend.app.models.course_library import CourseLibraryFile
from backend.app.models.course_research import CourseResearch, CourseResearchDraft
from backend.app.models.course_visual_workflow import CourseVisualWorkflow

BASE='/api/course-center/visual-workflows'


def call(r, row, route, payload=None, expected=200):
    c,h,*_=r
    got=c.post(f'{BASE}/{row["id"]}/{route}',headers=h,json={'expected_version':row['row_version'],**(payload or {})})
    assert got.status_code==expected,got.text
    return got.json()


def make(r):
    c,h,_,factory,*_=r
    with factory() as db:f=db.scalar(select(CourseLibraryFile).where(CourseLibraryFile.filename.like('%Final%')));fid,rid=f.id,f.current_revision_id
    response=c.post(BASE,headers=h,json={'file_id':fid,'revision_id':rid,'brand_id':'xingtu','request_key':str(uuid4())})
    assert response.status_code==200,response.text
    return response.json()


def copy_ready(r):
    c,h,_,__,___,____,account=r;row=make(r)
    row=call(r,row,'search',{'keyword':'MAST10007','account_id':account,'sort':4})
    row=call(r,row,'read',{'source_id':row['data']['evidence'][0]['id'],'account_id':account})
    copy={'topic':'线性无关怎么判断','title':'MAST10007怎么独立练习','body':'先检查适用条件，再独立练习，对照真实解析补齐判断理由。','tags':['MAST10007'],'takeaway':'说明条件和检查方法'}
    plan={**row['data']['visual_plan'],'sample_pages':[1],'sample_instructions':['读题后独立练习，再对照解析。'],'cover_lines':['公式与条件','如何连接解题'],'method_text':'先确认对象与条件。\n独立作答后，核对理由与结论。','method_layout':'flow','method_nodes':['读题｜确认对象','核查｜说明理由']}
    got=c.patch(f'{BASE}/{row["id"]}',headers=h,json={'expected_version':row['row_version'],'copy':copy,'visual_plan':plan,'selected_source_ids':[row['data']['evidence'][0]['id']]})
    assert got.status_code==200,got.text
    return got.json()


def approve(r,row,stage):return call(r,row,'approve',{'stage':stage,'reviewed':True,'digest':row['digests'][stage]})


def test_owner_permissions_and_no_automatic_side_effects(research):
    c,h,other,factory,w,*_=research;row=make(research)
    assert c.get(BASE).status_code==401
    assert c.get(f'{BASE}/{row["id"]}',headers=other).status_code==404
    assert c.get(BASE+'/catalog',headers=other).status_code==404
    with factory() as db:
        for model in [AiDraft,PublishJob,AutoTask,DraftAsset]:assert db.scalar(select(func.count()).select_from(model))==0
    assert row['data']['approvals']=={} and not row['publishing_enabled']


def test_history_is_scoped_to_requested_pdf_and_owner(research):
    c,h,other,factory,*_=research;row=make(research)
    with factory() as db:
        original=db.get(CourseLibraryFile,row['file_id'])
        second=CourseLibraryFile(user_id=original.user_id,root_id=original.root_id,relative_path='other-course.pdf',filename='Other-course.pdf',course_code='OTHER1000',status='ready')
        db.add(second);db.flush();second_id=second.id
        data=deepcopy(row['data']);data['source']['course_code']='OTHER1000'
        newer=CourseVisualWorkflow(user_id=original.user_id,file_id=second.id,request_key=str(uuid4()),data=data)
        db.add(newer);db.commit()
    all_items=c.get(BASE,headers=h).json()['items']
    assert len(all_items)==2 and all_items[0]['file_id']==second_id
    items=c.get(BASE,headers=h,params={'file_id':row['file_id']}).json()['items']
    assert len(items)==1 and items[0]['id']==row['id'] and items[0]['file_id']==row['file_id']
    assert c.get(BASE,headers=other,params={'file_id':row['file_id']}).status_code==404
    assert c.get(BASE,headers=h,params={'file_id':99999999}).status_code==404


def test_cannot_skip_copy_cover_or_set_gates(research):
    row=make(research)
    call(research,row,'render',{'stage':'cover'},409)
    call(research,row,'render',{'stage':'set'},409)
    call(research,row,'export',{'reviewed':True,'digest':row['digests']['set']},409)
    call(research,row,'approve',{'stage':'copy','reviewed':True,'digest':row['digests']['copy']},422)
    call(research,row,'approve',{'stage':'copy','reviewed':True,'limited_sources_reviewed':True,'digest':row['digests']['copy']},422)
    call(research,row,'approve',{'stage':'cover','reviewed':True,'digest':row['digests']['cover']},409)


def test_real_png_svg_single_revision_and_idempotent_new_draft(research):
    c,h,other,factory,w,*_=research;originals={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in w.root.rglob('*.pdf')}
    row=approve(research,copy_ready(research),'copy');row=call(research,row,'render',{'stage':'cover'})
    assert row['data']['cover']['width']==1080 and not row['approved']['cover']
    call(research,row,'render',{'stage':'set'},409)
    row=approve(research,row,'cover');row=call(research,row,'render',{'stage':'set'})
    assert len(row['data']['images'])==4 and not row['approved']['set']
    image=row['data']['images'][1]
    assert c.get(f'{BASE}/{row["id"]}/images/{image["id"]}',headers=h).content.startswith(b'\x89PNG')
    assert b'<svg' in c.get(f'{BASE}/{row["id"]}/images/{image["id"]}',headers=h,params={'source':True}).content
    assert c.get(f'{BASE}/{row["id"]}/images/{image["id"]}',headers=other).status_code==404
    old_id=image['id'];brief={**image['brief'],'title':'用条件和检查连接解题'}
    row=call(research,row,'revise',{'asset_id':old_id,'brief':brief})
    assert row['data']['images'][1]['id']!=old_id and row['approved']['cover'] and not row['approved']['set']
    assert c.get(f'{BASE}/{row["id"]}/images/{old_id}',headers=h).status_code==200
    row=approve(research,row,'set');version=row['row_version'];digest=row['digests']['set']
    row=call(research,row,'export',{'reviewed':True,'digest':digest});draft_id=row['data']['export']['draft_id']
    assert row['data']['export']['draft_available']
    snapshot=row['data']['export']['snapshot']
    assert snapshot['version']==1 and snapshot['source']==row['data']['source'] and snapshot['copy']==row['data']['copy']
    assert snapshot['approvals']==row['data']['approvals'] and snapshot['workflow_revision']==row['data']['revision']
    assert snapshot['workflow_digest']==digest and snapshot['source_research_id']==row['data']['research_id']
    assert snapshot['draft_id']==draft_id and snapshot['draft_created_at']
    assert [a['sha256'] for a in snapshot['materials']]==[a['sha256'] for a in row['data']['images']]
    retry=c.post(f'{BASE}/{row["id"]}/export',headers=h,json={'expected_version':version,'reviewed':True,'digest':digest})
    assert retry.status_code==200 and retry.json()['data']['export']['draft_id']==draft_id
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AiDraft))==1
        assert snapshot['draft_created_at']==db.get(AiDraft,draft_id).created_at.isoformat()
        assert db.scalar(select(func.count()).select_from(DraftAsset))==4
        assert db.scalar(select(func.count()).select_from(PublishJob))==db.scalar(select(func.count()).select_from(AutoTask))==0
    assert originals=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in w.root.rglob('*.pdf')}


@pytest.mark.parametrize('change', ['deleted', 'reused'])
def test_export_views_validate_current_and_historical_identity_without_writing(research, change):
    from backend.app.services import course_visual_workflow as flow
    from backend.app.services.course_draft_origin import draft_binding
    c, h, _, factory, *_ = research
    row = make(research)
    with factory() as db:
        run = db.get(CourseVisualWorkflow, row['id'])
        draft = AiDraft(user_id=run.user_id, platform='xhs', title='Original', body='Original text', tags=[])
        db.add(draft); db.flush()
        state = deepcopy(run.data)
        state['copy'] = {**state['copy'], 'title': draft.title, 'body': draft.body}
        state['export'] = {'draft_id': draft.id, 'at': draft.created_at.isoformat(),
            'digest': flow.fingerprint(state, 'set'), 'snapshot': draft_binding(draft)}
        run.data = flow.checkpoint(state, 'Preserve exported historical version')
        db.commit(); draft_id = draft.id; stored = deepcopy(run.data)
    current = c.get(f'{BASE}/{row["id"]}', headers=h).json()
    assert current['data']['export']['draft_available']
    assert current['data']['history'][-1]['export']['draft_available']
    with factory() as db:
        run = db.get(CourseVisualWorkflow, row['id'])
        assert run.data == stored and 'draft_available' not in run.data['export']
        draft = db.get(AiDraft, draft_id)
        if change == 'deleted':
            db.delete(draft)
        else:
            draft.created_at += timedelta(days=1)
            draft.title = 'A different new draft'; draft.body = 'New content'
        db.commit()
    current = c.get(f'{BASE}/{row["id"]}', headers=h).json()
    assert not current['data']['export']['draft_available']
    assert not current['data']['history'][-1]['export']['draft_available']
    blocked = c.post(f'{BASE}/{row["id"]}/export', headers=h, json={
        'expected_version': current['row_version'], 'reviewed': True, 'digest': current['digests']['set']})
    assert blocked.status_code == 409
    with factory() as db:
        assert db.get(CourseVisualWorkflow, row['id']).data == stored
        assert db.scalar(select(func.count()).select_from(AiDraft)) == (0 if change == 'deleted' else 1)


def research_handoff_ready(r, read=True, brand='星途留学'):
    from test_course_research import BASE as RBASE, create, search, generate
    c,h,_,factory,__,___,account=r
    origin=search(r,create(r))
    if read:
        got=c.post(f'{RBASE}/{origin["id"]}/sources/{origin["evidence"][0]["id"]}/read',headers=h,json={'account_id':account})
        assert got.status_code==200,got.text
        origin=got.json()
    with factory() as db:
        f=db.scalar(select(CourseLibraryFile).where(CourseLibraryFile.filename.like('%Final%')));fid,rid=f.id,f.current_revision_id
    draft,_=generate(r,origin,material_ids=[fid],brand=brand)
    got=c.patch(f'{RBASE}/{origin["id"]}/drafts/{draft["id"]}',headers=h,json={'title':'MAST10007先检查什么','body':'先独立判断线性无关，再对照期末复习讲义检查条件与理由。','tags':['MAST10007']})
    assert got.status_code==200,got.text
    return origin,got.json(),{'research_id':origin['id'],'research_draft_id':draft['id'],'file_id':fid,'revision_id':rid}


def handoff_plan(r,payload):
    c,h,*_=r
    got=c.post(BASE+'/from-research/plan',headers=h,json=payload)
    assert got.status_code==200,got.text
    return got.json()


def handoff_payload(payload,plan,**kw):
    return {**payload,'reviewed':True,'review_digest':plan['review_digest'],'request_key':str(uuid4()),**kw}


def test_research_handoff_keeps_exact_copy_evidence_pdf_and_manual_gates(research):
    c,h,_,factory,*_=research;origin,draft,payload=research_handoff_ready(research)
    with factory() as db:
        record=db.get(CourseResearch,origin['id']);extra=deepcopy(record.evidence[0]);extra['id']='unselected-source'
        extra['comments']=[{'comment_id':'unused-question','content':'其他课程怎么选择？','like_count':None}]
        record.evidence=[*record.evidence,extra];db.commit()
    calls=deepcopy(FakePC.calls);plan=handoff_plan(research,payload)
    assert {k:plan['copy'][k] for k in ['title','body','tags']}=={k:draft[k] for k in ['title','body','tags']}
    assert plan['source']['revision_id']==payload['revision_id'] and len(plan['source']['sha256'])==64
    assert plan['evidence']==draft['brief']['sources'] and plan['changed_since_draft']=={'sources':[],'material':False}
    assert plan['evidence_review'] == plan['source_quality']
    assert plan['evidence_review']['source_count'] == 1 and plan['evidence_review']['detail_count'] == 1
    assert not plan['evidence_review']['limited']
    assert 'DO_NOT_SEND_TO_AI' not in str(plan)
    request=handoff_payload(payload,plan)
    assert c.post(BASE+'/from-research',headers=h,json={**request,'reviewed':False}).status_code==409
    assert c.post(BASE+'/from-research',headers=h,json={**request,'review_digest':'0'*64}).status_code==409
    with factory() as db:assert db.scalar(select(func.count()).select_from(CourseVisualWorkflow))==0
    got=c.post(BASE+'/from-research',headers=h,json=request);assert got.status_code==200,got.text
    row=got.json();assert row['approved']=={'copy':True,'cover':False,'set':False}
    trace=row['data']['production_trace'][-1]
    assert trace['step']=='research_handoff' and trace['source']['sha256']==plan['source']['sha256']
    assert trace['selected_source_ids']==plan['selected_source_ids'] and trace['model'] is None
    assert 'DO_NOT_SEND_TO_AI' not in str(trace)
    assert row['data']['copy']==plan['copy'] and row['data']['evidence']==plan['evidence']
    assert all(q['source_id'] in plan['selected_source_ids'] for q in row['data']['analysis']['questions'])
    assert row['data']['source']==plan['source'] and row['data']['research_id']==origin['id']
    assert row['data']['cover'] is None and row['data']['images']==[] and row['data']['export'] is None
    handoff=row['data']['research_handoff'];assert handoff['research_draft_id']==draft['id'] and handoff['snapshot']['copy']==plan['copy']
    assert handoff['reviewed_at'] and handoff['original_reviewed_at'] is None
    assert FakePC.calls==calls
    with factory() as db:
        old=db.get(CourseResearchDraft,draft['id']);assert old.status=='pending' and old.reviewed_at is None and old.draft_id is None
        assert old.title==draft['title'] and old.body==draft['body']
        for model in [AiDraft,PublishJob,AutoTask,DraftAsset]:assert db.scalar(select(func.count()).select_from(model))==0


def test_research_handoff_retries_and_saved_history_do_not_modify_original_draft(research):
    from test_course_research import BASE as RBASE
    c,h,_,factory,*_=research;origin,draft,payload=research_handoff_ready(research)
    got=c.post(f'{RBASE}/{origin["id"]}/drafts/{draft["id"]}/approve',headers=h,json={'reviewed':True,'review_digest':draft['review_digest']})
    assert got.status_code==200,got.text
    saved=got.json();plan=handoff_plan(research,payload);request=handoff_payload(payload,plan)
    got=c.post(BASE+'/from-research',headers=h,json=request);assert got.status_code==200,got.text
    row=got.json();retry=c.post(BASE+'/from-research',headers=h,json=request)
    assert retry.status_code==200 and retry.json()['id']==row['id']
    assert c.post(BASE+'/from-research',headers=h,json={**request,'review_digest':'0'*64}).status_code==409
    assert row['data']['research_handoff']['source_draft_id']==saved['draft_id']
    assert row['data']['research_handoff']['original_reviewed_at']==saved['reviewed_at']
    with factory() as db:
        old=db.get(AiDraft,saved['draft_id']);assert old.title==draft['title'] and old.body==draft['body']
        assert db.scalar(select(func.count()).select_from(AiDraft))==1
        assert db.scalar(select(func.count()).select_from(CourseVisualWorkflow))==1


@pytest.mark.parametrize('field,value',[('university','Other University'),('course_code','MAST10006')])
def test_research_handoff_requires_same_school_and_course(research,field,value):
    from test_course_research import create
    c,h,other,factory,*_=research;origin,_,payload=research_handoff_ready(research)
    assert c.post(BASE+'/from-research/plan',headers=other,json=payload).status_code==404
    assert c.post(BASE+'/from-research/plan',headers=h,json={k:v for k,v in payload.items() if k!='file_id'}).status_code==422
    assert c.post(BASE+'/from-research/plan',headers=h,json={**payload,'research_draft_id':999999}).status_code==404
    different=create(research)
    assert c.post(BASE+'/from-research/plan',headers=h,json={**payload,'research_id':different['id']}).status_code==404
    with factory() as db:
        row=db.get(CourseResearch,origin['id']);row.context={**row.context,field:value};db.commit()
    got=c.post(BASE+'/from-research/plan',headers=h,json=payload)
    assert got.status_code==422 and '大学或课程代码不一致' in got.text


@pytest.mark.parametrize('change',['copy','source','pdf'])
def test_research_handoff_rejects_changes_after_confirmation_preview(research,change):
    c,h,_,factory,w,*_=research;origin,draft,payload=research_handoff_ready(research)
    plan=handoff_plan(research,payload)
    with factory() as db:
        if change=='copy':db.get(CourseResearchDraft,draft['id']).body='更新后的研究正文，请重新审核。'
        elif change=='source':
            row=db.get(CourseResearch,origin['id']);data=deepcopy(row.evidence);data[0]['content']='更新后的正文与来源内容';row.evidence=data
        else:
            file=db.get(CourseLibraryFile,payload['file_id']);path=w.root/file.relative_path;path.write_bytes(path.read_bytes()+b'\n% local fixture changed\n')
        db.commit()
    got=c.post(BASE+'/from-research',headers=h,json=handoff_payload(payload,plan))
    assert got.status_code==409,got.text
    with factory() as db:assert db.scalar(select(func.count()).select_from(CourseVisualWorkflow))==0
    if change!='pdf':
        fresh=handoff_plan(research,payload);assert fresh['review_digest']!=plan['review_digest']
        assert c.post(BASE+'/from-research',headers=h,json=handoff_payload(payload,fresh)).status_code==200


def test_research_handoff_summary_preview_requires_explicit_limit_review_and_blocks_excluded_sources(research):
    c,h,_,factory,*_=research;origin,draft,payload=research_handoff_ready(research,read=False)
    with factory() as db:source_before=deepcopy(db.get(CourseResearch,origin['id']).evidence)
    calls=deepcopy(FakePC.calls)
    got=c.post(BASE+'/from-research/plan',headers=h,json=payload);assert got.status_code==200,got.text
    plan=got.json();quality=plan['evidence_review']
    assert quality == plan['source_quality']
    assert quality['source_count']==1 and quality['detail_count']==0 and quality['comments_read']==0 and quality['limited']
    assert '选题线索' in quality['message'] and '不代表已验证' in quality['message']
    assert plan['evidence'][0]['content_status'] != 'detail' and plan['evidence'][0]['comments']==[]
    request=handoff_payload(payload,plan)
    got=c.post(BASE+'/from-research',headers=h,json=request)
    assert got.status_code==422 and '明确确认' in got.text
    assert c.post(BASE+'/from-research',headers=h,json={**request,'limited_sources_reviewed':True,'reviewed':False}).status_code==409
    assert c.post(BASE+'/from-research',headers=h,json={**request,'limited_sources_reviewed':True,'review_digest':'0'*64}).status_code==409
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(CourseVisualWorkflow))==0
        assert db.get(CourseResearch,origin['id']).evidence==source_before
    got=c.post(BASE+'/from-research',headers=h,json={**request,'limited_sources_reviewed':True})
    assert got.status_code==200,got.text
    row=got.json();assert row['approved']=={'copy':True,'cover':False,'set':False}
    assert row['data']['evidence_review']==quality
    handoff=row['data']['research_handoff']
    assert handoff['limited_sources_reviewed'] and handoff['snapshot']['source_quality']==quality
    assert row['data']['approvals']['copy']['limited_sources_reviewed']
    assert row['data']['approvals']['copy']['source_quality']==quality
    assert row['data']['copy']==plan['copy'] and row['data']['cover'] is None and row['data']['images']==[]
    assert FakePC.calls==calls
    with factory() as db:
        raw=db.get(CourseVisualWorkflow,row['id'])
        assert 'evidence_review' not in raw.data  # View metadata is derived, never silently persisted.
        for model in [AiDraft,PublishJob,AutoTask,DraftAsset]:assert db.scalar(select(func.count()).select_from(model))==0
    with factory() as db:
        row=db.get(CourseResearch,origin['id']);data=deepcopy(row.evidence);data[0]['excluded']=True;row.evidence=data;db.commit()
    assert c.post(BASE+'/from-research/plan',headers=h,json=payload).status_code==409


def test_workbench_summary_copy_requires_current_explicit_limit_review(research):
    c,h,_,factory,*_=research;row=copy_ready(research)
    with factory() as db:
        stored=db.get(CourseVisualWorkflow,row['id']);data=deepcopy(stored.data)
        for source in data['evidence']:
            source['content_status']='search_excerpt';source['content']='';source['comments']=[]
        stored.data=data;db.commit()
    row=c.get(f'{BASE}/{row["id"]}',headers=h).json();quality=row['data']['evidence_review']
    assert quality['limited'] and quality['comments_read']==0
    calls=deepcopy(FakePC.calls)
    call(research,row,'approve',{'stage':'copy','reviewed':True,'digest':row['digests']['copy']},422)
    row=call(research,row,'approve',{'stage':'copy','reviewed':True,'limited_sources_reviewed':True,'digest':row['digests']['copy']})
    assert row['approved']['copy'] and not row['approved']['cover'] and not row['approved']['set']
    assert row['data']['approvals']['copy']['limited_sources_reviewed']
    assert row['data']['approvals']['copy']['source_quality']==quality
    got=c.patch(f'{BASE}/{row["id"]}',headers=h,json={'expected_version':row['row_version'],'copy':{**row['data']['copy'],'body':'修改后的文案，需要重新确认当前内容与来源范围。'}})
    assert got.status_code==200,got.text
    changed=got.json();assert not changed['approved']['copy']
    call(research,changed,'approve',{'stage':'copy','reviewed':True,'digest':changed['digests']['copy']},422)
    assert FakePC.calls==calls


def test_research_handoff_explicitly_selected_different_pdf_needs_new_review(research):
    c,h,_,factory,*_=research;_,__,payload=research_handoff_ready(research)
    with factory() as db:
        second=db.scalar(select(CourseLibraryFile).where(CourseLibraryFile.filename.like('%Practice%')))
        payload={**payload,'file_id':second.id,'revision_id':second.current_revision_id}
    plan=handoff_plan(research,payload)
    assert plan['changed_since_draft']['material'] is True and 'Practice' in plan['source']['filename']
    response=c.post(BASE+'/from-research',headers=h,json=handoff_payload(payload,plan))
    assert response.status_code==200 and response.json()['file_id']==payload['file_id']


def test_changed_copy_stale_approval_and_old_version_retention(research):
    c,h,*_=research;row=approve(research,copy_ready(research),'copy');stale=row
    row=call(research,row,'render',{'stage':'cover'});row=approve(research,row,'cover')
    changed={**row['data']['copy'],'body':'重新编辑后的学习方法，需要重新核对并确认。'}
    got=c.patch(f'{BASE}/{row["id"]}',headers=h,json={'expected_version':row['row_version'],'copy':changed})
    assert got.status_code==200;current=got.json()
    assert not any(current['approved'].values()) and current['data']['cover'] is None and current['data']['history']
    assert c.post(f'{BASE}/{row["id"]}/approve',headers=h,json={'expected_version':stale['row_version'],'stage':'copy','digest':stale['digests']['copy'],'reviewed':True}).status_code==409
    restored=call(research,current,'restore',{'revision':row['data']['revision']})
    assert not any(restored['approved'].values())


def test_external_ai_requires_exact_plan_and_explicit_consent(research):
    c,h,*_=research;row=copy_ready(research)
    p=c.post(f'{BASE}/{row["id"]}/prompts',headers=h,json={});assert p.status_code==200,p.text
    plan=p.json();assert 'Series visual master lock' in plan['visual_direction']['master']
    assert 'DO_NOT_SEND_TO_AI' not in str(plan)
    call(research,row,'generate-copy',{'plan_digest':plan['plan_digest'],'external_consent':False,'request_key':str(uuid4())},422)
    call(research,row,'generate-copy',{'plan_digest':'wrong','external_consent':True,'request_key':str(uuid4())},422)


def test_source_update_and_corrupt_image_block_approval(research):
    c,h,_,factory,w,*_=research;row=approve(research,copy_ready(research),'copy');row=call(research,row,'render',{'stage':'cover'})
    from backend.app.api.course_visual_workflow import directory
    from backend.app.models import User
    with factory() as db:
        model=db.get(CourseVisualWorkflow,row['id']);owner=db.get(User,model.user_id)
        from types import SimpleNamespace
        settings=SimpleNamespace(storage_dir=w.root.parent/'storage')
        image_path=directory(settings,owner,model)/model.data['cover']['path'];image_path.write_bytes(b'corrupt local test image')
    call(research,row,'approve',{'stage':'cover','reviewed':True,'digest':row['digests']['cover']},409)


def test_changed_original_pdf_blocks_new_render_without_overwriting_old(research):
    c,h,_,factory,w,*_=research;row=approve(research,copy_ready(research),'copy')
    with factory() as db:relative=db.get(CourseLibraryFile,row['file_id']).relative_path
    source=w.root/relative;source.write_bytes(source.read_bytes()+b'\n% changed local fixture\n')
    call(research,row,'render',{'stage':'cover'},409)
    assert c.get(f'{BASE}/{row["id"]}',headers=h).json()['data']['cover'] is None


def test_consented_ai_is_one_call_and_output_requires_new_review(research):
    c,h,_,factory,*_=research
    from backend.app.models import ModelConfig,User
    from backend.app.core.security import encrypt_text
    with factory() as db:
        owner=db.scalar(select(User).where(User.username=='pdf-owner'))
        db.add(ModelConfig(user_id=owner.id,name='Local fake provider',model_type='text',provider='openai',model_name='fake-text',base_url='https://fake.invalid/v1',encrypted_api_key=encrypt_text('fixture-key'),is_default=True));db.commit()
    class AI:
        calls=0
        def generate_course_copy(self,**kwargs):
            self.calls+=1
            assert 'fixture-key' not in kwargs['reference'] and 'DO_NOT_SEND_TO_AI' not in kwargs['reference']
            return {'topic':'独立判断与理由核查','title':'MAST10007练习与核查','body':'独立练习后，对照解析补齐条件和理由。','tags':['MAST10007','线性无关'],'takeaway':'独立作答并补齐判断条件。'}
    fake=AI();app.dependency_overrides[get_text_ai_client]=lambda:fake
    row=copy_ready(research);p=c.post(f'{BASE}/{row["id"]}/prompts',headers=h,json={}).json()
    key=str(uuid4());result=call(research,row,'generate-copy',{'plan_digest':p['plan_digest'],'external_consent':True,'request_key':key})
    assert fake.calls==1 and not any(result['approved'].values())
    retry=call(research,result,'generate-copy',{'plan_digest':p['plan_digest'],'external_consent':True,'request_key':key})
    assert fake.calls==1 and retry['data']['copy']['body']==result['data']['copy']['body']


def test_visual_director_ai_plan_is_bound_to_real_skill_and_review_gates(research):
    c,h,_,factory,*_=research
    from backend.app.models import ModelConfig,User
    from backend.app.core.security import encrypt_text
    with factory() as db:
        owner=db.scalar(select(User).where(User.username=='pdf-owner'))
        db.add(ModelConfig(user_id=owner.id,name='Fake visual planner',model_type='text',provider='openai',model_name='fake-visual-plan',base_url='https://fake.invalid/v1',encrypted_api_key=encrypt_text('fixture-key'),is_default=True));db.commit()
    row=approve(research,copy_ready(research),'copy');original_copy=row['data']['copy']
    class Planner:
        calls=0;bad=False
        def plan_visuals(self,**kwargs):
            self.calls+=1
            assert '小红书高级图文视觉导演' in kwargs['reference'] and 'confirmed_copy' in kwargs['reference']
            assert 'fixture-key' not in kwargs['reference']
            plan={**row['data']['visual_plan'],'style':'evidence-editorial'}
            if self.bad:plan['sample_pages']=[999]
            return {'style_report':{k:'根据本篇学习问题与真实样页选择。' for k in ['content_type','goal','emotion','density','primary_style','supporting_style','avoid','reason']},'visual_plan':plan}
    fake=Planner();app.dependency_overrides[get_text_ai_client]=lambda:fake
    prepared=c.post(f'{BASE}/{row["id"]}/prompts?purpose=visual',headers=h,json={}).json()
    call(research,row,'generate-visual-plan',{'external_consent':False,'plan_digest':prepared['plan_digest'],'request_key':str(uuid4())},422)
    assert fake.calls==0
    result=call(research,row,'generate-visual-plan',{'external_consent':True,'plan_digest':prepared['plan_digest'],'request_key':str(uuid4())})
    assert fake.calls==1 and result['data']['copy']==original_copy and result['approved']['copy']
    assert result['data']['visual_plan']['style']=='evidence-editorial' and not result['approved']['cover']
    fake.bad=True
    prepared=c.post(f'{BASE}/{row["id"]}/prompts?purpose=visual',headers=h,json={}).json()
    call(research,result,'generate-visual-plan',{'external_consent':True,'plan_digest':prepared['plan_digest'],'request_key':str(uuid4())},502)
    after=c.get(f'{BASE}/{row["id"]}',headers=h).json()
    assert after['data']['visual_plan']==result['data']['visual_plan']


def test_actual_svg_avoids_stranded_chinese_punctuation(research):
    c,h,*_=research;row=copy_ready(research)
    plan={**row['data']['visual_plan'],'method_text':'适用对象与条件\n选出的列向量要张成原列空间，并且线性无关。\n\n做完后的检查\n检查张成与独立性，再核对基向量个数是否与 rank 一致。'}
    result=c.patch(f'{BASE}/{row["id"]}',headers=h,json={'expected_version':row['row_version'],'visual_plan':plan});assert result.status_code==200
    row=approve(research,result.json(),'copy');row=call(research,row,'render',{'stage':'cover'});row=approve(research,row,'cover');row=call(research,row,'render',{'stage':'set'})
    method=next(a for a in row['data']['images'] if a['kind']=='method')
    svg=c.get(f'{BASE}/{row["id"]}/images/{method["id"]}',headers=h,params={'source':True}).content
    from xml.etree import ElementTree as ET
    lines=[e.text or '' for e in ET.fromstring(svg).iter('{http://www.w3.org/2000/svg}text')]
    assert not any(s.startswith(('。','，','！','？','；','：')) for s in lines)
    assert any('rank' in s for s in lines)
