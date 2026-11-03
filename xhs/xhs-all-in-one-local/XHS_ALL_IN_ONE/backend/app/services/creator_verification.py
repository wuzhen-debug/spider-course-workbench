"""Hand off server-requested 209 challenges to the real official UI.

No challenge is solved here, and no note request is sent or retried. The
official fe-login bundle maps 209 to showQRCode. A live browser check confirmed
that opening its captcha page without the original verifyUuid did NOT give a
usable QR code, so missing historical contexts never get a fabricated link.
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import urlencode

from backend.app.core.security import decrypt_text, encrypt_text

PRIVATE_CONTEXT_KEY = "_creator_verification_encrypted"
CONTEXT_TTL_SECONDS = 15 * 60  # Local retention limit, not a platform expiry claim.
OFFICIAL_CAPTCHA = "https://www.xiaohongshu.com/web-login/captcha"
OFFICIAL_RETURN = "https://creator.xiaohongshu.com/publish/publish"


def capture_verification(response) -> dict | None:
    if response.status_code not in {461, 471}:
        return None
    headers = {str(k).lower(): str(v) for k, v in (getattr(response, "headers", None) or {}).items()}
    verify_uuid = headers.get("verifyuuid", "")
    if headers.get("verifytype") != "209" or not re.fullmatch(r"[A-Za-z0-9_.:-]{8,256}", verify_uuid):
        return None
    result = {"verify_uuid": verify_uuid, "verify_type": "209", "http_status": response.status_code}
    biz = headers.get("x-biz", "")
    if re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", biz):
        result["biz"] = biz
    return result


def seal_verification(context: dict, *, user_id: int, job_id: int, account_id: int, task_id: int) -> str:
    return encrypt_text(json.dumps({"context": context, "user_id": user_id, "job_id": job_id,
        "account_id": account_id, "task_id": task_id, "issued_at": time.time()}, separators=(",", ":")))


def official_verification_url(context: dict, *, http_status: int) -> str:
    params = {"redirectPath": OFFICIAL_RETURN, "callFrom": "web", "verifyType": "209",
        "verifyBiz": str(http_status), "platform": "web"}
    params["verifyUuid"] = context["verify_uuid"]
    if context.get("biz"):
        params["biz"] = context["biz"]
    return OFFICIAL_CAPTCHA + "?" + urlencode(params)


def verification_handoff(task, job) -> dict:
    """Return only an owned job's latest challenge; callers must authenticate."""
    payload = task.payload or {}
    diagnostics = payload.get("creator_response_diagnostics", {})
    result = {"job_id": job.id, "account_id": job.platform_account_id, "task_id": task.id,
        "verification_type": diagnostics.get("verification_type"),
        "automatic_retry": False, "will_publish": False, "state": "not_required"}
    if diagnostics.get("http_status") not in {461, 471} or diagnostics.get("verification_type") != "209":
        return result
    confirmation = payload.get("creator_verification_user_confirmation")
    if isinstance(confirmation, dict) and confirmation.get("task_id") == task.id:
        return {**result, "state": "reported_verified", "method": "qr_code", "official_url": None,
            "user_confirmed_at": confirmation.get("confirmed_at"),
            "message": "手机扫码已由本人确认完成。尚未再次提交笔记；接口是否恢复仍待验证，不会自动重试。"}
    result.update(method="qr_code", state="legacy_missing",
        message="209 要求本人扫码确认身份，但旧请求的验证编号未保存，无法还原本次二维码。获取新编号需要再次提交发布请求，可能真正发布；当前未执行。",
        official_url=None)
    encrypted = payload.get(PRIVATE_CONTEXT_KEY)
    if not encrypted:
        return result
    # Encrypted contexts are bound to the exact owner, job, account and task.
    try:
        saved = json.loads(decrypt_text(encrypted))
        if any(saved.get(k) != v for k, v in {"user_id": job.user_id, "job_id": job.id,
            "account_id": job.platform_account_id, "task_id": task.id}.items()):
            raise ValueError("Context binding mismatch")
        age = time.time() - float(saved["issued_at"])
        if not 0 <= age <= CONTEXT_TTL_SECONDS:
            return {**result, "state": "expired", "official_url": None,
                "message": "本次验证入口已超过本机保留时限。未重新提交笔记；请勿连续重试。"}
        context = saved["context"]
        if (context["verify_type"] != "209" or context["http_status"] not in {461, 471}
                or not re.fullmatch(r"[A-Za-z0-9_.:-]{8,256}", context["verify_uuid"])):
            raise ValueError("Invalid verification context")
        return {**result, "state": "available", "official_url": official_verification_url(context, http_status=context["http_status"]),
            "expires_in_seconds": int(CONTEXT_TTL_SECONDS - age),
            "message": "请用登录该小红书账号的 App 扫码，并在手机确认。这是本次请求的官方验证页；完成后不会自动发布或重试。"}
    except Exception:
        return {**result, "state": "unavailable", "official_url": None,
            "message": "本次验证信息无法安全恢复。未提交笔记，请勿连续重试。"}
