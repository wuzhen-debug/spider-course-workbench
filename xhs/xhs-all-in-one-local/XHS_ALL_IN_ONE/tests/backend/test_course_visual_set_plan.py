"""Independent inner-page plans: 4 explanations + 4 actual synthetic PDF pages.

All databases, source PDFs and rendered assets live in pytest temporary roots.
No real user record, external model or publishing endpoint is used.
"""
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path

from PIL import Image
import pytest
from sqlalchemy import func, select

from test_course_visual_workflow import BASE, approve, call, copy_ready, research
from test_course_library import library, scan
from backend.app.models import AiDraft, AutoTask, PublishJob
from backend.app.models.course_visual_workflow import CourseVisualWorkflow
from backend.app.services import course_visual_workflow as flow


def multipage_pdf(count=5):
    """Small independent PDF protocol fixture, not a course deliverable."""
    font_id = 3 + count * 2
    kids = ' '.join(f'{3 + i * 2} 0 R' for i in range(count))
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               f'<< /Type /Pages /Kids [{kids}] /Count {count} >>'.encode()]
    for i in range(count):
        stream = f'BT /F1 24 Tf 60 700 Td (SYNTHETIC SET PLAN PAGE {i + 1}) Tj ET'.encode()
        objects.extend([
            f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {4 + i * 2} 0 R >>'.encode(),
            b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream'])
    objects.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    data = b'%PDF-1.4\n'; offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data)); data += f'{number} 0 obj\n'.encode() + obj + b'\nendobj\n'
    start = len(data)
    data += f'xref\n0 {len(objects) + 1}\n0000000000 65535 f \n'.encode()
    data += b''.join(f'{offset:010} 00000 n \n'.encode() for offset in offsets)
    return data + f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()


@pytest.fixture
def set_workflow(research):
    c, headers, other, factory, watcher, settings, *_ = research
    source = watcher.root / '02墨大/MAST10007/期末复习讲义/MAST10007_26S2_Final.pdf'
    source.write_bytes(multipage_pdf()); scan(watcher)
    row = copy_ready(research)
    plan = {**row['data']['visual_plan'], 'template_id': 'decision-map', 'density': 'standard', 'sample_pages': [2, 3]}
    changed = c.patch(f'{BASE}/{row["id"]}', headers=headers,
                      json={'expected_version': row['row_version'], 'visual_plan': plan})
    assert changed.status_code == 200, changed.text
    row = approve(research, changed.json(), 'copy')
    before_source = (source.stat().st_mtime_ns, hashlib.sha256(source.read_bytes()).hexdigest())
    return research, row, source, before_source


def eight_plan():
    return {'sample_pages': [2, 3, 4, 5],
            'sample_instructions': ['目录结构示意', '条件检查示意', '项目练习示意', '核对步骤示意'],
            'extra_explanations': [{'title': '判断之前先核对口径', 'subtitle': '保留条件，再说明理由',
                'text': '先检查对象与口径，再说明为什么适用。', 'layout': 'flow',
                'nodes': ['对象｜先确认题目求什么', '条件｜检查方法成立的前提', '解释｜写出判断理由']}]} 


def raw(factory, run_id):
    with factory() as db:
        row = db.get(CourseVisualWorkflow, run_id)
        return {'row_version': row.row_version, 'data': deepcopy(row.data)}


def no_publication(factory):
    with factory() as db:
        for model in [AiDraft, PublishJob, AutoTask]:
            assert db.scalar(select(func.count()).select_from(model)) == 0


def seed_reviewed_visuals(r, row):
    c, headers, _, factory, *_ = r
    with factory() as db:
        record = db.get(CourseVisualWorkflow, row['id']); data = deepcopy(record.data)
        cover = {'id': 'approved-cover', 'kind': 'cover', 'slot': 'cover', 'role': 'Cover fixture',
                 'path': 'synthetic/cover.png', 'sha256': 'cover-fixture', 'brief': {'title': '已审核封面'}}
        sample = {'id': 'old-sample', 'kind': 'sample', 'slot': 'sample-0', 'source_page': 2,
                  'role': 'Old inner-page fixture', 'path': 'synthetic/sample.png', 'sha256': 'sample-fixture', 'brief': {}}
        data['cover'] = cover; data['images'] = [deepcopy(cover), sample]
        data['page_overrides'] = {'cover': {'title': '已审核封面'}, 'method': {'title': '旧内页覆盖'},
                                  'sample-0': {'subtitle': '旧样页说明'}}
        data['set_plan'] = {'sample_pages': [2], 'sample_instructions': ['旧方案'], 'extra_explanations': []}
        for stage in ['cover', 'set']:
            data['approvals'][stage] = {'digest': flow.fingerprint(data, stage), 'source': 'isolated-fixture'}
        data['export'] = {'draft_id': 990001, 'at': '2026-01-01T00:00:00', 'snapshot': {}}
        record.data = data; db.commit()
    return c.get(f'{BASE}/{row["id"]}', headers=headers).json()


def test_set_only_change_keeps_approved_copy_cover_and_archives_previous_set(set_workflow):
    r, row, source, before_source = set_workflow; c, headers, _, factory, *_ = r
    row = seed_reviewed_visuals(r, row); before = raw(factory, row['id'])
    changed = c.patch(f'{BASE}/{row["id"]}', headers=headers,
        json={'expected_version': row['row_version'], 'set_plan': eight_plan()})
    assert changed.status_code == 200, changed.text
    result = changed.json(); stored = raw(factory, row['id'])['data']
    for key in ['copy', 'cover', 'visual_plan', 'source']:
        assert stored[key] == before['data'][key]
    for stage in ['copy', 'cover']:
        assert stored['approvals'][stage] == before['data']['approvals'][stage]
        assert result['approved'][stage] and result['digests'][stage] == row['digests'][stage]
    assert result['data']['images'] == [] and result['data']['export'] is None
    assert not result['approved']['set'] and 'set' not in stored['approvals']
    assert stored['page_overrides'] == {'cover': before['data']['page_overrides']['cover']}
    history = stored['history'][-1]
    assert history['images'] == before['data']['images'] and history['export'] == before['data']['export']
    assert history['set_plan'] == before['data']['set_plan']
    assert history['approvals']['set'] == before['data']['approvals']['set']
    assert before_source == (source.stat().st_mtime_ns, hashlib.sha256(source.read_bytes()).hexdigest())
    no_publication(factory)


def test_same_inner_plan_is_noop_and_returning_to_old_plan_does_not_restore_old_approval(set_workflow):
    r, row, *_ = set_workflow; c, headers, _, factory, *_ = r
    row = seed_reviewed_visuals(r, row); old_plan = deepcopy(row['data']['set_plan'])
    first = c.patch(f'{BASE}/{row["id"]}', headers=headers,
        json={'expected_version': row['row_version'], 'set_plan': eight_plan()}).json()
    stored = raw(factory, row['id'])
    duplicate = c.patch(f'{BASE}/{row["id"]}', headers=headers,
        json={'expected_version': first['row_version'], 'set_plan': eight_plan()})
    assert duplicate.status_code == 200 and raw(factory, row['id']) == stored
    reverted = c.patch(f'{BASE}/{row["id"]}', headers=headers,
        json={'expected_version': first['row_version'], 'set_plan': old_plan})
    assert reverted.status_code == 200, reverted.text
    assert not reverted.json()['approved']['set'] and reverted.json()['data']['images'] == []
    assert reverted.json()['approved']['copy'] and reverted.json()['approved']['cover']


def test_independent_plan_fingerprints_and_cover_direction_are_stable(set_workflow):
    r, row, *_ = set_workflow; _, _, _, factory, *_ = r
    state = raw(factory, row['id'])['data']; baseline = deepcopy(state)
    cover = flow.direct(state)['pages'][0]; copy_digest = flow.fingerprint(state, 'copy'); cover_digest = flow.fingerprint(state, 'cover')
    old_set = flow.fingerprint(state, 'set'); state['set_plan'] = eight_plan()
    direction = flow.direct(state)
    assert flow.fingerprint(state, 'copy') == copy_digest and flow.fingerprint(state, 'cover') == cover_digest
    assert flow.fingerprint(state, 'set') != old_set
    assert direction['pages'][0] == cover, 'The accepted cover must still use visual_plan only'
    assert [p['slot'] for p in direction['pages']] == ['cover', 'method', 'method-extra-0', 'sample-0', 'sample-1', 'sample-2', 'sample-3', 'use']
    assert [p['source_page'] for p in direction['pages'] if p['kind'] == 'sample'] == [2, 3, 4, 5]
    assert len([p for p in direction['pages'] if p['kind'] != 'sample']) == 4
    assert baseline == raw(factory, row['id'])['data'], 'Planning must not mutate the stored record'


@pytest.mark.parametrize('invalid', [
    {'sample_pages': []}, {'sample_pages': [2, 2]}, {'sample_pages': [0]}, {'sample_pages': [6]},
    {'sample_pages': [1, 2, 3, 4, 5]},
    {'sample_pages': [2], 'extra_explanations': [{'title': '节点过多', 'text': '解释条件。', 'nodes': ['a', 'b', 'c', 'd']}]},
    {'sample_pages': [2], 'extra_explanations': [{'title': '错误布局', 'text': '解释条件。', 'layout': 'full-page'}]},
    {'sample_pages': [2], 'extra_explanations': [{'title': '卡片', 'text': '解释条件。'}] * 4},
])
def test_invalid_sample_or_empty_extra_card_cannot_touch_saved_data(set_workflow, invalid):
    r, row, *_ = set_workflow; c, headers, _, factory, *_ = r; before = raw(factory, row['id'])
    result = c.patch(f'{BASE}/{row["id"]}', headers=headers,
        json={'expected_version': row['row_version'], 'set_plan': invalid})
    assert result.status_code == 422, result.text
    assert raw(factory, row['id']) == before


@pytest.mark.parametrize('page', [{'title':'暂存标题','text':''}, {'title':'','text':'尚未写完的解释'}, {'title':'只写了标题'}])
def test_partial_extra_explanation_saves_as_wip_but_never_renders_an_empty_page(set_workflow, page):
    from uuid import uuid4
    r, row, *_ = set_workflow; c, headers, _, factory, *_ = r
    response = c.patch(f'{BASE}/{row["id"]}', headers=headers, json={
        'expected_version':row['row_version'], 'set_plan':{'sample_pages':[2], 'extra_explanations':[page]}})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved['production']['needs_planning'] and saved['approved']['copy']
    before = raw(factory,row['id'])
    rejected = c.post(f'{BASE}/{row["id"]}/render-bundle', headers=headers,
        json={'expected_version':saved['row_version'],'request_key':str(uuid4())})
    assert rejected.status_code == 422 and raw(factory,row['id']) == before
    no_publication(factory)


def test_set_plan_requires_auth_ownership_and_expected_version(set_workflow):
    r, row, *_ = set_workflow; c, headers, other, factory, *_ = r; before = raw(factory, row['id'])
    path = f'{BASE}/{row["id"]}'; payload = {'expected_version': row['row_version'], 'set_plan': eight_plan()}
    assert c.patch(path, json=payload).status_code == 401
    assert c.patch(path, headers=other, json=payload).status_code == 404
    assert c.patch(path, headers=headers, json={**payload, 'expected_version': row['row_version'] - 1}).status_code == 409
    assert raw(factory, row['id']) == before


def test_legacy_state_without_set_plan_keeps_original_pages_and_digests(set_workflow):
    r, row, *_ = set_workflow; _, _, _, factory, *_ = r
    state = raw(factory, row['id'])['data']; assert 'set_plan' not in state
    direction = flow.direct(state); old = deepcopy(state)
    assert [p['slot'] for p in direction['pages']] == ['cover', 'method', 'sample-0', 'sample-1', 'use']
    assert [p['source_page'] for p in direction['pages'] if p['kind'] == 'sample'] == [2, 3]
    assert not any(p['slot'].startswith('method-extra-') for p in direction['pages'])
    assert state == old and 'set_plan' not in raw(factory, row['id'])['data']


def test_restore_adds_or_removes_set_plan_from_the_selected_snapshot_without_reviving_approval(set_workflow):
    r, row, *_ = set_workflow; c, headers, _, factory, *_ = r
    original_revision = row['data']['revision']
    first = c.patch(f'{BASE}/{row["id"]}', headers=headers,
        json={'expected_version': row['row_version'], 'set_plan': eight_plan()})
    assert first.status_code == 200, first.text
    with_set = first.json(); with_set_revision = with_set['data']['revision']
    second = c.patch(f'{BASE}/{row["id"]}', headers=headers,
        json={'expected_version': with_set['row_version'], 'set_plan': {'sample_pages': [2], 'extra_explanations': []}})
    assert second.status_code == 200, second.text
    restored_legacy = call(r, second.json(), 'restore', {'revision': original_revision})
    assert 'set_plan' not in restored_legacy['data']
    assert not any(restored_legacy['approved'].values()) and restored_legacy['data']['export'] is None
    restored_set = call(r, restored_legacy, 'restore', {'revision': with_set_revision})
    assert restored_set['data']['set_plan'] == eight_plan()
    assert not any(restored_set['approved'].values()) and restored_set['data']['export'] is None
    assert restored_set['data']['copy'] == row['data']['copy']
    assert restored_set['data']['source'] == row['data']['source']
    no_publication(factory)


def test_actual_eight_image_render_and_extra_revision_preserve_cover_and_sources(set_workflow):
    r, row, source, before_source = set_workflow; c, headers, other, factory, _, settings, *_ = r
    row = call(r, row, 'render', {'stage': 'cover'}); row = approve(r, row, 'cover')
    saved_cover = raw(factory, row['id'])['data']['cover']; cover_digest = row['digests']['cover']
    changed = c.patch(f'{BASE}/{row["id"]}', headers=headers,
        json={'expected_version': row['row_version'], 'set_plan': eight_plan()})
    assert changed.status_code == 200, changed.text
    row = changed.json(); assert row['approved']['cover'] and row['digests']['cover'] == cover_digest
    row = call(r, row, 'render', {'stage': 'set'})
    assert len(row['data']['images']) == 8 and row['data']['images'][0]['id'] == saved_cover['id']
    assert row['approved']['copy'] and row['approved']['cover'] and not row['approved']['set']
    assert [a['source_page'] for a in row['data']['images'] if a['kind'] == 'sample'] == [2, 3, 4, 5]
    for asset in row['data']['images']:
        assert 'path' not in asset and 'source_images' not in asset
        response = c.get(f'{BASE}/{row["id"]}/images/{asset["id"]}', headers=headers)
        assert response.status_code == 200 and Image.open(BytesIO(response.content)).size == (1080, 1440)
        assert hashlib.sha256(response.content).hexdigest() == asset['sha256']
        assert c.get(f'{BASE}/{row["id"]}/images/{asset["id"]}', headers=other).status_code == 404
    extra = next(a for a in row['data']['images'] if a['slot'] == 'method-extra-0')
    row = approve(r, row, 'set')
    new_brief = {**extra['brief'], 'title': '先把判断条件写清楚'}
    row = call(r, row, 'revise', {'asset_id': extra['id'], 'brief': new_brief})
    current_extra = next(a for a in row['data']['images'] if a['slot'] == 'method-extra-0')
    assert current_extra['id'] != extra['id'] and current_extra['brief']['title'] == new_brief['title']
    assert len(row['data']['images']) == 8 and row['approved']['cover'] and not row['approved']['set']
    assert row['digests']['cover'] == cover_digest and raw(factory, row['id'])['data']['cover'] == saved_cover
    assert c.get(f'{BASE}/{row["id"]}/images/{extra["id"]}', headers=headers).status_code == 200
    source_svg = c.get(f'{BASE}/{row["id"]}/images/{current_extra["id"]}', headers=headers, params={'source': True})
    assert source_svg.status_code == 200 and b'<svg' in source_svg.content
    assert new_brief['title'].encode() in source_svg.content
    assert before_source == (source.stat().st_mtime_ns, hashlib.sha256(source.read_bytes()).hexdigest())
    assert row['data']['copy'] == set_workflow[1]['data']['copy'] and row['data']['export'] is None
    no_publication(factory)
