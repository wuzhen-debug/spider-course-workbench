from __future__ import annotations

from typing import Any

from backend.app.adapters.xhs.request_env import direct_xhs_request_env
from backend.app.adapters.xhs.login_context import LOGIN_CONTEXT_COOKIE, login_contexts, plain_cookies
from backend.app.adapters.xhs.login_errors import XhsLoginError, login_failure


class XhsCreatorLoginAdapter:
    def exchange_from_user_cookies(self, user_cookies: dict[str, Any]) -> dict[str, Any]:
        with direct_xhs_request_env():
            from xhs_utils.xhs_pc.auth import XHSPcAuth
            from xhs_utils.xhs_creator.auth import XHSCreatorAuth

            # The pinned SDK exposes the authenticated PC -> Creator bridge on
            # Auth. The old LoginApi exchange method no longer exists.
            pc_auth = XHSPcAuth.from_cookie(dict(user_cookies))
            creator_auth = None
            try:
                creator_auth = XHSCreatorAuth.from_pc_auth(pc_auth)
                cookies = creator_auth.cookies_for_url(creator_auth.origin("api"))
                return {"status": "confirmed", "cookies": cookies}
            finally:
                if creator_auth is not None:
                    creator_auth.close()
                pc_auth.close()

    def create_qrcode(self) -> dict[str, Any]:
        with direct_xhs_request_env():
            from apis.xhs_creator_login_apis import XHSCreatorLoginApi
            api = XHSCreatorLoginApi()
            try:
                cookies, _ = api._prepare_login_session()
                api._complete_security()
                success, message, payload = api.generate_qrcode(api.profile.cookie_map)
                if not success or not payload:
                    raise login_failure(message, 'qr')
                if not payload.get('qr_id') or not payload.get('qr_url'):
                    raise ValueError('missing qr fields')
                stored = login_contexts.add(api, 'creator', 'qr', api.profile.cookie_map, qr_id=payload['qr_id'])
                return {'cookies': stored, 'qr_id': payload['qr_id'], 'qr_url': payload['qr_url']}
            except Exception as exc:
                api.close()
                raise login_failure(exc, 'qr') from None

    def check_qrcode_status(self, qr_id: str, cookies: dict[str, Any]) -> dict[str, Any]:
        with direct_xhs_request_env(), login_contexts.use(cookies, 'creator', method='qr', qr_id=qr_id) as (token, context):
            try:
                if context.authenticated:
                    return {'status': 'confirmed', 'cookies': login_contexts.export(token, context)}
                detail = context.api.query_qrcode_status(qr_id, context.cookies)
                context.cookies = plain_cookies(detail['cookies'])
                status = {1: 'confirmed', 2: 'pending', 3: 'scanned', 4: 'expired'}.get(detail.get('status'))
                if not isinstance(detail.get('res_json'), dict) or detail['res_json'].get('success') is not True or status is None or (status == 'confirmed' and not detail.get('success')):
                    raise login_failure(detail.get('message') or ValueError('missing qr status'), 'qr')
                context.authenticated = status == 'confirmed'
                result = {'status': status, 'cookies': login_contexts.export(token, context)}
                if status == 'expired':
                    result['cookies'] = plain_cookies(context.cookies)
                    login_contexts.release(token)
                return result
            except Exception as exc:
                raise login_failure(exc, 'qr') from None

    def get_user_info(self, cookies: dict[str, Any]) -> dict[str, Any]:
        if LOGIN_CONTEXT_COOKIE in cookies:
            with direct_xhs_request_env(), login_contexts.use(cookies, 'creator') as (token, context):
                if not context.authenticated:
                    raise XhsLoginError('login_profile_failed', '请先完成手机确认或验证码校验，再读取账号信息。')
                try:
                    success, data, updated = context.api.get_user_info(context.cookies)
                    if not success or not data.get('userId'):
                        raise login_failure('profile not accepted', 'profile')
                    context.cookies = plain_cookies(updated)
                    final = context.api._cookies_for_url(context.api.creator_url, context.cookies)
                    cookies.clear(); cookies.update(plain_cookies(final))
                    result = self._user_info(data)
                    login_contexts.release(token)
                    return result
                except Exception as exc:
                    raise login_failure(exc, 'profile') from None
        with direct_xhs_request_env():
            from apis.xhs_creator_apis import XHS_Creator_Apis
            from xhs_utils.xhs_creator import XHSCreatorAuth

            # A persisted or PC-bridged session is already authenticated.
            # A fresh LoginApi has no initialized signing context and fails
            # before sending user/info. Use Auth's business-session lifecycle;
            # keep the live QR/SMS context branch above unchanged.
            auth = None
            try:
                auth = XHSCreatorAuth.from_cookie(plain_cookies(cookies))
                success, _, payload = XHS_Creator_Apis(auth).get_user_info()
                data = (payload or {}).get('data') or {}
                if not success or not data.get('userId'):
                    raise login_failure('profile not accepted', 'profile')
                cookies.clear()
                cookies.update(plain_cookies(auth.cookies_for_url(auth.origin('api'))))
                return self._user_info(data)
            except Exception as exc:
                raise login_failure(exc, 'profile') from None
            finally:
                if auth is not None:
                    auth.close()

    @staticmethod
    def _user_info(data: dict[str, Any]) -> dict[str, Any]:
        return {
            "external_user_id": data.get("userId", ""),
            "nickname": data.get("userName", ""),
            "avatar_url": data.get("userAvatar", ""),
            "profile": {
                "red_id": data.get("redId") or data.get("red_id") or "",
                "role": data.get("role") or "",
                "real_name_verified": data.get("realNameVerified"),
                "followers": data.get("fans") or data.get("followers") or data.get("followerCount"),
                "following": data.get("follows") or data.get("following") or data.get("followingCount"),
                "likes": data.get("likedCount") or data.get("likes") or data.get("likeCount"),
                "raw": data,
            },
        }

    def create_phone_session(self, phone: str) -> dict[str, Any]:
        with direct_xhs_request_env():
            from apis.xhs_creator_login_apis import XHSCreatorLoginApi

            api = XHSCreatorLoginApi()
            try:
                cookies, _ = api._prepare_login_session()
                api._complete_security()
                success, message, _ = api.send_phone_code(phone, api.profile.cookie_map)
                if not success:
                    raise login_failure(message, 'send')
                stored = login_contexts.add(api, 'creator', 'phone', api.profile.cookie_map, phone=phone)
                return {'cookies': stored, 'message': '验证码已发送，请查看手机短信。'}
            except Exception as exc:
                api.close()
                raise login_failure(exc, 'send') from None

    def confirm_phone_login(self, phone: str, code: str, cookies: dict[str, Any]) -> dict[str, Any]:
        with direct_xhs_request_env(), login_contexts.use(cookies, 'creator', method='phone', phone=phone) as (token, context):
            try:
                if not context.authenticated:
                    success, message, payload = context.api.login_by_phone(phone, code, context.cookies)
                    context.cookies = plain_cookies(context.api.profile.cookie_map)
                    if not success or not payload:
                        raise login_failure(message, 'confirm')
                    context.cookies = plain_cookies(payload['cookies'])
                    context.authenticated = True
                return {'status': 'confirmed', 'cookies': login_contexts.export(token, context)}
            except Exception as exc:
                raise login_failure(exc, 'confirm') from None
