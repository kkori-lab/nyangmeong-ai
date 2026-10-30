from typing import Annotated

import httpx2
from fastapi import Depends, Request

from app.core.backend import BackendError, external_error, get_backend_client
from app.core.config import Settings, get_settings
from app.core.response import AppError

AUTH_CHECK_PATH = "/internal/auth/check"
REQUESTED_WITH = "XMLHttpRequest"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


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
    """브라우저 Cookie로 Java /internal/auth/check 호출 -> 회원 번호 (캐시 없음)"""
    base_url = settings.backend_base_url.rstrip("/")
    if not base_url:
        raise external_error()
    cookie = request.headers.get("cookie")
    headers = {"Cookie": cookie} if cookie else {}
    try:
        res = await client.get(f"{base_url}{AUTH_CHECK_PATH}", headers=headers)
    except httpx2.HTTPError:
        raise external_error() from None

    if res.status_code in (401, 403):
        raise BackendError.of(res)
    if res.status_code != 200:
        raise external_error()
    try:
        return int(res.json()["data"]["mbrSn"])
    except (ValueError, KeyError, TypeError):
        raise external_error() from None
