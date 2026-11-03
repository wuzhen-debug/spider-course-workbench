"""HTTP 461 handling with synthetic responses only; never publish remotely."""
import json

import pytest

from backend.app.adapters.xhs.creator_api_adapter import CreatorRequestRejected, XhsCreatorApiAdapter
from tests.backend.test_creator_lookup_responses import Response, fake_api, mock_image_payload


def challenge_response(payload=None, *, headers=None, status=461):
    response = Response(payload if payload is not None else {"success": True, "code": 0, "msg": "成功", "data": {}}, status)
    response.headers = headers or {}
    return response


def test_http_461_overrides_success_true_and_zero_code():
    response = challenge_response()
    ok, message, payload = XhsCreatorApiAdapter._parse_creator_response(response, "笔记发布")
    assert not ok and "安全验证" in message and "HTTP 461" in message and "code=0" in message
    assert "成功" not in message and payload["success"] is True


@pytest.mark.parametrize("verify_type,expected", [("124", "安全验证"), ("209", "安全验证"), ("301", "重新登录"), ("302", "刷新页面")])
def test_verification_headers_are_case_insensitive_and_explain_platform_action(verify_type, expected):
    response = challenge_response(headers={"VerifyType": verify_type, "RiskUuid": "opaque-fixture", "ResultPolicy": "400"})
    ok, message, _ = XhsCreatorApiAdapter._parse_creator_response(response, "笔记发布")
    assert not ok and expected in message and f"verifytype={verify_type}" in message
    diagnostics = XhsCreatorApiAdapter._response_diagnostics(response, response.json())
    assert diagnostics["verification_type"] == verify_type and diagnostics["result_policy"] == "400"
    assert diagnostics["verification_id_present"] is True
    assert "opaque-fixture" not in json.dumps(diagnostics)


def test_diagnostics_allowlist_excludes_cookie_ids_and_untrusted_values():
    response = challenge_response(headers={"Set-Cookie": "secret-fixture", "Authorization": "secret-fixture",
        "VerifyType": "secret-fixture", "VerifyUuid": "opaque-fixture", "VerifyMsg": "secret-fixture"})
    diagnostics = XhsCreatorApiAdapter._response_diagnostics(response, response.json())
    assert "verification_type" not in diagnostics
    assert "secret-fixture" not in json.dumps(diagnostics) and "opaque-fixture" not in json.dumps(diagnostics)
    assert diagnostics["verification_id_present"] is True


@pytest.mark.parametrize("payload", [ValueError("invalid JSON"), ["unexpected"]])
def test_non_json_challenge_is_still_classified_from_http_status(payload):
    ok, message, returned = XhsCreatorApiAdapter._parse_creator_response(challenge_response(payload), "笔记发布")
    assert not ok and "安全验证" in message and returned == {}


def test_fixture_publish_challenge_is_not_retried_and_keeps_safe_diagnostics(monkeypatch):
    mock_image_payload(monkeypatch)
    adapter, calls = fake_api(monkeypatch, [challenge_response(headers={"VerifyType": "124"})])
    with pytest.raises(CreatorRequestRejected) as caught:
        adapter.post_note({"title": "fixture", "media_type": "image", "image_file_infos": [{}]})
    assert len(calls) == 1 and calls[0]["url"].endswith("/web_api/sns/v2/note")
    assert caught.value.diagnostics["http_status"] == 461
    assert caught.value.diagnostics["automatic_retry"] is False


def test_api_retains_sanitized_response_diagnostics_without_marking_published(tmp_path):
    from backend.app.api.publish import get_creator_publish_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.models import PublishJob, Task
    from tests.backend.test_api import _create_creator_account_with_cookie, app, client

    diagnostics = {"http_status": 461, "kind": "security_verification", "verification_type": "124", "automatic_retry": False}
    class FakeAdapter:
        def __init__(self, cookies):
            pass
        def upload_media(self, *args):
            return {"fileIds": "fixture-image", "width": 1080, "height": 1440}
        def post_note(self, note):
            raise CreatorRequestRejected("平台安全验证（HTTP 461）", diagnostics)

    dependency, token, account_id = _create_creator_account_with_cookie(tmp_path, "security-response-owner")
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: FakeAdapter
    headers = {"Authorization": f"Bearer {token}"}
    try:
        draft = client.post("/api/drafts", headers=headers, json={"platform": "xhs", "title": "fixture", "body": "fixture"}).json()
        job = client.post(f"/api/drafts/{draft['id']}/send-to-publish", headers=headers, json={"platform_account_id": account_id}).json()
        client.post(f"/api/publish/jobs/{job['id']}/assets", headers=headers, json={"asset_type": "image", "file_path": "fixture.png"})
        response = client.post(f"/api/publish/jobs/{job['id']}/publish", headers=headers)
        assert response.status_code == 502 and "461" in response.json()["detail"]
        db = next(app.dependency_overrides[get_db]())
        try:
            stored = db.get(PublishJob, job["id"])
            assert stored.status == "failed" and not stored.external_note_id
            task = db.query(Task).filter(Task.task_type == "creator_publish").one()
            assert task.payload["creator_response_diagnostics"] == diagnostics
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(dependency, None)
