"""PDF topic entry reuses the existing Skill plan without touching old research."""
from copy import deepcopy
from uuid import uuid4
import json

from sqlalchemy import func, select
from test_course_library import library
from test_course_research import research
from test_course_visual_workflow import BASE, call
from test_course_visual_pdf_lane import pdf_run, analysis_fixture, install_pdf_stub
from test_course_visual_collages import raw, untouched_tasks
from backend.app.models.course_visual_workflow import CourseVisualWorkflow


def test_readonly_preview_reuses_the_exact_skill_scope_and_preserves_original(research):
    existing, source = pdf_run(research)
    before = deepcopy(raw(research, existing)); original = source.read_bytes()
    stub = install_pdf_stub(research, {})
    payload = {'file_id': existing['file_id'], 'revision_id': existing['data']['source']['revision_id'], 'topic': '', 'goal': 'student-question', 'brand_id':'xingtu'}
    response = research[0].post(BASE+'/pdf-topic-plan', headers=research[1], json=payload)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview['preview_only'] and preview['entry_mode'] == 'pdf-driven' and preview['material']['pages']
    assert '星途留学' in preview['prompt'] and 'source_map' in preview['prompt']
    assert 'fixture-private-key' not in json.dumps(preview)
    assert raw(research, existing) == before and stub.calls == 0 and source.read_bytes() == original
    with research[3]() as db: assert db.scalar(select(func.count()).select_from(CourseVisualWorkflow)) == 1
    created = research[0].post(BASE, headers=research[1], json={**{key:payload[key] for key in ['file_id','revision_id','brand_id']}, 'entry_mode':'pdf-driven', 'template_id':'magazine-a', 'request_key':str(uuid4())})
    assert created.status_code == 200, created.text
    row = created.json(); plan = call(research, row, 'pdf-analysis-plan')
    for key in ['source','model','material','coverage','scope','prompt']: assert preview[key] == plan[key], key
    stub = install_pdf_stub(research, analysis_fixture(plan, row['data']))
    row = call(research, row, 'generate-from-pdf', {'external_consent':True, 'plan_digest':plan['plan_digest'], 'request_key':str(uuid4())})
    assert stub.calls == 1 and row['data']['pdf_analysis']
    assert all(source_id.startswith('pdf-') for source_id in row['data']['selected_source_ids'])
    assert row['data']['evidence_review']['comments_read'] == 0
    assert not any(row['approved'].values()) and row['data']['images'] == [] and row['data']['export'] is None
    assert raw(research, existing) == before and source.read_bytes() == original
    history = research[0].get(BASE, headers=research[1], params={'file_id':existing['file_id']}).json()['items']
    assert all(item['entry_mode']=='pdf-driven' and item['revision_id']==payload['revision_id'] for item in history)
    untouched_tasks(research)


def test_preview_preserves_ownership_and_target_topic(research):
    row, _ = pdf_run(research)
    payload={'file_id':row['file_id'], 'revision_id':row['data']['source']['revision_id'], 'topic':'独立练习前先查条件', 'goal':'method-save', 'brand_id':'xingtu'}
    assert research[0].post(BASE+'/pdf-topic-plan', json=payload).status_code == 401
    assert research[0].post(BASE+'/pdf-topic-plan', headers=research[2], json=payload).status_code == 404
    response=research[0].post(BASE+'/pdf-topic-plan', headers=research[1], json=payload)
    assert response.status_code == 200, response.text
    preview=response.json();assert payload['topic'] in preview['prompt']
    created=research[0].post(BASE, headers=research[1], json={'file_id':payload['file_id'],'revision_id':payload['revision_id'],'entry_mode':'pdf-driven','template_id':'magazine-a','request_key':str(uuid4()),'brand_id':'xingtu'})
    current=created.json()
    updated=research[0].patch(f'{BASE}/{current["id"]}',headers=research[1],json={'expected_version':current['row_version'],'copy':{**current['data']['copy'],'topic':payload['topic'],'goal':payload['goal']}})
    assert updated.status_code == 200, updated.text
    actual=call(research,updated.json(),'pdf-analysis-plan')
    for key in ['source','model','material','coverage','scope','prompt']:assert preview[key]==actual[key],key
    untouched_tasks(research)
