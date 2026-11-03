from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import AiDraft, DraftAsset, Note, NoteAsset, PlatformAccount, PublishAsset, PublishJob, User
from backend.app.schemas.common import paginated
from backend.app.services.course_draft_origin import course_origins

router = APIRouter(prefix="/drafts", tags=["drafts"])


class DraftCreateRequest(BaseModel):
    platform: str = Field(pattern="^xhs$")
    source_note_id: Optional[int] = None
    title: str = ""
    body: str = ""
    intent: str = Field(default="publish", max_length=32)


class DraftUpdateRequest(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    tags: Optional[list[dict]] = None


class DraftSendToPublishRequest(BaseModel):
    platform_account_id: Optional[int] = None
    publish_mode: str = Field(default="immediate", pattern="^(immediate|scheduled)$")
    scheduled_at: Optional[datetime] = None
    topics: Optional[list[str]] = None
    location: Optional[str] = None
    privacy_type: Optional[int] = Field(default=None, ge=0, le=1)
    is_private: Optional[bool] = None


def _clean_topics(topics: Optional[list[str]]) -> list[str]:
    if topics is None:
        return []
    return [topic.strip() for topic in topics if topic and topic.strip()]


def _build_publish_options(payload: DraftSendToPublishRequest) -> dict[str, Any]:
    options: dict[str, Any] = {}
    topics = _clean_topics(payload.topics)
    if topics:
        options["topics"] = topics
    if payload.location and payload.location.strip():
        options["location"] = payload.location.strip()
    if payload.is_private is not None:
        options["is_private"] = payload.is_private
        options["privacy_type"] = 1 if payload.is_private else 0
    elif payload.privacy_type is not None:
        options["privacy_type"] = payload.privacy_type
        options["is_private"] = payload.privacy_type == 1
    return options


def _serialize_draft(draft: AiDraft, course_origin=None) -> dict:
    return {
        "id": draft.id,
        "platform": draft.platform,
        "title": draft.title,
        "body": draft.body,
        "tags": draft.tags or [],
        "source_note_id": draft.source_note_id,
        "created_at": draft.created_at.isoformat(),
        "course_origin": course_origin,
    }


def _serialize_publish_job(job: PublishJob) -> dict:
    try:
        publish_options = json.loads(job.publish_options or "{}")
    except json.JSONDecodeError:
        publish_options = {}
    return {
        "id": job.id,
        "platform_account_id": job.platform_account_id,
        "source_draft_id": job.source_draft_id,
        "platform": job.platform,
        "title": job.title,
        "body": job.body,
        "publish_mode": job.publish_mode,
        "publish_options": publish_options,
        "status": job.status,
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
        "created_at": job.created_at.isoformat(),
    }


def _get_owned_source_note(db: Session, current_user: User, note_id: int) -> Note:
    note = db.get(Note, note_id)
    if note is None or note.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source note not found")
    return note


@router.get("")
def get_drafts(
    platform: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    statement = select(AiDraft).where(AiDraft.user_id == current_user.id)
    if platform:
        statement = statement.where(AiDraft.platform == platform)
    drafts = db.scalars(statement.order_by(AiDraft.created_at.desc())).all()
    origins = course_origins(db, current_user.id, [draft.id for draft in drafts])
    return paginated([_serialize_draft(draft, origins.get(draft.id)) for draft in drafts], page, page_size)


@router.post("")
def create_draft(
    payload: DraftCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    source_note = None
    if payload.source_note_id is not None:
        source_note = _get_owned_source_note(db, current_user, payload.source_note_id)

    # Extract tags from source note
    tags = None
    if source_note and source_note.raw_json:
        raw = source_note.raw_json if isinstance(source_note.raw_json, dict) else {}
        tag_list = raw.get("tags") or raw.get("tag_list")
        if not tag_list:
            data = raw.get("data")
            if isinstance(data, dict):
                items = data.get("items") or []
                if items and isinstance(items[0], dict):
                    card = items[0].get("note_card") or {}
                    if isinstance(card, dict):
                        tag_list = card.get("tag_list")
        if isinstance(tag_list, list):
            tags = []
            for t in tag_list:
                if isinstance(t, str):
                    tags.append({"name": t})
                elif isinstance(t, dict) and t.get("name"):
                    tags.append({"id": str(t.get("id", "")), "name": str(t["name"])})

    draft = AiDraft(
        user_id=current_user.id,
        platform=payload.platform,
        title=payload.title or (source_note.title if source_note else ""),
        body=payload.body or (source_note.content if source_note else ""),
        tags=tags,
        source_note_id=source_note.id if source_note else None,
    )
    db.add(draft)
    db.flush()

    if source_note:
        source_assets = db.scalars(
            select(NoteAsset).where(NoteAsset.note_id == source_note.id).order_by(NoteAsset.sort_order.asc(), NoteAsset.id.asc())
        ).all()
        for idx, na in enumerate(source_assets):
            db.add(DraftAsset(
                draft_id=draft.id,
                asset_type=na.asset_type,
                url=na.url,
                local_path=na.local_path,
                sort_order=idx,
            ))

    db.commit()
    db.refresh(draft)
    return _serialize_draft(draft)


@router.get('/{draft_id}')
def get_draft(draft_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(404, '草稿不存在或无权访问')
    return _serialize_draft(draft, course_origins(db, current_user.id, [draft.id]).get(draft.id))


@router.post("/{draft_id}/send-to-publish")
def send_draft_to_publish(
    draft_id: int,
    payload: DraftSendToPublishRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

    account_id: Optional[int] = None
    if payload.platform_account_id is not None:
        account = db.get(PlatformAccount, payload.platform_account_id)
        if account is None or account.user_id != current_user.id or account.platform != draft.platform:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Platform account not found")
        account_id = account.id

    options = _build_publish_options(payload)
    if draft.tags:
        options["draft_tags"] = draft.tags

    job = PublishJob(
        user_id=current_user.id,
        platform_account_id=account_id,
        source_draft_id=draft.id,
        platform=draft.platform,
        title=draft.title,
        body=draft.body,
        publish_mode=payload.publish_mode,
        publish_options=json.dumps(options, ensure_ascii=False, separators=(",", ":")),
        scheduled_at=payload.scheduled_at,
        status="pending",
    )
    db.add(job)
    db.flush()

    draft_assets = db.scalars(
        select(DraftAsset).where(DraftAsset.draft_id == draft.id).order_by(DraftAsset.sort_order.asc(), DraftAsset.id.asc())
    ).all()
    for da in draft_assets:
        if da.local_path:
            file_path = f"/api/files/media/{da.local_path}"
        else:
            file_path = da.url
        pa = PublishAsset(
            publish_job_id=job.id,
            asset_type=da.asset_type,
            file_path=file_path,
            upload_status="pending",
        )
        db.add(pa)

    db.commit()
    db.refresh(job)
    return _serialize_publish_job(job)


@router.patch("/{draft_id}")
def update_draft(
    draft_id: int,
    payload: DraftUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

    if payload.title is not None:
        draft.title = payload.title
    if payload.body is not None:
        draft.body = payload.body
    if payload.tags is not None:
        draft.tags = list(payload.tags)
        flag_modified(draft, "tags")

    db.commit()
    db.refresh(draft)
    return _serialize_draft(draft, course_origins(db, current_user.id, [draft.id]).get(draft.id))


@router.delete("/{draft_id}")
def delete_draft(
    draft_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    db.execute(select(DraftAsset).where(DraftAsset.draft_id == draft.id))
    for asset in db.scalars(select(DraftAsset).where(DraftAsset.draft_id == draft.id)).all():
        db.delete(asset)
    db.delete(draft)
    db.commit()
    return {"id": draft_id, "status": "deleted"}


# ---------------------------------------------------------------------------
# Draft assets
# ---------------------------------------------------------------------------

def _serialize_draft_asset(asset: DraftAsset) -> dict:
    display_url = f"/api/files/media/{asset.local_path}" if asset.local_path else asset.url
    return {
        "id": asset.id,
        "draft_id": asset.draft_id,
        "asset_type": asset.asset_type,
        "url": display_url,
        "local_path": asset.local_path,
        "sort_order": asset.sort_order,
    }


class DraftAssetCreateRequest(BaseModel):
    asset_type: str = Field(pattern="^(image|video)$")
    url: str = Field(default="", max_length=2048)
    local_path: str = Field(default="", max_length=512)


class DraftAssetReorderRequest(BaseModel):
    asset_ids: list[int] = Field(min_length=1)


class DraftAssetVariantRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


@router.post('/{draft_id}/assets/{asset_id}/variants')
def add_image_variant(draft_id: int, asset_id: int, payload: DraftAssetVariantRequest,
        current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    draft = db.get(AiDraft, draft_id)
    original = db.get(DraftAsset, asset_id)
    if not draft or draft.user_id != current_user.id or not original or original.draft_id != draft_id:
        raise HTTPException(404, 'Asset not found')
    if original.asset_type != 'image':
        raise HTTPException(422, '只有图片可以另存润色版本')
    if course_origins(db, current_user.id, [draft_id]):
        raise HTTPException(409, '课程图片请返回课程制作入口修改，旧图保持不变')
    if not payload.url.startswith(('https://', 'http://')):
        raise HTTPException(422, '图片结果地址无效，原图保留')
    assets = db.scalars(select(DraftAsset).where(DraftAsset.draft_id == draft_id).order_by(DraftAsset.sort_order, DraftAsset.id)).all()
    # A retried save of the same result must not append duplicate attachments.
    existing = next((a for a in assets if a.asset_type == 'image' and a.url == payload.url), None)
    if existing is None:
        position = assets.index(original) + 1
        saved = DraftAsset(draft_id=draft_id, asset_type='image', url=payload.url, local_path='')
        assets.insert(position, saved)
        for order, asset in enumerate(assets):
            asset.sort_order = order
        db.add(saved)
        db.commit()
    return {'items': [_serialize_draft_asset(a) for a in assets]}


@router.get("/{draft_id}/assets")
def get_draft_assets(
    draft_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Draft not found")
    assets = db.scalars(
        select(DraftAsset).where(DraftAsset.draft_id == draft.id).order_by(DraftAsset.sort_order.asc(), DraftAsset.id.asc())
    ).all()
    return {"items": [_serialize_draft_asset(a) for a in assets]}


@router.post("/{draft_id}/assets")
def add_draft_asset(
    draft_id: int,
    payload: DraftAssetCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Draft not found")
    max_order = db.scalar(select(func.max(DraftAsset.sort_order)).where(DraftAsset.draft_id == draft.id)) or 0
    asset = DraftAsset(
        draft_id=draft.id,
        asset_type=payload.asset_type,
        url=payload.url,
        local_path=payload.local_path,
        sort_order=max_order + 1,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return _serialize_draft_asset(asset)


@router.delete("/{draft_id}/assets/{asset_id}")
def delete_draft_asset(
    draft_id: int,
    asset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Draft not found")
    asset = db.scalars(select(DraftAsset).where(DraftAsset.id == asset_id, DraftAsset.draft_id == draft.id)).first()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    db.delete(asset)
    db.commit()
    return {"id": asset_id, "status": "deleted"}


class DraftAssetUpdateRequest(BaseModel):
    url: Optional[str] = Field(default=None, max_length=2048)
    local_path: Optional[str] = Field(default=None, max_length=512)


@router.patch("/{draft_id}/assets/{asset_id}")
def update_draft_asset(
    draft_id: int,
    asset_id: int,
    payload: DraftAssetUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Draft not found")
    asset = db.scalars(select(DraftAsset).where(DraftAsset.id == asset_id, DraftAsset.draft_id == draft.id)).first()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    if course_origins(db, current_user.id, [draft_id]):
        raise HTTPException(409, '课程图片请返回课程制作入口修改并另存，当前素材保持不变')
    if payload.url is not None:
        asset.url = payload.url
    if payload.local_path is not None:
        asset.local_path = payload.local_path
    db.commit()
    db.refresh(asset)
    return _serialize_draft_asset(asset)


@router.put("/{draft_id}/assets/reorder")
def reorder_draft_assets(
    draft_id: int,
    payload: DraftAssetReorderRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Draft not found")
    assets = db.scalars(select(DraftAsset).where(DraftAsset.draft_id == draft.id)).all()
    asset_map = {a.id: a for a in assets}
    for idx, aid in enumerate(payload.asset_ids):
        if aid in asset_map:
            asset_map[aid].sort_order = idx
    db.commit()
    return {"ok": True}
