"""Two appended real-PDF grids; isolated DB/PDF/rendering and no live AI."""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from PIL import Image
import pytest
from sqlalchemy import func, select

from test_course_library import library, scan
from test_course_visual_workflow import BASE, approve, call, copy_ready, research
from test_course_visual_set_plan import multipage_pdf
from backend.app.api import course_visual_workflow as api
from backend.app.models import AiDraft, AutoTask, DraftAsset, PublishJob
from backend.app.models.course_visual_workflow import CourseVisualWorkflow
from backend.app.services import course_visual_workflow as flow

PLAN = {'groups': [[2, 3, 4, 5], [6, 7, 8, 9]]}
OTHER = {'groups': [[3, 4, 5, 6], [7, 8, 9, 10]]}


def raw(r, row):
    with r[3]() as db:
        record = db.get(CourseVisualWorkflow, row['id'])
        return {'version': record.row_version, 'data': deepcopy(record.data)}


def untouched_tasks(r):
    with r[3]() as db:
        for model in (AiDraft, AutoTask, DraftAsset, PublishJob):
            assert db.scalar(select(func.count()).select_from(model)) == 0


def append(r, row, plan=PLAN, key=None, expected=200):
    return call(r, row, 'append-collages', {'request_key': key or str(uuid4()), 'collage_plan': plan}, expected)


def save(r, row, **values):
    result = r[0].patch(f'{BASE}/{row["id"]}', headers=r[1], json={'expected_version': row['row_version'], **values})
    assert result.status_code == 200, result.text
    return result.json()


def long_record(r):
    source = r[4].root / '02墨大/MAST10007/期末复习讲义/MAST10007_26S2_Final.pdf'
    source.write_bytes(multipage_pdf(12)); scan(r[4])
    return copy_ready(r), source


@pytest.fixture
def old_set(research):
    row, source = long_record(research)
    # Simulate an older user record. The feature never backfills real old records.
    with research[3]() as db:
        record = db.get(CourseVisualWorkflow, row['id']); data = deepcopy(record.data)
        data.pop('collage_plan', None); data.pop('pdf_page_plan', None); record.data = data; db.commit()
    row = research[0].get(f'{BASE}/{row["id"]}', headers=research[1]).json()
    row = save(research, row, visual_plan={**row['data']['visual_plan'], 'template_id': 'decision-map',
        'cover_sample_page': 3, 'sample_pages': [2], 'method_text': ''})
    row = approve(research, row, 'copy')
    row = call(research, row, 'render-bundle', {'request_key': str(uuid4())})
    assert len(row['data']['images']) == 3 and not row['approved']['cover']
    return research, row, source


def test_legacy_two_grid_plans_remain_explicitly_supported_after_new_default_changed(research):
    row, _ = long_record(research)
    assert row['data']['pdf_page_plan'] == {'pages': list(range(2, 10))} and 'collage_plan' not in row['data']
    with research[3]() as db:
        record = db.get(CourseVisualWorkflow, row['id']); data = deepcopy(record.data)
        data.pop('pdf_page_plan'); record.data = data; db.commit()
    row = research[0].get(f'{BASE}/{row["id"]}', headers=research[1]).json()
    row = save(research, row, collage_plan=PLAN)
    assert row['data']['collage_plan'] == PLAN and row['collage_status']['available']
    assert [page['slot'] for page in row['direction']['pages']][-2:] == ['collage-0', 'collage-1']
    assert [page['source_pages'] for page in row['direction']['pages'] if page['kind'] == 'collage'] == PLAN['groups']
    row = approve(research, row, 'copy')
    row = call(research, row, 'render-bundle', {'request_key': str(uuid4())})
    assert len(row['data']['images']) == 6 and flow.complete_set(raw(research, row)['data'])
    assert [asset['kind'] for asset in row['data']['images']][-2:] == ['collage', 'collage']
    short = deepcopy(row['data']); short['source']['page_count'] = 8; short.pop('collage_plan')
    status = flow.collage_status(short)
    assert not status['available'] and status['default_plan'] is None and '不重复' in status['message']
    source = {**row['data']['source'], 'page_count': 8}
    assert 'collage_plan' not in flow.initial_data(source, flow.catalog())
    untouched_tasks(research)


def test_append_keeps_three_original_assets_and_creates_two_pending_grids(old_set):
    r, row, source = old_set; before = raw(r, row); source_hash = flow.hash_file(source)
    assert 'collage_plan' not in before['data']
    row = append(r, row)
    assert row['data']['images'][:3] == [api.image_view(a, type('Row', (), {'id': row['id']})()) for a in before['data']['images']]
    assert len(row['data']['images']) == 5 and row['data']['cover']['id'] == before['data']['cover']['id']
    assert row['data']['approvals'] == before['data']['approvals'] and row['approved']['copy']
    assert not row['approved']['cover'] and not row['approved']['set'] and row['data']['export'] is None
    assert [asset['source_pages'] for asset in row['data']['images'][-2:]] == PLAN['groups']
    assert row['data']['history'][-1]['images'] == [api.image_view(a, type('Row', (), {'id': row['id']})()) for a in before['data']['images']]
    assert flow.bundle_ready(raw(r, row)['data']) and flow.hash_file(source) == source_hash
    for asset in row['data']['images']:
        response = r[0].get(f'{BASE}/{row["id"]}/images/{asset["id"]}', headers=r[1]); assert response.status_code == 200
        from io import BytesIO
        assert Image.open(BytesIO(response.content)).size == (1080, 1440)
    untouched_tasks(r)


def test_append_success_is_idempotent_and_replaces_only_old_tail(old_set):
    r, row, _ = old_set; original = deepcopy(row['data']['images']); version = row['row_version']; key = str(uuid4())
    row = append(r, row, key=key); first = raw(r, row)
    retry = r[0].post(f'{BASE}/{row["id"]}/append-collages', headers=r[1],
                     json={'expected_version': version, 'request_key': key, 'collage_plan': PLAN})
    assert retry.status_code == 200 and raw(r, row) == first
    assert append(r, row, key=key)['row_version'] == row['row_version']
    assert append(r, row)['row_version'] == row['row_version']
    assert raw(r, row) == first
    append(r, row, OTHER, key, expected=409)
    old_collages = [asset['id'] for asset in row['data']['images'][-2:]]
    row = append(r, row, OTHER)
    assert row['data']['images'][:3] == original and len(row['data']['images']) == 5
    assert [asset['id'] for asset in row['data']['images'][-2:]] != old_collages
    assert [asset['id'] for asset in row['data']['history'][-1]['images'][-2:]] == old_collages
    assert [asset['source_pages'] for asset in row['data']['images'][-2:]] == OTHER['groups']
    untouched_tasks(r)


def test_collage_config_changes_only_set_fingerprint_and_restore_removes_old_absence(old_set):
    r, row, _ = old_set
    row = approve(r, row, 'cover'); original = raw(r, row)['data']
    copy_digest = row['digests']['copy']; cover_digest = row['digests']['cover']
    row = append(r, row)
    assert row['approved']['cover'] and row['digests']['cover'] == cover_digest and row['digests']['copy'] == copy_digest
    previous = row['data']['history'][-1]['revision']
    row = call(r, row, 'restore', {'revision': previous})
    restored = raw(r, row)['data']
    assert 'collage_plan' not in restored and restored['images'] == original['images']
    assert not any(row['approved'].values())
    untouched_tasks(r)


def test_collage_patch_preserves_copy_and_cover_approval_and_keeps_old_images_in_history(old_set):
    r, row, _ = old_set; row = approve(r, row, 'cover'); original = raw(r, row)['data']
    row = save(r, row, collage_plan=PLAN)
    assert row['approved']['copy'] and row['approved']['cover'] and not row['approved']['set']
    assert row['data']['cover']['id'] == original['cover']['id'] and not row['data']['images']
    assert raw(r, row)['data']['history'][-1]['images'] == original['images']
    assert row['digests']['copy'] == flow.fingerprint(original, 'copy') and row['digests']['cover'] == flow.fingerprint(original, 'cover')
    untouched_tasks(r)


def test_fork_is_new_pending_record_with_full_pages_without_touching_legacy_original(old_set):
    r, row, _ = old_set; original = raw(r, row)
    result = call(r, row, 'fork')
    assert result['id'] != row['id'] and result['data']['pdf_page_plan'] == {'pages': list(range(2, 10))}
    assert 'collage_plan' not in result['data']
    assert not result['data']['images'] and not any(result['approved'].values())
    assert raw(r, row) == original and 'collage_plan' not in original['data']
    for field in ('render_bundle', 'bundle_requests', 'collage_requests'):
        assert field not in result['data']
    untouched_tasks(r)


@pytest.mark.parametrize('plan', [
    {'groups': []}, {'groups': [[2, 3, 4, 5]]}, {'groups': [[2, 3, 4], [5, 6, 7, 8]]},
    {'groups': [[2, 3, 4, 5], [6, 7, 8, 8]]}, {'groups': [[1, 2, 3, 4], [5, 6, 7, 8]]},
    {'groups': [[2, 3, 4, 5], [6, 7, 8, 13]]}, {'groups': [[2.5, 3, 4, 5], [6, 7, 8, 9]]},
])
def test_invalid_plan_never_touches_current_assets_or_operation(old_set, plan):
    r, row, _ = old_set; before = raw(r, row)
    append(r, row, plan, expected=422)
    assert raw(r, row) == before
    untouched_tasks(r)


def test_append_owner_version_and_copy_gates(old_set):
    r, row, _ = old_set; before = raw(r, row); path = f'{BASE}/{row["id"]}/append-collages'
    payload = {'expected_version': row['row_version'], 'request_key': str(uuid4()), 'collage_plan': PLAN}
    assert r[0].post(path, json=payload).status_code == 401
    assert r[0].post(path, headers=r[2], json=payload).status_code == 404
    assert r[0].post(path, headers=r[1], json={**payload, 'expected_version': row['row_version'] - 1}).status_code == 409
    assert raw(r, row) == before
    with r[3]() as db:
        record = db.get(CourseVisualWorkflow, row['id']); data = deepcopy(record.data)
        data['approvals'].pop('copy'); record.data = data; db.commit()
    current = r[0].get(f'{BASE}/{row["id"]}', headers=r[1]).json()
    append(r, current, expected=409)
    untouched_tasks(r)


def test_collage_failure_preserves_old_business_state(old_set, monkeypatch):
    r, row, _ = old_set; before = raw(r, row); real = api.render_assets
    def fail(*args, **kwargs):
        if args[4] == 'collage': raise HTTPException(422, 'Synthetic collage failure')
        return real(*args, **kwargs)
    monkeypatch.setattr(api, 'render_assets', fail)
    append(r, row, expected=422); after = raw(r, row)
    for field in ('copy', 'cover', 'images', 'visual_plan', 'approvals', 'history', 'revision', 'export'):
        assert after['data'][field] == before['data'][field]
    assert 'collage_plan' not in after['data'] and after['data']['operation']['status'] == 'failed'
    untouched_tasks(r)


def test_collage_final_review_rejects_wrong_source_pages_and_requires_explicit_export(old_set):
    r, row, _ = old_set; row = append(r, row)
    call(r, row, 'export', {'reviewed': True, 'digest': row['digests']['set']}, 409)
    row = call(r, row, 'approve', {'stage': 'set', 'combined_review': True, 'reviewed': True, 'digest': row['digests']['set']})
    assert all(row['approved'].values()) and row['data']['export'] is None
    untouched_tasks(r)
    row = call(r, row, 'export', {'reviewed': True, 'digest': row['digests']['set']})
    with r[3]() as db:
        assert db.scalar(select(func.count()).select_from(AiDraft)) == 1
        assert db.scalar(select(func.count()).select_from(DraftAsset)) == 5
        for model in (AutoTask, PublishJob): assert db.scalar(select(func.count()).select_from(model)) == 0


def test_collage_caption_revise_and_ai_background_guard(old_set):
    r, row, _ = old_set; row = append(r, row); original = deepcopy(row['data']['images'])
    asset = row['data']['images'][-1]
    call(r, row, 'background-plan', {'slot': asset['slot']}, 422)
    call(r, row, 'revise', {'asset_id': asset['id'], 'brief': {**asset['brief'], 'text': '不允许重写PDF'}}, 422)
    row = call(r, row, 'revise', {'asset_id': asset['id'], 'brief': {**asset['brief'], 'subtitle': '对照真实讲义，查看这一组内容。'}})
    assert row['data']['images'][:-1] == original[:-1] and row['data']['images'][-1]['id'] != asset['id']
    assert row['data']['images'][-1]['source_pages'] == asset['source_pages'] and flow.bundle_ready(raw(r, row)['data'])
    untouched_tasks(r)


def test_collage_source_page_metadata_is_part_of_complete_set_validation(old_set):
    r, row, _ = old_set; row = append(r, row)
    with r[3]() as db:
        record = db.get(CourseVisualWorkflow, row['id']); data = deepcopy(record.data)
        data['images'][-1]['source_pages'] = list(reversed(data['images'][-1]['source_pages']))
        data['render_bundle']['digest'] = flow.fingerprint(data, 'set')
        record.data = data; db.commit()
    row = r[0].get(f'{BASE}/{row["id"]}', headers=r[1]).json()
    call(r, row, 'approve', {'stage': 'set', 'combined_review': True, 'reviewed': True, 'digest': row['digests']['set']}, 409)
    untouched_tasks(r)


def test_append_source_change_after_render_keeps_original_assets(old_set, monkeypatch):
    r, row, source = old_set; before = raw(r, row); real = api.render_assets
    def change_source(*args, **kwargs):
        result = real(*args, **kwargs)
        if args[4] == 'collage':
            with source.open('ab') as stream: stream.write(b'\n% synthetic PDF changed during collage render\n')
        return result
    monkeypatch.setattr(api, 'render_assets', change_source)
    append(r, row, expected=409)
    after = raw(r, row)
    for field in ('cover', 'images', 'copy', 'approvals', 'history', 'revision'):
        assert after['data'][field] == before['data'][field]
    assert 'collage_plan' not in after['data'] and after['data']['operation']['status'] == 'failed'
    untouched_tasks(r)


def test_append_concurrent_record_change_is_not_overwritten(old_set, monkeypatch):
    r, row, _ = old_set; original = deepcopy(row['data']['images']); real = api.render_assets
    def change_record(*args, **kwargs):
        result = real(*args, **kwargs)
        if args[4] == 'collage':
            with r[3]() as db:
                record = db.get(CourseVisualWorkflow, row['id']); data = deepcopy(record.data)
                data['label'] = 'Another editor version'
                data['operation'] = {'key': 'other-request', 'status': 'generating', 'kind': 'fixture'}
                record.data = data; db.commit()
        return result
    monkeypatch.setattr(api, 'render_assets', change_record)
    append(r, row, expected=409); after = raw(r, row)['data']
    assert after['label'] == 'Another editor version' and after['operation']['key'] == 'other-request'
    assert after['operation']['status'] == 'generating' and 'collage_plan' not in after
    assert [a['id'] for a in after['images']] == [a['id'] for a in original]
    untouched_tasks(r)


def test_corrupt_original_asset_blocks_append_before_operation_reservation(old_set):
    r, row, _ = old_set; before = raw(r, row)
    with r[3]() as db:
        record = db.get(CourseVisualWorkflow, row['id'])
        directory = Path(r[5].storage_dir) / 'course-visual' / f'u{record.user_id}' / f'r{record.id}'
    original_path = directory / before['data']['images'][1]['path']
    original_path.write_bytes(b'corrupted synthetic asset')
    append(r, row, expected=409)
    assert raw(r, row) == before
    untouched_tasks(r)
