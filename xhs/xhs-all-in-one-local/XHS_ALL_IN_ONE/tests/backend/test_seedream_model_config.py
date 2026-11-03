"""Image configuration checks use an isolated DB and fake provider responses."""
from types import SimpleNamespace

import pytest

from test_api import app, client, _override_database, _register_and_get_access_token


@pytest.fixture
def image_config(tmp_path):
    dependency = _override_database(tmp_path)
    token = _register_and_get_access_token('seedream-config-owner')
    headers = {'Authorization': f'Bearer {token}'}
    try:
        result = client.post('/api/model-configs', headers=headers, json={
            'name': 'Seedream fixture', 'model_type': 'image', 'provider': 'openai-compatible',
            'model_name': 'doubao-seedream-5-0-flash-260915',
            'base_url': 'https://ark.cn-beijing.volces.com/api/v3',
            'api_key': 'fixture-secret', 'is_default': True,
        })
        assert result.status_code == 200
        yield result.json()['id'], headers
    finally:
        app.dependency_overrides.pop(dependency, None)


def test_seedream_check_uses_supported_size_and_returns_actual_preview(image_config, monkeypatch):
    config_id, headers = image_config
    calls = []
    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=200, json=lambda: {'data': [{'url': 'https://images.example.test/generated.png'}]})
    monkeypatch.setattr('requests.post', fake_post)
    result = client.post(f'/api/model-configs/{config_id}/test', headers=headers)
    assert result.json()['status'] == 'ok'
    assert result.json()['image_url'] == 'https://images.example.test/generated.png'
    assert len(calls) == 1
    url, request = calls[0]
    assert url == 'https://ark.cn-beijing.volces.com/api/v3/images/generations'
    assert request['json'] == {
        'model': 'doubao-seedream-5-0-flash-260915',
        'prompt': 'A single blue circle centered on a plain white background. No text.',
        'response_format': 'url', 'size': '1K',
    }
    assert request['timeout'] == 180
    assert 'fixture-secret' not in result.text


@pytest.mark.parametrize('payload', [{'object': 'image'}, {'data': []}, {'data': [{'error': {'message': 'model unavailable'}}]}])
def test_http_success_without_an_image_is_not_reported_as_working(image_config, monkeypatch, payload):
    config_id, headers = image_config
    monkeypatch.setattr('requests.post', lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: payload))
    result = client.post(f'/api/model-configs/{config_id}/test', headers=headers)
    assert result.json()['status'] == 'error'
    assert 'image_url' not in result.json()


def test_missing_key_and_wrong_owner_never_call_provider(image_config, monkeypatch):
    config_id, headers = image_config
    monkeypatch.setattr('requests.post', lambda *a, **k: pytest.fail('No provider request allowed'))
    other = _register_and_get_access_token('seedream-config-other')
    assert client.post(f'/api/model-configs/{config_id}/test', headers={'Authorization': f'Bearer {other}'}).status_code == 404
    client.patch(f'/api/model-configs/{config_id}', headers=headers, json={'api_key': ''})
    assert client.post(f'/api/model-configs/{config_id}/test', headers=headers).json()['message'] == '未配置 API Key'


def test_provider_errors_never_echo_api_key(image_config, monkeypatch):
    config_id, headers = image_config
    monkeypatch.setattr('requests.post', lambda *a, **k: SimpleNamespace(status_code=401, text='Rejected fixture-secret'))
    result = client.post(f'/api/model-configs/{config_id}/test', headers=headers)
    assert result.json()['status'] == 'error'
    assert 'fixture-secret' not in result.text

