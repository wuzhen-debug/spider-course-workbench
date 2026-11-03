"""Publish preparation checks; all HTTP is synthetic and no notes are sent."""
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.app.adapters.xhs.publish_validation import creator_title_length, validate_note_text
from backend.app.api.publish import (
    PublishJobUpdateRequest, _apply_publish_options, _update_publish_options,
    publish_job_to_creator,
)
from tests.backend.test_creator_lookup_responses import Response, fake_api


def image_note(**overrides):
    return {"title": "fixture", "desc": "fixture", "media_type": "image",
        "image_file_infos": [{"fileIds": "fixture-image", "width": 1080, "height": 1440}],
        "type": 0, "postTime": None, **overrides}


def mock_rap(monkeypatch):
    import xhs_utils.xhs_creator_util as util
    import xhs_utils.xhs_pc.params as params
    monkeypatch.setattr(util, "load_creator_rap_fingerprint_hex", lambda: "fixture")
    monkeypatch.setattr(params, "generate_x_rap_param", lambda *a, **kw: "fixture")


def topic_response(*names):
    return Response({"success": True, "data": {"topics": [
        {"topic_info_dto": {"id": f"fixture-{i}", "name": name, "link": "fixture-link"}}
        for i, name in enumerate(names)]}})


def test_title_count_matches_official_utf16_and_ascii_rules():
    assert creator_title_length("悉大线下Final难度大？考前7h突击思路拿捏了😭") == 23
    assert creator_title_length("悉大线下Final难度大？考前7h突击思路") == 18
    validate_note_text("a" * 40, "正文")
    validate_note_text("😭" * 10, "正文")
    assert creator_title_length("^" * 20) == 20
    with pytest.raises(ValueError, match="21"):
        validate_note_text("a" * 41, "正文")
    with pytest.raises(ValueError, match="1000"):
        validate_note_text("fixture", "😭" * 501)


def test_prepare_uses_same_named_topic_instead_of_first_fuzzy_result(monkeypatch):
    mock_rap(monkeypatch)
    adapter, calls = fake_api(monkeypatch, [topic_response("悉尼大学租房", "悉尼大学")])
    prepared = adapter.prepare_uploaded_image_note(adapter._api(), image_note(topics=["悉尼大学"]))
    data = json.loads(prepared.body)
    assert data["common"]["hash_tag"][0]["name"] == "悉尼大学"
    assert data["common"]["hash_tag"][0]["id"] == "fixture-1"
    assert len(calls) == 1 and "/search/topics" in calls[0]["url"]
    assert prepared.url == "https://edith.xiaohongshu.com/web_api/sns/v2/note"
    assert prepared.headers["x-rap-param"] == "fixture"
    assert data["common"]["privacy_info"] == {"op_type": 1, "type": 0, "user_ids": []}
    assert json.loads(data["common"]["business_binds"])["notePostTiming"] == {}
    assert "post_loc" not in data["common"]
    assert data["image_info"]["images"][0]["file_id"] == "spectrum/fixture-image"


def test_no_exact_topic_stops_before_publish(monkeypatch):
    mock_rap(monkeypatch)
    adapter, calls = fake_api(monkeypatch, [topic_response("悉尼大学租房")])
    with pytest.raises(RuntimeError, match="同名话题"):
        adapter.post_note(image_note(topics=["悉尼大学"]))
    assert len(calls) == 1 and "/search/topics" in calls[0]["url"]


def test_repeated_topics_and_existing_markers_are_not_appended_twice(monkeypatch):
    mock_rap(monkeypatch)
    adapter, calls = fake_api(monkeypatch, [topic_response("PastPaper")])
    prepared = adapter.prepare_uploaded_image_note(adapter._api(), image_note(
        desc="fixture #PastPaper[话题]#", topics=["PastPaper", "#pastpaper", " PastPaper "]))
    data = json.loads(prepared.body)
    assert len(calls) == 1
    assert len(data["common"]["hash_tag"]) == 1
    assert data["common"]["desc"].count("#PastPaper[话题]#") == 1


def test_final_body_overflow_after_topics_stops_before_publish(monkeypatch):
    mock_rap(monkeypatch)
    adapter, calls = fake_api(monkeypatch, [topic_response("悉尼大学")])
    with pytest.raises(ValueError, match="1000"):
        adapter.post_note(image_note(desc="文" * 995, topics=["悉尼大学"]))
    assert len(calls) == 1 and "/search/topics" in calls[0]["url"]


def test_overlong_title_is_rejected_before_login_or_upload(monkeypatch):
    import backend.app.api.publish as api
    job = SimpleNamespace(platform_account_id=2, status="failed", title="文" * 21, body="fixture")
    account = SimpleNamespace(user_id=1, platform="xhs", sub_type="creator")
    monkeypatch.setattr(api, "_get_owned_publish_job", lambda *a: job)
    def forbidden(*a):
        raise AssertionError("must validate before network/upload")
    with pytest.raises(HTTPException) as caught:
        publish_job_to_creator(4, SimpleNamespace(id=1), SimpleNamespace(get=lambda *a: account), forbidden)
    assert caught.value.status_code == 400 and "21" in caught.value.detail


def test_explicitly_cleared_topics_do_not_reappear_from_draft_tags():
    job = SimpleNamespace(publish_options=json.dumps({"draft_tags": [{"name": "悉尼大学"}]}))
    _update_publish_options(job, PublishJobUpdateRequest(topics=[]))
    options = json.loads(job.publish_options)
    assert options["topics"] == []
    note = {}
    _apply_publish_options(note, options)
    assert "topics" not in note
    inherited = {}
    _apply_publish_options(inherited, {"draft_tags": [{"name": "悉尼大学"}]})
    assert inherited["topics"] == ["悉尼大学"]
