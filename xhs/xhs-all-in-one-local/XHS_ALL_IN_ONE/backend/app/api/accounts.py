from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.adapters.xhs.creator_login_adapter import XhsCreatorLoginAdapter
from backend.app.adapters.xhs.creator_api_adapter import CreatorRequestRejected, XhsCreatorApiAdapter
from backend.app.adapters.xhs.pc_api_adapter import XhsPcApiAdapter
from backend.app.adapters.xhs.pc_login_adapter import XhsPcLoginAdapter
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.security import decrypt_text
from backend.app.core.time import shanghai_now
from backend.app.models import AccountCookieVersion, PlatformAccount, User
from backend.app.schemas.common import paginated
from backend.app.services.account_service import (
    account_profile_from_user_info,
    cookie_header_from_text,
    decode_cookie_text,
    enrich_user_info_with_xhs_self_profile,
    serialize_account,
    upsert_platform_account_from_login,
)
from xhs_utils.cookie_util import trans_cookies
from backend.app.services.creator_session_health import credential_coverage, latest_cookie, same_account_pc

router = APIRouter(prefix="/accounts", tags=["accounts"])


class CookieImportRequest(BaseModel):
    platform: str = Field(pattern="^xhs$")
    sub_type: str = Field(pattern="^(pc|creator)$")
    cookie_string: str = Field(min_length=3)
    sync_creator: bool = False


def get_pc_account_adapter() -> XhsPcLoginAdapter:
    return XhsPcLoginAdapter()


def get_creator_account_adapter() -> XhsCreatorLoginAdapter:
    return XhsCreatorLoginAdapter()


def get_creator_session_adapter_factory():
    return XhsCreatorApiAdapter


def _inspect_creator_session(cookies_text: str, adapter_factory) -> dict:
    result = {"session_ok": False, "publish_permission": "not_tested"}
    try:
        adapter_factory(cookie_header_from_text(cookies_text)).inspect_session()
        result.update(session_ok=True, message="登录与发布页身份会话检查通过；未上传素材、未提交笔记，实际发布结果尚未测试。")
    except CreatorRequestRejected as exc:
        diagnostics = exc.diagnostics
        result["diagnostics"] = diagnostics
        http_status = diagnostics.get("http_status")
        if http_status == 401:
            result["message"] = "跨站登录会话失效（HTTP 401），请在账号矩阵用同账号重新登录并同步 Creator。未提交笔记。"
        elif http_status in {461, 471}:
            verify_type = diagnostics.get("verification_type")
            detail = f"，verifytype={verify_type}" if verify_type else ""
            result["message"] = f"只读会话检查触发平台安全验证（HTTP {http_status}{detail}），请本人在官方页面处理提示。未重试发布。"
        else:
            result["message"] = f"只读会话检查未通过（HTTP {http_status}）；请检查官方登录状态。未提交笔记。"
    except Exception:
        # SDK/network exceptions may embed signed URLs or cookies. Never return
        # those to the UI, and never classify a connectivity failure as expiry.
        result["message"] = "只读会话检查未完成，请检查后台网络与官方登录状态；不能据此判定账号过期。未提交笔记。"
    return result


class XhsSelfProfileAdapter:
    def get_self_profile(self, cookies_text: str):
        return XhsPcApiAdapter(cookies_text).get_self_info()


def get_xhs_self_profile_adapter() -> XhsSelfProfileAdapter:
    return XhsSelfProfileAdapter()


def _select_adapter(sub_type: str, pc_adapter: XhsPcLoginAdapter, creator_adapter: XhsCreatorLoginAdapter):
    return creator_adapter if sub_type == "creator" else pc_adapter


def _sync_creator_account_from_pc_cookie(
    *,
    db: Session,
    user_id: int,
    platform: str,
    cookie_string: str,
    creator_adapter: XhsCreatorLoginAdapter,
):
    try:
        creator_result = creator_adapter.exchange_from_user_cookies(trans_cookies(cookie_string))
        creator_cookies_text = json.dumps(creator_result["cookies"], ensure_ascii=False, separators=(",", ":"))
        creator_user_info = creator_adapter.get_user_info(creator_result["cookies"])
        upsert_platform_account_from_login(
            db=db,
            user_id=user_id,
            platform=platform,
            sub_type="creator",
            user_info=creator_user_info,
            cookies_text=creator_cookies_text,
        )
    except Exception:
        return None
    return True


def _account_with_session_coverage(db, account):
    payload = serialize_account(account)
    if account.sub_type == 'creator':
        version = latest_cookie(db, account.id)
        try:
            payload['publish_session'] = credential_coverage(decrypt_text(version.encrypted_cookies)) if version else credential_coverage('')
        except Exception:
            payload['publish_session'] = credential_coverage('')
    return payload


@router.get("")
def get_accounts(
    platform: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    statement = select(PlatformAccount).where(PlatformAccount.user_id == current_user.id)
    if platform:
        statement = statement.where(PlatformAccount.platform == platform)
    accounts = db.scalars(statement.order_by(PlatformAccount.created_at.desc())).all()
    return paginated(
        [_account_with_session_coverage(db, account) for account in accounts],
        page,
        page_size,
    )


@router.post("/import-cookie")
def import_cookie(
    payload: CookieImportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    pc_adapter: XhsPcLoginAdapter = Depends(get_pc_account_adapter),
    creator_adapter: XhsCreatorLoginAdapter = Depends(get_creator_account_adapter),
    self_profile_adapter: XhsSelfProfileAdapter = Depends(get_xhs_self_profile_adapter),
):
    adapter = _select_adapter(payload.sub_type, pc_adapter, creator_adapter)
    try:
        user_info = adapter.get_user_info(trans_cookies(payload.cookie_string))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cookie is invalid or expired") from exc

    if payload.sub_type == "pc":
        try:
            self_profile = self_profile_adapter.get_self_profile(cookie_header_from_text(payload.cookie_string))
            user_info = enrich_user_info_with_xhs_self_profile(user_info, self_profile)
        except Exception:
            pass

    account, action = upsert_platform_account_from_login(
        db=db,
        user_id=current_user.id,
        platform=payload.platform,
        sub_type=payload.sub_type,
        user_info=user_info,
        cookies_text=payload.cookie_string,
    )
    if payload.sub_type == "pc" and payload.sync_creator:
        _sync_creator_account_from_pc_cookie(
            db=db,
            user_id=current_user.id,
            platform=payload.platform,
            cookie_string=payload.cookie_string,
            creator_adapter=creator_adapter,
        )
    db.commit()
    db.refresh(account)
    return serialize_account(account, action)


@router.post("/{account_id}/check")
def check_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    pc_adapter: XhsPcLoginAdapter = Depends(get_pc_account_adapter),
    creator_adapter: XhsCreatorLoginAdapter = Depends(get_creator_account_adapter),
    self_profile_adapter: XhsSelfProfileAdapter = Depends(get_xhs_self_profile_adapter),
    creator_session_adapter_factory=Depends(get_creator_session_adapter_factory),
):
    account = db.get(PlatformAccount, account_id)
    if account is None or account.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    cookie_version = db.scalars(
        select(AccountCookieVersion)
        .where(AccountCookieVersion.platform_account_id == account.id)
        .order_by(AccountCookieVersion.created_at.desc())
    ).first()
    if cookie_version is None:
        account.status = "expired"
        account.status_message = "No stored cookie version"
        db.commit()
        db.refresh(account)
        return serialize_account(account)

    adapter = _select_adapter(account.sub_type or "pc", pc_adapter, creator_adapter)
    try:
        cookies_text = decrypt_text(cookie_version.encrypted_cookies)
        user_info = adapter.get_user_info(decode_cookie_text(cookies_text))
        try:
            self_profile = self_profile_adapter.get_self_profile(cookie_header_from_text(cookies_text))
            user_info = enrich_user_info_with_xhs_self_profile(user_info, self_profile)
        except Exception:
            pass
        account.status = "active"
        account.status_message = ""
        account.nickname = user_info.get("nickname", account.nickname)
        account.avatar_url = user_info.get("avatar_url", account.avatar_url)
        account.external_user_id = user_info.get("external_user_id", account.external_user_id)
        account.profile_json = json.dumps(account_profile_from_user_info(user_info), ensure_ascii=False, separators=(",", ":"))
        account.updated_at = shanghai_now()

        if account.sub_type == "creator":
            session = _inspect_creator_session(cookies_text, creator_session_adapter_factory)
            if not session["session_ok"]:
                account.status = "expired" if session.get("diagnostics", {}).get("http_status") == 401 else "unknown"
                account.status_message = session["message"]
    except Exception as exc:
        account.status = "expired"
        account.status_message = str(exc)
        account.updated_at = shanghai_now()

    db.commit()
    db.refresh(account)
    return serialize_account(account)


@router.post("/{account_id}/check-publish-session")
def check_creator_publish_session(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_creator_session_adapter_factory),
):
    """No uploads, note submissions, cookie updates or job/task state changes."""
    account = db.get(PlatformAccount, account_id)
    if account is None or account.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.platform != "xhs" or account.sub_type != "creator":
        raise HTTPException(status_code=400, detail="Creator account required")
    cookie_version = db.scalars(select(AccountCookieVersion)
        .where(AccountCookieVersion.platform_account_id == account.id)
        .order_by(AccountCookieVersion.created_at.desc())).first()
    result = {"session_ok": False, "publish_permission": "not_tested", "message": "没有本机保存的登录会话，请先绑定账号。"}
    if cookie_version is not None:
        result = _inspect_creator_session(decrypt_text(cookie_version.encrypted_cookies), adapter_factory)
    pc = same_account_pc(db, account)
    return {"account_id": account.id, "account_name":account.nickname, "checked_at": shanghai_now().isoformat(), **result,
            'repair': {'matching_pc_account_id': pc.id if pc else None, 'requires_pc_login': pc is None}}


@router.post('/{account_id}/repair-publish-session')
def repair_creator_publish_session(account_id: int, current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db), creator_adapter: XhsCreatorLoginAdapter = Depends(get_creator_account_adapter),
    adapter_factory=Depends(get_creator_session_adapter_factory)):
    """Refresh one owner's matching login only. No job, upload or note request."""
    account = db.get(PlatformAccount, account_id)
    if account is None or account.user_id != current_user.id:
        raise HTTPException(404, 'Account not found')
    if account.platform != 'xhs' or account.sub_type != 'creator':
        raise HTTPException(400, 'Creator account required')
    pc = same_account_pc(db, account)
    version = latest_cookie(db, pc.id) if pc else None
    base = {'account_id':account.id, 'account_name':account.nickname, 'publish_permission':'not_tested',
            'checked_at':shanghai_now().isoformat(), 'session_ok':False}
    if version is None:
        return {**base, 'repair':{'requires_pc_login':True,'matching_pc_account_id':None},
                'message':f'请用「{account.nickname}」完成PC扫码登录并同步Creator；现有草稿和图片保留。'}
    try:
        cookies = decode_cookie_text(decrypt_text(version.encrypted_cookies))
        require = credential_coverage(json.dumps(cookies))
        if require['state'] != 'available':
            raise ValueError('missing PC session')
        exchanged = creator_adapter.exchange_from_user_cookies(cookies)
        user_info = creator_adapter.get_user_info(exchanged['cookies'])
        if not account.external_user_id or user_info.get('external_user_id') != account.external_user_id:
            raise HTTPException(409, '登录账号与当前发布账号不一致，未替换任何会话。')
        text = json.dumps(exchanged['cookies'], ensure_ascii=False, separators=(',',':'))
        if credential_coverage(text)['state'] != 'available':
            raise ValueError('incomplete exchange')
        result = _inspect_creator_session(text, adapter_factory)
        if not result['session_ok']:
            return {**base, **result, 'repair':{'requires_pc_login':True,'matching_pc_account_id':pc.id}}
        refreshed, _ = upsert_platform_account_from_login(db=db, user_id=current_user.id, platform='xhs',
            sub_type='creator', user_info=user_info, cookies_text=text)
        assert refreshed.id == account.id
        db.commit()
        return {**base, **result, 'message':'同账号PC与Creator会话已同步，只读检查通过；未提交笔记。',
                'repair':{'requires_pc_login':False,'matching_pc_account_id':pc.id}}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        # An SDK/network failure does not prove that the successful PC scan
        # expired. Do not send the user into another QR loop on this result.
        return {**base, 'message':'PC登录已保存，但同步检查未完成，请稍后再点“同步同账号登录”。原会话和草稿保留。',
                'repair':{'requires_pc_login':False,'matching_pc_account_id':pc.id}}


@router.patch("/{account_id}")
def update_account(account_id: int):
    return {"id": account_id, "status": "updated"}


@router.delete("/{account_id}")
def delete_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.get(PlatformAccount, account_id)
    if account is None or account.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    for cookie_version in db.scalars(
        select(AccountCookieVersion).where(AccountCookieVersion.platform_account_id == account.id)
    ).all():
        db.delete(cookie_version)
    db.delete(account)
    db.commit()
    return {"id": account_id, "status": "deleted"}
