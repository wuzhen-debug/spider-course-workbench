from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import threading
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.adapters.xhs.creator_login_adapter import XhsCreatorLoginAdapter
from backend.app.adapters.xhs.pc_login_adapter import XhsPcLoginAdapter
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.security import decrypt_text, encrypt_text
from backend.app.core.time import shanghai_now
from backend.app.models import LoginSession, PlatformAccount, User
from backend.app.adapters.xhs.pc_api_adapter import XhsPcApiAdapter
from backend.app.services.account_service import (
    cookie_header_from_text,
    enrich_user_info_with_xhs_self_profile,
    serialize_account,
    upsert_platform_account_from_login,
)

router = APIRouter(prefix="/xhs/login-sessions", tags=["xhs-login-sessions"])
_SESSION_LOCKS = tuple(threading.RLock() for _ in range(64))


class PcQrCodeRequest(BaseModel):
    sync_creator: bool = False
    target_creator_account_id: int | None = Field(default=None, gt=0)


class PhoneSendCodeRequest(BaseModel):
    phone: str = Field(min_length=6, max_length=32)
    sync_creator: bool = False


class PhoneConfirmRequest(BaseModel):
    session_id: int
    phone: str = Field(min_length=6, max_length=32)
    code: str = Field(min_length=4, max_length=12)
    sync_creator: bool | None = None


def _dump_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load_json(value: str | None) -> dict:
    if not value:
        return {}
    return json.loads(value)


def _dump_temp_state(cookies: dict, *, sync_creator: bool = False, **metadata) -> str:
    if sync_creator or metadata:
        return _dump_json({"cookies": cookies, **({"sync_creator": True} if sync_creator else {}), **metadata})
    return _dump_json(cookies)


def _load_temp_state(value: str | None) -> tuple[dict, bool]:
    payload = _load_json(value)
    if isinstance(payload, dict) and isinstance(payload.get("cookies"), dict):
        return payload["cookies"], bool(payload.get("sync_creator"))
    if isinstance(payload, dict):
        return payload, False
    return {}, False


def _qr_data_url(qr_url: str) -> str:
    import qrcode

    image = qrcode.make(qr_url)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def get_pc_login_adapter() -> XhsPcLoginAdapter:
    return XhsPcLoginAdapter()


def get_creator_login_adapter() -> XhsCreatorLoginAdapter:
    return XhsCreatorLoginAdapter()


def _mask_phone(phone: str) -> str:
    if len(phone) <= 7:
        return f"{phone[:2]}****"
    return f"{phone[:3]}****{phone[-4:]}"


def _metadata(session: LoginSession) -> dict:
    value = _load_json(decrypt_text(session.encrypted_temp_cookies))
    return {key: item for key, item in value.items() if key not in {"cookies", "sync_creator"}} if isinstance(value.get("cookies"), dict) else {}


def _save_state(session: LoginSession, cookies: dict, sync_creator: bool, **metadata) -> None:
    session.encrypted_temp_cookies = encrypt_text(_dump_temp_state(cookies, sync_creator=sync_creator, **metadata))


def _phone_digest(phone: str) -> str:
    return hashlib.sha256(phone.strip().encode()).hexdigest()


def _session_expired(session: LoginSession) -> bool:
    maximum = timedelta(minutes=8 if session.login_method == "phone" else 5)
    return session.status == "expired" or bool(session.created_at and shanghai_now() - session.created_at >= maximum)


def _expire_session(db: Session, session: LoginSession) -> None:
    from backend.app.adapters.xhs.login_context import LOGIN_CONTEXT_COOKIE, login_contexts

    cookies, _ = _load_temp_state(decrypt_text(session.encrypted_temp_cookies))
    token = cookies.get(LOGIN_CONTEXT_COOKIE)
    if isinstance(token, str):
        login_contexts.release(token)
    session.status = "expired"
    db.commit()


def _login_error(exc: Exception, phase: str) -> HTTPException:
    # Only the adapter's deliberately public message crosses the API boundary.
    # Never include raw SDK/transport errors, cookies, phone numbers, or codes.
    from backend.app.adapters.xhs.login_errors import XhsLoginError

    if isinstance(exc, XhsLoginError):
        code = 410 if exc.error_code == "login_session_expired" else 429 if exc.error_code == "login_rate_limited" else 400 if exc.error_code in {"login_code_invalid", "phone_mismatch"} else 502
        return HTTPException(status_code=code, detail=exc.public_message)
    messages = {
        "qr_create": "二维码暂时生成失败，请稍后重试；若官方页面有验证提示，请先手动完成。",
        "qr_poll": "暂时无法读取扫码状态，请稍后重试；不会将网络错误当作扫码成功。",
        "send": "短信验证码暂时发送失败，请稍后重试；如有安全验证，请先在官方页面完成。",
        "confirm": "短信登录未完成，可能是会话或平台接口异常；请重试并查看具体提示。",
        "profile": "登录确认已收到，但暂时无法读取账号资料；请重试确认，无需重复发送短信或扫描二维码。",
    }
    return HTTPException(status_code=502, detail=messages[phase])


def _fail_session(db: Session, session: LoginSession, exc: Exception, phase: str) -> None:
    if getattr(exc, "error_code", None) == "login_session_expired":
        _expire_session(db, session)
    raise _login_error(exc, phase) from None


def _confirmed_response(db: Session, session: LoginSession, metadata: dict) -> dict:
    result = {"session_id": session.id, "status": "confirmed", "qr_url": session.qr_url, "account": None, "creator_account": None}
    for key, output in [("account_id", "account"), ("creator_account_id", "creator_account")]:
        account = db.get(PlatformAccount, metadata.get(key)) if metadata.get(key) else None
        if account is not None and account.user_id == session.user_id:
            result[output] = serialize_account(account, metadata.get("account_action" if output == "account" else "creator_account_action"))
    return result


def _sync_creator_account_from_pc_login(
    *,
    db: Session,
    user_id: int,
    pc_cookies: dict,
    creator_adapter: XhsCreatorLoginAdapter,
    expected_external_user_id: str | None = None,
) -> dict | None:
    try:
        creator_result = creator_adapter.exchange_from_user_cookies(pc_cookies)
        creator_user_info = creator_adapter.get_user_info(creator_result["cookies"])
        if expected_external_user_id and creator_user_info.get('external_user_id') != expected_external_user_id:
            return None
        from backend.app.services.creator_session_health import credential_coverage
        if credential_coverage(_dump_json(creator_result['cookies']))['state'] != 'available':
            return None
        creator_account, creator_action = _create_account_from_login(
            db=db,
            user_id=user_id,
            sub_type="creator",
            user_info=creator_user_info,
            cookies=creator_result["cookies"],
        )
    except Exception:
        return None
    return serialize_account(creator_account, creator_action)


def _create_account_from_login(
    *,
    db: Session,
    user_id: int,
    sub_type: str,
    user_info: dict,
    cookies: dict,
) -> tuple[PlatformAccount, str]:
    from backend.app.adapters.xhs.login_context import plain_cookies

    # Runtime references belong only to encrypted temporary sessions.
    cookies = plain_cookies(cookies)
    cookies_text = _dump_json(cookies)
    if sub_type == "pc":
        try:
            self_profile = XhsPcApiAdapter(cookie_header_from_text(cookies_text)).get_self_info()
            user_info = enrich_user_info_with_xhs_self_profile(user_info, self_profile)
        except Exception:
            pass
    return upsert_platform_account_from_login(
        db=db,
        user_id=user_id,
        platform="xhs",
        sub_type=sub_type,
        user_info=user_info,
        cookies_text=cookies_text,
    )


@router.post("/pc/qrcode")
def pc_qrcode(
    payload: PcQrCodeRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsPcLoginAdapter = Depends(get_pc_login_adapter),
):
    payload = payload or PcQrCodeRequest()
    repair_metadata = {}
    if payload.target_creator_account_id is not None:
        target = db.get(PlatformAccount, payload.target_creator_account_id)
        if target is None or target.user_id != current_user.id:
            raise HTTPException(404, 'Account not found')
        if target.platform != 'xhs' or target.sub_type != 'creator' or not target.external_user_id:
            raise HTTPException(400, '可修复的Creator账号身份未登记')
        payload.sync_creator = True
        repair_metadata = {'target_creator_account_id':target.id, 'expected_external_user_id':target.external_user_id}
    try:
        qr_payload = adapter.create_qrcode()
    except Exception as exc:
        raise _login_error(exc, "qr_create") from None
    session = LoginSession(
        user_id=current_user.id,
        platform="xhs",
        sub_type="pc",
        status="pending",
        qr_id=qr_payload["qr_id"],
        code=qr_payload["code"],
        qr_url=qr_payload["qr_url"],
        encrypted_temp_cookies=encrypt_text(
            _dump_temp_state(qr_payload["cookies"], sync_creator=payload.sync_creator, **repair_metadata)
        ),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {
        "session_id": session.id,
        "status": session.status,
        "qr_url": session.qr_url,
        "qr_image_data_url": _qr_data_url(session.qr_url or ""),
    }


@router.post("/creator/qrcode")
def creator_qrcode(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsCreatorLoginAdapter = Depends(get_creator_login_adapter),
):
    try:
        payload = adapter.create_qrcode()
    except Exception as exc:
        raise _login_error(exc, "qr_create") from None
    session = LoginSession(
        user_id=current_user.id,
        platform="xhs",
        sub_type="creator",
        status="pending",
        qr_id=payload["qr_id"],
        qr_url=payload["qr_url"],
        encrypted_temp_cookies=encrypt_text(_dump_json(payload["cookies"])),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {
        "session_id": session.id,
        "status": session.status,
        "qr_url": session.qr_url,
        "qr_image_data_url": _qr_data_url(session.qr_url or ""),
    }


@router.get("/{session_id}")
def login_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    pc_adapter: XhsPcLoginAdapter = Depends(get_pc_login_adapter),
    creator_adapter: XhsCreatorLoginAdapter = Depends(get_creator_login_adapter),
):
    with _SESSION_LOCKS[session_id % len(_SESSION_LOCKS)]:
        db.expire_all()
        return _poll_login_session(session_id, current_user, db, pc_adapter, creator_adapter)


def _poll_login_session(session_id, current_user, db, pc_adapter, creator_adapter):
    session = db.get(LoginSession, session_id)
    if session is None or session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Login session not found")
    metadata = _metadata(session)
    if session.status == "confirmed":
        return _confirmed_response(db, session, metadata)
    if session.login_method != "qr" or session.sub_type not in {"pc", "creator"} or not session.qr_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported login session")
    if _session_expired(session):
        _expire_session(db, session)
        return {"session_id": session.id, "status": "expired", "qr_url": session.qr_url}

    cookies, sync_creator = _load_temp_state(decrypt_text(session.encrypted_temp_cookies))
    adapter = pc_adapter if session.sub_type == "pc" else creator_adapter
    try:
        if metadata.get("authenticated"):
            result = {"status": "confirmed", "cookies": cookies}
        elif session.sub_type == "pc":
            if not session.code:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported login session")
            result = pc_adapter.check_qrcode_status(session.qr_id, session.code, cookies)
        else:
            result = creator_adapter.check_qrcode_status(session.qr_id, cookies)
    except HTTPException:
        raise
    except Exception as exc:
        _fail_session(db, session, exc, "qr_poll")
    if result.get("status") not in {"pending", "scanned", "confirmed", "expired"}:
        raise HTTPException(502, "登录服务返回了无法识别的扫码状态，请重新获取二维码。")
    cookies = result["cookies"]
    if result["status"] != "confirmed":
        session.status = result["status"]
        _save_state(session, cookies, sync_creator, **metadata)
        db.commit()
        return {"session_id": session.id, "status": session.status, "qr_url": session.qr_url, "account": None, "creator_account": None}
    # The one-time scan/ticket has been accepted. Persist it before profile
    # acceptance so a temporary network failure does not consume it twice.
    metadata["authenticated"] = True
    session.status = "scanned"
    _save_state(session, cookies, sync_creator, **metadata)
    db.commit()
    try:
        user_info = adapter.get_user_info(cookies)
    except Exception as exc:
        _save_state(session, cookies, sync_creator, **metadata)
        db.commit()
        _fail_session(db, session, exc, "profile")
    if metadata.get('target_creator_account_id'):
        target = db.get(PlatformAccount, metadata['target_creator_account_id'])
        expected = metadata.get('expected_external_user_id')
        if (target is None or target.user_id != current_user.id or target.external_user_id != expected
                or not expected or user_info.get('external_user_id') != expected):
            _expire_session(db, session)
            raise HTTPException(409, '扫码账号与待修复的发布账号不一致。未替换账号、登录信息或笔记，请使用正确账号重新扫码。')
    try:
        account, action = _create_account_from_login(
            db=db,
            user_id=current_user.id,
            sub_type=session.sub_type,
            user_info=user_info,
            cookies=cookies,
        )
        metadata.update(account_id=account.id, account_action=action)
        if session.sub_type == "pc" and sync_creator:
            creator_account = _sync_creator_account_from_pc_login(
                db=db,
                user_id=current_user.id,
                pc_cookies=cookies,
                creator_adapter=creator_adapter,
                expected_external_user_id=user_info.get('external_user_id'),
            )
            if creator_account:
                metadata.update(creator_account_id=creator_account["id"], creator_account_action=creator_account.get("action"))
        session.status = "confirmed"
        _save_state(session, cookies, sync_creator, **metadata)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(500, "登录已确认，但本机账号保存未完成；请重试，已有账号保持不变。") from None
    return _confirmed_response(db, session, metadata)


@router.post("/pc/phone/send-code")
def pc_phone_send_code(
    payload: PhoneSendCodeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsPcLoginAdapter = Depends(get_pc_login_adapter),
):
    try:
        result = adapter.create_phone_session(payload.phone)
    except Exception as exc:
        raise _login_error(exc, "send") from None
    session = LoginSession(
        user_id=current_user.id,
        platform="xhs",
        sub_type="pc",
        login_method="phone",
        phone_mask=_mask_phone(payload.phone),
        status="pending",
        encrypted_temp_cookies=encrypt_text(
            _dump_temp_state(result["cookies"], sync_creator=payload.sync_creator, phone_digest=_phone_digest(payload.phone))
        ),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"session_id": session.id, "status": session.status, "message": result.get("message", "sent")}


@router.post("/pc/phone/confirm")
def pc_phone_confirm(
    payload: PhoneConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsPcLoginAdapter = Depends(get_pc_login_adapter),
    creator_adapter: XhsCreatorLoginAdapter = Depends(get_creator_login_adapter),
):
    return _confirm_phone_login(payload, current_user, db, adapter, "pc", creator_adapter)


@router.post("/creator/phone/send-code")
def creator_phone_send_code(
    payload: PhoneSendCodeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsCreatorLoginAdapter = Depends(get_creator_login_adapter),
):
    try:
        result = adapter.create_phone_session(payload.phone)
    except Exception as exc:
        raise _login_error(exc, "send") from None
    session = LoginSession(
        user_id=current_user.id,
        platform="xhs",
        sub_type="creator",
        login_method="phone",
        phone_mask=_mask_phone(payload.phone),
        status="pending",
        encrypted_temp_cookies=encrypt_text(_dump_temp_state(result["cookies"], phone_digest=_phone_digest(payload.phone))),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"session_id": session.id, "status": session.status, "message": result.get("message", "sent")}


@router.post("/creator/phone/confirm")
def creator_phone_confirm(
    payload: PhoneConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsCreatorLoginAdapter = Depends(get_creator_login_adapter),
):
    return _confirm_phone_login(payload, current_user, db, adapter, "creator", None)


def _confirm_phone_login(
    payload: PhoneConfirmRequest,
    current_user: User,
    db: Session,
    adapter,
    sub_type: str,
    creator_adapter: XhsCreatorLoginAdapter | None,
):
    with _SESSION_LOCKS[payload.session_id % len(_SESSION_LOCKS)]:
        db.expire_all()
        return _confirm_phone_session(payload, current_user, db, adapter, sub_type, creator_adapter)


def _confirm_phone_session(payload, current_user, db, adapter, sub_type, creator_adapter):
    session = db.get(LoginSession, payload.session_id)
    if (
        session is None
        or session.user_id != current_user.id
        or session.sub_type != sub_type
        or session.login_method != "phone"
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Login session not found")
    metadata = _metadata(session)
    expected_phone = metadata.get("phone_digest")
    matches_phone = hmac.compare_digest(expected_phone, _phone_digest(payload.phone)) if expected_phone else session.phone_mask == _mask_phone(payload.phone)
    if not matches_phone:
        raise HTTPException(409, "手机号已变化，请为当前手机号重新获取验证码；不会使用旧手机号的登录会话。")
    if session.status == "confirmed":
        return _confirmed_response(db, session, metadata)
    if _session_expired(session):
        _expire_session(db, session)
        raise HTTPException(410, "本次短信登录会话已过期，请重新获取验证码。")
    cookies, stored_sync_creator = _load_temp_state(decrypt_text(session.encrypted_temp_cookies))
    sync_creator = payload.sync_creator if payload.sync_creator is not None else stored_sync_creator
    try:
        result = {"status": "confirmed", "cookies": cookies} if metadata.get("authenticated") else adapter.confirm_phone_login(payload.phone, payload.code, cookies)
    except Exception as exc:
        _fail_session(db, session, exc, "confirm")
    if result.get("status") != "confirmed":
        raise HTTPException(502, "登录服务尚未确认验证码，请按平台提示完成验证后重试。")
    cookies = result["cookies"]
    metadata["authenticated"] = True
    _save_state(session, cookies, sync_creator, **metadata)
    db.commit()
    try:
        user_info = adapter.get_user_info(cookies)
    except Exception as exc:
        _save_state(session, cookies, sync_creator, **metadata)
        db.commit()
        _fail_session(db, session, exc, "profile")
    try:
        account, action = _create_account_from_login(
            db=db,
            user_id=current_user.id,
            sub_type=sub_type,
            user_info=user_info,
            cookies=cookies,
        )
        metadata.update(account_id=account.id, account_action=action)
        if sub_type == "pc" and creator_adapter is not None and sync_creator:
            creator_account = _sync_creator_account_from_pc_login(
                db=db, user_id=current_user.id, pc_cookies=cookies, creator_adapter=creator_adapter,
                expected_external_user_id=user_info.get('external_user_id'),
            )
            if creator_account:
                metadata.update(creator_account_id=creator_account["id"], creator_account_action=creator_account.get("action"))
        session.status = "confirmed"
        _save_state(session, cookies, sync_creator, **metadata)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(500, "登录已确认，但本机账号保存未完成；请重试，已有账号保持不变。") from None
    return _confirmed_response(db, session, metadata)
