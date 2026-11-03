"""All challenges are synthetic. Never contact XHS or publish a real note."""
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from backend.app.adapters.xhs.creator_api_adapter import CreatorRequestRejected
from backend.app.services import creator_verification as service
from tests.backend.test_creator_lookup_responses import fake_api, mock_image_payload
from tests.backend.test_creator_security_response import challenge_response


DIAGNOSTICS = {"http_status": 461, "verification_type": "209", "automatic_retry": False}
UUID = "server-issued-fixture-12345678"


def context():
    return service.capture_verification(challenge_response(headers={"VerifyType": "209", "VerifyUuid": UUID, "X-Biz": "ugc"}))


def test_only_server_issued_209_context_is_retained_separately_from_logs(monkeypatch):
    mock_image_payload(monkeypatch)
    adapter, calls = fake_api(monkeypatch, [challenge_response(headers={"VerifyType": "209", "VerifyUuid": UUID})])
    with pytest.raises(CreatorRequestRejected) as caught:
        adapter.post_note({"title": "fixture", "media_type": "image", "image_file_infos": [{}]})
    error = caught.value
    assert "扫码" in str(error) and "正常登录不等于" in str(error)
    assert UUID not in str(error) and UUID not in repr(error) and UUID not in json.dumps(error.diagnostics)
    assert error.verification["verify_uuid"] == UUID
    assert len(calls) == 1  # Never retries the rejected note.


@pytest.mark.parametrize("headers,status", [({}, 461), ({"verifytype": "209"}, 461),
    ({"verifytype": "124", "verifyuuid": UUID}, 461), ({"verifytype": "209", "verifyuuid": UUID}, 200),
    ({"verifytype": "209", "verifyuuid": "bad\nheader"}, 461)])
def test_missing_invalid_or_unrequested_challenge_is_not_fabricated(headers, status):
    assert service.capture_verification(challenge_response(headers=headers, status=status)) is None


def bound_task():
    encrypted = service.seal_verification(context(), user_id=1, job_id=2, account_id=3, task_id=4)
    assert UUID not in encrypted
    task = SimpleNamespace(id=4, payload={"creator_response_diagnostics": DIAGNOSTICS, service.PRIVATE_CONTEXT_KEY: encrypted})
    job = SimpleNamespace(id=2, user_id=1, platform_account_id=3)
    return task, job


def test_official_route_uses_original_challenge_and_fixed_return_only():
    task, job = bound_task()
    result = service.verification_handoff(task, job)
    parsed = urlparse(result["official_url"])
    assert parsed.scheme == "https" and parsed.netloc == "www.xiaohongshu.com" and parsed.path == "/web-login/captcha"
    params = parse_qs(parsed.query)
    assert params["verifyUuid"] == [UUID] and params["verifyType"] == ["209"]
    assert params["verifyBiz"] == ["461"] and params["biz"] == ["ugc"]
    assert params["redirectPath"] == [service.OFFICIAL_RETURN]
    assert "Cookie" not in parsed.query and not result["will_publish"] and not result["automatic_retry"]


@pytest.mark.parametrize("field", ["id", "user_id", "platform_account_id"])
def test_private_context_cannot_be_reused_by_another_job_owner_or_account(field):
    task, job = bound_task()
    setattr(job, field, 99)
    result = service.verification_handoff(task, job)
    assert result["state"] == "unavailable" and result["official_url"] is None


def test_expired_or_tampered_context_is_not_a_valid_handoff(monkeypatch):
    task, job = bound_task()
    now = service.time.time()
    monkeypatch.setattr(service.time, "time", lambda: now + 901)
    expired = service.verification_handoff(task, job)
    assert expired["state"] == "expired" and expired["official_url"] is None
    task.payload[service.PRIVATE_CONTEXT_KEY] = "tampered"
    assert service.verification_handoff(task, job)["state"] == "unavailable"


def test_legacy_record_does_not_invent_request_uuid_or_claim_recovered():
    task = SimpleNamespace(id=4, payload={"creator_response_diagnostics": DIAGNOSTICS})
    job = SimpleNamespace(id=2, user_id=1, platform_account_id=3)
    result = service.verification_handoff(task, job)
    assert result["state"] == "legacy_missing" and "无法还原" in result["message"]
    assert result["official_url"] is None


def test_authenticated_handoff_is_read_only_and_task_serializers_do_not_leak_private_context(tmp_path):
    from backend.app.api.publish import get_creator_publish_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.models import Task, PublishJob
    from tests.backend.test_api import _create_creator_account_with_cookie, _register_and_get_access_token, app, client

    class Adapter:
        calls = 0
        def __init__(self, cookies): pass
        def upload_media(self, *a): return {"fileIds": "fixture", "width": 1080, "height": 1440}
        def post_note(self, note):
            Adapter.calls += 1
            raise CreatorRequestRejected("需要扫码安全验证（HTTP 461，verifytype=209）", DIAGNOSTICS, verification=context())

    dependency, token, account_id = _create_creator_account_with_cookie(tmp_path, "verification-owner")
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: Adapter
    headers = {"Authorization": f"Bearer {token}"}
    try:
        other = _register_and_get_access_token("verification-other")
        draft = client.post("/api/drafts", headers=headers, json={"platform":"xhs", "title":"fixture", "body":"fixture"}).json()
        job = client.post(f"/api/drafts/{draft['id']}/send-to-publish", headers=headers, json={"platform_account_id": account_id}).json()
        client.post(f"/api/publish/jobs/{job['id']}/assets", headers=headers, json={"asset_type":"image", "file_path":"fixture.png"})
        assert client.post(f"/api/publish/jobs/{job['id']}/publish", headers=headers).status_code == 502
        path = f"/api/publish/jobs/{job['id']}/verification"
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization":f"Bearer {other}"}).status_code == 404
        db = next(app.dependency_overrides[get_db]())
        try:
            def snapshot():
                return {name:[tuple(r) for r in db.execute(table.select()).all()] for name,table in Task.metadata.tables.items()}
            before = snapshot()
            response = client.get(path, headers=headers)
            assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
            assert response.json()["state"] == "available" and UUID in response.json()["official_url"]
            task = db.query(Task).filter(Task.task_type == "creator_publish").one()
            assert UUID not in json.dumps(task.payload) and service.PRIVATE_CONTEXT_KEY in task.payload
            for payload in [client.get(f"/api/tasks/{task.id}", headers=headers).json(), client.get("/api/tasks", headers=headers).json()]:
                assert UUID not in json.dumps(payload) and service.PRIVATE_CONTEXT_KEY not in json.dumps(payload)
            assert client.get(f"/api/publish/jobs/{job['id']}", headers=headers).json()["status"] == "failed"
            db.expire_all()
            assert snapshot() == before and Adapter.calls == 1
            acknowledge = path + "/acknowledge"
            assert client.post(acknowledge, headers={"Authorization":f"Bearer {other}"}, json={"task_id":task.id}).status_code == 404
            assert client.post(acknowledge, headers=headers, json={"task_id":task.id + 1}).status_code == 409
            confirmed = client.post(acknowledge, headers=headers, json={"task_id":task.id})
            assert confirmed.status_code == 200 and confirmed.json()["state"] == "reported_verified"
            assert confirmed.json()["official_url"] is None and confirmed.json()["will_publish"] is False
            assert client.get(path, headers=headers).json()["state"] == "reported_verified"
            db.expire_all()
            assert db.get(PublishJob, job["id"]).status == "failed" and Adapter.calls == 1
            assert db.get(Task, task.id).payload["creator_verification_user_confirmation"]["source"] == "user_report"
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(dependency, None)
