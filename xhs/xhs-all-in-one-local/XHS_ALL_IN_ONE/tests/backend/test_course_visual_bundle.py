"""Atomic local production and one explicit final review, using isolated files/DB."""
from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from test_course_visual_workflow import BASE, approve, call, copy_ready, make, research
from test_course_library import library
from test_course_visual_background import setup, prepared
from backend.app.api import course_visual_workflow as api
from backend.app.models import AiDraft, AutoTask, PublishJob
from backend.app.models.course_visual_workflow import CourseVisualWorkflow
from backend.app.services import course_visual_workflow as flow


def bundle(r, row, **kwargs):
    return call(r, row, 'render-bundle', {'request_key': str(uuid4()), **kwargs})


def state(r, row):
    with r[3]() as db:
        value = db.get(CourseVisualWorkflow, row['id'])
        return deepcopy(value.data)


def no_publish(r):
    with r[3]() as db:
        for model in (AiDraft, AutoTask, PublishJob):
            assert db.scalar(select(func.count()).select_from(model)) == 0


def final_review(r, row):
    return call(r, row, 'approve', {'stage': 'set', 'reviewed': True,
        'combined_review': True, 'digest': row['digests']['set']})


def test_bundle_produces_cover_and_set_without_cover_approval_and_retries_once(research):
    c, headers, other, *_ = research
    row = approve(research, copy_ready(research), 'copy')
    copy_before = deepcopy(row['data']['copy']); copy_approval = deepcopy(row['data']['approvals']['copy'])
    key = str(uuid4()); version = row['row_version']
    row = bundle(research, row, request_key=key)
    assert len(row['data']['images']) == 4 and row['data']['images'][0] == row['data']['cover']
    assert row['approved'] == {'copy': True, 'cover': False, 'set': False}
    assert row['data']['copy'] == copy_before and row['data']['approvals']['copy'] == copy_approval
    assert flow.bundle_ready(state(research, row)) and row['data']['export'] is None
    assert row['data']['production_trace'][-1]['tool'] == 'deterministic_pdf_svg_renderer'
    assert row['data']['production_trace'][-1]['model'] is None
    for image in row['data']['images']:
        assert c.get(f'{BASE}/{row["id"]}/images/{image["id"]}', headers=headers).content.startswith(b'\x89PNG')
    stored = state(research, row)
    replay = c.post(f'{BASE}/{row["id"]}/render-bundle', headers=headers,
                    json={'expected_version': version, 'request_key': key})
    assert replay.status_code == 200 and replay.json()['row_version'] == row['row_version']
    assert state(research, row) == stored
    assert c.post(f'{BASE}/{row["id"]}/render-bundle', headers=other,
                  json={'expected_version': version, 'request_key': key}).status_code == 404
    no_publish(research)


def test_bundle_keeps_explicit_combined_final_review_before_export(research):
    row = bundle(research, approve(research, copy_ready(research), 'copy'))
    call(research, row, 'approve', {'stage': 'set', 'reviewed': True, 'digest': row['digests']['set']}, 409)
    call(research, row, 'approve', {'stage': 'set', 'reviewed': False, 'combined_review': True,
                                  'digest': row['digests']['set']}, 409)
    call(research, row, 'export', {'reviewed': True, 'digest': row['digests']['set']}, 409)
    row = final_review(research, row)
    assert all(row['approved'].values())
    assert row['data']['approvals']['cover']['source'] == 'manual_combined_final_review'
    assert row['data']['approvals']['set']['review_scope'] == 'cover_and_all_inner_pages'
    assert row['data']['export'] is None
    no_publish(research)
    row = call(research, row, 'export', {'reviewed': True, 'digest': row['digests']['set']})
    assert row['data']['export']['draft_available']
    with research[3]() as db:
        assert db.scalar(select(func.count()).select_from(AiDraft)) == 1
        for model in (AutoTask, PublishJob): assert db.scalar(select(func.count()).select_from(model)) == 0


def test_bundle_reuses_real_approved_cover_and_preserves_old_set_history(research):
    row = approve(research, copy_ready(research), 'copy')
    row = call(research, row, 'render', {'stage': 'cover'})
    row = approve(research, row, 'cover')
    row = call(research, row, 'render', {'stage': 'set'})
    old_cover = deepcopy(row['data']['cover']); old_images = deepcopy(row['data']['images'])
    row = bundle(research, row)
    assert row['data']['cover'] == old_cover and row['approved']['cover']
    assert row['data']['render_bundle']['reused_cover']
    assert row['data']['history'][-1]['images'] == old_images
    assert not row['approved']['set'] and len(row['data']['images']) == 4
    no_publish(research)


@pytest.mark.parametrize('slot', ['cover', 'method'])
def test_pending_bundle_single_image_revision_keeps_other_pages_and_review_scope(research, slot):
    row = bundle(research, approve(research, copy_ready(research), 'copy'))
    before = deepcopy(row['data']['images']); image = next(a for a in before if a['slot'] == slot)
    row = call(research, row, 'revise', {'asset_id': image['id'], 'brief': {**image['brief'], 'title': '先核对条件'}})
    assert len(row['data']['images']) == 4 and not row['approved']['cover'] and not row['approved']['set']
    assert flow.bundle_ready(state(research, row))
    for a, b in zip(before, row['data']['images']):
        assert (a['id'] != b['id']) == (a['slot'] == slot)
    assert row['data']['images'][0] == row['data']['cover']
    assert all(final_review(research, row)['approved'].values())
    no_publish(research)


def test_bundle_failure_never_replaces_current_images_or_approvals(research, monkeypatch):
    row = bundle(research, approve(research, copy_ready(research), 'copy'))
    before = state(research, row); old_render = api.render_assets
    def fail_inner(*args, **kwargs):
        if args[4] == 'set': raise HTTPException(422, 'Synthetic inner failure')
        return old_render(*args, **kwargs)
    monkeypatch.setattr(api, 'render_assets', fail_inner)
    key = str(uuid4())
    call(research, row, 'render-bundle', {'request_key': key}, 422)
    after = state(research, row)
    for field in ('cover', 'images', 'copy', 'visual_plan', 'approvals', 'history', 'revision', 'export'):
        assert after[field] == before[field]
    assert after['operation']['status'] == 'failed' and after['bundle_requests'][key]['status'] == 'failed'
    assert after['production_trace'][-1]['status'] == 'failed'
    no_publish(research)


def test_bundle_requires_owner_version_copy_and_nonreused_request_key(research):
    c, h, other, *_ = research; row = make(research); key = str(uuid4())
    path = f'{BASE}/{row["id"]}/render-bundle'
    payload = {'expected_version': row['row_version'], 'request_key': key}
    assert c.post(path, json=payload).status_code == 401
    assert c.post(path, headers=other, json=payload).status_code == 404
    assert c.post(path, headers=h, json=payload).status_code == 409
    row = approve(research, copy_ready(research), 'copy')
    call(research, row, 'render-bundle', {'request_key': key, 'expected_version': row['row_version']-1}, 409)
    row = bundle(research, row, request_key=key)
    stored = state(research, row)
    replay = call(research, row, 'render-bundle', {'request_key': key})
    assert replay['row_version'] == row['row_version'] and state(research, row) == stored
    no_publish(research)


@pytest.mark.parametrize('tamper', ['cover', 'slots', 'sample'])
def test_final_combined_review_rejects_incomplete_or_stale_bundle(research, tamper):
    row = bundle(research, approve(research, copy_ready(research), 'copy'))
    with research[3]() as db:
        record = db.get(CourseVisualWorkflow, row['id']); data = deepcopy(record.data)
        if tamper == 'cover': data['images'][0]['id'] = 'wrong-cover'
        if tamper == 'slots': data['images'] = data['images'][:-1]
        if tamper == 'sample': data['images'][2]['source_page'] = 500
        data['render_bundle']['digest'] = flow.fingerprint(data, 'set')
        record.data = data; db.commit()
    row = research[0].get(f'{BASE}/{row["id"]}', headers=research[1]).json()
    call(research, row, 'approve', {'stage': 'set', 'reviewed': True, 'combined_review': True,
                                   'digest': row['digests']['set']}, 409)
    no_publish(research)


@pytest.mark.parametrize('slot', ['cover', 'method'])
def test_pending_bundle_optional_background_keeps_complete_set(setup, slot):
    r, client = setup
    row = bundle(r, approve(r, copy_ready(r), 'copy'))
    original = deepcopy(row['data']['images'])
    row = call(r, row, 'generate-background', prepared(r, row, slot))
    assert client.calls == 1 and flow.bundle_ready(state(r, row))
    assert row['approved'] == {'copy': True, 'cover': False, 'set': False}
    for before, after in zip(original, row['data']['images']):
        assert (before['id'] != after['id']) == (before['slot'] == slot)
    assert all(final_review(r, row)['approved'].values())
    no_publish(r)


def test_source_change_during_bundle_retains_previous_content(research, monkeypatch):
    row = approve(research, copy_ready(research), 'copy'); before = state(research, row)
    old_render = api.render_assets
    def change_source(*args, **kwargs):
        result = old_render(*args, **kwargs)
        if args[4] == 'cover':
            source = research[4].root / row['data']['source']['relative_path']
            with source.open('ab') as stream: stream.write(b'\n% changed synthetic source\n')
        return result
    monkeypatch.setattr(api, 'render_assets', change_source)
    call(research, row, 'render-bundle', {'request_key': str(uuid4())}, 409)
    after = state(research, row)
    for field in ('cover', 'images', 'copy', 'approvals', 'history', 'revision'):
        assert after[field] == before[field]
    assert after['operation']['status'] == 'failed'
    no_publish(research)


def test_concurrent_record_change_is_never_overwritten(research, monkeypatch):
    row = approve(research, copy_ready(research), 'copy'); old_render = api.render_assets
    def change_record(*args, **kwargs):
        result = old_render(*args, **kwargs)
        if args[4] == 'set':
            with research[3]() as db:
                record = db.get(CourseVisualWorkflow, row['id']); data = deepcopy(record.data)
                data['copy']['title'] = 'Concurrent edit'
                data['operation'] = {'key': 'other-operation', 'kind': 'fixture', 'status': 'generating'}
                record.data = data; db.commit()
        return result
    monkeypatch.setattr(api, 'render_assets', change_record)
    call(research, row, 'render-bundle', {'request_key': str(uuid4())}, 409)
    after = state(research, row)
    assert after['copy']['title'] == 'Concurrent edit'
    assert after['operation']['key'] == 'other-operation' and after['operation']['status'] == 'generating'
    assert not after['images'] and not after['cover'] and not after['approvals'].get('cover')
    no_publish(research)
