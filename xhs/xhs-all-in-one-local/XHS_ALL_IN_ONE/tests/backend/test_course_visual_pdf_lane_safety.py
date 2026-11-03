"""Independent PDF-lane contracts; temporary files/stub AI only, never live data."""
import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from test_course_library import library, pdf_bytes, scan
from test_course_research import research
from test_course_visual_collages import raw, untouched_tasks
from test_course_visual_workflow import BASE, call
from test_course_visual_pdf_lane import analysis_fixture, install_pdf_stub
from test_course_visual_set_plan import multipage_pdf
from backend.app.core.security import encrypt_text
from backend.app.models import ModelConfig
from backend.app.models.course_library import CourseLibraryFile
from backend.app.models.course_visual_workflow import CourseVisualWorkflow
from backend.app.services import course_pdf_intake as intake
from backend.app.services import course_pdf_analysis as analysis
from backend.app.services import course_visual_workflow as flow


def read_only_intake(path):
    before = (path.stat().st_size, path.stat().st_mtime_ns,
              hashlib.sha256(path.read_bytes()).hexdigest())
    fd = os.open(path, os.O_RDONLY)
    try:
        result = intake.extract(fd)
    finally:
        os.close(fd)
    assert before == (path.stat().st_size, path.stat().st_mtime_ns,
                      hashlib.sha256(path.read_bytes()).hexdigest())
    return result


def test_intake_reports_partial_coverage_without_rewriting_the_document(tmp_path, monkeypatch):
    path = tmp_path / 'fixture.pdf'
    path.write_bytes(multipage_pdf(18))
    monkeypatch.setattr(intake, 'MAX_PAGES', 8)
    result = read_only_intake(path)
    assert result['page_count'] == 18
    assert result['local_truncated'] is True
    pages = [entry['page'] for entry in result['pages']]
    assert len(pages) <= 8 and pages == sorted(set(pages))
    assert pages[0] == 1 and pages[-1] == 18
    assert result['limits']['pages'] == 8


def test_intake_enforces_text_limits_and_marks_a_cut_excerpt(tmp_path, monkeypatch):
    path = tmp_path / 'fixture.pdf'
    path.write_bytes(multipage_pdf(4))
    monkeypatch.setattr(intake, 'MAX_PAGE_CHARS', 10)
    monkeypatch.setattr(intake, 'MAX_CHARS', 17)
    result = read_only_intake(path)
    assert result['local_truncated'] is True
    assert sum(len(page['text']) for page in result['pages']) <= 17
    assert all(len(page['text']) <= 10 for page in result['pages'])
    assert any(page['truncated'] for page in result['pages'])


def test_image_only_or_empty_page_is_not_invented_text(tmp_path):
    path = tmp_path / 'blank.pdf'
    path.write_bytes(pdf_bytes(''))
    result = read_only_intake(path)
    assert result['page_count'] == 1
    assert not any(page['text'].strip() for page in result['pages'])
    assert result['local_truncated'] is False


def parser_fixture():
    """No real course text or model call: isolate validation of untrusted JSON."""
    data = flow.initial_data({'filename': 'synthetic.pdf', 'university': 'Synthetic University',
        'course_code': 'TEST1001', 'material_type': '期末复习讲义', 'term': '', 'page_count': 14,
        'revision_id': 2, 'sha256': 'a' * 64}, flow.catalog(), 'magazine-a', 'pdf-driven')
    text = 'LITERAL QUOTE: check the applicable conditions before independent practice.'
    plan = {'material': {'page_count': 14, 'pages': [{'page': n, 'text': text, 'truncated': False}
                                                    for n in (1, 3, 5)]},
            'coverage': {'read_pages': list(range(1, 15)), 'excerpt_pages': [1, 3, 5]}}
    visual = {**deepcopy(data['visual_plan']), 'cover_lines': ['条件怎么选', '先核对再计算'],
              'sample_pages': [3], 'cover_sample_page': 3,
              'method_text': 'Read the conditions, identify the method, then explain why it applies.'}
    extra = {**deepcopy(data['set_plan']), 'sample_pages': [5], 'extra_explanations': [
        {'title': title, 'subtitle': '', 'text': 'A synthetic explanation for local safety validation.',
         'nodes': [], 'layout': 'editorial'} for title in ('Independent practice', 'Compare the reasons')]}
    quote = 'check the applicable conditions'
    result = {
        'pain_points': [{'pain': 'May apply a method without checking conditions.',
                         'basis': 'teaching-inference', 'pdf_pages': [1, 3], 'quote': quote}],
        'product_facts': [{'fact': 'Discusses conditions for applying methods.', 'pdf_pages': [3], 'quote': quote}],
        'topic_candidates': [{'id': f't{i}', 'topic': topic, 'reader_takeaway': 'Check before applying.',
                              'rationale': 'Based on the supplied teaching excerpt.', 'pdf_pages': [3]}
                             for i, topic in enumerate(('选公式前检查条件', '怎样独立检查练习'), 1)],
        'recommended_topic_id': 't1',
        'copy': {'goal': 'student-question', 'topic': '选公式前检查条件', 'title': '选公式前先看条件',
                 'body': '先识别条件，再选择方法，最后用独立练习核对理由。', 'tags': ['学习方法'],
                 'takeaway': '能够先判断条件再选方法。'},
        'visual_plan': visual, 'set_plan': extra, 'pdf_preview_pages': list(range(2, 11)),
        'source_map': [{'claim': 'Discusses applicable conditions.', 'pdf_pages': [5], 'quote': quote}],
        'editor_notes': ['Synthetic local parser test.'],
    }
    return data, plan, result


def test_validated_quotes_record_the_actual_matching_page_without_mutating_input():
    data, plan, value = parser_fixture()
    # The claimed list includes an earlier page that does not contain the quote.
    plan['material']['pages'][0]['text'] = 'A different synthetic introduction without matching words.'
    original = deepcopy(data)
    result = analysis.parse_result(value, plan, data)
    assert result['pdf_analysis']['pain_points'][0]['matched_page'] == 3
    assert result['source_map'][0]['matched_page'] == 5
    assert result['pdf_analysis']['status'] == 'pending_review'
    assert '没有平台需求验证' in result['pdf_analysis']['basis']
    assert 'approvals' not in result and 'export' not in result
    assert data == original


@pytest.mark.parametrize('mutation', [
    lambda x: x['pain_points'][0].update(quote='THIS SENTENCE DOES NOT OCCUR IN THE SOURCE'),
    lambda x: x['product_facts'][0].update(pdf_pages=[2]),  # read locally but never sent
    lambda x: x['source_map'][0].update(pdf_pages=[5, 5]),
    lambda x: x['pain_points'][0].update(pdf_pages=[True]),
    lambda x: x['source_map'][0].update(quote='        '),
    lambda x: x['copy'].update(topic='A mismatched topic'),
    lambda x: x['copy'].update(goal='method-save'),
    lambda x: x.update(auto_approve=True),
    lambda x: x.update(pdf_preview_pages=list(reversed(range(2, 11)))),
    lambda x: x.update(pdf_preview_pages=[2] * 9),
    lambda x: x.update(pdf_preview_pages=list(range(1, 10))),
    lambda x: x['visual_plan'].update(cover_sample_page=99999),
    lambda x: x['visual_plan'].update(template_id='legacy'),
])
def test_untrusted_analysis_rejects_fabricated_or_misaligned_output(mutation):
    data, plan, value = parser_fixture()
    original = deepcopy(data)
    mutation(value)
    with pytest.raises((ValueError, TypeError)):
        analysis.parse_result(value, plan, data)
    assert data == original


def test_selected_topic_cannot_silently_reuse_previous_recommended_copy():
    data, plan, value = parser_fixture()
    data['copy']['topic'] = '怎样独立检查练习'
    with pytest.raises(ValueError, match='selected or recommended topic'):
        analysis.parse_result(value, plan, data)


REAL_PDF = Path.home() / 'Desktop/题库/08莫那什大学/acc1001/期末复习讲义/MONASH__ACC1001__FinalRevision.pdf'
REAL_SHA = '4e22e39557dd9120092c9db25a0a38b599fb793a15173ebdbd6fab122e610a13'


@pytest.fixture
def real_pdf_lane(research):
    """A byte-identical *temporary* copy, with live source stat/hash protected."""
    if not REAL_PDF.is_file():
        pytest.skip('Local ACC1001 acceptance source is not present on this machine')
    content = REAL_PDF.read_bytes()
    before = (REAL_PDF.stat().st_size, REAL_PDF.stat().st_mtime_ns, hashlib.sha256(content).hexdigest())
    assert before[2] == REAL_SHA, 'The real source changed: re-pin the acceptance input explicitly.'
    source = research[4].root / '08莫那什大学/acc1001/期末复习讲义/MONASH__ACC1001__FinalRevision.pdf'
    source.parent.mkdir(parents=True)
    source.write_bytes(content)
    scan(research[4])
    with research[3]() as db:
        file = db.scalar(select(CourseLibraryFile).where(CourseLibraryFile.filename == source.name))
        file_id, revision_id = file.id, file.current_revision_id
        db.add(ModelConfig(user_id=file.user_id, name='Local safety stub only', model_type='text',
            provider='openai', model_name='safety-fixture', base_url='https://fixture.invalid/v1',
            encrypted_api_key=encrypt_text('SAFETY_SECRET_NEVER_OUTBOUND'), is_default=True))
        db.commit()
    response = research[0].post(BASE, headers=research[1], json={'file_id': file_id, 'revision_id': revision_id,
        'request_key': str(uuid4()), 'entry_mode': 'pdf-driven', 'template_id': 'magazine-a'})
    assert response.status_code == 200, response.text
    try:
        yield research, response.json(), source
    finally:
        assert before == (REAL_PDF.stat().st_size, REAL_PDF.stat().st_mtime_ns,
                          hashlib.sha256(REAL_PDF.read_bytes()).hexdigest())


def request_for(plan):
    return {'external_consent': True, 'plan_digest': plan['plan_digest'], 'request_key': str(uuid4())}


def real_result(plan, row):
    result = analysis_fixture(plan, row['data'])
    # The stub tests protocol boundaries, not the actual quality of real AI copy.
    result['copy'].update(title='ACC1001学习方法核对', tags=['ACC1001'])
    result['editor_notes'] = ['隔离stub协议验收，不代表真实课程事实、用户审核或AI成品。']
    return result


def test_real_pdf_prepare_is_read_only_and_all_rejected_requests_are_zero_call(real_pdf_lane):
    r, row, source = real_pdf_lane
    before = raw(r, row)
    stub = install_pdf_stub(r, lambda _: pytest.fail('Prepare/rejection must not call AI'))
    plan = call(r, row, 'pdf-analysis-plan')
    assert plan['coverage']['read_pages'] == list(range(1, 45))
    assert plan['coverage']['local_chars'] == 57258 and not plan['coverage']['local_truncated']
    assert plan['coverage']['sent_chars'] == sum(len(p['text']) for p in plan['material']['pages']) <= 24000
    assert plan['coverage']['excerpt_pages'] == [p['page'] for p in plan['material']['pages']]
    assert len(plan['material']['pages']) <= 16 and plan['source']['sha256'] == REAL_SHA
    assert plan['model']['destination'] == 'https://fixture.invalid/v1'
    encoded = json.dumps(plan, ensure_ascii=False)
    assert str(REAL_PDF) not in encoded and str(source) not in encoded
    assert 'SAFETY_SECRET_NEVER_OUTBOUND' not in encoded and 'credential_version' not in encoded
    assert call(r, row, 'pdf-analysis-plan')['plan_digest'] == plan['plan_digest']
    payload = request_for(plan)
    call(r, row, 'generate-from-pdf', {**payload, 'external_consent': False}, 422)
    call(r, row, 'generate-from-pdf', {**payload, 'plan_digest': 'wrong'}, 422)
    assert r[0].post(f'{BASE}/{row["id"]}/generate-from-pdf', json={
        'expected_version': row['row_version'], **payload}).status_code == 401
    assert r[0].post(f'{BASE}/{row["id"]}/generate-from-pdf', headers=r[2], json={
        'expected_version': row['row_version'], **payload}).status_code == 404
    with r[3]() as db:
        model = db.scalar(select(ModelConfig))
        model.is_default = False
        db.commit()
    unconfigured = call(r, row, 'pdf-analysis-plan')
    assert unconfigured['model'] is None
    call(r, row, 'generate-from-pdf', request_for(unconfigured), 422)
    assert stub.calls == 0 and raw(r, row) == before
    untouched_tasks(r)


def test_scan_only_extraction_rejects_before_prompt_or_model_call(real_pdf_lane, monkeypatch):
    r, row, _ = real_pdf_lane
    before = raw(r, row)
    stub = install_pdf_stub(r, lambda _: pytest.fail('Empty extraction must not call AI'))
    monkeypatch.setattr('backend.app.api.course_library_drafts.subprocess_json', lambda *args: {
        'page_count': 44, 'pages': [{'page': n, 'text': '', 'truncated': False, 'original_chars': 0}
                                   for n in range(1, 45)],
        'local_truncated': False, 'limits': {'pages': 120, 'page_chars': 4000, 'total_chars': 120000}})
    response = call(r, row, 'pdf-analysis-plan', expected=422)
    assert '未启用OCR' in response['detail']
    assert stub.calls == 0 and raw(r, row) == before
    untouched_tasks(r)


@pytest.mark.parametrize('field,value', [('base_url', 'https://changed.invalid/v1'),
                                        ('model_name', 'different-fixture'),
                                        ('encrypted_api_key', None)])
def test_consent_digest_rejects_model_or_credential_rotation_before_call(real_pdf_lane, field, value):
    r, row, _ = real_pdf_lane
    plan = call(r, row, 'pdf-analysis-plan')
    before = raw(r, row)
    stub = install_pdf_stub(r, real_result(plan, row))
    with r[3]() as db:
        model = db.scalar(select(ModelConfig))
        setattr(model, field, encrypt_text('ANOTHER_FIXTURE_KEY') if value is None else value)
        db.commit()
    call(r, row, 'generate-from-pdf', request_for(plan), 422)
    assert stub.calls == 0 and raw(r, row) == before
    untouched_tasks(r)


def test_pending_and_failed_uuid_never_repeat_a_call_or_leak_provider_errors(real_pdf_lane):
    r, row, _ = real_pdf_lane
    plan = call(r, row, 'pdf-analysis-plan')
    payload = request_for(plan)
    before = raw(r, row)
    def during_call(_):
        call(r, row, 'generate-from-pdf', payload, 409)
        raise RuntimeError('SAFETY_SECRET_NEVER_OUTBOUND https://user:secret@provider.invalid/?token=secret')
    stub = install_pdf_stub(r, during_call)
    failed = call(r, row, 'generate-from-pdf', payload, 502)
    assert 'SAFETY_SECRET_NEVER_OUTBOUND' not in json.dumps(failed)
    call(r, row, 'generate-from-pdf', payload, 409)
    now = raw(r, row)
    assert stub.calls == 1 and now['data']['operation']['status'] == 'failed'
    for field in ('copy', 'images', 'cover', 'history', 'approvals', 'export'):
        assert now['data'][field] == before['data'][field]
    assert 'SAFETY_SECRET_NEVER_OUTBOUND' not in json.dumps(now['data']['production_trace'])
    untouched_tasks(r)


def test_a_new_source_revision_during_stub_wait_discards_the_old_result(real_pdf_lane):
    r, row, source = real_pdf_lane
    plan = call(r, row, 'pdf-analysis-plan')
    before = raw(r, row)
    payload = request_for(plan)
    def during_call(_):
        source.write_bytes(source.read_bytes() + b'\n% changed temporary acceptance copy\n')
        scan(r[4])
        return real_result(plan, row)
    stub = install_pdf_stub(r, during_call)
    call(r, row, 'generate-from-pdf', payload, 409)
    call(r, row, 'generate-from-pdf', payload, 409)
    now = raw(r, row)
    assert stub.calls == 1 and now['data']['operation']['status'] == 'failed'
    assert now['data']['copy'] == before['data']['copy']
    assert 'pdf_analysis' not in now['data'] and now['data']['history'] == before['data']['history']
    with r[3]() as db:
        file = db.get(CourseLibraryFile, row['file_id'])
        assert file.current_revision_id != row['data']['source']['revision_id']
    untouched_tasks(r)


def test_late_callback_never_restores_old_state_over_a_newer_workflow(real_pdf_lane):
    r, row, _ = real_pdf_lane
    plan = call(r, row, 'pdf-analysis-plan')
    payload = request_for(plan)
    saved = {}
    def during_call(_):
        with r[3]() as db:
            record = db.get(CourseVisualWorkflow, row['id'])
            current = deepcopy(record.data)
            current['copy']['topic'] = 'A newer deliberate local update'
            current['operation'] = {'key': str(uuid4()), 'status': 'completed', 'kind': 'newer-local-state'}
            record.data = current
            db.commit()
        saved.update(raw(r, row))
        return real_result(plan, row)
    stub = install_pdf_stub(r, during_call)
    call(r, row, 'generate-from-pdf', payload, 409)
    assert raw(r, row) == saved and stub.calls == 1
    call(r, row, 'generate-from-pdf', payload, 409)
    assert raw(r, row) == saved and stub.calls == 1
    untouched_tasks(r)


def test_model_changed_during_stub_wait_rejects_result_and_success_trace_is_private(real_pdf_lane):
    r, row, _ = real_pdf_lane
    plan = call(r, row, 'pdf-analysis-plan')
    before = raw(r, row)
    def during_call(_):
        with r[3]() as db:
            model = db.scalar(select(ModelConfig))
            model.base_url = 'https://changed-after-consent.invalid/v1'
            db.commit()
        return real_result(plan, row)
    stub = install_pdf_stub(r, during_call)
    call(r, row, 'generate-from-pdf', request_for(plan), 409)
    now = raw(r, row)
    assert now['data']['copy'] == before['data']['copy'] and now['data']['operation']['status'] == 'failed'
    assert stub.calls == 1 and 'pdf_analysis' not in now['data']
    current = r[0].get(f'{BASE}/{row["id"]}', headers=r[1]).json()
    new_plan = call(r, current, 'pdf-analysis-plan')
    stub = install_pdf_stub(r, real_result(new_plan, current))
    result = call(r, current, 'generate-from-pdf', request_for(new_plan))
    trace = json.dumps(result['data']['production_trace'], ensure_ascii=False)
    assert 'SAFETY_SECRET_NEVER_OUTBOUND' not in trace and str(REAL_PDF) not in trace
    assert new_plan['prompt'] not in trace
    for fact in result['data']['pdf_analysis']['product_facts']:
        assert fact['quote'] not in trace
    assert not any(result['approved'].values()) and result['data']['export'] is None
    assert result['data']['images'] == [] and stub.calls == 1
    untouched_tasks(r)
