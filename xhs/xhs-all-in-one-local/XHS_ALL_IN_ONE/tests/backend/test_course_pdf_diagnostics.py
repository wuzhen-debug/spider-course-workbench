"""Safe failures and official-PDF-only request options; no real HTTP or DB."""
from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
import requests
from pydantic import ValidationError

from test_course_library import library
from test_course_research import research
from test_course_visual_workflow import BASE, call
from test_course_visual_collages import raw, untouched_tasks
from test_course_visual_pdf_lane import pdf_run, analysis_fixture, install_pdf_stub
from backend.app.services.ai_service import OpenAICompatibleTextClient, TextCompletionResponseError
from backend.app.services import course_pdf_analysis as analysis

PRIVATE = 'PRIVATE_RESPONSE_INPUT_CONTEXT_MUST_NOT_BE_STORED'


def response_fixture(monkeypatch, *, content='{}', finish='stop', missing=False):
    calls = []
    def fake_post(url, **kwargs):
        calls.append({'url': url, **kwargs})
        choice = {'finish_reason': finish, 'message': {'content': content, 'reasoning_content': PRIVATE}}
        if missing:
            choice.pop('message')
        response = requests.Response(); response.status_code = 200
        response._content = json.dumps({'choices': [choice]}).encode()
        return response
    monkeypatch.setattr(requests, 'post', fake_post)
    return calls


@pytest.mark.parametrize('name', ['deepseek-flash', 'deepseek-v4-pro'])
def test_only_known_official_pdf_call_disables_thinking_and_requests_json(monkeypatch, name):
    calls = response_fixture(monkeypatch)
    model = SimpleNamespace(base_url='https://api.deepseek.com/v1', model_name=name)
    client = OpenAICompatibleTextClient()
    assert client.analyze_course_pdf(model_config=model, api_key='synthetic', reference='Return JSON') == {}
    call = calls[-1]
    assert call['timeout'] == (10, 150)
    assert call['json']['thinking'] == {'type': 'disabled'}
    assert call['json']['response_format'] == {'type': 'json_object'}
    assert call['json']['temperature'] == 0.3 and call['json']['max_tokens'] == 8192
    assert client.generate_course_copy(model_config=model, api_key='synthetic', reference='Return JSON') == {}
    assert calls[-1]['timeout'] == 60 and calls[-1]['json']['temperature'] == 0.7
    assert not set(calls[-1]['json']) & {'thinking', 'response_format', 'max_tokens'}


@pytest.mark.parametrize('url,name', [
    ('https://api.deepseek.com.proxy.invalid/v1', 'deepseek-flash'),
    ('https://gateway.invalid/v1', 'deepseek-v4-pro'),
    ('https://api.deepseek.com/v1', 'other-model'),
])
def test_other_pdf_providers_keep_generic_options(monkeypatch, url, name):
    calls = response_fixture(monkeypatch)
    model = SimpleNamespace(base_url=url, model_name=name)
    OpenAICompatibleTextClient().analyze_course_pdf(model_config=model, api_key='synthetic', reference='JSON')
    assert calls[-1]['timeout'] == (10, 150)
    assert not set(calls[-1]['json']) & {'thinking', 'response_format'}


@pytest.mark.parametrize('kwargs,code', [
    ({'finish': 'length', 'content': PRIVATE}, 'response_length'),
    ({'content': ''}, 'empty_content'),
    ({'content': None}, 'empty_content'),
    ({'missing': True}, 'missing_content'),
])
def test_pdf_protocol_errors_have_typed_safe_codes(monkeypatch, kwargs, code):
    response_fixture(monkeypatch, **kwargs)
    model = SimpleNamespace(base_url='https://api.deepseek.com/v1', model_name='deepseek-flash')
    with pytest.raises(TextCompletionResponseError) as raised:
        OpenAICompatibleTextClient().analyze_course_pdf(model_config=model, api_key='synthetic', reference='JSON')
    assert raised.value.code == code and PRIVATE not in str(raised.value)
    safe = analysis.safe_failure_diagnostic(raised.value, 'model_request')
    assert safe['category'] == 'response-protocol' and safe['code'] == code and PRIVATE not in json.dumps(safe)


def test_safe_validation_locations_never_keep_input_context_message_or_unknown_key():
    try:
        analysis.PdfPain.model_validate({'pain': 'x', 'pdf_pages': [PRIVATE], 'quote': PRIVATE, PRIVATE: PRIVATE})
    except ValidationError as error:
        diagnostic = analysis.safe_failure_diagnostic(error, 'response_validation')
    assert diagnostic['code'] == 'schema_validation' and diagnostic['validation']
    assert any(entry['loc'] == ['<field>'] for entry in diagnostic['validation'])
    serialized = json.dumps(diagnostic)
    assert PRIVATE not in serialized
    assert not any(token in entry for entry in diagnostic['validation'] for token in ('input', 'ctx', 'msg'))


@pytest.mark.parametrize('kind,stage,code', [
    ('timeout', 'model_request', 'text_request_timeout'),
    ('schema', 'response_validation', 'schema_validation'),
    ('citation', 'response_validation', 'citation_quote_mismatch'),
    ('unknown', 'model_request', 'unexpected_error'),
])
def test_api_retains_safe_failure_diagnostic_without_old_content_changes(research, kind, stage, code):
    row, _ = pdf_run(research)
    before = raw(research, row)['data']
    plan = call(research, row, 'pdf-analysis-plan')
    result = analysis_fixture(plan, row['data'])
    if kind == 'schema':
        result['copy']['body'] = PRIVATE * 50
        result[PRIVATE] = PRIVATE
    if kind == 'citation':
        result['source_map'][0]['quote'] = PRIVATE
    def execute(_):
        if kind == 'timeout':
            raise requests.ReadTimeout(PRIVATE)
        if kind == 'unknown':
            raise RuntimeError(PRIVATE)
        return result
    stub = install_pdf_stub(research, execute)
    key = str(uuid4())
    request = {'external_consent': True, 'plan_digest': plan['plan_digest'], 'request_key': key}
    failed = call(research, row, 'generate-from-pdf', request, 502)
    current = research[0].get(f'{BASE}/{row["id"]}', headers=research[1]).json()
    diagnostic = current['data']['operation']['diagnostic']
    assert diagnostic['stage'] == stage and diagnostic['code'] == code
    assert current['data']['pdf_requests'][key]['diagnostic'] == diagnostic
    assert current['data']['copy'] == before['copy'] and current['data']['images'] == before['images']
    assert current['data']['history'] == [] and current['data']['export'] is None
    assert PRIVATE not in json.dumps(current) and PRIVATE not in json.dumps(failed)
    call(research, current, 'generate-from-pdf', request, 409)
    assert stub.calls == 1
    untouched_tasks(research)
