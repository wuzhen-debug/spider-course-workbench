"""Creator session exchange follows the installed SDK Auth contract."""
from types import SimpleNamespace

import pytest

from backend.app.adapters.xhs.creator_login_adapter import XhsCreatorLoginAdapter
from backend.app.adapters.xhs.creator_api_adapter import CreatorRequestRejected
from tests.backend.test_creator_lookup_responses import Response, fake_api, mock_image_payload


def test_exchange_uses_coherent_pc_auth_and_keeps_shared_and_creator_cookies(monkeypatch):
    from xhs_utils.xhs_pc.auth import XHSPcAuth
    from xhs_utils.xhs_creator.auth import XHSCreatorAuth
    closed = []
    source = {"a1": "fixture-a1", "web_session": "fixture-web-session", "id_token": "fixture-id-token"}
    pc = SimpleNamespace(close=lambda: closed.append("pc"))
    complete = {**source, "customer-sso-sid": "fixture-creator-session", "acw_tc": "fixture-host-cookie"}
    creator = SimpleNamespace(close=lambda: closed.append("creator"), origin=lambda key: "https://creator.xiaohongshu.com",
        cookies_for_url=lambda url: complete)
    def from_cookie(cls, cookies):
        assert cookies == source and cookies is not source
        return pc
    def from_pc_auth(cls, auth):
        assert auth is pc
        return creator
    monkeypatch.setattr(XHSPcAuth, "from_cookie", classmethod(from_cookie))
    monkeypatch.setattr(XHSCreatorAuth, "from_pc_auth", classmethod(from_pc_auth))
    result = XhsCreatorLoginAdapter().exchange_from_user_cookies(source)
    assert result == {"status": "confirmed", "cookies": complete}
    assert closed == ["creator", "pc"]


def test_exchange_closes_pc_auth_when_creator_exchange_fails(monkeypatch):
    from xhs_utils.xhs_pc.auth import XHSPcAuth
    from xhs_utils.xhs_creator.auth import XHSCreatorAuth
    closed = []
    pc = SimpleNamespace(close=lambda: closed.append("pc"))
    monkeypatch.setattr(XHSPcAuth, "from_cookie", classmethod(lambda cls, cookies: pc))
    def fail(cls, auth):
        raise RuntimeError("fixture challenge")
    monkeypatch.setattr(XHSCreatorAuth, "from_pc_auth", classmethod(fail))
    with pytest.raises(RuntimeError, match="fixture challenge"):
        XhsCreatorLoginAdapter().exchange_from_user_cookies({"a1": "fixture"})
    assert closed == ["pc"]


@pytest.mark.parametrize('accepted', [True, False])
def test_persisted_profile_uses_initialized_business_auth_not_new_login_context(monkeypatch, accepted):
    from xhs_utils.xhs_creator import XHSCreatorAuth
    import apis.xhs_creator_apis as business
    import apis.xhs_creator_login_apis as login
    from backend.app.adapters.xhs.login_errors import XhsLoginError
    closed = []
    source = {'a1': 'fixture', 'web_session': 'issued-session'}
    updated = {**source, 'acw_tc': 'server-cookie'}
    auth = SimpleNamespace(close=lambda: closed.append(True),
        origin=lambda key: 'https://creator.xiaohongshu.com', cookies_for_url=lambda url: updated)
    def from_cookie(cls, cookies):
        assert cookies == source
        return auth
    monkeypatch.setattr(XHSCreatorAuth, 'from_cookie', classmethod(from_cookie))
    def forbidden_login():
        pytest.fail('Persisted login must not start a fresh QR/SMS signing context')
    monkeypatch.setattr(login, 'XHSCreatorLoginApi', forbidden_login)
    monkeypatch.setattr(business, 'XHS_Creator_Apis', lambda actual: SimpleNamespace(
        get_user_info=lambda: (accepted, '', {'data': {'userId': 'same-user', 'userName': 'Fixture'}})))
    if accepted:
        assert XhsCreatorLoginAdapter().get_user_info(source)['external_user_id'] == 'same-user'
        assert source == updated
    else:
        with pytest.raises(XhsLoginError):
            XhsCreatorLoginAdapter().get_user_info(source)
        assert source == {'a1': 'fixture', 'web_session': 'issued-session'}
    assert closed == [True]


def test_identity_read_keeps_host_cookies_without_requiring_real_name_status(monkeypatch):
    adapter, posts = fake_api(monkeypatch, [])
    api = adapter._api()
    updates = []
    api.auth = SimpleNamespace(update_cookies=lambda cookies, **kw: updates.append((cookies, kw)))
    response = Response({"success": True, "code": 0, "data": {"verified": False}})
    response.cookies = {"acw_tc": "fixture-edith-cookie"}
    api.http.get = lambda *a, **kw: response
    returned = adapter.check_publish_session(api)
    assert returned["data"]["verified"] is False
    assert updates == [({"acw_tc": "fixture-edith-cookie"}, {"source_url": "https://edith.xiaohongshu.com/web_api/sns/v6/creator/user/verify"})]
    assert posts == []


def test_invalid_cross_site_session_stops_before_final_note_request(monkeypatch):
    mock_image_payload(monkeypatch)
    adapter, posts = fake_api(monkeypatch, [])
    api = adapter._api()
    api.http.get = lambda *a, **kw: Response({"success": False, "code": -100}, 401)
    with pytest.raises(CreatorRequestRejected, match="跨站登录信息"):
        adapter.post_note({"title": "fixture", "media_type": "image", "image_file_infos": [{}]})
    assert posts == []
