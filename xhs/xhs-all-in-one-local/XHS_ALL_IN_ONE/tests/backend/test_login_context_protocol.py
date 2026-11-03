"""Installed pinned SDK login methods over fake transports; no external requests."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

# Import the backend adapter first so tests use the production pinned snapshot.
from backend.app.adapters.xhs.creator_login_adapter import XhsCreatorLoginAdapter
from backend.app.adapters.xhs.pc_login_adapter import XhsPcLoginAdapter
from backend.app.adapters.xhs.login_context import LOGIN_CONTEXT_COOKIE, LoginContextRegistry, login_contexts
from backend.app.adapters.xhs.login_errors import XhsLoginError, login_failure


class Response:
    def __init__(self, url, payload, cookies=None, status=200):
        self.url, self.payload, self.cookies, self.status_code = url, payload, cookies or {}, status

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class Transport:
    def __init__(self):
        self.routes = []
        self.calls = []
        self.closed = 0

    def queue(self, suffix, payload, cookies=None, status=200):
        self.routes.append((suffix, payload, cookies, status))

    def _send(self, url, **kwargs):
        assert '__xhs_' not in json.dumps(kwargs, default=str), 'Private context token must never reach the SDK transport'
        self.calls.append((url, kwargs))
        suffix, payload, cookies, status = self.routes.pop(0)
        assert suffix in url
        if isinstance(payload, Exception) and not isinstance(payload, ValueError):
            raise payload
        return Response(url, payload, cookies, status)

    get = _send
    post = _send

    def close(self):
        self.closed += 1


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    import requests
    from curl_cffi import requests as curl_requests
    def deny_network(*args, **kwargs):
        raise AssertionError('No real HTTP permitted in login protocol tests')
    monkeypatch.setattr(requests.sessions.Session, 'request', deny_network)
    monkeypatch.setattr(curl_requests.Session, 'request', deny_network)
    login_contexts.clear()
    yield
    login_contexts.clear()


@pytest.fixture
def creator(monkeypatch):
    import apis.xhs_creator_login_apis as sdk
    assert 'vendor/spider_xhs_23dab803' in sdk.__file__
    actual = sdk.XHSCreatorLoginApi
    transport = Transport()
    api = actual(http_client=transport)
    steps = []
    def prepare():
        steps.append('prepare')
        api.profile.update_cookies({'a1': 'fixture-a1', 'loadts': '1000', 'ets': '1000', 'websectiga': 'w' * 64, 'sec_poison_id': 's' * 36, 'gid': 'g' * 72})
        api._cookie_store.update(api.creator_url, {'acw_tc': 'fixture-creator-host'})
        api._cookie_store.update(api.customer_url, {'acw_tc': 'fixture-customer-host'})
        return api.profile.cookie_map, {'active': False}
    monkeypatch.setattr(api, '_prepare_login_session', prepare)
    monkeypatch.setattr(api, '_complete_security', lambda: steps.append('complete'))
    seq = []
    def signed(path, data='', method='POST', **kwargs):
        seq.append(api.profile.session.next_seq())
        return {}, api.profile.cookie_map, json.dumps(data)
    monkeypatch.setattr(api, '_signed', signed)
    monkeypatch.setattr(sdk, 'build_creator_login_headers', lambda headers, cookies=None, **kwargs: {**headers, 'cookie': '; '.join(f'{key}={value}' for key, value in (cookies or {}).items())})
    monkeypatch.setattr(sdk, 'XHSCreatorLoginApi', lambda: api)
    return SimpleNamespace(api=api, transport=transport, adapter=XhsCreatorLoginAdapter(), steps=steps, seq=seq)


@pytest.fixture
def pc(monkeypatch):
    import apis.xhs_pc_login_apis as sdk
    assert 'vendor/spider_xhs_23dab803' in sdk.__file__
    actual = sdk.XHSLoginApi
    transport = Transport()
    api = actual(http_client=transport)
    steps, seq = [], []
    def prepare():
        steps.append('prepare')
        cookies = {'a1': 'fixture-a1', 'loadts': '1000', 'web_session': 'fixture-visitor'}
        api._ensure_profile(cookies)
        api._cookie_store.update(api.base_url, {'acw_tc': 'fixture-pc-host'})
        return cookies
    def profile(cookies):
        steps.append('webprofile')
        cookies['gid'] = 'fixture-gid'
        api._ensure_profile(cookies)
    def signed(cookies, path, data='', method='POST', **kwargs):
        assert LOGIN_CONTEXT_COOKIE not in cookies
        api._ensure_profile(cookies)
        seq.append(api.profile.session.next_seq())
        return {}, json.dumps(data)
    monkeypatch.setattr(api, 'generate_init_cookies', prepare)
    monkeypatch.setattr(api, 'ensure_webprofile', profile)
    monkeypatch.setattr(api, '_signed_request_params', signed)
    monkeypatch.setattr(sdk, 'build_pc_login_headers', lambda headers, cookies=None, **kwargs: {**headers, 'cookie': '; '.join(f'{key}={value}' for key, value in (cookies or {}).items())})
    monkeypatch.setattr(sdk, 'XHSLoginApi', lambda: api)
    return SimpleNamespace(api=api, transport=transport, adapter=XhsPcLoginAdapter(), steps=steps, seq=seq)


def creator_phone_sent(fixture):
    fixture.transport.queue('/verify-code', {'success': True}, {'sms_binding': 'fixture-response-cookie'})
    return fixture.adapter.create_phone_session('13800138000')['cookies']


def creator_phone_confirmed(fixture, cookies):
    fixture.transport.queue('/service-ticket', {'success': True}, {'customer-sso-sid': 'fixture-auth'})
    return fixture.adapter.confirm_phone_login('13800138000', '123456', cookies)['cookies']


def test_creator_sms_preserves_response_cookies_host_scope_sequence_and_client(creator):
    cookies = creator_phone_sent(creator)
    assert cookies['sms_binding'] == 'fixture-response-cookie'
    assert creator.steps == ['prepare', 'complete'] and creator.transport.closed == 0
    final = creator_phone_confirmed(creator, cookies)
    creator.transport.queue('/user/info', {'success': True, 'data': {'userId': 'fixture-user', 'userName': 'fixture-name'}})
    info = creator.adapter.get_user_info(final)
    assert info['external_user_id'] == 'fixture-user'
    assert creator.seq == [1, 2, 3]
    assert creator.transport.closed == 1 and LOGIN_CONTEXT_COOKIE not in final
    assert final['customer-sso-sid'] == 'fixture-auth'
    assert 'fixture-customer-host' in creator.transport.calls[1][1]['headers']['cookie']
    assert 'fixture-creator-host' in creator.transport.calls[2][1]['headers']['cookie']


def test_creator_profile_retry_does_not_resubmit_consumed_sms_code(creator):
    final = creator_phone_confirmed(creator, creator_phone_sent(creator))
    creator.transport.queue('/user/info', ConnectionError('fixture network'))
    with pytest.raises(XhsLoginError) as failed:
        creator.adapter.get_user_info(final)
    assert failed.value.error_code == 'login_network_error' and LOGIN_CONTEXT_COOKIE in final
    repeated = creator.adapter.confirm_phone_login('13800138000', '123456', final)['cookies']
    assert len([url for url, _ in creator.transport.calls if '/service-ticket' in url]) == 1
    creator.transport.queue('/user/info', {'success': True, 'data': {'userId': 'fixture-user'}})
    creator.adapter.get_user_info(repeated)
    assert creator.transport.closed == 1 and LOGIN_CONTEXT_COOKIE not in repeated


def test_creator_numeric_qr_states_and_same_context_until_identity_acceptance(creator):
    creator.transport.queue('/qr-code', {'success': True, 'data': {'id': 'fixture-qr', 'url': 'https://example.test/qr'}})
    state = creator.adapter.create_qrcode()
    for number, expected in [(2, 'pending'), (3, 'scanned'), (1, 'confirmed')]:
        creator.transport.queue('/qr-code', {'success': True, 'data': {'status': number}}, {'customer-sso-sid': 'fixture-auth'} if number == 1 else {})
        state = creator.adapter.check_qrcode_status('fixture-qr', state['cookies'])
        assert state['status'] == expected
    # Once the ticket was accepted, retrying profile must not poll/consume it again.
    assert creator.adapter.check_qrcode_status('fixture-qr', state['cookies'])['status'] == 'confirmed'
    creator.transport.queue('/user/info', {'success': True, 'data': {'userId': 'fixture-user'}})
    creator.adapter.get_user_info(state['cookies'])
    assert creator.seq == [1, 2, 3, 4, 5] and creator.transport.closed == 1


@pytest.mark.parametrize('payload', [{'success': False, 'code': 0}, {'success': True, 'data': {'status': 7}}, {'success': False, 'data': {'status': 2}}])
def test_creator_unknown_or_rejected_qr_is_not_infinite_pending(creator, payload):
    creator.transport.queue('/qr-code', {'success': True, 'data': {'id': 'fixture-qr', 'url': 'https://example.test/qr'}})
    state = creator.adapter.create_qrcode()
    creator.transport.queue('/qr-code', payload)
    with pytest.raises(XhsLoginError):
        creator.adapter.check_qrcode_status('fixture-qr', state['cookies'])


def test_creator_qr_expiry_releases_client_and_cannot_be_polled_again(creator):
    creator.transport.queue('/qr-code', {'success': True, 'data': {'id': 'fixture-qr', 'url': 'https://example.test/qr'}})
    state = creator.adapter.create_qrcode()
    creator.transport.queue('/qr-code', {'success': True, 'data': {'status': 4}})
    assert creator.adapter.check_qrcode_status('fixture-qr', state['cookies'])['status'] == 'expired'
    with pytest.raises(XhsLoginError, match='过期'):
        creator.adapter.check_qrcode_status('fixture-qr', state['cookies'])
    assert creator.transport.closed == 1


def test_pc_qr_initial_profile_then_scan_confirm_and_clean_final_cookie(pc):
    pc.transport.queue('/qrcode/create', {'success': True, 'data': {'qr_id': 'fixture-qr', 'code': 'fixture-qr-code', 'url': 'https://example.test/qr'}})
    pc.transport.queue('/qrcode/userinfo', {'success': True, 'data': {'codeStatus': 0}})
    state = pc.adapter.create_qrcode()
    assert pc.steps == ['prepare', 'webprofile']
    pc.transport.queue('/qrcode/userinfo', {'success': True, 'data': {'codeStatus': 1}})
    assert pc.adapter.check_qrcode_status(state['qr_id'], state['code'], state['cookies'])['status'] == 'scanned'
    pc.transport.queue('/qrcode/userinfo', {'success': True, 'data': {'codeStatus': 2}})
    pc.transport.queue('/qrcode/status', {'success': True, 'data': {'code_status': 2, 'login_info': {'session': 'fixture-auth'}}})
    confirmed = pc.adapter.check_qrcode_status(state['qr_id'], state['code'], state['cookies'])
    pc.transport.queue('/user/me', {'success': True, 'data': {'user_id': 'fixture-user', 'nickname': 'fixture-name', 'guest': False}})
    pc.adapter.get_user_info(confirmed['cookies'])
    assert confirmed['cookies']['web_session'] == 'fixture-auth' and LOGIN_CONTEXT_COOKIE not in confirmed['cookies']
    assert pc.seq == list(range(1, 7)) and pc.transport.closed == 1


def test_pc_missing_qr_response_success_is_safe_failure_and_closes(pc):
    pc.transport.queue('/qrcode/create', {'code': 0})
    with pytest.raises(XhsLoginError) as failed:
        pc.adapter.create_qrcode()
    assert failed.value.error_code in {'login_protocol_error', 'login_platform_rejected'}
    assert pc.transport.closed == 1


def test_pc_sms_uses_webprofile_and_same_client_through_code_and_profile(pc):
    pc.transport.queue('/send_code', {'success': True}, {'sms_binding': 'fixture-response-cookie'})
    state = pc.adapter.create_phone_session('13800138000')
    assert pc.steps == ['prepare', 'webprofile'] and state['cookies']['sms_binding'] == 'fixture-response-cookie'
    pc.transport.queue('/check_code', {'success': True, 'data': {'mobile_token': 'fixture-mobile-token'}})
    pc.transport.queue('/login/code', {'success': True, 'data': {'session': 'fixture-auth'}})
    final = pc.adapter.confirm_phone_login('13800138000', '123456', state['cookies'])['cookies']
    pc.transport.queue('/user/me', {'success': True, 'data': {'user_id': 'fixture-user', 'guest': False}})
    pc.adapter.get_user_info(final)
    assert LOGIN_CONTEXT_COOKIE not in final and pc.seq == [1, 2, 3, 4] and pc.transport.closed == 1


def test_pc_success_cannot_be_reclassified_as_scanned_by_english_confirmed(pc, monkeypatch):
    pc.transport.queue('/send_code', {'success': True})
    state = pc.adapter.create_phone_session('13800138000')['cookies']
    with login_contexts.use(state, 'pc') as (token, context):
        context.method = 'qr'; context.qr_id = 'fixture-qr'; context.qr_code = 'fixture-code'
    monkeypatch.setattr(pc.api, 'check_qrcode_status', lambda *args: (True, 'confirmed', {'web_session': 'fixture-auth'}))
    result = pc.adapter.check_qrcode_status('fixture-qr', 'fixture-code', state)
    assert result['status'] == 'confirmed'


def test_pc_guest_profile_is_not_accepted_or_saved(pc):
    pc.transport.queue('/send_code', {'success': True})
    state = pc.adapter.create_phone_session('13800138000')['cookies']
    pc.transport.queue('/check_code', {'success': True, 'data': {'mobile_token': 'fixture-mobile-token'}})
    pc.transport.queue('/login/code', {'success': True, 'data': {'session': 'fixture-auth'}})
    final = pc.adapter.confirm_phone_login('13800138000', '123456', state)['cookies']
    pc.transport.queue('/user/me', {'success': True, 'data': {'user_id': 'fixture-user', 'guest': True}})
    with pytest.raises(XhsLoginError) as failed:
        pc.adapter.get_user_info(final)
    assert failed.value.error_code == 'login_profile_failed' and LOGIN_CONTEXT_COOKIE in final


def test_creator_bad_code_keeps_original_context_without_sending_another_sms(creator):
    state = creator_phone_sent(creator)
    creator.transport.queue('/service-ticket', {'success': False, 'msg': '验证码错误'})
    with pytest.raises(XhsLoginError) as failed:
        creator.adapter.confirm_phone_login('13800138000', '123456', state)
    assert failed.value.error_code == 'login_code_invalid'
    assert len(creator.transport.calls) == 2 and creator.transport.closed == 0


@pytest.mark.parametrize('platform', ['creator', 'pc'])
def test_old_or_cross_context_confirm_is_expired_without_network(platform):
    adapter = XhsCreatorLoginAdapter() if platform == 'creator' else XhsPcLoginAdapter()
    with pytest.raises(XhsLoginError) as failed:
        adapter.confirm_phone_login('13800138000', '123456', {'a1': 'legacy'})
    assert failed.value.error_code == 'login_session_expired'


def test_phone_change_and_qr_identity_mismatch_never_send_requests(creator):
    state = creator_phone_sent(creator)
    with pytest.raises(XhsLoginError) as failed:
        creator.adapter.confirm_phone_login('13900139000', '123456', state)
    assert failed.value.error_code == 'phone_mismatch' and len(creator.transport.calls) == 1
    with pytest.raises(XhsLoginError):
        XhsPcLoginAdapter().confirm_phone_login('13800138000', '123456', state)
    assert len(creator.transport.calls) == 1


@pytest.mark.parametrize('method,ttl', [('qr', 300), ('phone', 480)])
def test_registry_ttl_closes_without_background_job(method, ttl):
    now = [0.0]; store = LoginContextRegistry(clock=lambda: now[0]); client = Transport()
    state = store.add(client, 'creator', method, {'a1': 'fixture'})
    now[0] = ttl
    with pytest.raises(XhsLoginError) as failed:
        with store.use(state, 'creator'):
            pytest.fail('expired lifecycle was reopened')
    assert failed.value.error_code == 'login_session_expired' and client.closed == 1


def test_registry_capacity_never_evicts_active_login():
    store = LoginContextRegistry(limit=1)
    first, second = Transport(), Transport()
    state = store.add(first, 'creator', 'qr', {})
    with pytest.raises(XhsLoginError):
        store.add(second, 'pc', 'phone', {})
    with store.use(state, 'creator'):
        assert first.closed == 0
    store.clear(); assert first.closed == 1


def test_registry_serializes_mutable_session_operations():
    store = LoginContextRegistry(); state = store.add(Transport(), 'creator', 'qr', {})
    active = [0]; overlaps = []
    def operation(_):
        with store.use(state, 'creator'):
            active[0] += 1
            if active[0] != 1: overlaps.append(True)
            time.sleep(0.003)
            active[0] -= 1
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(operation, range(8)))
    assert not overlaps
    store.clear()


@pytest.mark.parametrize('exception,code', [(KeyError('success'), 'login_protocol_error'), (RuntimeError('HTTP 461 private_cookie=secret'), 'login_verification_required'), (RuntimeError('验证码错误 secret'), 'login_code_invalid'), (ConnectionError('https://example.test?phone=13800138000&code=123456'), 'login_network_error')])
def test_safe_errors_never_return_raw_credentials_or_upstream_body(exception, code):
    failure = login_failure(exception, 'confirm')
    assert failure.error_code == code
    assert all(value not in str(failure) for value in ['secret', '13800138000', '123456', 'https://'])
