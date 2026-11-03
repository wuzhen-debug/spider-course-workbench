from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile
import hashlib

import pytest

from backend.app.services.official_publish_package import build_official_package, OfficialPackageError, official_body


def sample_assets(root, count=13):
    media = root / "media"; media.mkdir(parents=True, exist_ok=True)
    result = []
    for i in range(count):
        path = media / f"xhs-asset-u1-fixture-{i}.png"
        path.write_bytes(f"synthetic image bytes {i}".encode())
        result.append(SimpleNamespace(asset_type="image", file_path=f"/api/files/media/{path.name}"))
    return result


def test_package_keeps_exact_bytes_order_and_copy_without_publishing(tmp_path):
    assets = sample_assets(tmp_path)
    original = [(tmp_path / "media" / Path(a.file_path).name).read_bytes() for a in assets]
    package = build_official_package(user_id=1, title="BISM1201 fixture", body="正文\n第二段\n",
        topics=["BISM1201", "#期末复习", "BISM1201"], assets=assets, storage_dir=tmp_path)
    with ZipFile(BytesIO(package)) as z:
        names = [n for n in z.namelist() if n.startswith("图片/")]
        assert names == [f"图片/{n:02d}.png" for n in range(1, 14)]
        assert [z.read(n) for n in names] == original
        assert z.read("文案.txt").decode() == "标题\nBISM1201 fixture\n\n正文（含话题）\n正文\n第二段\n\n#BISM1201 #期末复习\n"
        assert "不会发布或改变Spider任务状态" in z.read("使用说明.txt").decode()
        assert len(z.namelist()) == 15
    assert [(tmp_path / "media" / Path(a.file_path).name).read_bytes() for a in assets] == original


@pytest.mark.parametrize("path", ["/etc/passwd", "https://example.test/private.png", "/api/files/media/xhs-asset-u2-other.png",
    "/api/files/media/../private.png", "/api/files/media/xhs-asset-u1-fixture-0.png/../../private.png"])
def test_package_cannot_read_arbitrary_or_another_users_files(tmp_path, path):
    sample_assets(tmp_path, 1)
    with pytest.raises(OfficialPackageError):
        build_official_package(user_id=1, title="fixture", body="fixture", topics=[],
            assets=[SimpleNamespace(asset_type="image", file_path=path)], storage_dir=tmp_path)


def test_symlink_escape_is_rejected(tmp_path):
    media = tmp_path / "storage" / "media"; media.mkdir(parents=True)
    target = tmp_path / "private.png"; target.write_bytes(b"private")
    (media / "xhs-asset-u1-link.png").symlink_to(target)
    with pytest.raises(OfficialPackageError):
        build_official_package(user_id=1, title="fixture", body="fixture", topics=[],
            assets=[SimpleNamespace(asset_type="image", file_path="/api/files/media/xhs-asset-u1-link.png")], storage_dir=tmp_path / "storage")


@pytest.mark.parametrize("assets", [[], [SimpleNamespace(asset_type="video", file_path="/api/files/media/xhs-upload-u1-video.mp4")]])
def test_unsupported_empty_or_video_package_is_not_silently_incomplete(tmp_path, assets):
    with pytest.raises(OfficialPackageError):
        build_official_package(user_id=1, title="fixture", body="fixture", topics=[], assets=assets, storage_dir=tmp_path)


def test_authenticated_export_preserves_all_publish_data_and_never_calls_sdk(tmp_path, monkeypatch):
    import backend.app.api.publish as api
    from backend.app.core.database import get_db
    from backend.app.models import PublishAsset, PublishJob, AccountCookieVersion, PlatformAccount, Task
    from tests.backend.test_api import _create_creator_account_with_cookie, _register_and_get_access_token, app, client
    dependency, token, account_id = _create_creator_account_with_cookie(tmp_path, "official-package-owner")
    root = tmp_path / "storage"
    assets = sample_assets(root)
    monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(storage_dir=str(root)))
    def forbidden(*a):
        pytest.fail("export must not initialize SDK, upload or publish")
    app.dependency_overrides[api.get_creator_publish_adapter_factory] = lambda: forbidden
    headers = {"Authorization": f"Bearer {token}"}
    try:
        other = _register_and_get_access_token("official-package-other")
        draft = client.post("/api/drafts", headers=headers, json={"platform":"xhs","title":"fixture","body":"正文"}).json()
        job = client.post(f"/api/drafts/{draft['id']}/send-to-publish", headers=headers, json={"platform_account_id":account_id}).json()
        for a in assets:
            assert client.post(f"/api/publish/jobs/{job['id']}/assets", headers=headers,
                json={"asset_type":a.asset_type,"file_path":a.file_path}).status_code == 200
        db = next(app.dependency_overrides[get_db]())
        try:
            stored = db.get(PublishJob, job["id"]); stored.status="failed"; stored.publish_error="HTTP 461, verifytype=209"; db.commit()
            models = [PublishJob, PublishAsset, Task, PlatformAccount, AccountCookieVersion]
            def snapshot():
                return {m.__tablename__:[tuple(r) for r in db.execute(m.__table__.select()).all()] for m in models}
            before = snapshot()
            path=f"/api/publish/jobs/{job['id']}/official-package"
            assert client.post(path,json={}).status_code == 401
            assert client.post(path,json={},headers={"Authorization":f"Bearer {other}"}).status_code == 404
            response = client.post(path,json={"topics":["BISM1201","期末复习"]},headers=headers)
            assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
            assert response.headers["cache-control"] == "no-store"
            with ZipFile(BytesIO(response.content)) as z:
                assert len([n for n in z.namelist() if n.startswith("图片/")]) == 13
                assert "#BISM1201 #期末复习" in z.read("文案.txt").decode()
                assert all("creator-session" not in z.read(n).decode(errors="ignore") for n in z.namelist())
            db.expire_all()
            assert snapshot() == before
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(api.get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(dependency, None)
