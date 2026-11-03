"""Creator response compatibility; all HTTP and publish responses are fixtures."""
import json
from types import SimpleNamespace

import pytest

from backend.app.adapters.xhs.creator_api_adapter import XhsCreatorApiAdapter


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def fake_api(monkeypatch, responses):
    from apis.xhs_creator_apis import XHS_Creator_Apis
    import apis.xhs_creator_apis as sdk

    calls = []
    def post(url, **kwargs):
        calls.append({"url": url, "body": json.loads(kwargs["data"])})
        return responses.pop(0)
    api = XHS_Creator_Apis.__new__(XHS_Creator_Apis)
    api.edith_url = "https://edith.xiaohongshu.com"
    api.base_url = "https://creator.xiaohongshu.com"
    api._proxies = lambda value=None: None
    api.fixture_get_calls = []
    def get(url, **kwargs):
        api.fixture_get_calls.append(url)
        return Response({"success": True, "code": 0, "data": {"verified": False}})
    api.http = SimpleNamespace(post=post, get=get)
    api._request_params = lambda path, data, method, **kwargs: ({}, {}, json.dumps(data))
    monkeypatch.setattr(sdk, "_log_api_error", lambda exc: str(exc))
    adapter = XhsCreatorApiAdapter("synthetic fixture only")
    monkeypatch.setattr(adapter, "_api", lambda: api)
    return adapter, calls


def test_topic_success_without_msg_preserves_results(monkeypatch):
    topic = {"id": "fixture-topic", "name": "fixture"}
    payload = {"success": True, "data": {"topics": [{"topic_info_dto": topic}]}}
    adapter, calls = fake_api(monkeypatch, [Response(payload)])
    success, message, returned = adapter.get_topic("fixture")
    assert success is True
    assert returned["data"]["topic_info_dtos"] == [topic]
    assert returned["data"]["topics"] == payload["data"]["topics"]
    assert len(calls) == 1
    assert calls[0]["url"] == "https://creator.xiaohongshu.com/api/galaxy/v2/creator/servicegw/v2/search/topics"
    assert set(calls[0]["body"]) == {"keyword", "topic_round_start_time", "content"}
    assert calls[0]["body"]["content"] == ""


def test_topic_rejection_without_msg_exposes_http_and_platform_code(monkeypatch):
    adapter, calls = fake_api(monkeypatch, [Response({"success": False, "code": -1}, 406)])
    success, message, payload = adapter.get_topic("fixture")
    assert success is False
    assert "406" in message and "-1" in message and "话题" in message
    assert payload == {"success": False, "code": -1}
    assert len(calls) == 1


def mock_image_payload(monkeypatch):
    import xhs_utils.xhs_creator_util as util
    import xhs_utils.xhs_pc.params as params
    monkeypatch.setattr(util, "get_post_note_image_data", lambda *args: {"common": {"desc": "fixture", "hash_tag": [], "post_loc": {}}})
    monkeypatch.setattr(util, "load_creator_rap_fingerprint_hex", lambda: "fixture")
    monkeypatch.setattr(params, "generate_x_rap_param", lambda *args, **kwargs: "fixture")


def test_image_publish_stops_before_note_request_when_topic_is_rejected(monkeypatch):
    mock_image_payload(monkeypatch)
    adapter, calls = fake_api(monkeypatch, [Response({"success": False, "code": -1}, 406)])
    with pytest.raises(RuntimeError, match="406"):
        adapter.post_note({"title": "fixture", "media_type": "image", "image_file_infos": [{}], "topics": ["fixture"]})
    assert [c["url"] for c in calls] == ["https://creator.xiaohongshu.com/api/galaxy/v2/creator/servicegw/v2/search/topics"]


def test_image_publish_fixture_succeeds_without_optional_msg(monkeypatch):
    mock_image_payload(monkeypatch)
    topic = {"success": True, "data": {"topics": [{"topic_info_dto": {"id": "fixture-id", "name": "fixture"}}]}}
    published = {"success": True, "data": {"note_id": "fixture-note"}}
    adapter, calls = fake_api(monkeypatch, [Response(topic), Response(published)])
    assert adapter.post_note({"title": "fixture", "media_type": "image", "image_file_infos": [{}], "topics": ["fixture"]}) == published
    assert len(calls) == 2
    assert calls[1]["body"]["common"]["hash_tag"][0]["id"] == "fixture-id"


@pytest.mark.parametrize("response", [Response(["unexpected"]), Response(ValueError("invalid JSON")), Response({"success": True}, 406)])
def test_lookup_does_not_treat_invalid_or_http_rejected_response_as_success(monkeypatch, response):
    adapter, _ = fake_api(monkeypatch, [response])
    success, message, _ = adapter.get_topic("fixture")
    assert success is False and message and message != "'msg'"


def test_location_success_without_msg(monkeypatch):
    payload = {"success": True, "data": {"poi_list": []}}
    adapter, calls = fake_api(monkeypatch, [Response(payload)])
    success, _, returned = adapter.get_location_info("fixture")
    assert success is True and returned == payload
    assert calls[0]["url"].endswith("/web_api/sns/v1/local/poi/creator/search")


def test_topic_normalization_skips_invalid_candidates(monkeypatch):
    payload = {"success": True, "data": {"topics": [None, {"topic_info_dto": {}},
        {"topic_info_dto": {"id": "fixture-id", "name": "fixture", "link": "fixture-link"}}]}}
    adapter, _ = fake_api(monkeypatch, [Response(payload)])
    success, _, returned = adapter.get_topic("fixture")
    assert success is True
    assert returned["data"]["topic_info_dtos"] == [{"id": "fixture-id", "name": "fixture", "link": "fixture-link"}]
