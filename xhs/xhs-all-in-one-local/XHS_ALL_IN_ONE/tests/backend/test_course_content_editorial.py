"""Actual writing strategies and structured API results; no live AI/DB writes."""
from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from test_course_visual_workflow import BASE, call, copy_ready, research
from test_course_library import library
from backend.app.api.ai import get_text_ai_client
from backend.app.main import app
from backend.app.core.security import encrypt_text
from backend.app.models import AiDraft, AutoTask, ModelConfig, PublishJob, User
from backend.app.models.course_visual_workflow import CourseVisualWorkflow
from backend.app.services import course_content_editorial as editorial
from backend.app.services import course_visual_workflow as flow
from backend.app.services.ai_service import OpenAICompatibleTextClient
from backend.app.services.course_research_service import writing_prompt as research_writing_prompt


def prompt_data():
    data = flow.initial_data({'university': 'Synthetic University', 'course_code': 'TEST1001',
        'term': 'fixture', 'filename': 'synthetic.pdf', 'material_type': '期末复习讲义', 'page_count': 8}, flow.catalog())
    data['copy'].update(topic='条件判断', takeaway='先标已知量和所求量', goal='method-save')
    data['evidence'] = [{'id': 'source-1', 'title': 'Synthetic question', 'content': '',
        'content_status': 'search_excerpt', 'source_url': 'https://example.com/source',
        'comments': [], 'metrics': {'likes': None, 'collects': None, 'comments': None}}]
    data['selected_source_ids'] = ['source-1']
    material = {'filename': 'synthetic.pdf', 'page_count': 8, 'pages': [{'page': 1, 'text': 'Synthetic cover'}]}
    return data, material


def test_actual_writing_references_are_compiled_and_visual_roles_are_separate():
    data, material = prompt_data()
    prompt = flow.writing_prompt(data, material)
    assert '从学生问题决定内容，而不是从模板填空' in prompt
    assert '学生需求与选题' in prompt and '笔记、课程事实与资料卖点' in prompt
    assert 'method-save' in prompt and 'student_questions_verified' in prompt
    assert '没有读到正文的来源不能证明原文结构或结论' in prompt
    assert 'takeaway必须' in prompt and 'source_map' in prompt and 'editor_notes' in prompt
    assert 'XHS Visual Director 只负责后续视觉编排' in prompt
    data['visual_plan'].update(template_id='decision-map', density='compact')
    visual = flow.visual_prompt(data, material)
    assert '本阶段不重新选题、不重写发布正文' in visual
    assert '小红书高级图文视觉导演' in visual
    assert '"selected_visual_standard": {"template_id": "decision-map", "density": "compact"}' in visual
    assert '【skills/aussie-course-xhs/references/' not in visual
    assert data['copy']['goal'] == 'method-save', 'Prompt preparation is read-only'


def test_research_entry_uses_the_same_verified_copy_strategy():
    data, material = prompt_data()
    prompt = research_writing_prompt(data['source'], {'topic': '条件判断', 'purpose': 'product', 'brand': '星途留学'},
        data['evidence'], [{'source': {'filename': 'synthetic.pdf', 'sha256': 'fixture'}, 'pages': material['pages']}])
    assert 'sample-trial' in prompt and '真实样张试读' in prompt
    assert '从学生问题决定内容，而不是从模板填空' in prompt
    assert 'student_questions_verified' in prompt and '没有评论时不能声称学生都在问' in prompt


def test_missing_or_tampered_writing_snapshot_is_rejected_without_fallback(tmp_path, monkeypatch):
    data, _ = prompt_data()
    with pytest.raises(HTTPException) as missing:
        editorial.writing_skill_bundle({'skills': []})
    assert missing.value.status_code == 409
    for entry in data['rules']['skills']:
        if entry['file'].endswith(tuple(editorial.COPY_REFERENCES)):
            path = tmp_path / entry['file']; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((editorial.RESOURCES / entry['file']).read_bytes())
    (tmp_path / 'skills/aussie-course-xhs/references/writing.md').write_text('Changed fixture')
    monkeypatch.setattr(editorial, 'RESOURCES', tmp_path)
    with pytest.raises(HTTPException) as changed:
        editorial.writing_skill_bundle(data['rules'])
    assert changed.value.status_code == 409


def test_no_selected_evidence_still_blocks_generation_and_quality_is_not_a_score():
    data, material = prompt_data(); data['selected_source_ids'] = []
    with pytest.raises(HTTPException) as absent:
        flow.writing_prompt(data, material)
    assert absent.value.status_code == 422
    result = editorial.quality_hints({'title': 'Fixture', 'body': '', 'tags': [], 'takeaway': ''},
        '星途留学', data['evidence'], {'sample_pages': [1]})
    assert result['not_engagement_prediction']
    assert {'missing_takeaway', 'missing_tags', 'limited_research', 'cover_only_sample'} <= {x['code'] for x in result['items']}
    assert 'score' not in result


def test_dedicated_client_parses_complete_json_and_generic_generator_is_unchanged(monkeypatch):
    seen = []
    def complete(**kwargs):
        seen.append(kwargs)
        if '待审核文案' in kwargs['system_prompt']:
            return '```json\n' + json.dumps({'goal': 'student-question', 'topic': 'fixture', 'title': '标题', 'body': '正文', 'tags': ['TEST1001'], 'takeaway': '动作'}) + '\n```'
        return '标题：原通用入口\n正文：原正文格式'
    client = OpenAICompatibleTextClient(); monkeypatch.setattr(client, '_complete', complete)
    actual = client.generate_course_copy(model_config=None, api_key='fixture', reference='bounded fixture')
    assert actual['tags'] == ['TEST1001'] and actual['takeaway'] == '动作'
    assert '不得调用工具' in seen[0]['system_prompt']
    generic = client.generate_note(model_config=None, api_key='fixture', topic='通用', reference='', instruction='')
    assert generic == {'title': '原通用入口', 'body': '原正文格式'}
    monkeypatch.setattr(client, '_complete', lambda **_: '标题：只有旧式两字段')
    with pytest.raises(ValueError):
        client.generate_course_copy(model_config=None, api_key='fixture', reference='fixture')


def setup_copy(r, result):
    c, headers, _, factory, *_ = r
    with factory() as db:
        owner = db.scalar(select(User).where(User.username == 'pdf-owner'))
        db.add(ModelConfig(user_id=owner.id, name='Editorial fixture', model_type='text', provider='openai',
            model_name='synthetic-model', base_url='https://never-called.invalid/v1',
            encrypted_api_key=encrypt_text('editorial-fixture-secret'), is_default=True)); db.commit()
    row = copy_ready(r)
    # A previous local asset can be retained even if the new AI response fails.
    with factory() as db:
        record = db.get(CourseVisualWorkflow, row['id']); data = deepcopy(record.data)
        data['cover'] = {'id': 'existing-cover', 'path': 'fixture/cover.png', 'kind': 'cover', 'slot': 'cover', 'role': 'Retained fixture', 'sha256': 'fixture', 'brief': {}}
        data['images'] = [deepcopy(data['cover'])]
        record.data = data; db.commit()
    row = c.get(f'{BASE}/{row["id"]}', headers=headers).json()
    class AI:
        calls = 0
        def generate_course_copy(self, **kwargs):
            self.calls += 1
            assert 'editorial-fixture-secret' not in kwargs['reference']
            return result(row)
        def generate_note(self, **kwargs):
            raise AssertionError('Do not silently fallback to the generic two-field generator')
    fake = AI(); app.dependency_overrides[get_text_ai_client] = lambda: fake
    prepared = c.post(f'{BASE}/{row["id"]}/prompts', headers=headers, json={})
    assert prepared.status_code == 200, prepared.text
    return row, prepared.json(), fake


def complete_result(row):
    return {'topic': '线性关系的判断条件', 'title': '先核查线性关系', 'body': '写出对象与条件，独立作答后解释自己的判断理由。',
            'tags': ['MAST10007', '线性无关'], 'takeaway': '写出判断条件并独立核查理由',
            'source_map': [{'claim': '本篇问题来源', 'source_ids': row['data']['selected_source_ids'], 'pdf_pages': [1]}],
            'editor_notes': ['内部核验事项保留在编辑区。']}


def test_structured_copy_updates_all_fields_and_keeps_internal_notes_out_of_body(research):
    row, prepared, fake = setup_copy(research, complete_result)
    expected = complete_result(row); c, headers, _, factory, *_ = research
    result = call(research, row, 'generate-copy', {'external_consent': True, 'plan_digest': prepared['plan_digest'], 'request_key': str(uuid4())})
    for key in ['topic', 'title', 'body', 'tags', 'takeaway']:
        assert result['data']['copy'][key] == expected[key]
    assert result['data']['copy']['goal'] == 'student-question'
    assert result['data']['copy_editorial']['editor_notes'] == expected['editor_notes']
    assert '内部核验' not in result['data']['copy']['body']
    assert result['data']['history'][-1]['cover']['id'] == 'existing-cover'
    assert result['data']['cover'] is None and result['data']['images'] == []
    assert not any(result['approved'].values()) and fake.calls == 1
    with factory() as db:
        for model in [AiDraft, PublishJob, AutoTask]:
            assert db.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize('invalid', ['takeaway', 'tags', 'long_title', 'unprovided_source', 'unprovided_page', 'changed_goal', 'notes_in_body', 'generic_only'])
def test_incomplete_or_ungrounded_structured_copy_preserves_old_copy_and_images(research, invalid):
    def result(row):
        value = complete_result(row)
        if invalid in ['takeaway', 'tags']: value.pop(invalid)
        elif invalid == 'long_title': value['title'] = '标题' * 11
        elif invalid == 'unprovided_source': value['source_map'][0]['source_ids'] = ['unknown-source']
        elif invalid == 'unprovided_page': value['source_map'][0]['pdf_pages'] = [999]
        elif invalid == 'changed_goal': value['goal'] = 'sample-trial'
        elif invalid == 'notes_in_body': value['body'] += '\n配图建议：此段不能成为发布文案。'
        elif invalid == 'generic_only': value = {'title': '旧式结果', 'body': '只有两个字段'}
        return value
    row, prepared, fake = setup_copy(research, result)
    error = call(research, row, 'generate-copy', {'external_consent': True, 'plan_digest': prepared['plan_digest'], 'request_key': str(uuid4())}, 502)
    assert 'editorial-fixture-secret' not in str(error)
    c, headers, *_ = research
    actual = c.get(f'{BASE}/{row["id"]}', headers=headers).json()
    for key in ['copy', 'cover', 'images']:
        assert actual['data'][key] == row['data'][key]
    assert fake.calls == 1 and actual['data']['operation']['status'] == 'failed'
