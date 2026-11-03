from __future__ import annotations

from typing import Any
from dataclasses import dataclass, field
from contextlib import contextmanager
import re
import time

from backend.app.adapters.xhs.request_env import direct_xhs_request_env
from backend.app.adapters.xhs.publish_validation import validate_note_text
from backend.app.services.creator_verification import capture_verification


@dataclass(repr=False)
class PreparedImageNote:
    """Local preparation result. Credentials and signed data must not be logged."""
    url: str
    headers: dict = field(repr=False)
    cookies: dict = field(repr=False)
    body: str = field(repr=False)
    topic_resolution: list[dict[str, Any]] = field(default_factory=list)


class CreatorRequestRejected(RuntimeError):
    """A rejected response with allowlisted, credential-free diagnostic fields."""
    def __init__(self, message: str, diagnostics: dict[str, Any], *, verification: dict | None = None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics
        # Private, server-issued handoff context; never put it in str/repr/logs.
        self.verification = verification


class XhsCreatorApiAdapter:
    def __init__(self, cookies: str) -> None:
        self.cookies = cookies
        self._session_api = None

    def _api(self):
        from apis.xhs_creator_apis import XHS_Creator_Apis
        from xhs_utils.xhs_creator import XHSCreatorAuth

        auth = XHSCreatorAuth.from_cookie(self.cookies)
        try:
            return XHS_Creator_Apis(auth).bootstrap()
        except Exception:
            auth.close()
            raise

    @contextmanager
    def _api_scope(self):
        if self._session_api is not None:
            yield self._session_api
            return
        api = self._api()
        try:
            yield api
        finally:
            auth = getattr(api, "auth", None)
            if auth is not None:
                auth.close()

    @contextmanager
    def session(self):
        """Retain server-issued cookies across one upload/submit operation."""
        with direct_xhs_request_env(), self._api_scope() as api:
            previous = self._session_api
            self._session_api = api
            try:
                yield self
            finally:
                self._session_api = previous

    def inspect_session(self) -> None:
        """Only read login/identity. Never request an upload permit or post a note."""
        with direct_xhs_request_env(), self._api_scope() as api:
            self.check_publish_session(api)

    def get_topic(self, keyword: str) -> Any:
        with direct_xhs_request_env(), self._api_scope() as api:
            return self._query_topic(api, keyword)

    def get_location_info(self, keyword: str) -> Any:
        with direct_xhs_request_env(), self._api_scope() as api:
            return self._query_location(api, keyword)

    @staticmethod
    def _response_diagnostics(response, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {str(key).lower(): str(value) for key, value in
                   (getattr(response, "headers", None) or {}).items()}
        status = response.status_code
        result = {"http_status": status,
            "kind": "security_verification" if status in {461, 471} else "http_rejection",
            "verification_headers_present": [key for key in
                ("verifytype", "verifyuuid", "riskuuid", "verifymsg", "resultpolicy") if key in headers],
            "verification_id_present": bool(headers.get("verifyuuid") or headers.get("riskuuid")),
            "automatic_retry": False}
        if isinstance(payload.get("code"), int) or (
            isinstance(payload.get("code"), str) and re.fullmatch(r"-?\d{1,10}", payload["code"])):
            result["platform_code"] = payload["code"]
        if isinstance(payload.get("success"), bool):
            result["body_success"] = payload["success"]
        for header, key in (("verifytype", "verification_type"), ("resultpolicy", "result_policy")):
            if re.fullmatch(r"\d{1,6}", headers.get(header, "")):
                result[key] = headers[header]
        return result

    @classmethod
    def _parse_creator_response(cls, response, operation: str) -> tuple[bool, str, dict[str, Any]]:
        """`msg` is optional, including on HTTP 406/code=-1 rejections."""
        http_status = response.status_code
        try:
            payload = response.json()
        except ValueError:
            if http_status in {461, 471}:
                payload = {}
            else:
                return False, f"{operation}返回非 JSON 响应（HTTP {http_status}）", {}
        if not isinstance(payload, dict) and http_status in {461, 471}:
            payload = {}
        if not isinstance(payload, dict):
            return False, f"{operation}返回格式异常（HTTP {http_status}）", {}

        message = next((value.strip() for key in ("msg", "message", "error_msg")
                        if isinstance(value := payload.get(key), str) and value.strip()), "")
        success = http_status < 400 and payload.get("success") is True
        if success:
            return True, message or "成功", payload

        detail = f"HTTP {http_status}"
        if isinstance(payload.get("code"), (str, int)):
            detail += f"，code={payload['code']}"
        message = f"{operation}失败（{detail}）" + (f"：{message}" if message else "")
        if http_status in {461, 471}:
            diagnostics = cls._response_diagnostics(response, payload)
            verify_type = diagnostics.get("verification_type")
            if verify_type == "301":
                message = f"{operation}被平台要求重新登录（{detail}，verifytype=301）。请本人在官方创作中心重新登录。未自动重试。"
            elif verify_type == "302":
                message = f"{operation}被平台要求刷新页面（{detail}，verifytype=302）。请本人刷新官方创作中心。未自动重试。"
            elif verify_type == "209":
                message = f"{operation}需要扫码安全验证（{detail}，verifytype=209）。请打开本次请求的官方扫码验证入口，由本人在手机确认。正常登录不等于已完成此验证。未自动重试。"
            else:
                extra = f"，verifytype={verify_type}" if verify_type else ""
                message = f"{operation}触发平台安全验证（{detail}{extra}）。账号已登录时也可能出现；请本人在官方页面处理平台提示。未自动重试。"
        elif http_status in {401, 403, 406}:
            message += "。小红书拒绝了此接口请求，请在官方创作中心检查登录状态或平台提示。"
        return False, message, payload

    @classmethod
    def _lookup(cls, api, path: str, data: dict[str, Any], operation: str, *, target_origin=None, referer=None, sec_fetch_site="same-site"):
        from xhs_utils.http_util import REQUEST_TIMEOUT

        origin = target_origin or api.edith_url
        headers, cookies, body = api._request_params(path, data, "POST", target_origin=origin,
            referer=referer, sec_fetch_site=sec_fetch_site)
        response = api.http.post(
            origin + path,
            headers=headers,
            cookies=cookies,
            data=body.encode("utf-8"),
            proxies=api._proxies(),
            timeout=REQUEST_TIMEOUT,
        )
        return cls._parse_creator_response(response, operation)

    @classmethod
    def _query_topic(cls, api, keyword: str):
        # Current official publish UI: module 34563/JD, with the common HTTP
        # wrapper converting topicRoundStartTime to topic_round_start_time.
        success, message, payload = cls._lookup(api, "/api/galaxy/v2/creator/servicegw/v2/search/topics", {
            "keyword": keyword,
            "topic_round_start_time": int(time.time() * 1000),
            "content": "",
        }, "话题查询", target_origin=api.base_url,
            referer=f"{api.base_url}/publish/publish?from=menu&target=image", sec_fetch_site="same-origin")
        if not success:
            return success, message, payload
        data = payload.get("data")
        if not isinstance(data, dict):
            return False, "话题查询返回格式异常：缺少 data 对象", payload
        if "topics" in data:
            if not isinstance(data["topics"], list):
                return False, "话题查询返回格式异常：topics 不是列表", payload
            topics = []
            for item in data["topics"]:
                if not isinstance(item, dict):
                    continue
                topic = item.get("topic_info_dto") or item.get("topicInfoDto")
                if isinstance(topic, dict) and topic.get("id") and topic.get("name"):
                    topics.append(topic)
            # Preserve the existing adapter/API result shape for consumers.
            payload = {**payload, "data": {**data, "topic_info_dtos": topics}}
        return success, message, payload

    @classmethod
    def _query_location(cls, api, keyword: str):
        from xhs_utils.xhs_creator_util import get_loc_data

        return cls._lookup(api, "/web_api/sns/v1/local/poi/creator/search", get_loc_data(keyword), "地点查询")

    def get_published_notes(self) -> Any:
        with direct_xhs_request_env(), self._api_scope() as api:
            return api.get_all_posted_notes()

    def upload_media(self, file_path: str, media_type: str) -> dict[str, Any]:
        file_data = self._resolve_file_data(file_path)
        with direct_xhs_request_env(), self._api_scope() as api:
            success, message, payload = api.upload_media(file_data, media_type)
        if not success:
            raise RuntimeError(message or "Creator media upload failed")
        return payload or {}

    @staticmethod
    def _resolve_file_data(file_path: str) -> bytes:
        import pathlib
        raw_bytes: bytes | None = None

        if file_path.startswith("http://") or file_path.startswith("https://"):
            import requests
            resp = requests.get(file_path, timeout=30, headers={"Referer": ""})
            resp.raise_for_status()
            raw_bytes = resp.content
        elif file_path.startswith("/api/files/media/"):
            from backend.app.core.config import get_settings
            file_name = file_path.split("/")[-1]
            local = pathlib.Path(get_settings().storage_dir) / "media" / file_name
            if local.is_file():
                raw_bytes = local.read_bytes()
        else:
            p = pathlib.Path(file_path)
            if p.is_file():
                raw_bytes = p.read_bytes()

        if raw_bytes is None:
            raise FileNotFoundError(f"素材文件不存在: {file_path}")

        lower = file_path.lower()
        if lower.endswith(".webp") or (len(raw_bytes) > 4 and raw_bytes[:4] == b"RIFF"):
            try:
                import io
                from PIL import Image
                img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=92)
                raw_bytes = buf.getvalue()
            except Exception:
                pass

        return raw_bytes

    def post_note(self, note_info: dict[str, Any]) -> dict[str, Any]:
        validate_note_text(note_info.get("title", ""), note_info.get("desc", ""))
        with direct_xhs_request_env():
            if note_info.get("media_type") == "image" and note_info.get("image_file_infos"):
                return self._post_uploaded_image_note(note_info)

            with self._api_scope() as api:
                success, message, payload = api.post_note(note_info)
        if not success:
            raise RuntimeError(message or "Creator note publish failed")
        return payload or {}

    def check_publish_session(self, api) -> dict[str, Any]:
        """Read the publish page's identity status and retain Edith host cookies.

        `verified` is real-name status, not the HTTP authentication result. It
        must not be mistaken for the platform's 461 captcha or a publish result.
        """
        from xhs_utils.http_util import REQUEST_TIMEOUT

        path = "/web_api/sns/v6/creator/user/verify"
        headers, cookies, _ = api._request_params(path, "", "GET",
            target_origin=api.edith_url, referer=f"{api.base_url}/")
        response = api.http.get(api.edith_url + path, headers=headers, cookies=cookies,
            proxies=api._proxies(), timeout=REQUEST_TIMEOUT)
        auth = getattr(api, "auth", None)
        if auth is not None:
            auth.update_cookies(getattr(response, "cookies", {}), source_url=api.edith_url + path)
        success, message, payload = self._parse_creator_response(response, "发布会话只读检查")
        if not success:
            if response.status_code == 401:
                message = "发布会话缺少有效的跨站登录信息（HTTP 401）。请在账号矩阵使用同账号 PC 登录并同步 Creator，再检查发布会话。未提交笔记。"
            raise CreatorRequestRejected(message, self._response_diagnostics(response, payload), verification=capture_verification(response))
        return payload

    def _post_uploaded_image_note(self, note_info: dict[str, Any]) -> dict[str, Any]:
        from xhs_utils.http_util import REQUEST_TIMEOUT

        with self._api_scope() as api:
            self.check_publish_session(api)
            prepared = self.prepare_uploaded_image_note(api, note_info)
            response = api.http.post(
                prepared.url,
                headers=prepared.headers,
                data=prepared.body.encode("utf-8"),
                cookies=prepared.cookies,
                proxies=api._proxies(),
                timeout=REQUEST_TIMEOUT,
            )
            success, message, payload = self._parse_creator_response(response, "笔记发布")
            if not success:
                raise CreatorRequestRejected(message, self._response_diagnostics(response, payload), verification=capture_verification(response))
            return payload

    def prepare_uploaded_image_note(self, api, note_info: dict[str, Any]) -> PreparedImageNote:
        """Resolve read-only lookups and sign locally; never upload or publish."""
        from xhs_utils.xhs_creator_util import (
            get_post_note_image_data,
            load_creator_rap_fingerprint_hex,
        )
        from xhs_utils.xhs_pc.params import generate_x_rap_param

        validate_note_text(note_info.get("title", ""), note_info.get("desc", ""))
        post_api = "/web_api/sns/v2/note"
        post_loc = {}
        location = note_info.get("location")
        if isinstance(location, dict):
            post_loc = location
        elif isinstance(location, str) and location.strip():
            success, message, location_info = self._query_location(api, location.strip())
            if not success:
                raise RuntimeError(message or "Creator location lookup failed")
            poi_list = (location_info.get("data") or {}).get("poi_list") or []
            if not poi_list:
                raise RuntimeError("未找到该地点")
            poi = poi_list[0]
            post_loc = {
                "name": poi["name"],
                "subname": poi["full_address"],
                "poi_id": poi["poi_id"],
                "poi_type": poi["poi_type"],
            }
        data = get_post_note_image_data(
            note_info.get("title", ""),
            note_info.get("desc", ""),
            note_info.get("postTime"),
            post_loc,
            note_info.get("type", 1),
            note_info["image_file_infos"],
        )
        # 浏览器实抓：未选地点时省略 post_loc 键，空对象会被服务端以参数错误打回
        if not post_loc:
            data["common"].pop("post_loc", None)
        topic_resolution = []
        seen_topics = set()
        for topic in note_info.get("topics") or []:
            if not isinstance(topic, str) or not topic.strip():
                continue
            topic = topic.strip().lstrip("#").strip()
            key = topic.casefold()
            if not key or key in seen_topics:
                continue
            seen_topics.add(key)
            success, message, topic_payload = self._query_topic(api, topic)
            if not success:
                raise RuntimeError(message or "Creator topic lookup failed")
            topic_items = (topic_payload.get("data") or {}).get("topic_info_dtos") or []
            item = next((item for item in topic_items
                         if str(item.get("name", "")).strip().casefold() == key), None)
            if item is None:
                # Search ranking is fuzzy. Never attach an unrelated first result.
                raise RuntimeError(f"未找到同名话题“{topic}”，请移除或重新选择，避免误挂相似话题")
            insert_topic = {
                "id": item["id"],
                "link": item.get("link", ""),
                "name": item["name"],
                "type": "topic",
            }
            data["common"]["hash_tag"].append(insert_topic)
            marker = f"#{insert_topic['name']}[话题]#"
            if marker not in data["common"]["desc"]:
                data["common"]["desc"] += f" {marker} "
            topic_resolution.append({"requested": topic, "linked": True, "name": item["name"]})
        validate_note_text(data["common"].get("title", note_info.get("title", "")), data["common"]["desc"])
        headers, cookies, body = api._request_params(
            post_api,
            data,
            "POST",
            referer=f"{api.base_url}/",
            target_origin=api.edith_url,
            order_wire_headers=False,
        )
        headers["x-rap-param"] = generate_x_rap_param(
            post_api,
            body,
            fingerprint_hex=load_creator_rap_fingerprint_hex(),
        )
        return PreparedImageNote(api.edith_url + post_api, headers, cookies, body, topic_resolution)
