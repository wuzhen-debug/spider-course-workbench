"""Synthetic pipeline tests. No uploads, notes or credentials leave this test."""
from contextlib import contextmanager
from types import SimpleNamespace
import json

import pytest

from backend.app.adapters.xhs.creator_api_adapter import CreatorRequestRejected
from tests.backend.test_creator_lookup_responses import Response, fake_api, mock_image_payload


@pytest.mark.parametrize("challenge", [False, True])
def test_one_sdk_session_retains_upload_cookies_until_submit_and_closes(monkeypatch, challenge):
    mock_image_payload(monkeypatch)
    payload = {"success": True, "code": 0, "data": {"note_id": "fixture-note"}}
    response = Response(payload, 461 if challenge else 200)
    response.headers = {"verifytype": "209"} if challenge else {}
    adapter, calls = fake_api(monkeypatch, [response])
    api = adapter._api()
    constructed, closed = [], []
    jar = {}
    api.auth = SimpleNamespace(close=lambda: closed.append(True), update_cookies=lambda cookies, **kw: jar.update(cookies))
    def make_api():
        constructed.append(True)
        return api
    monkeypatch.setattr(adapter, "_api", make_api)
    monkeypatch.setattr(adapter, "_resolve_file_data", lambda path: b"fixture")
    def upload(*a):
        jar["refreshed-host-cookie"] = "server-issued-fixture"
        return True, "ok", {"fileIds": "fixture-id", "width": 1080, "height": 1440}
    api.upload_media = upload
    api._request_params = lambda path, data, method, **kwargs: ({}, dict(jar), json.dumps(data))
    original_post = api.http.post
    def post(url, **kwargs):
        assert kwargs["cookies"]["refreshed-host-cookie"] == "server-issued-fixture"
        assert not closed
        return original_post(url, **kwargs)
    api.http.post = post
    with adapter.session():
        uploaded = adapter.upload_media("fixture.png", "image")
        with adapter.session():  # nested calls borrow rather than close the owner
            adapter.inspect_session()
        assert not closed
        note = {"title": "fixture", "desc": "fixture", "media_type": "image", "image_file_infos": [uploaded]}
        if challenge:
            with pytest.raises(CreatorRequestRejected):
                adapter.post_note(note)
        else:
            assert adapter.post_note(note) == payload
        assert not closed
    assert len(constructed) == 1 and closed == [True]
    assert len(calls) == 1  # including on 461: no automatic retry
    assert adapter._session_api is None


def test_standalone_upload_also_releases_the_http_client(monkeypatch):
    adapter, calls = fake_api(monkeypatch, [])
    api = adapter._api()
    closed = []
    api.auth = SimpleNamespace(close=lambda: closed.append(True))
    api.upload_media = lambda *a: (False, "fixture failure", {})
    monkeypatch.setattr(adapter, "_resolve_file_data", lambda path: b"fixture")
    with pytest.raises(RuntimeError, match="fixture failure"):
        adapter.upload_media("fixture.png", "image")
    assert closed == [True] and calls == []


@pytest.mark.parametrize("challenge", [False, True])
def test_publish_route_reuses_the_adapter_and_session_for_all_assets(tmp_path, challenge):
    from backend.app.api.publish import get_creator_publish_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.models import PublishJob
    from tests.backend.test_api import _create_creator_account_with_cookie, app, client
    dependency, token, account_id = _create_creator_account_with_cookie(tmp_path, "session-pipeline-owner")
    instances, events = [], []
    class Adapter:
        def __init__(self, cookies):
            self.active = False
            self.uploaded = []
            instances.append(self)
        @contextmanager
        def session(self):
            self.active = True; events.append("open")
            try:
                yield self
            finally:
                self.active = False; events.append("close")
        def upload_media(self, path, kind):
            assert self.active
            self.uploaded.append(path)
            return {"fileIds": path, "width": 1080, "height": 1440}
        def post_note(self, note):
            assert self.active and self.uploaded == ["fixture-1.png", "fixture-2.png"]
            assert len(note["image_file_infos"]) == 2
            events.append("submit-fixture")
            if challenge:
                raise CreatorRequestRejected("fixture HTTP 461", {"http_status": 461, "verification_type": "209"})
            return {"success": True, "data": {"note_id": "fixture-note"}}
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: Adapter
    headers = {"Authorization": f"Bearer {token}"}
    try:
        draft = client.post("/api/drafts", headers=headers, json={"platform": "xhs", "title": "fixture", "body": "fixture"}).json()
        job = client.post(f"/api/drafts/{draft['id']}/send-to-publish", headers=headers, json={"platform_account_id": account_id}).json()
        for name in ("fixture-1.png", "fixture-2.png"):
            assert client.post(f"/api/publish/jobs/{job['id']}/assets", headers=headers,
                json={"asset_type": "image", "file_path": name}).status_code == 200
        response = client.post(f"/api/publish/jobs/{job['id']}/publish", headers=headers)
        assert response.status_code == (502 if challenge else 200)
        assert len(instances) == 1 and events == ["open", "submit-fixture", "close"]
        db = next(app.dependency_overrides[get_db]())
        try:
            stored = db.get(PublishJob, job["id"])
            assert stored.status == ("failed" if challenge else "published")
            assert stored.external_note_id == ("" if challenge else "fixture-note")
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(dependency, None)
