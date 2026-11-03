"""Execute normal workflow endpoints against isolated fixtures; no live AI/data."""
import json
from uuid import uuid4

from sqlalchemy import select

from test_course_visual_workflow import BASE, approve, call, copy_ready, research
from test_course_library import library
from test_course_visual_set_plan import set_workflow
from backend.app.api.ai import get_text_ai_client
from backend.app.core.security import encrypt_text
from backend.app.main import app
from backend.app.models import ModelConfig, User
from backend.app.services import course_visual_workflow as flow


def test_visual_planning_can_read_content_before_user_has_selected_samples(set_workflow):
    isolated, row, *_ = set_workflow
    client, headers, *_ = isolated
    plan = {**row['data']['visual_plan'], 'sample_pages': [1]}
    changed = client.patch(f'{BASE}/{row["id"]}', headers=headers,
        json={'expected_version': row['row_version'], 'visual_plan': plan})
    assert changed.status_code == 200
    row = changed.json()
    prepared = client.post(f'{BASE}/{row["id"]}/prompts?purpose=visual', headers=headers, json={})
    assert prepared.status_code == 200, prepared.text
    value = prepared.json()
    assert value['allowed_pages'] == [1, 2, 3]
    assert '1、2、3' in value['scope']
    assert '不发送完整PDF' in value['scope']
    assert '本工作台用户已明确要求的当前流程' in value['prompt']
    after = client.get(f'{BASE}/{row["id"]}', headers=headers).json()
    assert after == row, 'Preparing and disclosing pages must not edit or approve the plan'


def test_search_read_edit_and_review_record_internal_provenance(research):
    row = copy_ready(research)
    trace = row['data']['production_trace']
    assert {entry['step'] for entry in trace} >= {'research_search', 'research_read', 'content_edit'}
    assert all(entry['source']['sha256'] == row['data']['source']['sha256'] for entry in trace)
    assert all(entry['skills'] for entry in trace)
    assert 'DO_NOT_SEND_TO_AI' not in json.dumps(trace)
    before = row['digests']['copy']
    row = approve(research, row, 'copy')
    assert row['digests']['copy'] == before and row['approved']['copy']
    assert row['data']['production_trace'][-1]['step'] == 'copy_review'
    assert 'production_trace' not in row['direction']


def test_copy_model_identity_and_failure_stay_internal_without_secrets(research):
    client, headers, _, factory, *_ = research
    with factory() as db:
        owner = db.scalar(select(User).where(User.username == 'pdf-owner'))
        db.add(ModelConfig(user_id=owner.id, name='Isolated model', model_type='text',
            provider='openai', model_name='fixture-text', base_url='https://fake.invalid/v1',
            encrypted_api_key=encrypt_text('fixture-private-key'), is_default=True))
        db.commit()

    class Model:
        fail = False
        def generate_course_copy(self, **kwargs):
            if self.fail:
                raise ValueError('fixture-private-key must never enter the trace')
            return {'topic': '独立判断与理由核查', 'title': 'MAST10007练习与核查',
                'body': '独立练习后，对照解析补齐条件和理由。', 'tags': ['MAST10007'],
                'takeaway': '独立作答并补齐判断条件。'}

    model = Model()
    app.dependency_overrides[get_text_ai_client] = lambda: model
    row = copy_ready(research)
    plan = client.post(f'{BASE}/{row["id"]}/prompts', headers=headers, json={}).json()
    row = call(research, row, 'generate-copy', {'external_consent': True,
        'plan_digest': plan['plan_digest'], 'request_key': str(uuid4())})
    entry = row['data']['production_trace'][-1]
    assert entry['step'] == 'copy_generation' and entry['status'] == 'completed'
    assert entry['model'] == {'name': 'Isolated model', 'model_name': 'fixture-text',
        'destination': 'https://fake.invalid'}
    assert entry['inputs_digest'] and entry['outputs_digest']
    assert 'fixture-private-key' not in json.dumps(row['data']['production_trace'])
    assert not any(row['approved'].values())
    original = row['data']['copy']
    model.fail = True
    plan = client.post(f'{BASE}/{row["id"]}/prompts', headers=headers, json={}).json()
    call(research, row, 'generate-copy', {'external_consent': True,
        'plan_digest': plan['plan_digest'], 'request_key': str(uuid4())}, 502)
    after = client.get(f'{BASE}/{row["id"]}', headers=headers).json()
    failed = after['data']['production_trace'][-1]
    assert failed['step'] == 'copy_generation' and failed['status'] == 'failed'
    assert after['data']['copy'] == original
    assert 'fixture-private-key' not in json.dumps(after['data']['production_trace'])
    assert flow.fingerprint(after['data'], 'copy') == row['digests']['copy']
