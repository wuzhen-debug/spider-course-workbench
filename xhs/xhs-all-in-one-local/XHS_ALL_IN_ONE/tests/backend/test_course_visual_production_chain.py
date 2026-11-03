"""Research handoff placeholders, paid planning recovery and late-response fences."""
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import select

from test_course_library import library
from test_course_visual_workflow import BASE, research, call, approve
from test_course_visual_collages import long_record, untouched_tasks, raw
from backend.app.api.ai import get_text_ai_client
from backend.app.core.security import encrypt_text
from backend.app.main import app
from backend.app.models import ModelConfig, User
from backend.app.models.course_visual_workflow import CourseVisualWorkflow
from backend.app.api.course_visual_workflow import DesignResult
from backend.app.services import course_visual_workflow as flow


@pytest.fixture
def planning(research):
    row, source = long_record(research)
    row = call(research, row, 'select-template', {'template_id': 'magazine-a'})
    row = approve(research, row, 'copy')
    with research[3]() as db:
        owner = db.scalar(select(User).where(User.username == 'pdf-owner'))
        model = ModelConfig(user_id=owner.id, name='Synthetic text planner', model_type='text',
            provider='openai', model_name='fixture-planner', base_url='https://fake.invalid/v1',
            encrypted_api_key=encrypt_text('fixture-only-private-key'), is_default=True)
        db.add(model); db.commit(); model_id = model.id

    class Planner:
        calls = 0
        callback = None
        fail = False

        def plan_visuals(self, **kwargs):
            self.calls += 1
            assert 'fixture-only-private-key' not in kwargs['reference']
            if self.callback:
                self.callback()
            if self.fail:
                raise RuntimeError('fixture-only-private-key must never enter errors')
            return {'style_report': {key: 'Specific student question, explicit conditions and real source.'
                for key in ['content_type','goal','emotion','density','primary_style','supporting_style','avoid','reason']},
                'visual_plan': {**row['data']['visual_plan'], 'cover_lines': ['先看条件，再做判断'],
                    'cover_subtitle': '用明确条件连接独立练习', 'method_text': 'Read the conditions. Explain the decision and check the result.'},
                'set_plan': {**row['data']['set_plan'], 'extra_explanations': [
                    {'title':'Independent practice', 'text':'Hide the solution and explain the chosen method before comparing.'},
                    {'title':'Check the reason', 'text':'Return to the original explanation when an assumption does not hold.'}]}}

    client = Planner(); app.dependency_overrides[get_text_ai_client] = lambda: client
    plan = research[0].post(f'{BASE}/{row["id"]}/prompts?purpose=visual', headers=research[1], json={}).json()
    body = {'external_consent': True, 'plan_digest': plan['plan_digest'], 'request_key': str(uuid4())}
    return research, row, source, client, model_id, body


def test_placeholders_count_thirteen_and_save_wip_but_cannot_render(planning):
    r, row, _, client, _, _ = planning
    assert row['production']['planned_count'] == 13 and row['production']['needs_planning']
    pending = deepcopy(row['data']['set_plan']); pending['extra_explanations'][0]['title'] = ''
    saved = r[0].patch(f'{BASE}/{row["id"]}', headers=r[1], json={
        'expected_version':row['row_version'], 'set_plan':pending})
    assert saved.status_code == 200, saved.text
    after = saved.json(); assert after['production']['needs_planning']
    assert after['data']['copy'] == row['data']['copy'] and after['approved']['copy']
    call(r, after, 'render-bundle', {'request_key':str(uuid4())}, 422)
    assert client.calls == 0
    untouched_tasks(r)


def test_json_example_is_schema_valid_and_keeps_course_selection_without_private_inputs(planning):
    _, row, _, _, _, _ = planning
    example = flow.visual_json_example(row['data'], {'pages':[{'page':1},{'page':3}]})
    parsed = DesignResult.model_validate(example)
    assert parsed.visual_plan.template_id == 'magazine-a'
    assert parsed.visual_plan.density == row['data']['visual_plan']['density']
    assert parsed.visual_plan.sample_pages == [3]
    assert len(parsed.set_plan.extra_explanations) == 2
    assert all(isinstance(value, str) for value in example['style_report'].values())
    assert row['data']['copy']['body'] not in str(example)
    assert 'api_key' not in str(example) and '/Users/' not in str(example)


def test_same_planning_key_recovers_after_render_without_second_model_call(planning):
    r, row, _, client, _, body = planning
    planned = call(r, row, 'generate-visual-plan', body)
    assert not planned['production']['needs_planning']
    assert planned['data']['copy'] == row['data']['copy'] and planned['approved']['copy']
    assert planned['data']['visual_plan']['cover_subtitle']
    rendered = call(r, planned, 'render-bundle', {'request_key':str(uuid4())})
    replay = call(r, row, 'generate-visual-plan', body)
    assert replay['row_version'] == rendered['row_version'] and client.calls == 1
    assert len(replay['data']['images']) == 13 and not replay['approved']['set']
    call(r, replay, 'generate-visual-plan', {**body,'external_consent':False}, 409)
    call(r, replay, 'generate-visual-plan', {**body,'plan_digest':'different'}, 409)
    assert client.calls == 1
    untouched_tasks(r)


def test_failed_same_key_never_retries_a_billable_call_or_loses_copy(planning):
    r, row, _, client, _, body = planning; client.fail = True
    failure = call(r, row, 'generate-visual-plan', body, 502)
    assert 'private-key' not in str(failure)
    after = r[0].get(f'{BASE}/{row["id"]}', headers=r[1]).json()
    assert after['data']['copy'] == row['data']['copy'] and after['data']['visual_plan'] == row['data']['visual_plan']
    call(r, after, 'generate-visual-plan', body, 409)
    assert client.calls == 1
    untouched_tasks(r)


def test_late_planning_does_not_overwrite_concurrent_content(planning):
    r, row, _, client, _, body = planning
    def change():
        with r[3]() as db:
            record = db.get(CourseVisualWorkflow, row['id']); data = deepcopy(record.data)
            data['copy']['body'] = 'A newer user edit that must survive.'
            data['operation'] = {'key':'different-request', 'status':'completed'}
            record.data = data; db.commit()
    client.callback = change
    call(r, row, 'generate-visual-plan', body, 409)
    after = raw(r, row)['data']
    assert after['copy']['body'] == 'A newer user edit that must survive.'
    assert after['visual_plan'] == row['data']['visual_plan']
    assert after['operation']['key'] == 'different-request' and client.calls == 1
    untouched_tasks(r)


@pytest.mark.parametrize('when', ['before', 'during'])
def test_credential_change_invalidates_consent_or_late_result(planning, when):
    r, row, _, client, model_id, body = planning
    def rotate():
        with r[3]() as db:
            model = db.get(ModelConfig, model_id); model.encrypted_api_key = encrypt_text('new-fixture-key'); db.commit()
    if when == 'before':
        rotate(); expected = 422
    else:
        client.callback = rotate; expected = 409
    call(r, row, 'generate-visual-plan', body, expected)
    assert client.calls == (0 if when == 'before' else 1)
    assert raw(r, row)['data']['copy'] == row['data']['copy']
    assert raw(r, row)['data']['visual_plan'] == row['data']['visual_plan']
    untouched_tasks(r)


@pytest.mark.parametrize('kind,stage,category', [
    ('http', 'model_request', 'provider-http'),
    ('connection', 'model_request', 'network-connection'),
    ('json', 'response_validation', 'response-json'),
    ('schema', 'response_validation', 'response-schema'),
])
def test_planning_failures_retain_safe_diagnostics_without_content_or_retry(planning, kind, stage, category):
    import requests
    r, row, _, client, _, body = planning
    secret = 'PRIVATE_PROVIDER_BODY_FIXTURE_KEY'
    def fail(**kwargs):
        client.calls += 1
        if kind == 'http':
            response = requests.Response(); response.status_code = 400
            response._content = secret.encode()
            raise requests.HTTPError(secret, response=response)
        if kind == 'connection':
            raise requests.ConnectionError(secret)
        if kind == 'json':
            return '{' + secret
        return {'style_report': {secret: secret}}
    client.plan_visuals = fail
    before = raw(r, row)['data']
    failure = call(r, row, 'generate-visual-plan', body, 502)
    current = raw(r, row)['data']; key = body['request_key']
    diagnostic = current['operation']['diagnostic']
    assert diagnostic['stage'] == stage and diagnostic['category'] == category
    assert current['visual_plan_requests'][key]['diagnostic'] == diagnostic
    if kind == 'http':
        assert diagnostic['http_status'] == 400 and 'HTTP 400' in failure['detail']
    assert secret not in str(failure) and secret not in str(diagnostic)
    assert all(current.get(field) == before.get(field) for field in
        ['copy', 'visual_plan', 'set_plan', 'cover', 'images', 'history', 'approvals', 'source'])
    call(r, row, 'generate-visual-plan', body, 409)
    assert client.calls == 1
    untouched_tasks(r)
