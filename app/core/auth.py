from typing import Annotated

import httpx2
from fastapi import Depends, Request

from app.core.backend import get_backend_client
from app.core.config import Settings, get_settings
from app.core.response import AppError

AUTH_CHECK_PATH = "/internal/auth/check"
REQUESTED_WITH = "XMLHttpRequest"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class BackendAuthError(Exception):
    """Java 인증 오류. 본문·Set-Cookie를 다시 만들지 않고 그대로 전달한다"""

    def __init__(
        self, status_code: int, body: bytes, content_type: str | None, set_cookies: list[str]
    ) -> None:
        super().__init__(status_code)
        self.status_code = status_code
        self.body = body
        self.content_type = content_type
        self.set_cookies = set_cookies


def require_requested_with(request: Request) -> None:
    """상태 변경 요청에 X-Requested-With 필수 (CSRF 토큰 대체, 백엔드 RequestedWithFilter와 같음)"""
    if request.method not in SAFE_METHODS and request.headers.get("X-Requested-With") != (
        REQUESTED_WITH
    ):
        raise AppError("FORBIDDEN", 403, "접근 권한이 없습니다.")


async def require_member(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    client: Annotated[httpx2.AsyncClient, Depends(get_backend_client)],
) -> int:
    """브라우저 Cookie를 실어 Java /internal/auth/check 호출 후 회원 번호 반환. 캐시하지 않음"""
    base_url = settings.backend_base_url.rstrip("/")
    if not base_url:
        raise _external_error()
    headers = {"X-Internal-Key": settings.backend_internal_key.get_secret_value()}
    cookie = request.headers.get("cookie")
    if cookie:
        headers["Cookie"] = cookie
    try:
        res = await client.get(f"{base_url}{AUTH_CHECK_PATH}", headers=headers)
    except httpx2.HTTPError:
        raise _external_error() from None

    if res.status_code in (401, 403):
        raise BackendAuthError(
            res.status_code,
            res.content,
            res.headers.get("content-type"),
            res.headers.get_list("set-cookie"),
        )
    if res.status_code != 200:
        raise _external_error()
    try:
        return int(res.json()["data"]["mbrSn"])
    except (ValueError, KeyError, TypeError):
        raise _external_error() from None


def _external_error() -> AppError:
    return AppError(
        "EXTERNAL_API_ERROR", 502, "외부 서비스 호출에 실패했습니다. 잠시 후 다시 시도해 주세요."
    )
