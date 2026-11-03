"""Real isolated PDF/PNG composition with a stub image provider; never live billing."""
from copy import deepcopy
from io import BytesIO
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import select, func

from test_course_library import library
from test_course_visual_workflow import BASE, research, call, approve
from test_course_visual_pdf_lane import generated
from test_course_visual_bundle import state, no_publish
from backend.app.main import app
from backend.app.api import course_visual_workflow as api
from backend.app.services import course_visual_api_images as images
from backend.app.services import course_visual_workflow as flow
from backend.app.models import User, ModelConfig, AiDraft, DraftAsset, AutoTask, PublishJob
from backend.app.models.course_visual_workflow import CourseVisualWorkflow
from backend.app.core.security import encrypt_text


@pytest.fixture
def ready(research):
    _, row, source, _, _ = generated(research)
    row = approve(research, row, 'copy')
    with research[3]() as db:
        owner = db.scalar(select(User).where(User.username == 'pdf-owner'))
        model = ModelConfig(user_id=owner.id, name='Synthetic image provider', model_type='image',
                            provider='openai-compatible', model_name='doubao-seedream-5-0-flash-260915',
                            base_url='https://ark.cn-beijing.volces.com/api/v3',
                            encrypted_api_key=encrypt_text('synthetic-image-private-key'), is_default=True)
        db.add(model); db.commit(); model_id = model.id

    class Client:
        calls = 0
        fail_at = None
        callback = None
        prompts = []

        def generate(self, **kwargs):
            self.calls += 1; self.prompts.append(kwargs['prompt'])
            assert kwargs['api_key'] == 'synthetic-image-private-key'
            assert not any(s in kwargs['prompt'] for s in ('synthetic-image-private-key',
                           'fixture-private-key', 'SYNTHETIC PDF PAGE', str(research[4].root)))
            if self.callback:
                self.callback()
            if self.calls == self.fail_at:
                raise RuntimeError('synthetic-image-private-key SECRET PROVIDER BODY')
            stream = BytesIO()
            Image.new('RGB', (768, 1024), (240, 245, 250)).save(stream, 'PNG')
            return stream.getvalue()

    client = Client()
    app.dependency_overrides[images.get_image_client] = lambda: client
    return research, row, source, client, model_id


def prepared(r, row, target='bundle'):
    plan = call(r, row, 'api-image-plan', {'target': target})
    return plan, {'target': target, 'external_consent': True,
                  'plan_digest': plan['plan_digest'], 'request_key': str(uuid4())}


def latest(r, row):
    return r[0].get(f'{BASE}/{row["id"]}', headers=r[1]).json()


def test_read_only_plan_exact_count_no_pdf_logo_excerpts_or_key_transfer(ready):
    r, row, source, client, _ = ready
    before = state(r, row); original = source.read_bytes()
    plan, _ = prepared(r, row)
    assert plan['count'] == plan['image_count'] == 4 and plan['pdf_count'] == 9
    assert plan['reused_count'] == 0 and plan['local_header']['course_code'] == 'MAST10007'
    assert [p['slot'] for p in plan['pages']] == ['cover', 'method', 'method-extra-0', 'method-extra-1']
    assert plan['model']['destination'] == 'https://ark.cn-beijing.volces.com/api/v3/images/generations'
    assert state(r, row) == before and source.read_bytes() == original and client.calls == 0
    assert 'synthetic-image-private-key' not in json.dumps(plan)
    for p in plan['pages']:
        assert 'NOT a decorative background' in p['prompt']
        assert 'No page counters' in p['prompt']
        assert 'SYNTHETIC PDF PAGE' not in p['prompt']
    no_publish(r)


def test_wenguo_api_composition_uses_saved_real_logo_instead_of_global_default(ready):
    import base64
    from backend.app.services.course_brands import resolve_brand, logo_path
    from backend.app.services.course_draft_images import preview_brand
    r,row,source,client,_=ready
    with r[3]() as db:
        item=db.get(CourseVisualWorkflow,row['id']);data=deepcopy(item.data)
        data['brand']=resolve_brand('wenguo');data['source']['preview_brand']=preview_brand('wenguo')
        data['approvals']={};item.data=data;db.commit()
    row=approve(r,latest(r,row),'copy');before=source.read_bytes()
    plan,body=prepared(r,row,'cover')
    assert plan['local_header']['brand']=='稳过留学'
    result=call(r,row,'generate-api-images',body)
    assert client.calls==1 and result['data']['brand']['id']=='wenguo'
    cover=result['data']['cover']
    svg=r[0].get(f'{BASE}/{row["id"]}/images/{cover["id"]}',headers=r[1],params={'source':True}).text
    assert base64.b64encode(logo_path(resolve_brand('wenguo')).read_bytes()).decode() in svg
    assert base64.b64encode(logo_path(resolve_brand('xingtu')).read_bytes()).decode() not in svg
    assert not result['approved']['cover'] and not result['approved']['set'] and result['data']['export'] is None
    assert source.read_bytes()==before
    no_publish(r)


def test_consent_version_owner_and_target_gates_prevent_any_paid_call(ready):
    r, row, _, client, _ = ready; plan, body = prepared(r, row)
    path = f'{BASE}/{row["id"]}/generate-api-images'
    assert r[0].post(path, json=body).status_code == 401
    assert r[0].post(path, headers=r[2], json={'expected_version': row['row_version'], **body}).status_code == 404
    call(r, row, 'generate-api-images', {**body, 'external_consent': False}, 422)
    call(r, row, 'generate-api-images', {**body, 'plan_digest': '0'*64}, 422)
    call(r, row, 'generate-api-images', {**body, 'expected_version': row['row_version']-1}, 409)
    call(r, row, 'generate-api-images', {**body, 'target': 'cover'}, 422)
    call(r, row, 'api-image-plan', {'target': 'pdf-page-0'}, 422)
    with r[3]() as db:
        record = db.get(CourseVisualWorkflow, row['id']); data = deepcopy(record.data)
        data['approvals'] = {}; record.data = data; db.commit()
    call(r, latest(r, row), 'api-image-plan', {}, 409)
    assert client.calls == 0
    no_publish(r)


def test_bundle_real_composition_retains_13_old_images_copy_approval_and_raw_pdf(ready):
    r, row, source, client, _ = ready
    row = call(r, row, 'render-bundle', {'request_key': str(uuid4())})
    old = deepcopy(row['data']['images']); approval = deepcopy(state(r, row)['approvals']['copy'])
    source_hash = flow.hash_file(source); _, body = prepared(r, row)
    result = call(r, row, 'generate-api-images', body)
    assert client.calls == 4 and len(result['data']['images']) == 13
    assert result['approved'] == {'copy': True, 'cover': False, 'set': False}
    assert state(r, result)['approvals']['copy'] == approval
    assert result['data']['copy'] == row['data']['copy']
    assert flow.bundle_ready(state(r, result)) and result['data']['export'] is None
    assert all(a.get('api_generated') for a in result['data']['images'][:4])
    assert [a['id'] for a in result['data']['images'][4:]] == [a['id'] for a in old[4:]]
    assert result['data']['history'][-1]['images'][0]['id'] == old[0]['id']
    assert flow.hash_file(source) == source_hash
    for a in old:
        assert r[0].get(f'{BASE}/{row["id"]}/images/{a["id"]}', headers=r[1]).status_code == 200
    cover = result['data']['cover']
    png = r[0].get(f'{BASE}/{row["id"]}/images/{cover["id"]}', headers=r[1]).content
    with Image.open(BytesIO(png)) as image:
        assert image.size == (1080, 1440)
        assert image.getpixel((65, 90))[:3] == (7, 85, 162)  # Prominent local school/code banner.
    svg = r[0].get(f'{BASE}/{row["id"]}/images/{cover["id"]}', headers=r[1], params={'source': True}).text
    assert row['data']['source']['university'] in svg and 'MAST10007' in svg
    assert 'font-size="84"' in svg and 'font-size="52"' in svg
    assert result['data']['production_trace'][-1]['tool'] == 'seedream_full_page_with_local_identity'
    assert 'API' in result['direction']['tool']
    assert call(r, row, 'generate-api-images', body)['row_version'] == result['row_version']
    assert client.calls == 4
    call(r, result, 'export', {'reviewed': True, 'digest': result['digests']['set']}, 409)
    no_publish(r)
    # Approval/export are tested only against this disposable database.
    reviewed = call(r, result, 'approve', {'stage': 'set', 'reviewed': True,
        'combined_review': True, 'digest': result['digests']['set']})
    exported = call(r, reviewed, 'export', {'reviewed': True, 'digest': reviewed['digests']['set']})
    assert exported['data']['export']['draft_available']
    with r[3]() as db:
        assert db.scalar(select(func.count()).select_from(AiDraft)) == 1
        assert db.scalar(select(func.count()).select_from(DraftAsset)) == 13
        for model in (AutoTask, PublishJob):
            assert db.scalar(select(func.count()).select_from(model)) == 0


def test_first_cover_is_one_call_not_a_fake_approved_set(ready):
    r, row, _, client, _ = ready; plan, body = prepared(r, row, 'cover')
    assert plan['count'] == 1 and plan['pdf_count'] == 0
    result = call(r, row, 'generate-api-images', body)
    assert client.calls == 1 and result['data']['cover']['api_generated']
    assert result['data']['images'] == [] and not result['approved']['cover']
    assert not flow.bundle_ready(state(r, result))
    call(r, result, 'api-image-plan', {'target': 'method'}, 422)
    no_publish(r)


def test_api_single_image_redo_keeps_all_other_images_and_pending_review(ready):
    r, row, _, client, _ = ready
    row = call(r, row, 'render-bundle', {'request_key': str(uuid4())})
    before = deepcopy(row['data']['images']); _, body = prepared(r, row, 'method-extra-0')
    result = call(r, row, 'generate-api-images', body)
    assert client.calls == 1 and len(result['data']['images']) == 13
    assert [(a['id'] != b['id']) for a, b in zip(result['data']['images'], before)] == [False, False, True]+[False]*10
    assert flow.bundle_ready(state(r, result)) and not result['approved']['set']
    no_publish(r)


@pytest.mark.parametrize('failure', ['provider', 'composition'])
def test_failed_attempt_preserves_old_set_and_reuses_saved_paid_bytes(ready, monkeypatch, failure):
    r, row, _, client, _ = ready
    row = call(r, row, 'render-bundle', {'request_key': str(uuid4())})
    before = state(r, row); _, body = prepared(r, row)
    original_compose = images.compose
    if failure == 'provider':
        client.fail_at = 2
    else:
        def bad(*a, **kw):
            raise ValueError('local synthetic failure')
        monkeypatch.setattr(images, 'compose', bad)
    response = call(r, row, 'generate-api-images', body, 502)
    assert 'private-key' not in str(response) and 'SECRET' not in str(response)
    after = state(r, row)
    for key in ('copy', 'cover', 'images', 'approvals', 'history', 'revision', 'export'):
        assert before[key] == after[key]
    assert after['operation']['status'] == 'failed'
    calls = client.calls
    call(r, row, 'generate-api-images', body, 409)
    assert client.calls == calls
    monkeypatch.setattr(images, 'compose', original_compose); client.fail_at = None
    fresh = latest(r, row); plan, retry = prepared(r, fresh)
    assert plan['reused_count'] == 1 and plan['count'] == 3
    result = call(r, fresh, 'generate-api-images', retry)
    assert client.calls == calls+3 and len(result['data']['images']) == 13
    no_publish(r)


def test_model_key_change_invalidates_prepared_consent_before_charge(ready):
    r, row, _, client, model_id = ready; _, body = prepared(r, row)
    with r[3]() as db:
        model = db.get(ModelConfig, model_id); model.encrypted_api_key = encrypt_text('new-private-key'); db.commit()
    call(r, row, 'generate-api-images', body, 422)
    assert client.calls == 0


def test_source_change_or_concurrent_edit_during_paid_wait_never_overwrites(ready):
    r, row, _, client, _ = ready
    _, body = prepared(r, row)
    def mutate():
        with r[3]() as db:
            record = db.get(CourseVisualWorkflow, row['id']); data = deepcopy(record.data)
            data['copy']['title'] = 'Concurrent owner edit'
            data['operation'] = {'key': 'another-request', 'status': 'generating'}
            record.data = data; db.commit()
    client.callback = mutate
    call(r, row, 'generate-api-images', body, 409)
    after = state(r, row)
    assert client.calls == 1 and after['copy']['title'] == 'Concurrent owner edit'
    assert after['operation'] == {'key': 'another-request', 'status': 'generating'}
    assert after['images'] == []
    no_publish(r)


def test_no_default_image_model_is_explained_without_network(ready):
    r, row, _, client, model_id = ready
    with r[3]() as db:
        db.get(ModelConfig, model_id).is_default = False; db.commit()
    plan, body = prepared(r, row)
    assert not plan['supported'] and plan['model'] is None
    call(r, row, 'generate-api-images', body, 422)
    assert client.calls == 0


def test_all_provider_images_cached_after_last_composition_failure_retry_has_zero_calls(ready, monkeypatch):
    r, row, _, client, _ = ready; _, body = prepared(r, row)
    compose = images.compose
    def last_fails(*args, **kwargs):
        if args[3]['slot'] == 'method-extra-1':
            raise ValueError('Synthetic last composition failure')
        return compose(*args, **kwargs)
    monkeypatch.setattr(images, 'compose', last_fails)
    call(r, row, 'generate-api-images', body, 502)
    assert client.calls == 4
    monkeypatch.setattr(images, 'compose', compose)
    row = latest(r, row); plan, body = prepared(r, row)
    assert plan['count'] == 0 and plan['reused_count'] == 4
    assert all(not page['will_send'] for page in plan['pages'])
    result = call(r, row, 'generate-api-images', body)
    assert client.calls == 4 and len(result['data']['images']) == 13
    no_publish(r)


def test_pdf_change_during_first_api_wait_stops_remaining_calls_and_retains_old_work(ready):
    r, row, source, client, _ = ready; _, body = prepared(r, row)
    before = state(r, row)
    def change_source():
        with source.open('ab') as stream:
            stream.write(b'\n% synthetic changed PDF\n')
    client.callback = change_source
    call(r, row, 'generate-api-images', body, 409)
    after = state(r, row)
    assert client.calls == 1
    for field in ('copy', 'cover', 'images', 'approvals', 'history', 'revision', 'export'):
        assert after[field] == before[field]
    assert after['operation']['status'] == 'failed'
    no_publish(r)
