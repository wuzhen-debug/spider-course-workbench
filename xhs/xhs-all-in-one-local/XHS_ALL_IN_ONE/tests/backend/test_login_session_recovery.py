"""Offline acceptance for split-step account binding and consumed-code recovery.

Every database is a tmp_path fixture; adapters and optional self-profile reads
are fake. No existing user account, session, cookie or draft is loaded.
"""
from copy import deepcopy
from datetime import timedelta
import json

import pytest

from backend.app.api import login_sessions as routes
from backend.app.core.database import get_db
from backend.app.core.security import decrypt_text
from backend.app.core.time import shanghai_now
from backend.app.models import AccountCookieVersion, LoginSession, PlatformAccount
from test_api import _override_database, _register_and_get_access_token, app, client


PHONE = "13800138000"
CODE = "123456"
CONTEXT = "runtime-context-only"
SECRET = "upstream-private-cookie-never-render"


class BindingAdapter:
    """Models server success followed by independently retryable profile read."""

    def __init__(self, *, profile_failures=0, confirm_error=None, poll_error=None):
        self.profile_failures = profile_failures
        self.confirm_error = confirm_error
        self.poll_error = poll_error
        self.calls = {"send": 0, "confirm": 0, "qr": 0, "poll": 0, "profile": 0}

    def create_qrcode(self):
        self.calls["qr"] += 1
        return {"qr_id": "fake-qr", "code": "fake-qr-code", "qr_url": "https://example.test/qr",
                "cookies": {"a1": "anonymous", "__xhs_login_context": CONTEXT}}

    def create_phone_session(self, phone):
        assert phone == PHONE
        self.calls["send"] += 1
        return {"message": "sent", "cookies": {"a1": "anonymous", "__xhs_login_context": CONTEXT}}

    def confirm_phone_login(self, phone, code, cookies):
        assert phone == PHONE and code == CODE
        self.calls["confirm"] += 1
        if self.confirm_error:
            raise self.confirm_error
        return {"status": "confirmed", "cookies": {"a1": "anonymous", "web_session": "issued-auth",
                                                     "__xhs_login_context": CONTEXT}}

    def check_qrcode_status(self, qr_id, *args):
        assert qr_id == "fake-qr"
        self.calls["poll"] += 1
        if self.poll_error:
            raise self.poll_error
        return {"status": "confirmed", "cookies": {"a1": "anonymous", "web_session": "issued-auth",
                                                     "__xhs_login_context": CONTEXT}}

    def get_user_info(self, cookies):
        assert cookies.get("web_session") == "issued-auth", "Profile retry must use newly issued auth cookies"
        self.calls["profile"] += 1
        if self.profile_failures:
            self.profile_failures -= 1
            raise TimeoutError(f"upstream timeout {SECRET} phone={PHONE} code={CODE}")
        # Match the real adapter contract: the transient context never becomes
        # a final persistent account cookie.
        cookies.pop("__xhs_login_context", None)
        return {"external_user_id": "fixture-bound-account", "nickname": "Offline binding fixture",
                "avatar_url": "", "profile": {}}


@pytest.fixture
def binding(tmp_path, monkeypatch):
    dependency = _override_database(tmp_path)
    original_overrides = dict(app.dependency_overrides)
    adapter = BindingAdapter()
    app.dependency_overrides[routes.get_creator_login_adapter] = lambda: adapter
    app.dependency_overrides[routes.get_pc_login_adapter] = lambda: adapter

    class SelfProfile:
        def __init__(self, *_args):
            pass

        def get_self_info(self):
            return {}

    monkeypatch.setattr(routes, "XhsPcApiAdapter", SelfProfile)
    # Even a future accidental call from optional enrichment must fail closed.
    def no_network(*_args, **_kwargs):
        raise AssertionError("Network forbidden in isolated binding tests")

    monkeypatch.setattr("requests.sessions.Session.request", no_network)
    try:
        import curl_cffi.requests
        monkeypatch.setattr(curl_cffi.requests.Session, "request", no_network)
    except ImportError:
        pass
    token = _register_and_get_access_token("binding-fixture-owner")
    headers = {"Authorization": f"Bearer {token}"}
    yield adapter, headers
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original_overrides)
    app.dependency_overrides.pop(dependency, None)


def db_read(callback):
    db = next(app.dependency_overrides[get_db]())
    try:
        return callback(db)
    finally:
        db.close()


def new_session(headers, method, sub_type="creator"):
    path = f"/api/xhs/login-sessions/{sub_type}/" + ("qrcode" if method == "qr" else "phone/send-code")
    response = client.post(path, headers=headers, json={} if method == "qr" else {"phone": PHONE})
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def finish(headers, session_id, method, sub_type="creator", *, phone=PHONE):
    if method == "qr":
        return client.get(f"/api/xhs/login-sessions/{session_id}", headers=headers)
    return client.post(f"/api/xhs/login-sessions/{sub_type}/phone/confirm", headers=headers,
                       json={"session_id": session_id, "phone": phone, "code": CODE})


def cookie_counts():
    return db_read(lambda db: (db.query(PlatformAccount).count(), db.query(AccountCookieVersion).count()))


@pytest.mark.parametrize("method,minutes", [("qr", 6), ("phone", 9)])
def test_expired_session_stops_before_any_platform_call(binding, method, minutes):
    adapter, headers = binding
    session_id = new_session(headers, method)

    def expire(db):
        db.get(LoginSession, session_id).created_at = shanghai_now() - timedelta(minutes=minutes)
        db.commit()

    db_read(expire)
    before_calls = deepcopy(adapter.calls)
    response = finish(headers, session_id, method)
    assert response.status_code in {200, 409, 410}, response.text
    if response.status_code == 200:
        assert response.json()["status"] == "expired"
    else:
        assert "过期" in response.json()["detail"] or "失效" in response.json()["detail"]
    assert adapter.calls == before_calls
    assert db_read(lambda db: db.get(LoginSession, session_id).status) == "expired"
    assert cookie_counts() == (0, 0)


@pytest.mark.parametrize("method", ["qr", "phone"])
@pytest.mark.parametrize("sub_type", ["creator", "pc"])
def test_completed_session_retry_returns_same_account_without_duplicate_credentials(binding, method, sub_type):
    adapter, headers = binding
    session_id = new_session(headers, method, sub_type)
    first = finish(headers, session_id, method, sub_type)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "confirmed"
    before_calls = deepcopy(adapter.calls)
    second = finish(headers, session_id, method, sub_type)
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "confirmed"
    assert second.json()["account"]["id"] == first.json()["account"]["id"]
    assert adapter.calls == before_calls
    assert cookie_counts() == (1, 1)
    saved = db_read(lambda db: decrypt_text(db.query(AccountCookieVersion).one().encrypted_cookies))
    assert "__xhs_login_context" not in saved and CONTEXT not in saved


@pytest.mark.parametrize("method", ["qr", "phone"])
def test_authenticated_session_resumes_profile_without_reusing_consumed_code_or_ticket(binding, method):
    adapter, headers = binding
    adapter.profile_failures = 1
    session_id = new_session(headers, method)
    first = finish(headers, session_id, method)
    assert first.status_code in {400, 409, 502, 503, 504}, first.text
    assert SECRET not in first.text and PHONE not in first.text and CODE not in first.text
    assert cookie_counts() == (0, 0)
    pending = db_read(lambda db: json.loads(decrypt_text(db.get(LoginSession, session_id).encrypted_temp_cookies)))
    assert pending.get("authenticated") is True
    cookies = pending.get("cookies", pending)
    assert cookies.get("web_session") == "issued-auth"
    authenticated_calls = adapter.calls["poll" if method == "qr" else "confirm"]
    second = finish(headers, session_id, method)
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "confirmed" and second.json()["account"]["nickname"]
    assert adapter.calls["poll" if method == "qr" else "confirm"] == authenticated_calls == 1
    assert adapter.calls["profile"] == 2
    assert cookie_counts() == (1, 1)


@pytest.mark.parametrize("changed_phone", ["13900138000", "13811118000"])
def test_changed_phone_including_same_mask_is_rejected_before_confirmation(binding, changed_phone):
    adapter, headers = binding
    session_id = new_session(headers, "phone")
    response = finish(headers, session_id, "phone", phone=changed_phone)
    assert response.status_code in {400, 409, 422}, response.text
    assert "手机号" in response.json()["detail"]
    assert adapter.calls["confirm"] == 0 and adapter.calls["profile"] == 0
    assert cookie_counts() == (0, 0)


@pytest.mark.parametrize("method", ["qr", "phone"])
def test_another_user_cannot_poll_or_confirm_owners_session(binding, method):
    adapter, headers = binding
    session_id = new_session(headers, method)
    other_token = _register_and_get_access_token("binding-fixture-other")
    other_headers = {"Authorization": f"Bearer {other_token}"}
    response = finish(other_headers, session_id, method)
    assert response.status_code == 404
    assert adapter.calls["poll"] == adapter.calls["confirm"] == adapter.calls["profile"] == 0
    assert cookie_counts() == (0, 0)


def test_wrong_account_type_cannot_consume_phone_session(binding):
    adapter, headers = binding
    session_id = new_session(headers, "phone", "creator")
    response = finish(headers, session_id, "phone", "pc")
    assert response.status_code == 404
    assert adapter.calls["confirm"] == 0
    assert cookie_counts() == (0, 0)


@pytest.mark.parametrize("method", ["qr", "phone"])
def test_upstream_failure_is_safe_and_not_always_labeled_wrong_code(binding, method):
    adapter, headers = binding
    session_id = new_session(headers, method)
    error = RuntimeError(f"unrecognized upstream body Cookie: {SECRET} phone={PHONE} code={CODE}")
    if method == "qr":
        adapter.poll_error = error
    else:
        adapter.confirm_error = error
    response = finish(headers, session_id, method)
    assert response.status_code in {400, 409, 502, 503, 504}
    detail = response.json()["detail"]
    assert isinstance(detail, str) and any("\u4e00" <= char <= "\u9fff" for char in detail)
    assert "验证码校验失败或已过期" not in detail
    assert all(private not in response.text for private in [SECRET, PHONE, CODE, "unrecognized upstream"])
    assert cookie_counts() == (0, 0)


@pytest.mark.parametrize("method", ["qr", "phone"])
def test_lost_runtime_session_becomes_expired_with_recovery_message(binding, method):
    from backend.app.adapters.xhs.login_errors import XhsLoginError

    adapter, headers = binding
    session_id = new_session(headers, method)
    error = XhsLoginError("login_session_expired", "本次登录会话已失效，请重新获取二维码或验证码。")
    if method == "qr":
        adapter.poll_error = error
    else:
        adapter.confirm_error = error
    response = finish(headers, session_id, method)
    assert response.status_code in {409, 410}, response.text
    assert "会话" in response.json()["detail"] and "重新" in response.json()["detail"]
    assert db_read(lambda db: db.get(LoginSession, session_id).status) == "expired"
    assert cookie_counts() == (0, 0)
