"""Local course/material registration. No SDK, AI or scheduler execution."""
from __future__ import annotations

from datetime import date
import hashlib
import re
import unicodedata
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import AiDraft, Note, PublishJob, User
from backend.app.models.course_center import CourseOffering, CourseMaterialProduct, CourseMaterialVersion, CourseAsset, CourseDemoContent, CourseContentLink
from backend.app.schemas.common import paginated

router = APIRouter(prefix="/course-center", tags=["course-center"])


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CourseInput(InputModel):
    university: str = Field(min_length=1, max_length=180)
    course_code: str = Field(min_length=1, max_length=40)
    course_name: str = Field(min_length=1, max_length=240)
    term: str = Field(min_length=1, max_length=40)
    language: str = Field(default="中英双语", min_length=1, max_length=40)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    exam_date: date | None = None
    source_reference: str = Field(default="", max_length=2000)
    priority: Literal["high", "normal", "low"] = "normal"
    notes: str = Field(default="", max_length=5000)
    is_demo: bool = True

    @field_validator("aliases")
    @classmethod
    def clean_aliases(cls, value):
        result = list(dict.fromkeys(v.strip() for v in value if v.strip()))
        if any(len(v) > 100 for v in result):
            raise ValueError("课程别名最多 100 字")
        return result


class ProductInput(InputModel):
    title: str = Field(min_length=1, max_length=240)
    material_type: str = Field(min_length=1, max_length=80)
    coverage: str = Field(default="", max_length=5000)
    owner: str = Field(default="", max_length=120)
    listing_status: Literal["not_listed", "listed", "retired"] = "not_listed"
    notes: str = Field(default="", max_length=5000)


class VersionInput(InputModel):
    version: str = Field(min_length=1, max_length=60)
    language: str = Field(default="中英双语", min_length=1, max_length=40)
    source_reference: str = Field(default="", max_length=2000)
    sha256: str = Field(default="", pattern=r"^(|[a-fA-F0-9]{64})$")
    qa_status: Literal["pending", "passed", "changes_required"] = "pending"
    notes: str = Field(default="", max_length=5000)


class AssetInput(InputModel):
    title: str = Field(min_length=1, max_length=180)
    asset_kind: Literal["sample", "brand_logo"] = "sample"
    version_id: int | None = Field(default=None, gt=0)
    reference: str = Field(default="", max_length=2000)
    source_notes: str = Field(default="", max_length=5000)
    page_reference: str = Field(default="", max_length=80)
    watermarked: bool = False
    rights_confirmed: bool = False
    usage_status: Literal["pending", "approved", "not_allowed"] = "pending"


class LinkInput(InputModel):
    target_kind: Literal["note", "draft", "publish_job"]
    target_id: int = Field(gt=0)
    target_is_demo: bool = True
    version_id: int | None = Field(default=None, gt=0)
    notes: str = Field(default="", max_length=2000)


class ArchiveInput(InputModel):
    archived: bool


def require_enabled():
    settings = get_settings()
    if not settings.course_center_enabled:
        raise HTTPException(404, "课程与资料中心未启用")
    return settings


def _owned(db, model, record_id, user):
    row = db.get(model, record_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "记录不存在")
    return row


def _course_for(db, record, user):
    if isinstance(record, CourseOffering):
        return record
    if isinstance(record, CourseMaterialVersion):
        product = _owned(db, CourseMaterialProduct, record.product_id, user)
        return _owned(db, CourseOffering, product.course_id, user)
    return _owned(db, CourseOffering, record.course_id, user)


def _write_allowed(course):
    if get_settings().course_center_demo_only and not course.is_demo:
        raise HTTPException(403, "当前仅开放演示数据登记")


def _commit(db):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "同一大学、课程和学期，或同一产品的资料版本已经存在") from exc


def _row(record):
    result = {}
    for column in record.__table__.columns:
        if column.name in {"user_id", "seed_key", "university_key", "code_key", "term_key", "aliases_search"}:
            continue
        value = getattr(record, column.name)
        result[column.name] = value.isoformat() if hasattr(value, "isoformat") else value
    return result


def _identity(payload):
    value = payload.model_dump()
    value["course_code"] = re.sub(r"\s+", "", unicodedata.normalize("NFKC", value["course_code"])).upper()
    value["term"] = re.sub(r"\s+", "", unicodedata.normalize("NFKC", value["term"])).upper()
    value["university_key"] = unicodedata.normalize("NFKC", value["university"]).casefold().strip()
    value["code_key"] = value["course_code"]
    value["term_key"] = value["term"]
    value["aliases_search"] = "\n".join(value["aliases"]).casefold()
    value["exam_date"] = payload.exam_date.isoformat() if payload.exam_date else None
    return value


def _course_summary(db, course):
    result = _row(course)
    result["product_count"] = db.scalar(select(func.count()).select_from(CourseMaterialProduct).where(CourseMaterialProduct.course_id == course.id, CourseMaterialProduct.user_id == course.user_id))
    result["link_count"] = db.scalar(select(func.count()).select_from(CourseContentLink).where(CourseContentLink.course_id == course.id, CourseContentLink.user_id == course.user_id, CourseContentLink.active.is_(True)))
    return result


def _version_course(db, version_id, course, user):
    if version_id is None:
        return
    version = _owned(db, CourseMaterialVersion, version_id, user)
    if _course_for(db, version, user).id != course.id:
        raise HTTPException(400, "资料版本不属于当前课程")


def _content(db, kind, record_id, is_demo, user):
    model = CourseDemoContent if is_demo else {"note": Note, "draft": AiDraft, "publish_job": PublishJob}[kind]
    row = _owned(db, model, record_id, user)
    if is_demo and row.content_kind != kind:
        raise HTTPException(400, "演示内容类型不匹配")
    return row


def _content_view(db, kind, row, is_demo, user):
    view = {"id": row.id, "target_kind": kind, "target_is_demo": is_demo, "title": row.title,
        "body": row.body if is_demo or kind != "note" else row.content,
        "status": "demo_only" if is_demo else getattr(row, "status", "saved"),
        "source_available": True, "is_demo": is_demo}
    if not is_demo and kind == "publish_job":
        source = db.get(AiDraft, row.source_draft_id) if row.source_draft_id else None
        view["source_available"] = bool(source and source.user_id == user.id)
        view["source_hint"] = "来源草稿可用" if view["source_available"] else "原草稿已不可用，保留发布快照"
    return view


@router.get("/capabilities")
def capabilities(user: User = Depends(get_current_user)):
    settings = get_settings()
    return {"enabled": settings.course_center_enabled, "demo_only": settings.course_center_demo_only,
        "external_actions_enabled": False, "can_publish": False, "can_run_automation": False}


@router.get("/courses")
def list_courses(q: str = "", include_archived: bool = False, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_enabled)):
    statement = select(CourseOffering).where(CourseOffering.user_id == user.id)
    if settings.course_center_demo_only:
        statement = statement.where(CourseOffering.is_demo.is_(True))
    if not include_archived:
        statement = statement.where(CourseOffering.archived.is_(False))
    if q.strip():
        pattern = f"%{q.strip()}%"
        normalized = re.sub(r"\s+", "", unicodedata.normalize("NFKC", q)).upper()
        statement = statement.where(or_(CourseOffering.university.ilike(pattern), CourseOffering.code_key.ilike(f"%{normalized}%"), CourseOffering.course_name.ilike(pattern), CourseOffering.term_key.ilike(f"%{normalized}%"), CourseOffering.notes.ilike(pattern), CourseOffering.aliases_search.ilike(pattern)))
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    courses = db.scalars(statement.order_by(CourseOffering.archived, CourseOffering.id).offset((page - 1) * page_size).limit(page_size)).all()
    result = paginated([_course_summary(db, c) for c in courses], page, page_size)
    result["total"] = total
    return result


@router.post("/courses")
def create_course(payload: CourseInput, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_enabled)):
    if settings.course_center_demo_only and not payload.is_demo:
        raise HTTPException(403, "当前仅开放演示课程")
    course = CourseOffering(user_id=user.id, **_identity(payload))
    db.add(course); _commit(db)
    return _course_summary(db, course)


@router.put("/courses/{course_id}")
def update_course(course_id: int, payload: CourseInput, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_enabled)):
    course = _owned(db, CourseOffering, course_id, user); _write_allowed(course)
    if course.is_demo != payload.is_demo:
        raise HTTPException(400, "不能转换课程的演示/真实数据归属")
    for key, value in _identity(payload).items(): setattr(course, key, value)
    _commit(db)
    return _course_summary(db, course)


@router.patch("/courses/{course_id}/archive")
def archive_course(course_id: int, payload: ArchiveInput, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_enabled)):
    course = _owned(db, CourseOffering, course_id, user); _write_allowed(course)
    course.archived = payload.archived; _commit(db)
    return _course_summary(db, course)


@router.get("/courses/{course_id}")
def workspace(course_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_enabled)):
    course = _owned(db, CourseOffering, course_id, user)
    if settings.course_center_demo_only and not course.is_demo: raise HTTPException(404, "当前仅展示演示课程")
    products = db.scalars(select(CourseMaterialProduct).where(CourseMaterialProduct.course_id == course_id, CourseMaterialProduct.user_id == user.id).order_by(CourseMaterialProduct.id)).all()
    versions = db.scalars(select(CourseMaterialVersion).where(CourseMaterialVersion.product_id.in_([p.id for p in products]), CourseMaterialVersion.user_id == user.id).order_by(CourseMaterialVersion.id.desc())).all()
    assets = db.scalars(select(CourseAsset).where(CourseAsset.course_id == course_id, CourseAsset.user_id == user.id).order_by(CourseAsset.id)).all()
    links = db.scalars(select(CourseContentLink).where(CourseContentLink.course_id == course_id, CourseContentLink.user_id == user.id, CourseContentLink.active.is_(True)).order_by(CourseContentLink.id)).all()
    resolved = []
    for link in links:
        view = _row(link)
        try:
            view["content"] = _content_view(db, link.target_kind, _content(db, link.target_kind, link.target_id, link.target_is_demo, user), link.target_is_demo, user)
        except HTTPException:
            view["content"] = {"title": "原内容已不可用", "status": "unavailable", "body": "", "source_available": False, "is_demo": link.target_is_demo}
        resolved.append(view)
    return {"course": _course_summary(db, course), "products": [_row(p) for p in products], "versions": [_row(v) for v in versions], "assets": [_row(a) for a in assets], "links": resolved}


@router.post("/courses/{course_id}/products")
def create_product(course_id: int, payload: ProductInput, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_enabled)):
    course = _owned(db, CourseOffering, course_id, user); _write_allowed(course)
    product = CourseMaterialProduct(user_id=user.id, course_id=course_id, **payload.model_dump())
    db.add(product); _commit(db)
    return _row(product)


@router.put("/products/{product_id}")
def update_product(product_id: int, payload: ProductInput, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_enabled)):
    product = _owned(db, CourseMaterialProduct, product_id, user); _write_allowed(_course_for(db, product, user))
    for k, v in payload.model_dump().items(): setattr(product, k, v)
    _commit(db); return _row(product)


@router.post("/products/{product_id}/versions")
def create_version(product_id: int, payload: VersionInput, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_enabled)):
    product = _owned(db, CourseMaterialProduct, product_id, user); _write_allowed(_course_for(db, product, user))
    version = CourseMaterialVersion(user_id=user.id, product_id=product_id, **payload.model_dump())
    db.add(version); _commit(db); return _row(version)


@router.put("/versions/{version_id}")
def update_version(version_id: int, payload: VersionInput, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_enabled)):
    version = _owned(db, CourseMaterialVersion, version_id, user); _write_allowed(_course_for(db, version, user))
    if version.source_reference != payload.source_reference or version.sha256 != payload.sha256:
        version.file_status = "registered"
    for k, v in payload.model_dump().items(): setattr(version, k, v)
    _commit(db); return _row(version)


@router.post("/courses/{course_id}/assets")
def create_asset(course_id: int, payload: AssetInput, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_enabled)):
    course = _owned(db, CourseOffering, course_id, user); _write_allowed(course)
    _validate_asset(db, payload, course, user)
    asset = CourseAsset(user_id=user.id, course_id=course_id, **payload.model_dump())
    db.add(asset); _commit(db); return _row(asset)


def _validate_asset(db, payload, course, user):
    _version_course(db, payload.version_id, course, user)
    if payload.usage_status == "approved" and (not payload.rights_confirmed or (payload.asset_kind == "sample" and not payload.watermarked)):
        raise HTTPException(400, "可用样张需确认使用权并标记水印；品牌标识需确认使用权")


@router.put("/assets/{asset_id}")
def update_asset(asset_id: int, payload: AssetInput, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_enabled)):
    asset = _owned(db, CourseAsset, asset_id, user); course = _course_for(db, asset, user); _write_allowed(course)
    _validate_asset(db, payload, course, user)
    for k, v in payload.model_dump().items(): setattr(asset, k, v)
    _commit(db); return _row(asset)


@router.get("/content-candidates")
def content_candidates(demo: bool = True, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_enabled)):
    items = []
    models = [("draft", CourseDemoContent)] if demo else [("note", Note), ("draft", AiDraft), ("publish_job", PublishJob)]
    for kind, model in models:
        rows = db.scalars(select(model).where(model.user_id == user.id).order_by(model.id.desc()).limit(100)).all()
        for row in rows:
            row_kind = row.content_kind if demo else kind
            view = _content_view(db, row_kind, row, demo, user)
            view["linked_count"] = db.scalar(select(func.count()).select_from(CourseContentLink).where(CourseContentLink.user_id == user.id, CourseContentLink.target_kind == row_kind, CourseContentLink.target_id == row.id, CourseContentLink.target_is_demo == demo, CourseContentLink.active.is_(True)))
            items.append(view)
    return {"items": items, "can_associate": demo or not settings.course_center_demo_only}


@router.post("/courses/{course_id}/links")
def create_link(course_id: int, payload: LinkInput, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_enabled)):
    course = _owned(db, CourseOffering, course_id, user); _write_allowed(course)
    if bool(course.is_demo) != payload.target_is_demo:
        raise HTTPException(400, "演示课程与真实内容保持隔离")
    _content(db, payload.target_kind, payload.target_id, payload.target_is_demo, user)
    _version_course(db, payload.version_id, course, user)
    existing = db.scalar(select(CourseContentLink).where(CourseContentLink.course_id == course_id, CourseContentLink.user_id == user.id, CourseContentLink.target_kind == payload.target_kind, CourseContentLink.target_id == payload.target_id, CourseContentLink.target_is_demo == payload.target_is_demo))
    if existing is not None:
        existing.active = True; existing.version_id = payload.version_id; existing.notes = payload.notes
        _commit(db); return _row(existing)
    link = CourseContentLink(user_id=user.id, course_id=course_id, **payload.model_dump())
    db.add(link); _commit(db); return _row(link)


@router.post("/links/{link_id}/detach")
def detach_link(link_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_enabled)):
    link = _owned(db, CourseContentLink, link_id, user); _write_allowed(_course_for(db, link, user))
    link.active = False; _commit(db)
    return {"id": link.id, "active": False, "history_retained": True}


def _demo_dir():
    return get_settings().storage_dir / "course-center-demo"


@router.get("/demo-assets/{name}")
def demo_asset(name: str, user: User = Depends(get_current_user), settings=Depends(require_enabled)):
    if name not in {"sample-watermarked.svg", "brand-placeholder.svg"}:
        raise HTTPException(404, "演示素材不存在")
    path = _demo_dir() / name
    if not path.is_file(): raise HTTPException(404, "请先载入演示数据")
    return FileResponse(path, media_type="image/svg+xml", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox"})


@router.post("/versions/{version_id}/check-file")
def check_file(version_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_enabled)):
    version = _owned(db, CourseMaterialVersion, version_id, user); course = _course_for(db, version, user); _write_allowed(course)
    allowed = {"demo://handout.txt": "handout.txt", "demo://missing-v0.txt": "missing-v0.txt"}
    if not course.is_demo or version.source_reference not in allowed:
        raise HTTPException(400, "本版仅核对受控演示文件；其他路径仅登记，不读取或移动文件")
    path = _demo_dir() / allowed[version.source_reference]
    if path.is_file():
        version.sha256 = hashlib.sha256(path.read_bytes()).hexdigest(); version.file_status = "verified"
    else:
        version.file_status = "missing"
    _commit(db); return _row(version)


@router.post("/demo/seed")
def seed_demo(user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_enabled)):
    from backend.app.services.course_demo_service import seed_course_demo
    result = seed_course_demo(db, user.id)
    _commit(db)
    return result
