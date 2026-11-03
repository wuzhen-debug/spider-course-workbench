"""A is additive: explicit selection, 4+9 slots, no fabricated approvals."""
from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi import HTTPException

from test_course_library import library
from test_course_visual_workflow import BASE, research, call
from test_course_visual_collages import long_record, raw, untouched_tasks
from backend.app.api import course_visual_workflow as api
from backend.app.services import course_visual_workflow as flow
from backend.app.services.course_visual_import import local_file, safe_svg


def test_new_a_record_is_explicit_and_old_create_default_stays_legacy(research):
    old, _ = long_record(research)
    assert old['data']['visual_plan'].get('template_id', 'legacy') == 'legacy'
    created = research[0].post(BASE, headers=research[1], json={'file_id': old['file_id'],
        'revision_id': old['data']['source']['revision_id'], 'request_key': str(uuid4()), 'template_id': 'magazine-a'})
    assert created.status_code == 200, created.text
    row = created.json()
    assert row['data']['visual_plan']['template_id'] == 'magazine-a'
    assert row['data']['pdf_page_plan']['pages'] == list(range(2, 11))
    assert len(row['data']['set_plan']['extra_explanations']) == 2
    assert row['data']['approvals'] == {} and row['data']['export'] is None
    assert [p['kind'] for p in row['direction']['pages']] == ['cover'] + ['method'] * 3 + ['pdf-page'] * 9
    untouched_tasks(research)


def test_explicit_a_switch_checkpoints_preserves_copy_and_refuses_empty_teaching(research):
    old, _ = long_record(research)
    before = raw(research, old)
    row = call(research, old, 'select-template', {'template_id': 'magazine-a'})
    assert raw(research, row)['data']['history'][-1]['visual_plan'] == before['data']['visual_plan']
    assert row['data']['copy'] == before['data']['copy']
    assert len(row['data']['pdf_page_plan']['pages']) == 9
    assert not any(row['approved'].values())
    with pytest.raises(HTTPException):
        flow.require_magazine_content(row['data'])
    assert call(research, row, 'select-template', {'template_id': 'magazine-a'})['row_version'] == row['row_version']
    untouched_tasks(research)


def test_a_complete_set_accepts_raw_previews_and_legacy_still_requires_samples(research):
    old, _ = long_record(research)
    data = flow.magazine_defaults(old['data'])
    for item in data['set_plan']['extra_explanations']:
        item['text'] = 'An explicit synthetic explanation for this fixture.'
    flow.require_magazine_content(data)
    pages = flow.direct(data)['pages']
    assert len(pages) == 13 and [p['slot'] for p in pages[:4]] == ['cover', 'method', 'method-extra-0', 'method-extra-1']
    assert all(p['raw_pdf'] for p in pages[4:])
    images = [{'id': str(i), **{k: p[k] for k in ['kind', 'slot', 'source_page'] if k in p}} for i, p in enumerate(pages)]
    data.update(cover=images[0], images=images)
    assert flow.complete_set(data)
    flow.mark_bundle(data)
    assert flow.bundle_ready(data) and not any(flow.approved(data, stage) for stage in ['copy', 'cover', 'set'])
    bad = deepcopy(data); bad['images'] = bad['images'][:-1]
    assert not flow.complete_set(bad)
    assert api.PdfPagePlan(pages=list(reversed(range(2, 11)))).pages == list(range(2, 11))
    assert api.PdfPagePlan(pages=list(range(2, 10))).pages == list(range(2, 10))


def test_pdf_analysis_is_not_mislabelled_as_xhs_detail_or_comments():
    actual = api.evidence_review([{'id': 'local-pdf', 'evidence_type': 'pdf-analysis'}])
    assert actual['basis'] == 'pdf-analysis' and not actual['limited']
    assert actual['detail_count'] == actual['comments_read'] == 0
    assert '教学分析' in actual['message'] and '未执行' in actual['message']


def test_import_asset_paths_and_svg_are_passive_and_bounded(tmp_path):
    root = tmp_path / 'bundle'; root.mkdir()
    png = root / 'image.png'; png.write_bytes(b'fixture')
    assert local_file(root, 'image.png', '.png') == png
    for name in ['../image.png', '/etc/passwd', 'image.jpg']:
        with pytest.raises((ValueError, FileNotFoundError)):
            local_file(root, name, '.png')
    (root / 'linked.png').symlink_to(png)
    with pytest.raises(ValueError):
        local_file(root, 'linked.png', '.png')
    passive = root / 'safe.svg'; passive.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>Safe</text></svg>')
    safe_svg(passive)
    for value in ['<svg><script>alert(1)</script></svg>', '<svg><image href="https://external.example/a.png"/></svg>', '<svg onload="alert(1)"/>']:
        passive.write_text(value)
        with pytest.raises(ValueError):
            safe_svg(passive)


def test_a_ai_prompt_requests_two_real_explanations_only_for_a(research):
    row, _ = long_record(research); original = row['data']
    assert 'A版额外返回set_plan' not in flow.visual_prompt(original, {'pages': []})
    selected = flow.magazine_defaults(original)
    assert 'A版额外返回set_plan' in flow.visual_prompt(selected, {'pages': []})


def test_a_rejects_unused_paid_background_before_planning_or_external_requests(research):
    old, _ = long_record(research)
    row = call(research, old, 'select-template', {'template_id': 'magazine-a'})
    before = raw(research, row)
    first = call(research, row, 'background-plan', {}, 422)
    assert '未调用图片模型' in first['detail']
    second = call(research, row, 'generate-background', {'external_consent': True,
        'plan_digest': 'x', 'request_key': str(uuid4())}, 422)
    assert '未调用图片模型' in second['detail']
    assert raw(research, row) == before
    untouched_tasks(research)
