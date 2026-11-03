"""PDF-driven drafting: disposable DB/PDF and stub-only AI; no live requests."""
from copy import deepcopy
from uuid import uuid4
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select, func

from test_course_library import library, scan
from test_course_research import research
from test_course_visual_workflow import BASE, call, approve
from test_course_visual_collages import raw, untouched_tasks
from backend.app.main import app
from backend.app.api.ai import get_text_ai_client
from backend.app.core.security import encrypt_text
from backend.app.models import User, ModelConfig, PublishJob, AutoTask, AiDraft, DraftAsset
from backend.app.models.course_library import CourseLibraryFile
from backend.app.models.course_visual_workflow import CourseVisualWorkflow
from backend.app.services import course_pdf_analysis as analysis


def pdf_fixture_bytes(count=12):
    font = 3 + count * 2
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
        f'<< /Type /Pages /Kids [{" ".join(f"{3+i*2} 0 R" for i in range(count))}] /Count {count} >>'.encode()]
    for i in range(count):
        # >40 actual extracted characters, so this tests real intake (not OCR).
        text = f'SYNTHETIC PDF PAGE {i+1}: Read the method and check its conditions before independent practice.'
        stream = f'BT /F1 12 Tf 60 700 Td ({text}) Tj ET'.encode()
        objects.extend([f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font} 0 R >> >> /Contents {4+i*2} 0 R >>'.encode(),
            b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream'])
    objects.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    data = b'%PDF-1.4\n'; offsets = []
    for n, item in enumerate(objects, 1):
        offsets.append(len(data)); data += f'{n} 0 obj\n'.encode()+item+b'\nendobj\n'
    start = len(data)
    data += f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode()
    data += b''.join(f'{offset:010} 00000 n \n'.encode() for offset in offsets)
    return data+f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()


def pdf_run(r, model=True):
    source = r[4].root / '02墨大/MAST10007/期末复习讲义/MAST10007_26S2_Final.pdf'
    source.write_bytes(pdf_fixture_bytes()); scan(r[4])
    with r[3]() as db:
        file = db.scalar(select(CourseLibraryFile).where(CourseLibraryFile.filename.like('%Final%')))
        file_id, revision = file.id, file.current_revision_id
        if model:
            db.add(ModelConfig(user_id=file.user_id, name='PDF fixture model', model_type='text',
                provider='openai', model_name='fixture-text', base_url='https://text.test/v1',
                encrypted_api_key=encrypt_text('fixture-private-key'), is_default=True)); db.commit()
    response = r[0].post(BASE, headers=r[1], json={'file_id': file_id, 'revision_id': revision,
        'request_key': str(uuid4()), 'entry_mode': 'pdf-driven', 'brand_id':'xingtu'})
    assert response.status_code == 200, response.text
    return response.json(), source


def analysis_fixture(plan, data):
    """Reusable success response, genuinely anchored to the provided excerpt."""
    body = next(p for p in plan['material']['pages'] if p['page'] > 1)
    quote = body['text'].strip()[:70]
    code = data['source']['course_code']
    topic = data['copy'].get('topic') or '先检查条件，再独立练习'
    reference = {'pdf_pages': [body['page']], 'quote': quote}
    return {
        'pain_points': [{'pain': '读过方法后，独立练习时可能忘记核对适用条件。', 'basis': 'teaching-inference', **reference}],
        'product_facts': [{'fact': '摘录明确提示先阅读方法、检查条件再独立练习。', **reference}],
        'topic_candidates': [{'id': 'method', 'topic': topic, 'reader_takeaway': '形成独立练习前的条件核查习惯',
            'rationale': '从本次实际摘录得到的教学分析', 'pdf_pages': [body['page']]},
            {'id': 'review', 'topic': '练习后怎样检查理由', 'reader_takeaway': '回看条件与结论之间的联系',
            'rationale': '为独立学习提供另一种复习角度', 'pdf_pages': [body['page']]}],
        'recommended_topic_id': 'method',
        'copy': {'goal': data['copy'].get('goal') or 'student-question', 'topic': topic,
            'title': f'{code}先检查条件', 'body': '读过方法，不等于能独立练习。先核对题目对象与方法条件，再独立作答。这份资料的摘录提示阅读方法、检查条件与独立练习；可以先看真实样张，判断讲解方式是否适合自己。',
            'tags': [code], 'takeaway': '把条件核查和独立练习连接起来'},
        'visual_plan': {'template_id': 'magazine-a', 'density': data['visual_plan'].get('density', 'standard'),
            'cover_lines': ['方法看过了', '先检查条件'], 'method_title': '独立练习前先核对',
            'method_text': '先读清题目对象，再核对方法条件。独立作答时写出判断依据，练习后回看条件与结论是否一致。',
            'sample_pages': [body['page']], 'sample_instructions': [], 'usage_steps': ['独立练习', '核对条件'],
            'cta': '先看真实样张，判断是否适合自己', 'style': 'product-editorial', 'method_layout': 'editorial', 'method_nodes': []},
        'set_plan': {'sample_pages': [body['page']], 'sample_instructions': [], 'extra_explanations': [
            {'title': '把条件写清楚', 'subtitle': '', 'text': '练习时先写明方法适用的条件，再说明为什么这样处理。', 'nodes': [], 'layout': 'editorial'},
            {'title': '怎样使用这份资料', 'subtitle': '', 'text': '先看方法说明，再检查条件，最后独立练习。看真实样张后再判断是否适合自己的学习阶段。', 'nodes': [], 'layout': 'editorial'}]},
        'pdf_preview_pages': [p for p in plan['coverage']['read_pages'] if p >= 2][:9],
        'source_map': [{'claim': '资料摘录提示方法、条件与独立练习。', **reference}],
        'editor_notes': ['合成测试资料，不代表真实课程事实或发布审核。']}


def install_pdf_stub(r, result):
    class Stub:
        calls = 0
        def analyze_course_pdf(self, **kwargs):
            self.calls += 1
            return result(kwargs) if callable(result) else deepcopy(result)
    stub = Stub()
    app.dependency_overrides[get_text_ai_client] = lambda: stub
    return stub


def generated(r):
    row, source = pdf_run(r)
    plan = call(r, row, 'pdf-analysis-plan')
    stub = install_pdf_stub(r, analysis_fixture(plan, row['data']))
    payload = {'external_consent': True, 'plan_digest': plan['plan_digest'], 'request_key': str(uuid4())}
    return row, call(r, row, 'generate-from-pdf', payload), source, stub, payload


def test_pdf_plan_reads_all_pages_is_explicit_and_does_not_write(research):
    row, source = pdf_run(research); before = raw(research, row); content = source.read_bytes()
    plan = call(research, row, 'pdf-analysis-plan')
    assert plan['coverage']['read_pages'] == list(range(1, 13)) and not plan['coverage']['local_truncated']
    assert plan['coverage']['sent_chars'] <= 24000 and plan['model']['destination'] == 'https://text.test/v1'
    assert plan['entry_mode'] == 'pdf-driven' and plan['material']['pages']
    assert 'fixture-private-key' not in json.dumps(plan) and not any(k.startswith('_') for k in plan)
    assert raw(research, row) == before and source.read_bytes() == content
    assert row['data']['label'] == 'MAST10007 · PDF资料选题'
    untouched_tasks(research)


def test_success_is_once_only_pending_review_with_matching_visuals_and_real_references(research):
    original, row, source, stub, payload = generated(research)
    assert stub.calls == 1 and row['data']['visual_candidate']['status'] == 'ready'
    assert not any(row['approved'].values()) and row['data']['images'] == [] and row['data']['export'] is None
    assert row['data']['pdf_page_plan']['pages'] == list(range(2, 11)) and len(row['direction']['pages']) == 13
    assert row['data']['evidence_review']['basis'] == 'pdf-analysis'
    assert row['data']['evidence_review']['comments_read'] == 0
    fact = row['data']['pdf_analysis']['product_facts'][0]
    assert fact['matched_page'] in fact['pdf_pages']
    retry = call(research, original, 'generate-from-pdf', payload)
    assert retry['row_version'] == row['row_version'] and stub.calls == 1
    assert original['data']['copy'] == raw(research, row)['data']['history'][-1]['copy']
    trace = json.dumps(row['data']['production_trace'])
    assert fact['quote'] not in trace and 'fixture-private-key' not in trace
    untouched_tasks(research)


def test_copy_edit_stales_candidate_with_free_explicit_manual_recovery(research):
    _, row, _, stub, _ = generated(research)
    edited_copy = {**row['data']['copy'], 'body': row['data']['copy']['body'] + '再检查一次。'}
    changed = research[0].patch(f'{BASE}/{row["id"]}', headers=research[1], json={
        'expected_version': row['row_version'], 'copy': edited_copy})
    assert changed.status_code == 200, changed.text
    row = changed.json(); assert row['data']['visual_candidate']['status'] == 'stale'
    row = approve(research, row, 'copy')
    call(research, row, 'render-bundle', {'request_key': str(uuid4())}, 409)
    saved = research[0].patch(f'{BASE}/{row["id"]}', headers=research[1], json={'expected_version': row['row_version'],
        'visual_candidate_reviewed': True, 'visual_plan': row['data']['visual_plan'], 'set_plan': row['data']['set_plan']})
    assert saved.status_code == 200, saved.text
    row = saved.json(); assert row['approved']['copy'] and row['data']['visual_candidate']['status'] == 'ready'
    assert not row['approved']['cover'] and not row['approved']['set'] and stub.calls == 1
    untouched_tasks(research)


def test_pdf_route_mode_switch_is_explicit_and_research_line_remains(research):
    row, _ = pdf_run(research)
    row = call(research, row, 'select-entry-mode', {'entry_mode': 'xhs-research'})
    call(research, row, 'pdf-analysis-plan', {}, 422)
    assert raw(research, row)['data']['history'][-1]['copy']['title'] == ''
    row = call(research, row, 'search', {'keyword': 'MAST10007', 'account_id': research[6]})
    assert row['data']['evidence'] and row['data']['evidence'][0].get('evidence_type') != 'pdf-analysis'
    row = call(research, row, 'select-entry-mode', {'entry_mode': 'pdf-driven'})
    assert not row['data']['selected_source_ids'] and row['data']['evidence']
    untouched_tasks(research)


def test_pending_copy_prevents_render_and_preserves_original_bytes(research):
    _, row, source, stub, _ = generated(research)
    original = source.read_bytes()
    call(research, row, 'render-bundle', {'request_key': str(uuid4())}, 409)
    assert source.read_bytes() == original and stub.calls == 1
    untouched_tasks(research)


def test_pdf_adapter_has_bounded_response_budget_without_changing_old_call_payload(monkeypatch):
    from backend.app.services.ai_service import OpenAICompatibleTextClient
    import requests
    sent = []
    def fake_post(url, **kwargs):
        sent.append(kwargs['json'])
        response = requests.Response(); response.status_code = 200
        response._content = json.dumps({'choices': [{'message': {'content': '{}'}}]}).encode()
        return response
    monkeypatch.setattr(requests, 'post', fake_post)
    model = SimpleNamespace(base_url='https://stub.invalid/v1', model_name='test-model')
    client = OpenAICompatibleTextClient()
    assert client.analyze_course_pdf(model_config=model, api_key='not-real', reference='synthetic') == {}
    assert sent[-1]['max_tokens'] == 8192
    assert client.generate_course_copy(model_config=model, api_key='not-real', reference='synthetic') == {}
    assert 'max_tokens' not in sent[-1]
