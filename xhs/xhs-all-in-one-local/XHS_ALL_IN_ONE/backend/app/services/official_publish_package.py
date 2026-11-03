"""Local handoff to the official editor; never calls a platform API."""
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


class OfficialPackageError(ValueError):
    pass


def official_body(body: str, topics: list[str]) -> str:
    tags = list(dict.fromkeys(t.strip().lstrip("#").strip() for t in topics if t.strip().lstrip("#").strip()))
    return body.rstrip() + ("\n\n" + " ".join(f"#{t}" for t in tags) if tags else "")


def build_official_package(*, user_id: int, title: str, body: str, topics: list[str], assets, storage_dir: Path) -> bytes:
    if not assets:
        raise OfficialPackageError("没有可导出的图片，请先添加素材。")
    media_root = (storage_dir / "media").resolve()
    prefixes = (f"xhs-image-u{user_id}-", f"xhs-asset-u{user_id}-", f"xhs-upload-u{user_id}-")
    sources = []
    size = 0
    for asset in assets:
        if asset.asset_type != "image" or not asset.file_path.startswith("/api/files/media/"):
            raise OfficialPackageError("此准备包支持草稿中已保存的图片；请先将其他素材添加到草稿。")
        name = asset.file_path.removeprefix("/api/files/media/")
        if Path(name).name != name or ".." in name or "\x00" in name or not name.startswith(prefixes):
            raise OfficialPackageError("素材不属于当前账号或路径无效，未生成准备包。")
        path = (media_root / name).resolve()
        if not path.is_relative_to(media_root) or not path.name.startswith(prefixes) or not path.is_file():
            raise OfficialPackageError("有图片文件已不可用，请在草稿中核对素材。")
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            raise OfficialPackageError("素材格式不支持导出为图文图片。")
        size += path.stat().st_size
        if size > 200 * 1024 * 1024:
            raise OfficialPackageError("图片合计超过200MB，请分批整理后再导出。")
        sources.append(path)
    text = f"标题\n{title}\n\n正文（含话题）\n{official_body(body, topics)}\n"
    instructions = (
        "1. 解压后，按图片文件名顺序在官方创作中心上传全部图片。\n"
        "2. 复制标题和正文，在官方页面核对话题、图片顺序及发布账号。\n"
        "3. 最后由你在官方页面确认发布。下载此包不会发布或改变Spider任务状态。\n"
        "官方页面：https://creator.xiaohongshu.com/publish/publish\n"
    )
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=1) as package:
        package.writestr("文案.txt", text)
        package.writestr("使用说明.txt", instructions)
        for index, path in enumerate(sources, 1):
            package.write(path, f"图片/{index:02d}{path.suffix.lower()}")
    return output.getvalue()
