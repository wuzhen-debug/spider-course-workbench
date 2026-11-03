"""Local credential coverage, never a claim that a post has been accepted."""
from sqlalchemy import select
from backend.app.models import AccountCookieVersion, PlatformAccount
from backend.app.services.account_service import decode_cookie_text


def latest_cookie(db, account_id):
    return db.scalar(select(AccountCookieVersion).where(AccountCookieVersion.platform_account_id == account_id)
                     .order_by(AccountCookieVersion.created_at.desc(), AccountCookieVersion.id.desc()))


def same_account_pc(db, creator):
    if not creator.external_user_id:
        return None
    return db.scalar(select(PlatformAccount).where(PlatformAccount.user_id == creator.user_id,
        PlatformAccount.platform == 'xhs', PlatformAccount.sub_type == 'pc',
        PlatformAccount.external_user_id == creator.external_user_id).order_by(PlatformAccount.id.desc()))


def credential_coverage(cookies_text):
    try:
        cookies = decode_cookie_text(cookies_text)
        present = bool(cookies.get('web_session'))
    except (ValueError, TypeError):
        present = False
    return {'state': 'available' if present else 'pc_login_required', 'publish_permission': 'not_tested'}


def require_publish_credentials(cookies_text):
    if credential_coverage(cookies_text)['state'] != 'available':
        from fastapi import HTTPException
        raise HTTPException(409, '发布登录尚未补全：当前只有创作中心登录，请用同一小红书账号完成PC登录并同步Creator。未上传素材、未提交笔记。')
