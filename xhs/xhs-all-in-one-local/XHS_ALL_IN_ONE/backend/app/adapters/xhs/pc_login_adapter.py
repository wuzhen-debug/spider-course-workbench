from __future__ import annotations

from typing import Any

from backend.app.adapters.xhs.request_env import direct_xhs_request_env
from backend.app.adapters.xhs.login_context import LOGIN_CONTEXT_COOKIE, login_contexts, plain_cookies
from backend.app.adapters.xhs.login_errors import XhsLoginError, login_failure


class XhsPcLoginAdapter:
    def create_qrcode(self) -> dict[str, Any]:
        with direct_xhs_request_env():
            from apis.xhs_pc_login_apis import XHSLoginApi

            api = XHSLoginApi()
            try:
                cookies = api.generate_init_cookies()
                success, message, payload = api.generate_qrcode(cookies)
                if not success or not payload:
                    raise login_failure(message, 'qr')
                if not all(payload.get(key) for key in ('qr_id', 'code', 'qr_url')):
                    raise ValueError('missing qr fields')
                # Follow this pinned SDK's own QR login order: initial poll,
                # report profile, then expose the QR for the user to scan.
                initial, message, cookies = api.check_qrcode_status(payload['qr_id'], payload['code'], payload['cookies'])
                if initial or message != '请扫描二维码':
                    raise login_failure(message or ValueError('missing qr status'), 'qr')
                api.ensure_webprofile(cookies)
                stored = login_contexts.add(api, 'pc', 'qr', cookies, qr_id=payload['qr_id'], qr_code=payload['code'])
                return {'cookies': stored, 'qr_id': payload['qr_id'], 'code': payload['code'], 'qr_url': payload['qr_url']}
            except Exception as exc:
                api.close()
                raise login_failure(exc, 'qr') from None

    def check_qrcode_status(self, qr_id: str, code: str, cookies: dict[str, Any]) -> dict[str, Any]:
        with direct_xhs_request_env(), login_contexts.use(cookies, 'pc', method='qr', qr_id=qr_id, qr_code=code) as (token, context):
            try:
                if context.authenticated:
                    return {'status': 'confirmed', 'cookies': login_contexts.export(token, context)}
                success, message, updated = context.api.check_qrcode_status(qr_id, code, context.cookies)
                context.cookies = plain_cookies(updated)
                if success:
                    status = 'confirmed'
                    context.authenticated = True
                elif message == '请扫描二维码':
                    status = 'pending'
                elif message == '请确认登录':
                    status = 'scanned'
                elif message == '二维码已过期':
                    status = 'expired'
                else:
                    raise login_failure(message or ValueError('missing qr status'), 'qr')
                result = {'status': status, 'cookies': login_contexts.export(token, context)}
                if status == 'expired':
                    result['cookies'] = plain_cookies(context.cookies)
                    login_contexts.release(token)
                return result
            except Exception as exc:
                raise login_failure(exc, 'qr') from None

    def get_user_info(self, cookies: dict[str, Any]) -> dict[str, Any]:
        if LOGIN_CONTEXT_COOKIE in cookies:
            with direct_xhs_request_env(), login_contexts.use(cookies, 'pc') as (token, context):
                if not context.authenticated:
                    raise XhsLoginError('login_profile_failed', '请先完成手机确认或验证码校验，再读取账号信息。')
                try:
                    success, data, updated = context.api.get_user_info(context.cookies)
                    if not success or not data.get('user_id') or data.get('guest') is not False:
                        raise login_failure('profile not accepted', 'profile')
                    context.cookies = plain_cookies(updated)
                    final = context.api._cookies_for_url(context.api.base_url, context.cookies)
                    cookies.clear(); cookies.update(plain_cookies(final))
                    result = self._user_info(data)
                    login_contexts.release(token)
                    return result
                except Exception as exc:
                    raise login_failure(exc, 'profile') from None
        with direct_xhs_request_env():
            from apis.xhs_pc_login_apis import XHSLoginApi
            api = XHSLoginApi()
            try:
                success, data, _ = api.get_user_info(plain_cookies(cookies))
                if not success or not data.get('user_id'):
                    raise login_failure('profile not accepted', 'profile')
                return self._user_info(data)
            except Exception as exc:
                raise login_failure(exc, 'profile') from None
            finally:
                api.close()

    @staticmethod
    def _user_info(data: dict[str, Any]) -> dict[str, Any]:
        return {
            "external_user_id": data.get("user_id", ""),
            "nickname": data.get("nickname", ""),
            "avatar_url": data.get("images") or data.get("imageb") or "",
            "profile": {
                "red_id": data.get("red_id") or data.get("redId") or "",
                "followers": data.get("fans") or data.get("followers") or data.get("follower_count"),
                "following": data.get("follows") or data.get("following") or data.get("following_count"),
                "likes": data.get("liked_count") or data.get("likes") or data.get("like_count"),
                "raw": data,
            },
        }

    def create_phone_session(self, phone: str) -> dict[str, Any]:
        with direct_xhs_request_env():
            from apis.xhs_pc_login_apis import XHSLoginApi

            api = XHSLoginApi()
            try:
                cookies = api.generate_init_cookies()
                api.ensure_webprofile(cookies)
                success, message, _ = api.send_phone_code(phone, cookies)
                if not success:
                    raise login_failure(message, 'send')
                stored = login_contexts.add(api, 'pc', 'phone', cookies, phone=phone)
                return {'cookies': stored, 'message': '验证码已发送，请查看手机短信。'}
            except Exception as exc:
                api.close()
                raise login_failure(exc, 'send') from None

    def confirm_phone_login(self, phone: str, code: str, cookies: dict[str, Any]) -> dict[str, Any]:
        with direct_xhs_request_env(), login_contexts.use(cookies, 'pc', method='phone', phone=phone) as (token, context):
            try:
                if not context.authenticated:
                    success, message, payload = context.api.login_by_phone(phone, code, context.cookies)
                    if not success or not payload:
                        raise login_failure(message, 'confirm')
                    context.cookies = plain_cookies(payload['cookies'])
                    context.authenticated = True
                return {'status': 'confirmed', 'cookies': login_contexts.export(token, context)}
            except Exception as exc:
                raise login_failure(exc, 'confirm') from None
