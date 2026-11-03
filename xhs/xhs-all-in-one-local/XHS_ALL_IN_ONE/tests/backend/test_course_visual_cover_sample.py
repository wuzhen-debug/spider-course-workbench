"""Explicit cover reference is independently editable from inner-page samples."""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import base64

import pytest
from sqlalchemy import select

from test_course_library import library
from test_course_visual_workflow import BASE, call, approve, research
from test_course_visual_set_plan import set_workflow, raw, no_publication
from backend.app.services import course_visual_workflow as flow
from backend.app.main import app
from backend.app.api.ai import get_text_ai_client
from backend.app.models import ModelConfig, User
from backend.app.core.security import encrypt_text


def save(r, row, **values):
    c, headers, *_ = r
    result = c.patch(f'{BASE}/{row["id"]}', headers=headers,
                     json={'expected_version': row['row_version'], **values})
    assert result.status_code == 200, result.text
    return result.json()


def test_inner_page_selection_cannot_silently_select_cover_and_preflight_does_not_write(set_workflow):
    r, row, *_ = set_workflow
    row = save(r, row, visual_plan={**row['data']['visual_plan'], 'sample_pages': [1]},
               set_plan={'sample_pages': [2, 3], 'extra_explanations': []})
    before = raw(r[3], row['id'])
    failed = call(r, row, 'render-bundle', {'request_key': str(uuid4())}, 422)
    assert '封面正文样张' in failed['detail'] and '保存方案' in failed['detail']
    assert before == raw(r[3], row['id']), 'Missing cover choice must not reserve operation or append requests'
    assert flow.content_sample_page(row['data']) is None
    no_publication(r[3])


def test_explicit_cover_page_renders_even_when_old_sample_list_contains_only_cover(set_workflow):
    r, row, source, original_source = set_workflow
    row = save(r, row, visual_plan={**row['data']['visual_plan'], 'sample_pages': [1], 'cover_sample_page': 4},
               set_plan={'sample_pages': [2, 3], 'extra_explanations': []})
    copy_approval = deepcopy(row['data']['approvals']['copy'])
    row = call(r, row, 'render-bundle', {'request_key': str(uuid4())})
    assert row['approved'] == {'copy': True, 'cover': False, 'set': False}
    assert row['data']['approvals']['copy'] == copy_approval
    assert row['data']['visual_plan']['cover_sample_page'] == 4
    assert not any(check['id'] == 'cover_only_sample' for check in row['quality']['checks'])
    assert [image['source_page'] for image in row['data']['images'] if image['kind'] == 'sample'] == [2, 3]
    stored = raw(r[3], row['id'])['data']; cover = stored['cover']
    storage = Path(r[5].storage_dir) / 'course-visual' / 'u1' / f'r{row["id"]}'
    cover_dir = (storage / cover['path']).parent
    # The cover's actual embedded page came from explicit page4, not set_plan pages2/3.
    image4 = (cover_dir / 'input-4.png').read_bytes()
    actual_svg = r[0].get(f'{BASE}/{row["id"]}/images/{cover["id"]}', headers=r[1], params={'source': True}).text
    assert 'data:image/png;base64,' + base64.b64encode(image4).decode() in actual_svg
    assert flow.bundle_ready(stored)
    assert (source.stat().st_mtime_ns, flow.hash_file(source)) == original_source
    no_publication(r[3])


def test_set_only_updates_keep_explicit_cover_identity_and_approval(set_workflow):
    r, row, *_ = set_workflow
    row = save(r, row, visual_plan={**row['data']['visual_plan'], 'cover_sample_page': 4})
    row = call(r, row, 'render-bundle', {'request_key': str(uuid4())})
    row = approve(r, row, 'cover')
    cover = deepcopy(row['data']['cover']); digest = row['digests']['cover']
    row = save(r, row, set_plan={'sample_pages': [5], 'sample_instructions': ['只更新内页'], 'extra_explanations': []})
    assert row['approved']['cover'] and row['digests']['cover'] == digest
    assert row['data']['cover'] == cover and row['data']['visual_plan']['cover_sample_page'] == 4
    row = call(r, row, 'render-bundle', {'request_key': str(uuid4())})
    assert row['data']['cover'] == cover and row['data']['render_bundle']['reused_cover']
    assert [a['source_page'] for a in row['data']['images'] if a['kind'] == 'sample'] == [5]
    no_publication(r[3])


def test_explicit_cover_change_versions_and_invalidates_only_visual_approval(set_workflow):
    r, row, *_ = set_workflow
    row = call(r, row, 'render-bundle', {'request_key': str(uuid4())})
    row = approve(r, row, 'cover'); previous = deepcopy(row['data']['cover'])
    copy_approval = deepcopy(row['data']['approvals']['copy'])
    row = save(r, row, visual_plan={**row['data']['visual_plan'], 'cover_sample_page': 4})
    assert row['approved']['copy'] and not row['approved']['cover'] and not row['approved']['set']
    assert row['data']['approvals']['copy'] == copy_approval
    assert row['data']['cover'] is None and row['data']['images'] == []
    assert row['data']['history'][-1]['cover'] == previous
    no_publication(r[3])


@pytest.mark.parametrize('page', [1, 0, 6, 3.5, -1])
def test_invalid_explicit_cover_page_never_changes_record(set_workflow, page):
    r, row, *_ = set_workflow; before = raw(r[3], row['id'])
    result = r[0].patch(f'{BASE}/{row["id"]}', headers=r[1], json={'expected_version': row['row_version'],
                       'visual_plan': {**row['data']['visual_plan'], 'cover_sample_page': page}})
    assert result.status_code == 422, result.text
    assert raw(r[3], row['id']) == before


def test_legacy_field_absence_is_not_injected_and_fallback_keeps_original_cover(set_workflow):
    r, row, *_ = set_workflow; before = raw(r[3], row['id'])
    assert 'cover_sample_page' not in row['data']['visual_plan']
    assert flow.content_sample_page(row['data']) == 2
    unchanged = save(r, row, visual_plan=row['data']['visual_plan'])
    assert unchanged['row_version'] == row['row_version'] and raw(r[3], row['id']) == before
    data = deepcopy(row['data']); data['visual_plan']['cover_sample_page'] = None
    assert flow.content_sample_page(data) == 2


def test_visual_ai_receives_explicit_reference_and_cannot_replace_user_choice(set_workflow):
    r, row, *_ = set_workflow
    with r[3]() as db:
        owner = db.scalar(select(User).where(User.username == 'pdf-owner'))
        db.add(ModelConfig(user_id=owner.id, name='Fake visual planner', model_type='text', provider='openai',
                           model_name='fake-visual-plan', base_url='https://fake.invalid/v1',
                           encrypted_api_key=encrypt_text('fixture-key'), is_default=True)); db.commit()
    row = save(r, row, visual_plan={**row['data']['visual_plan'], 'cover_sample_page': 4})
    initial = deepcopy(row['data']['visual_plan'])
    class Planner:
        bad = False
        def plan_visuals(self, **kwargs):
            assert 'SYNTHETIC SET PLAN PAGE 4' in kwargs['reference']
            plan = {k: v for k, v in initial.items() if k != 'cover_sample_page'}
            if self.bad: plan['cover_sample_page'] = 3
            return {'visual_plan': plan, 'style_report': {key: '本篇真实资料。' for key in
                    ('content_type', 'goal', 'emotion', 'density', 'primary_style', 'supporting_style', 'avoid', 'reason')}}
    planner = Planner(); app.dependency_overrides[get_text_ai_client] = lambda: planner
    def prepared(value):
        result = r[0].post(f'{BASE}/{value["id"]}/prompts?purpose=visual', headers=r[1], json={})
        assert result.status_code == 200, result.text
        return result.json()
    prompt = prepared(row)
    assert 4 in prompt['allowed_pages'] and 'cover_sample_page' in prompt['prompt']
    row = call(r, row, 'generate-visual-plan', {'external_consent': True, 'plan_digest': prompt['plan_digest'], 'request_key': str(uuid4())})
    assert row['data']['visual_plan']['cover_sample_page'] == 4 and row['approved']['copy']
    before_plan = deepcopy(row['data']['visual_plan']); planner.bad = True; prompt = prepared(row)
    call(r, row, 'generate-visual-plan', {'external_consent': True, 'plan_digest': prompt['plan_digest'], 'request_key': str(uuid4())}, 502)
    current = r[0].get(f'{BASE}/{row["id"]}', headers=r[1]).json()
    assert current['data']['visual_plan'] == before_plan
    no_publication(r[3])
