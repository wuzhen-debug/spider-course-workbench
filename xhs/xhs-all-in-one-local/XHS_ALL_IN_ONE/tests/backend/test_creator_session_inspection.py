"""Read-only diagnostics must never become a publish retry or expiry guess."""
from types import SimpleNamespace

import pytest

from backend.app.adapters.xhs.creator_api_adapter import CreatorRequestRejected, XhsCreatorApiAdapter
from backend.app.api.accounts import get_creator_session_adapter_factory
from backend.app.core.database import get_db
from tests.backend.test_creator_lookup_responses import Response, fake_api


@pytest.mark.parametrize("status", [200, 401, 461])
def test_session_inspection_only_reads_identity_and_always_closes(monkeypatch, status):
    adapter, posts = fake_api(monkeypatch, [])
    api = adapter._api()
    closed = []
    api.auth = SimpleNamespace(close=lambda: closed.append(True), update_cookies=lambda *a, **kw: None)
    reads = []
    def get(url, **kwargs):
        reads.append(url)
        response = Response({"success": True, "code": 0, "data": {"verified": False}}, status)
        response.headers = {"verifytype": "209"} if status == 461 else {}
        return response
    api.http.get = get
    if status == 200:
        assert adapter.inspect_session() is None  # real-name status is not authentication
    else:
        with pytest.raises(CreatorRequestRejected):
            adapter.inspect_session()
    assert reads == ["https://edith.xiaohongshu.com/web_api/sns/v6/creator/user/verify"]
    assert posts == [] and closed == [True]


def test_failed_bootstrap_releases_sdk_auth(monkeypatch):
    from apis.xhs_creator_apis import XHS_Creator_Apis
    from xhs_utils.xhs_creator import XHSCreatorAuth
    closed = []
    auth = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(XHSCreatorAuth, "from_cookie", classmethod(lambda cls, cookies: auth))
    monkeypatch.setattr(XHS_Creator_Apis, "__init__", lambda self, auth: None)
    def fail(self):
        raise RuntimeError("fixture bootstrap failure")
    monkeypatch.setattr(XHS_Creator_Apis, "bootstrap", fail)
    with pytest.raises(RuntimeError, match="fixture bootstrap failure"):
        XhsCreatorApiAdapter("fixture").inspect_session()
    assert closed == [True]


@pytest.mark.parametrize("failure,expected", [
    (None, True),
    (CreatorRequestRejected("fixture challenge", {"http_status": 461, "verification_type": "209"}), False),
    (RuntimeError("fixture-secret-cookie"), False),
])
def test_endpoint_preserves_jobs_assets_cookies_and_task_history(tmp_path, failure, expected):
    from backend.app.models import AccountCookieVersion, PlatformAccount, PublishAsset, PublishJob, Task
    from tests.backend.test_api import _create_creator_account_with_cookie, _register_and_get_access_token, app, client
    dependency, token, account_id = _create_creator_account_with_cookie(tmp_path, "readonly-owner")
    calls = []
    class Adapter:
        def __init__(self, cookies):
            assert "creator-session" in cookies
        def inspect_session(self):
            calls.append("read")
            if failure is not None:
                raise failure
        def upload_media(self, *a):
            pytest.fail("must not upload")
        def post_note(self, *a):
            pytest.fail("must not submit")
    app.dependency_overrides[get_creator_session_adapter_factory] = lambda: Adapter
    try:
        other_token = _register_and_get_access_token("readonly-other")
        db = next(app.dependency_overrides[get_db]())
        try:
            job = PublishJob(user_id=1, platform="xhs", platform_account_id=account_id,
                title="fixture", body="fixture", status="failed", publish_error="HTTP 461, verifytype=209")
            db.add(job); db.flush()
            db.add(PublishAsset(publish_job_id=job.id, asset_type="image", file_path="fixture.png", upload_status="uploaded"))
            db.add(Task(user_id=1, platform="xhs", task_type="creator_publish", status="failed", payload={"publish_job_id": job.id}))
            db.commit()
            models = [AccountCookieVersion, PlatformAccount, PublishAsset, PublishJob, Task]
            def snapshot():
                return {m.__tablename__: [tuple(row) for row in db.execute(m.__table__.select()).all()] for m in models}
            before = snapshot()
            path = f"/api/accounts/{account_id}/check-publish-session"
            assert client.post(path).status_code == 401
            assert client.post(path, headers={"Authorization": f"Bearer {other_token}"}).status_code == 404
            assert calls == []
            response = client.post(path, headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 200
            assert response.json()["session_ok"] is expected
            assert response.json()["publish_permission"] == "not_tested"
            assert "fixture-secret-cookie" not in response.text
            assert calls == ["read"]
            db.expire_all()
            assert snapshot() == before
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_creator_session_adapter_factory, None)
        app.dependency_overrides.pop(dependency, None)


@pytest.mark.parametrize("failure,expected_status", [
    (None, "active"),
    (CreatorRequestRejected("fixture", {"http_status": 401}), "expired"),
    (CreatorRequestRejected("fixture", {"http_status": 461, "verification_type": "209"}), "unknown"),
    (RuntimeError("fixture network failure"), "unknown"),
])
def test_account_health_uses_installed_sdk_session_contract(tmp_path, failure, expected_status):
    from backend.app.api.accounts import get_creator_account_adapter, get_xhs_self_profile_adapter
    from tests.backend.test_api import _create_creator_account_with_cookie, app, client
    dependency, token, account_id = _create_creator_account_with_cookie(tmp_path, "creator-health-owner")
    class SessionAdapter:
        def __init__(self, cookies):
            pass
        def inspect_session(self):
            if failure is not None:
                raise failure
    app.dependency_overrides[get_creator_session_adapter_factory] = lambda: SessionAdapter
    app.dependency_overrides[get_creator_account_adapter] = lambda: SimpleNamespace(get_user_info=lambda cookies: {"external_user_id": "creator-user"})
    app.dependency_overrides[get_xhs_self_profile_adapter] = lambda: SimpleNamespace(get_self_profile=lambda cookies: {})
    try:
        response = client.post(f"/api/accounts/{account_id}/check", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200 and response.json()["status"] == expected_status
        assert "missing" not in response.json()["status_message"]
    finally:
        for key in (dependency, get_creator_session_adapter_factory, get_creator_account_adapter, get_xhs_self_profile_adapter):
            app.dependency_overrides.pop(key, None)
