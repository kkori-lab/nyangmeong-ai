import logging
from typing import Annotated

import httpx2
from fastapi import Depends, Request

from app.core.backend import BackendError, cause_reason, external_error, get_backend_client
from app.core.config import Settings, get_settings
from app.core.response import AppError

AUTH_CHECK_PATH = "/internal/auth/check"
REQUESTED_WITH = "XMLHttpRequest"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# FN-ADM-001-01 : 관리자 권한 코드
ADMIN_AUTHORITY = "USRC0005"

logger = logging.getLogger(__name__)


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
    mbr_sn, _ = await _check(request, settings, client)
    return mbr_sn


async def require_admin(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    client: Annotated[httpx2.AsyncClient, Depends(get_backend_client)],
) -> int:
    """관리자만 통과 -> 회원 번호 (권한 판정 값은 Java)"""
    mbr_sn, authority = await _check(request, settings, client)
    if authority != ADMIN_AUTHORITY:
        raise AppError("FORBIDDEN", 403, "접근 권한이 없습니다.")
    return mbr_sn


async def _check(
    request: Request, settings: Settings, client: httpx2.AsyncClient
) -> tuple[int, str | None]:
    base_url = settings.backend_base_url.rstrip("/")
    if not base_url:
        raise _fail("주소 비어 있음")
    cookie = request.headers.get("cookie")
    headers = {"Cookie": cookie} if cookie else {}
    try:
        res = await client.get(f"{base_url}{AUTH_CHECK_PATH}", headers=headers)
    except (httpx2.HTTPError, httpx2.InvalidURL, OverflowError) as error:
        # InvalidURL·OverflowError : 주소 꼴이 틀림(backend._send와 같게 502)
        raise _fail(cause_reason(error) or type(error).__name__) from None

    if res.status_code in (401, 403):
        raise BackendError.of(res)
    if res.status_code != 200:
        raise _fail(f"Java {res.status_code}")
    try:
        data = res.json()["data"]
        authority = data.get("mbrAuthrtCd")
        return int(data["mbrSn"]), authority if isinstance(authority, str) else None
    except (ValueError, KeyError, TypeError, AttributeError):
        raise _fail("응답 형식 틀림") from None


def _fail(reason: str) -> AppError:
    # 502 이유 한 줄 : 주소 값·쿠키·응답 본문은 남기지 않는다
    logger.warning("인증 확인 실패(%s), 502", reason)
    return external_error()
