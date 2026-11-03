"""Safe login failures: never return upstream URLs, credentials or response bodies."""
from __future__ import annotations

import re


class XhsLoginError(RuntimeError):
    def __init__(self, error_code: str, public_message: str, *, retryable: bool = False, upstream_status: int | None = None):
        super().__init__(public_message)
        self.error_code = error_code
        self.public_message = public_message
        self.retryable = retryable
        self.upstream_status = upstream_status


def login_failure(error: object, stage: str) -> XhsLoginError:
    if isinstance(error, XhsLoginError):
        return error
    # Read only for categorization; no raw text is retained in the error.
    text = str(error).lower()
    match = re.search(r'(?:http(?:/\d(?:\.\d)?)?\s*[:=]?\s*|status(?:_code)?\s*[:=]\s*)([45]\d\d)', text)
    upstream = int(match.group(1)) if match else None
    if upstream in {406, 461, 471} or any(value in text for value in ['captcha', 'verifytype', '人机', '滑块', '安全验证', '风控']):
        return XhsLoginError('login_verification_required', '小红书拒绝了当前登录请求，请先在官方页面查看并完成验证，再重新绑定。', upstream_status=upstream)
    if upstream == 429 or any(value in text for value in ['频繁', '稍后再试', 'too many', 'rate limit']):
        return XhsLoginError('login_rate_limited', '小红书提示请求过于频繁，请稍后再试，不要连续获取二维码或短信。', upstream_status=upstream)
    if any(value in text for value in ['验证码错误', '验证码不正确', '验证码已过期', '验证码失效', '验证码验证失败', 'invalid code', 'code expired']):
        return XhsLoginError('login_code_invalid', '小红书未通过验证码校验，请核对本次短信；过期后重新获取。', retryable=True, upstream_status=upstream)
    if isinstance(error, (TimeoutError, ConnectionError)) or any(value in text for value in ['could not resolve', 'couldn\'t resolve', 'dns', 'timed out', 'timeout', 'connection', 'network', 'curl: (6)', 'curl: (28)']):
        return XhsLoginError('login_network_error', '后台连接小红书失败，请检查网络后重试；这不代表验证码错误。', retryable=True, upstream_status=upstream)
    if isinstance(error, (KeyError, TypeError, ValueError)) or any(value in text for value in ['missing', '缺少', 'not json', '未知状态']):
        return XhsLoginError('login_protocol_error', '小红书登录响应格式异常，未绑定账号；请重新获取登录会话。', upstream_status=upstream)
    if stage == 'profile':
        return XhsLoginError('login_profile_failed', '登录已确认，但账号信息读取失败，请重试完成绑定；无需重复输入验证码。', retryable=True, upstream_status=upstream)
    return XhsLoginError('login_platform_rejected', '小红书未接受本次登录请求，未绑定账号。请查看官方登录页提示后重试。', upstream_status=upstream)
