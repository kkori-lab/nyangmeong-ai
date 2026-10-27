from http.cookiejar import CookieJar, DefaultCookiePolicy
from typing import Any

import httpx2
from fastapi import Request

from app.core.config import Settings
from app.core.response import AppError

# Java 내부 API 제한 시간(초)
TIMEOUT_SEC = 3.0


class BackendError(Exception):
    """Java 4xx 오류. 본문·Set-Cookie를 다시 만들지 않고 그대로 전달한다"""

    def __init__(
        self, status_code: int, body: bytes, content_type: str | None, set_cookies: list[str]
    ) -> None:
        super().__init__(status_code)
        self.status_code = status_code
        self.body = body
        self.content_type = content_type
        self.set_cookies = set_cookies

    @classmethod
    def of(cls, res: httpx2.Response) -> "BackendError":
        return cls(
            res.status_code,
            res.content,
            res.headers.get("content-type"),
            res.headers.get_list("set-cookie"),
        )


def create_backend_client() -> httpx2.AsyncClient:
    # 요청끼리 공유하므로 Java의 Set-Cookie를 저장하지 않는다 : 다른 회원 요청에 섞임 방지
    jar = CookieJar(policy=DefaultCookiePolicy(allowed_domains=[]))
    return httpx2.AsyncClient(timeout=TIMEOUT_SEC, cookies=jar)


def get_backend_client(request: Request) -> httpx2.AsyncClient:
    return request.app.state.backend_client


async def call_backend(
    client: httpx2.AsyncClient, settings: Settings, method: str, path: str, **kwargs: Any
) -> Any:
    """Java 내부 API를 불러 ApiResponse의 data를 돌려준다. 4xx는 그대로 전달, 그 밖의 실패는 502"""
    base_url = settings.backend_base_url.rstrip("/")
    if not base_url:
        raise external_error()
    try:
        res = await client.request(method, f"{base_url}{path}", **kwargs)
    except httpx2.HTTPError:
        raise external_error() from None
    if 400 <= res.status_code < 500:
        raise BackendError.of(res)
    if not res.is_success:
        raise external_error()
    if not res.content:
        return None
    try:
        return res.json().get("data")
    except (ValueError, AttributeError):
        raise external_error() from None


def external_error() -> AppError:
    return AppError(
        "EXTERNAL_API_ERROR", 502, "외부 서비스 호출에 실패했습니다. 잠시 후 다시 시도해 주세요."
    )
