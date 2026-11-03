"""Historical export evidence and precise draft access; isolated fixture DB only."""
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_course_research import research
from test_course_library import library
from test_course_draft_image_guard import image_guard
from backend.app.models import AiDraft, DraftAsset
from backend.app.models.course_visual_workflow import CourseVisualWorkflow
from backend.app.models.course_research import CourseResearchDraft
from backend.app.models.course_library_draft import CourseLibraryDraft
from backend.app.services import course_visual_workflow as flow
from backend.app.services.course_draft_origin import course_origins, draft_binding, linked_draft_is_current


def export_fixture(factory, draft_id, run_id, explicit):
    with factory() as db:
        run = db.get(CourseVisualWorkflow, run_id)
        draft = db.get(AiDraft, draft_id)
        state = flow.initial_data({'university': 'Example University', 'course_code': 'TEST1000',
            'filename': 'review-v1.pdf', 'revision_id': 7, 'sha256': 'a'*64, 'term': '2026S2'},
            {'brand': {'name': 'Example'}, 'version': 1, 'skills': [], 'rules': '', 'contract_digest': 'rules'})
        state['revision'] = 4
        state['copy'] = {'title': draft.title, 'body': draft.body, 'tags': ['TEST1000']}
        state['research_id'] = 41
        state['images'] = [{'id': 'first', 'sha256': 'b'*64}, {'id': 'second', 'sha256': 'c'*64}]
        state['cover'] = state['images'][0]
        for stage in ('copy', 'cover', 'set'):
            state['approvals'][stage] = {'at': '2026-10-29T09:00:00', 'digest': flow.fingerprint(state, stage)}
        draft.tags = [{'id': '', 'name': 'TEST1000'}]
        first = db.scalar(select(DraftAsset).where(DraftAsset.draft_id == draft_id))
        first.local_path = f'xhs-asset-u{run.user_id}-workflow-{run_id}-first.png'
        second = DraftAsset(draft_id=draft_id, asset_type='image', url='',
            local_path=f'xhs-asset-u{run.user_id}-workflow-{run_id}-second.png', sort_order=1)
        db.add(second)
        state['export'] = {'draft_id': draft_id, 'at': draft.created_at.isoformat(), 'digest': flow.fingerprint(state, 'set')}
        if explicit:
            state['export']['snapshot'] = {'version': 1, 'source': deepcopy(state['source']),
                'copy': deepcopy(state['copy']), 'approvals': deepcopy(state['approvals']),
                'workflow_revision': 4, 'source_research_id': 41, 'workflow_digest': state['export']['digest'],
                'materials': [{'asset_type': 'image', 'url': '', 'local_path': a.local_path} for a in (first, second)]}
        current = flow.checkpoint(state, 'new version')
        flow.invalidate(current, 'copy')
        current['source'] = {**current['source'], 'filename': 'different-current.pdf'}
        current['copy'] = {**current['copy'], 'title': 'Current work is different'}
        run.data = current
        db.commit()
        return deepcopy(current), run.user_id


@pytest.mark.parametrize('explicit', [False, True])
def test_export_history_reports_exact_source_reviews_and_draft_only_changes(image_guard, explicit):
    r, ids, aids, runid, _ = image_guard
    c, h, other, factory, *_ = r
    before, owner = export_fixture(factory, ids[0], runid, explicit)
    detail = c.get(f'/api/drafts/{ids[0]}', headers=h)
    assert detail.status_code == 200
    origin = detail.json()['course_origin']
    assert origin['source']['filename'] == 'review-v1.pdf'
    assert origin['source']['revision_id'] == 7 and origin['source']['sha256'] == 'a'*64
    assert origin['workflow_revision'] == 4 and origin['research_id'] == 41
    assert origin['snapshot_complete'] and origin['comparison']['status'] == 'unchanged'
    assert all(r['status'] == 'confirmed' for r in origin['review_snapshot'].values())
    assert origin['href'].endswith(f'?run={runid}')
    changed = c.patch(f'/api/drafts/{ids[0]}', headers=h,
        json={'title': 'Edited only in drafts', 'tags': [{'name': 'new tag'}], 'course_origin': None})
    assert changed.status_code == 200
    assert changed.json()['course_origin']['comparison'] == {'status': 'modified', 'changed_fields': ['标题', '标签']}
    assets = c.get(f'/api/drafts/{ids[0]}/assets', headers=h).json()['items']
    response = c.put(f'/api/drafts/{ids[0]}/assets/reorder', headers=h, json={'asset_ids': [a['id'] for a in reversed(assets)]})
    assert response.status_code == 200, response.text
    assert '图片或素材顺序' in c.get(f'/api/drafts/{ids[0]}', headers=h).json()['course_origin']['comparison']['changed_fields']
    with factory() as db:
        assert db.get(CourseVisualWorkflow, runid).data == before
        assert course_origins(db, owner + 1000, ids) == {}
    assert c.get(f'/api/drafts/{ids[0]}', headers=other).status_code == 404


def test_incomplete_history_does_not_borrow_current_approval_or_source(image_guard):
    r, ids, aids, runid, _ = image_guard
    c, h, _, factory, *_ = r
    origin = c.get(f'/api/drafts/{ids[0]}', headers=h).json()['course_origin']
    assert not origin['snapshot_complete'] and origin['comparison']['status'] == 'unknown'
    assert origin['source'] == {} and origin['snapshot_note'] == '旧稿未记录完整快照'
    assert all(x['status'] == 'not_recorded' for x in origin['review_snapshot'].values())
    assert c.get('/api/drafts/99999999', headers=h).status_code == 404


def test_exact_access_beyond_first_page_and_legacy_review_semantics(image_guard):
    r, ids, aids, runid, _ = image_guard
    c, h, other, factory, *_ = r
    with factory() as db:
        original = db.get(AiDraft, ids[0])
        for i in range(25):
            db.add(AiDraft(user_id=original.user_id, platform='xhs', title=f'new{i}', body=''))
        research_draft = db.scalar(select(CourseResearchDraft).where(CourseResearchDraft.draft_id == ids[2]))
        research_draft.status = 'saved'; research_draft.reviewed_at = db.get(AiDraft, ids[2]).created_at
        research_draft.brief = {'materials': [{'file_id': 99, 'source': {'filename': 'historical.pdf', 'revision_id': 8, 'sha256': 'd'*64}}]}
        pdf = db.scalar(select(CourseLibraryDraft).where(CourseLibraryDraft.draft_id == ids[1]))
        pdf.status = 'saved'; pdf.reviewed_at = db.get(AiDraft, ids[1]).created_at; pdf.source_snapshot = {}
        db.commit(); research_id, research_draft_id = research_draft.research_id, research_draft.id
        package_id, file_id = pdf.id, pdf.file_id
    assert ids[0] not in [d['id'] for d in c.get('/api/drafts', headers=h).json()['items']]
    assert c.get(f'/api/drafts/{ids[0]}', headers=h).json()['id'] == ids[0]
    origin = c.get(f'/api/drafts/{ids[2]}', headers=h).json()['course_origin']
    assert origin['review_snapshot']['copy']['status'] == 'confirmed'
    assert origin['review_snapshot']['cover']['status'] == 'not_applicable'
    query = parse_qs(urlsplit(origin['href']).query)
    assert query['research_id'] == [str(research_id)] and query['research_draft_id'] == [str(research_draft_id)]
    assert query['file_id'] == ['99']
    assert origin['source']['filename'] == 'historical.pdf'
    pdf_origin = c.get(f'/api/drafts/{ids[1]}', headers=h).json()['course_origin']
    pdf_query = parse_qs(urlsplit(pdf_origin['href']).query)
    assert pdf_query['library_file_id'] == [str(file_id)]
    assert pdf_query['package_id'] == [str(package_id)]
    assert pdf_origin['review_snapshot']['cover']['status'] == 'not_recorded'
    assert pdf_origin['review_snapshot']['set']['status'] == 'confirmed'


def test_draft_identity_requires_precise_binding_or_time_and_complete_legacy_proof():
    created = datetime(2026, 10, 30, 13, 52, 56, 647428)
    draft = SimpleNamespace(id=1, user_id=7, created_at=created, title='Current', body='Full copy', tags=[{'name': 'FNCE10002'}])
    copy = {'copy': {'title': 'Current', 'body': 'Full copy', 'tags': ['FNCE10002']}}
    assert linked_draft_is_current(draft, created + timedelta(microseconds=315), copy)
    assert not linked_draft_is_current(draft, created - timedelta(days=1), copy)
    assert not linked_draft_is_current(draft, created + timedelta(seconds=1), copy)
    assert not linked_draft_is_current(draft, created, {'copy': {'title': 'Current'}})
    assert not linked_draft_is_current(draft, created)
    assert not linked_draft_is_current(draft, 'invalid', copy)
    assert not linked_draft_is_current(draft, created, {**copy, 'draft_created_at': (created-timedelta(days=1)).isoformat()})
    assert not linked_draft_is_current(draft, created, {**copy, 'user_id': 8})
    immutable = draft_binding(draft)
    draft.title = 'Edited title'; draft.body = 'Edited body'; draft.tags = []
    assert linked_draft_is_current(draft, None, immutable)
    assert not linked_draft_is_current(draft, created, copy)
    assert linked_draft_is_current(draft, None, {**immutable, 'draft_created_at': '2026-10-30T05:52:56.647428Z'})
    assert not linked_draft_is_current(draft, created, {**immutable, 'draft_created_at': 'invalid'})


def test_legacy_identity_can_use_protected_asset_set_after_copy_edit_and_reorder():
    created = datetime(2026, 10, 30, 13)
    draft = SimpleNamespace(id=1, user_id=7, created_at=created, title='Edited', body='Changed', tags=[])
    images = [{'asset_type': 'image', 'local_path': f'xhs-asset-u7-workflow-4-{name}.png'} for name in ['one', 'two']]
    proof = {'materials': images, 'current_materials': list(reversed(images))}
    assert linked_draft_is_current(draft, created, proof)
    assert not linked_draft_is_current(draft, created, {**proof, 'current_materials': images[:1]})
    assert not linked_draft_is_current(draft, created + timedelta(days=1), proof)
    assert not linked_draft_is_current(draft, created, {'materials': [1], 'current_materials': [1]})
    ordinary = [{'local_path': 'ordinary.png'}]
    assert not linked_draft_is_current(draft, created, {'materials': ordinary, 'current_materials': ordinary})


def test_reused_draft_id_does_not_link_old_exports_packages_or_research(image_guard):
    r, ids, _, runid, _ = image_guard
    c, h, _, factory, *_ = r
    target_id = ids[3]
    with factory() as db:
        target = db.get(AiDraft, target_id)
        old_time = target.created_at - timedelta(days=1)
        stale_binding = {**draft_binding(target), 'draft_created_at': old_time.isoformat()}
        package = db.scalar(select(CourseLibraryDraft))
        package.draft_id = target_id; package.status = 'saved'; package.reviewed_at = old_time
        package.title = target.title; package.body = target.body; package.tags = target.tags or []
        package.source_snapshot = {'draft_binding': stale_binding}
        old_research = db.scalar(select(CourseResearchDraft))
        old_research.draft_id = target_id; old_research.status = 'saved'; old_research.reviewed_at = old_time
        old_research.title = target.title; old_research.body = target.body; old_research.tags = target.tags or []
        old_research.brief = {'draft_binding': stale_binding}
        run = db.get(CourseVisualWorkflow, runid)
        run.data = {'history': [{'export': {'draft_id': target_id, 'at': old_time.isoformat(), 'snapshot': stale_binding}}]}
        db.commit()
        package_id, research_id, old_research_id = package.id, old_research.research_id, old_research.id
    assert c.get(f'/api/drafts/{target_id}', headers=h).json()['course_origin'] is None
    study = c.get(f'/api/course-center/research/{research_id}', headers=h)
    assert study.status_code == 200, study.text
    assert study.json()['drafts'][0]['draft_available'] is False
    package_url = f'/api/course-center/library/draft-reviews/{package_id}'
    assert c.get(package_url, headers=h).json()['draft_available'] is False
    assert c.post(f'/api/course-center/research/{research_id}/drafts/{old_research_id}/approve', headers=h, json={'reviewed': True}).status_code == 409
    assert c.post(package_url+'/approve', headers=h, json={'reviewed': True}).status_code == 409
    with factory() as db:
        target = db.get(AiDraft, target_id)
        current = CourseResearchDraft(user_id=target.user_id, research_id=research_id, request_key=str(uuid4()), request_digest='current',
            title=target.title, body=target.body, tags=target.tags or [], prompt='', brief={}, status='saved', draft_id=target_id,
            reviewed_at=target.created_at+timedelta(microseconds=315))
        db.add(current); db.commit(); current_id = current.id
    origin = c.get(f'/api/drafts/{target_id}', headers=h).json()['course_origin']
    assert origin['kind'] == 'course_research'
    assert parse_qs(urlsplit(origin['href']).query)['research_draft_id'] == [str(current_id)]
    # New immutable bindings survive arbitrary later copy changes.
    with factory() as db:
        current = db.get(CourseResearchDraft, current_id)
        current.brief = {'draft_binding': draft_binding(db.get(AiDraft, target_id))}
        db.commit()
    result = c.patch(f'/api/drafts/{target_id}', headers=h, json={'title': 'Edited after save', 'body': 'Another body', 'tags': []})
    assert result.status_code == 200 and result.json()['course_origin']['kind'] == 'course_research'
    study = c.get(f'/api/course-center/research/{research_id}', headers=h).json()
    assert next(d for d in study['drafts'] if d['id'] == current_id)['draft_available']
    assert not next(d for d in study['drafts'] if d['id'] == old_research_id)['draft_available']
