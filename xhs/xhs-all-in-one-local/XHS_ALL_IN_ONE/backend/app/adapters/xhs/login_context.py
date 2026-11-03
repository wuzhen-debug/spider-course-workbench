"""Bounded short-lived SDK lifecycles for interactive login, without background jobs."""
from __future__ import annotations

import atexit
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import secrets
import threading
import time
from typing import Any

from .login_errors import XhsLoginError

LOGIN_CONTEXT_COOKIE = '__xhs_login_context'


def plain_cookies(cookies: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in cookies.items() if not str(key).startswith('__xhs_')}


def phone_digest(phone: str) -> str:
    return hashlib.sha256(phone.strip().encode()).hexdigest()


@dataclass(repr=False)
class LoginContext:
    api: Any
    platform: str
    method: str
    cookies: dict[str, Any] = field(repr=False)
    expires_at: float
    qr_id: str = field(default='', repr=False)
    qr_code: str = field(default='', repr=False)
    phone_hash: str = field(default='', repr=False)
    authenticated: bool = False


class LoginContextRegistry:
    def __init__(self, *, limit: int = 64, clock=time.monotonic):
        self.limit = limit
        self.clock = clock
        self._contexts: dict[str, LoginContext] = {}
        # SDK/profile/http objects are mutable; serialize their entire operation.
        self._lock = threading.RLock()

    def _drop(self, token: str) -> None:
        context = self._contexts.pop(token, None)
        if context is not None:
            try:
                context.api.close()
            except Exception:
                pass

    def _prune(self) -> None:
        for token, context in list(self._contexts.items()):
            if context.expires_at <= self.clock():
                self._drop(token)

    def add(self, api, platform: str, method: str, cookies: dict, *, qr_id: str = '', qr_code: str = '', phone: str = '') -> dict:
        with self._lock:
            self._prune()
            if len(self._contexts) >= self.limit:
                raise XhsLoginError('login_rate_limited', '当前等待绑定的会话过多，请稍后再试。')
            token = secrets.token_urlsafe(32)
            context = LoginContext(api, platform, method, plain_cookies(cookies), self.clock() + (300 if method == 'qr' else 480), qr_id, qr_code, phone_digest(phone) if phone else '')
            self._contexts[token] = context
            return self.export(token, context)

    @staticmethod
    def export(token: str, context: LoginContext) -> dict:
        return {**plain_cookies(context.cookies), LOGIN_CONTEXT_COOKIE: token}

    @contextmanager
    def use(self, cookies: dict, platform: str, *, method: str | None = None, qr_id: str | None = None, qr_code: str | None = None, phone: str | None = None):
        with self._lock:
            self._prune()
            token = cookies.get(LOGIN_CONTEXT_COOKIE)
            context = self._contexts.get(token) if isinstance(token, str) else None
            if context is None:
                raise XhsLoginError('login_session_expired', '登录会话已过期或后台已重启，请重新获取二维码或验证码。')
            if context.platform != platform or (method is not None and method != context.method) or (qr_id is not None and context.qr_id != qr_id) or (qr_code is not None and context.qr_code != qr_code):
                raise XhsLoginError('login_context_mismatch', '当前登录会话不匹配，请重新获取二维码或验证码。')
            if phone is not None and phone_digest(phone) != context.phone_hash:
                raise XhsLoginError('phone_mismatch', '手机号与本次接收短信的号码不同，请使用原号码或重新获取验证码。')
            yield token, context

    def release(self, token: str) -> None:
        with self._lock:
            self._drop(token)

    def clear(self) -> None:
        with self._lock:
            for token in list(self._contexts):
                self._drop(token)


login_contexts = LoginContextRegistry()
atexit.register(login_contexts.clear)
