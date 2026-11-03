"""Replace old collage tails with eight independent PDF pages in an isolated app."""
from copy import deepcopy
from io import BytesIO
from uuid import uuid4

from fastapi import HTTPException
from PIL import Image
import pytest
from sqlalchemy import func, select

from test_course_library import library
from test_course_visual_workflow import BASE, approve, call, research
from test_course_visual_collages import old_set, long_record, raw, save, append as legacy_append, untouched_tasks
from backend.app.api import course_visual_workflow as api
from backend.app.models import AiDraft, AutoTask, DraftAsset, PublishJob
from backend.app.models.course_visual_workflow import CourseVisualWorkflow
from backend.app.services import course_visual_workflow as flow

PLAN = {'pages': list(range(2, 10))}
OTHER = {'pages': list(range(3, 11))}


def append(r, row, plan=PLAN, key=None, expected=200):
    return call(r, row, 'append-pdf-pages', {'request_key': key or str(uuid4()), 'pdf_page_plan': plan}, expected)


def test_new_records_default_to_eight_full_pages_and_short_records_do_not_fake_pages(research):
    row, _ = long_record(research)
    assert row['data']['pdf_page_plan'] == PLAN and 'collage_plan' not in row['data']
    assert row['pdf_page_status']['enabled'] and row['pdf_page_status']['available']
    assert [p['kind'] for p in row['direction']['pages']][-8:] == ['pdf-page'] * 8
    row = approve(research, row, 'copy')
    row = call(research, row, 'render-bundle', {'request_key': str(uuid4())})
    assert len(row['data']['images']) == 12 and flow.complete_set(raw(research, row)['data'])
    assert [a['source_page'] for a in row['data']['images'][-8:]] == PLAN['pages']
    short = {**row['data'], 'source': {**row['data']['source'], 'page_count': 8}}
    status = flow.pdf_page_status(short)
    assert not status['available'] and status['default_plan'] is None and '不重复' in status['message']
    initial = flow.initial_data(short['source'], flow.catalog())
    assert 'pdf_page_plan' not in initial and 'collage_plan' not in initial
    untouched_tasks(research)


def test_migrate_three_plus_two_into_three_plus_eight_keeps_originals_and_old_collage_history(old_set):
    r, row, source = old_set; base = deepcopy(row['data']['images']); source_hash = flow.hash_file(source)
    row = legacy_append(r, row); legacy = deepcopy(row['data']['images']); before = raw(r, row)['data']
    assert len(legacy) == 5
    row = append(r, row, {'pages': [9, 2, 8, 3, 7, 4, 6, 5]})
    assert len(row['data']['images']) == 11 and row['data']['images'][:3] == base
    assert row['data']['pdf_page_plan'] == PLAN and 'collage_plan' not in row['data']
    assert row['data']['approvals'] == before['approvals'] and row['approved']['copy']
    assert not row['approved']['cover'] and not row['approved']['set'] and row['data']['export'] is None
    assert [a['kind'] for a in row['data']['images'][-8:]] == ['pdf-page'] * 8
    assert [a['source_page'] for a in row['data']['images'][-8:]] == PLAN['pages']
    stored = raw(r, row)['data']
    assert stored['history'][-1]['collage_plan'] == before['collage_plan']
    assert stored['history'][-1]['images'] == before['images'] and flow.bundle_ready(stored)
    for asset in legacy[-2:]:
        assert r[0].get(f'{BASE}/{row["id"]}/images/{asset["id"]}', headers=r[1]).status_code == 200
    for asset in row['data']['images']:
        data = r[0].get(f'{BASE}/{row["id"]}/images/{asset["id"]}', headers=r[1]).content
        assert Image.open(BytesIO(data)).size == (1080, 1440)
    assert all(a['full_page'] for a in row['data']['images'][-8:]) and flow.hash_file(source) == source_hash
    untouched_tasks(r)


def test_full_page_append_replays_without_duplicates_and_replaces_only_the_eight_page_tail(old_set):
    r, row, _ = old_set; original = deepcopy(row['data']['images']); key = str(uuid4()); version = row['row_version']
    row = append(r, row, key=key); before = raw(r, row)
    result = r[0].post(f'{BASE}/{row["id"]}/append-pdf-pages', headers=r[1],
                      json={'expected_version': version, 'request_key': key, 'pdf_page_plan': PLAN})
    assert result.status_code == 200 and raw(r, row) == before
    assert append(r, row, key=key)['row_version'] == row['row_version']
    assert append(r, row)['row_version'] == row['row_version'] and raw(r, row) == before
    append(r, row, OTHER, key, expected=409)
    previous_tail = [a['id'] for a in row['data']['images'][-8:]]
    row = append(r, row, OTHER)
    assert row['data']['images'][:3] == original and len(row['data']['images']) == 11
    assert [a['source_page'] for a in row['data']['images'][-8:]] == OTHER['pages']
    assert [a['id'] for a in row['data']['history'][-1]['images'][-8:]] == previous_tail
    untouched_tasks(r)


def test_single_page_plan_takes_precedence_over_legacy_collage_in_direction(old_set):
    _, row, _ = old_set; data = deepcopy(row['data'])
    data['collage_plan'] = {'groups': [[2, 3, 4, 5], [6, 7, 8, 9]]}; data['pdf_page_plan'] = PLAN
    direction = flow.direct(data)
    assert len([p for p in direction['pages'] if p['kind'] == 'pdf-page']) == 8
    assert not any(p['kind'] == 'collage' for p in direction['pages'])
    assert not flow.collage_status(data)['enabled']


def test_plan_only_patch_and_fork_keep_copy_cover_scope_and_do_not_reenable_collages(old_set):
    r, row, _ = old_set; row = approve(r, row, 'cover'); original = raw(r, row)
    row = legacy_append(r, row)
    copy_digest = row['digests']['copy']; cover_digest = row['digests']['cover']
    row = save(r, row, pdf_page_plan={'pages': list(reversed(PLAN['pages']))})
    assert row['data']['pdf_page_plan'] == PLAN and 'collage_plan' not in row['data']
    assert row['approved']['copy'] and row['approved']['cover'] and not row['approved']['set']
    assert row['digests']['copy'] == copy_digest and row['digests']['cover'] == cover_digest
    assert not row['data']['images'] and row['data']['cover']['id'] == original['data']['cover']['id']
    child = call(r, row, 'fork')
    assert child['data']['pdf_page_plan'] == PLAN and 'collage_plan' not in child['data']
    assert not child['data']['images'] and not any(child['approved'].values())
    untouched_tasks(r)


@pytest.mark.parametrize('plan', [
    {'pages': []}, {'pages': list(range(2, 9))}, {'pages': list(range(2, 12))},
    {'pages': [2, 3, 4, 5, 6, 7, 8, 8]}, {'pages': list(range(1, 9))},
    {'pages': [2, 3, 4, 5, 6, 7, 8, 13]}, {'pages': [2.5, 3, 4, 5, 6, 7, 8, 9]},
])
def test_invalid_or_insufficient_page_selections_never_modify_business_state(old_set, plan):
    r, row, _ = old_set; before = raw(r, row)
    append(r, row, plan, expected=422)
    assert raw(r, row) == before
    untouched_tasks(r)


def test_owner_version_copy_and_source_guards(old_set):
    r, row, source = old_set; before = raw(r, row); path = f'{BASE}/{row["id"]}/append-pdf-pages'
    payload = {'expected_version': row['row_version'], 'request_key': str(uuid4()), 'pdf_page_plan': PLAN}
    assert r[0].post(path, json=payload).status_code == 401
    assert r[0].post(path, headers=r[2], json=payload).status_code == 404
    assert r[0].post(path, headers=r[1], json={**payload, 'expected_version': row['row_version']-1}).status_code == 409
    assert raw(r, row) == before
    with source.open('ab') as stream: stream.write(b'\n% synthetic source version change\n')
    append(r, row, expected=409)
    assert raw(r, row) == before
    untouched_tasks(r)


def test_failed_render_and_concurrent_change_do_not_overwrite_original_tail(old_set, monkeypatch):
    r, row, _ = old_set; row = legacy_append(r, row); before = raw(r, row); real = api.render_assets
    def fail(*args, **kwargs):
        if args[4] == 'pdf-pages': raise HTTPException(422, 'Synthetic single-page rendering failure')
        return real(*args, **kwargs)
    monkeypatch.setattr(api, 'render_assets', fail)
    append(r, row, expected=422); after = raw(r, row)
    for field in ('copy', 'cover', 'images', 'approvals', 'history', 'collage_plan', 'revision', 'export'):
        assert after['data'][field] == before['data'][field]
    assert 'pdf_page_plan' not in after['data'] and after['data']['operation']['status'] == 'failed'
    current = r[0].get(f'{BASE}/{row["id"]}', headers=r[1]).json()
    def change_record(*args, **kwargs):
        result = real(*args, **kwargs)
        if args[4] == 'pdf-pages':
            with r[3]() as db:
                record = db.get(CourseVisualWorkflow, row['id']); data = deepcopy(record.data)
                data['label'] = 'Concurrent editor'; data['operation'] = {'key': 'other', 'status': 'generating'}
                record.data = data; db.commit()
        return result
    monkeypatch.setattr(api, 'render_assets', change_record)
    append(r, current, expected=409); final = raw(r, row)['data']
    assert final['label'] == 'Concurrent editor' and final['operation'] == {'key': 'other', 'status': 'generating'}
    assert final['images'] == before['data']['images'] and 'pdf_page_plan' not in final
    untouched_tasks(r)


def test_full_page_caption_only_revise_blocks_background_and_keeps_source_order(old_set):
    r, row, _ = old_set; row = append(r, row); original = deepcopy(row['data']['images']); asset = original[-1]
    call(r, row, 'background-plan', {'slot': asset['slot']}, 422)
    call(r, row, 'revise', {'asset_id': asset['id'], 'brief': {**asset['brief'], 'text': '不允许改原文'}}, 422)
    row = call(r, row, 'revise', {'asset_id': asset['id'], 'brief': {**asset['brief'], 'subtitle': '保留完整原页，放大查看细节。'}})
    assert row['data']['images'][:-1] == original[:-1] and row['data']['images'][-1]['id'] != asset['id']
    assert row['data']['images'][-1]['source_page'] == asset['source_page'] and flow.bundle_ready(raw(r, row)['data'])
    legacy_append(r, row, expected=409)
    untouched_tasks(r)


def test_restore_keeps_legacy_collage_history_and_removes_active_single_page_plan(old_set):
    r, row, _ = old_set; row = legacy_append(r, row); before = raw(r, row)['data']
    row = append(r, row); previous = row['data']['history'][-1]['revision']
    row = call(r, row, 'restore', {'revision': previous}); restored = raw(r, row)['data']
    assert restored['collage_plan'] == before['collage_plan'] and 'pdf_page_plan' not in restored
    assert restored['images'] == before['images'] and not any(row['approved'].values())
    untouched_tasks(r)


def test_existing_exported_draft_is_retained_and_new_pages_stay_pending_until_review(old_set):
    r, row, _ = old_set; row = legacy_append(r, row)
    row = call(r, row, 'approve', {'stage': 'set', 'combined_review': True, 'reviewed': True, 'digest': row['digests']['set']})
    row = call(r, row, 'export', {'reviewed': True, 'digest': row['digests']['set']})
    old_draft = row['data']['export']['draft_id']; original_approvals = deepcopy(row['data']['approvals'])
    row = append(r, row)
    assert row['data']['approvals']['copy'] == original_approvals['copy']
    assert row['data']['approvals']['cover'] == original_approvals['cover']
    assert row['data']['export'] is None and not row['approved']['set']
    assert row['data']['history'][-1]['export']['draft_id'] == old_draft
    call(r, row, 'export', {'reviewed': True, 'digest': row['digests']['set']}, 409)
    with r[3]() as db:
        assert db.scalar(select(func.count()).select_from(AiDraft)) == 1 and db.get(AiDraft, old_draft) is not None
        assert db.scalar(select(func.count()).select_from(DraftAsset)) == 5
        for model in (AutoTask, PublishJob): assert db.scalar(select(func.count()).select_from(model)) == 0


def test_missing_current_copy_approval_blocks_append_without_reserving_operation(old_set):
    r, row, _ = old_set
    with r[3]() as db:
        record = db.get(CourseVisualWorkflow, row['id']); data = deepcopy(record.data)
        data['approvals'].pop('copy'); record.data = data; db.commit()
    row = r[0].get(f'{BASE}/{row["id"]}', headers=r[1]).json(); before = raw(r, row)
    append(r, row, expected=409)
    assert raw(r, row) == before
    untouched_tasks(r)


def test_wrong_source_page_order_cannot_be_approved_as_the_current_plan(old_set):
    r, row, _ = old_set; row = append(r, row)
    with r[3]() as db:
        record = db.get(CourseVisualWorkflow, row['id']); data = deepcopy(record.data)
        data['images'][-1]['source_page'] = 2
        data['render_bundle']['digest'] = flow.fingerprint(data, 'set')
        record.data = data; db.commit()
    row = r[0].get(f'{BASE}/{row["id"]}', headers=r[1]).json()
    call(r, row, 'approve', {'stage': 'set', 'combined_review': True, 'reviewed': True, 'digest': row['digests']['set']}, 409)
    untouched_tasks(r)
