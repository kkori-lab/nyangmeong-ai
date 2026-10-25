import base64
import binascii
from typing import Annotated

import jwt
from fastapi import Cookie, Depends, Request

from app.core.config import Settings, get_settings
from app.core.response import AppError

ALGORITHM = "HS256"
TYP_ACCESS = "access"
REQUESTED_WITH = "XMLHttpRequest"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def require_requested_with(request: Request) -> None:
    """상태 변경 요청에 X-Requested-With 필수 (CSRF 토큰 대체, 백엔드 RequestedWithFilter와 같음)"""
    if request.method not in SAFE_METHODS and request.headers.get("X-Requested-With") != (
        REQUESTED_WITH
    ):
        raise AppError("FORBIDDEN", 403, "접근 권한이 없습니다.")


def require_member(
    settings: Annotated[Settings, Depends(get_settings)],
    access_token: Annotated[str | None, Cookie()] = None,
) -> int:
    """쿠키 access_token 검증 후 회원 번호(sub) 반환. 서명·만료·typ만 본다(세션 테이블은 못 읽음)"""
    key = _secret_bytes(settings)
    if not access_token or key is None:
        raise _unauthorized()
    try:
        claims = jwt.decode(
            access_token, key, algorithms=[ALGORITHM], options={"require": ["exp", "sub"]}
        )
    except jwt.ExpiredSignatureError:
        raise AppError(
            "TOKEN_EXPIRED", 401, "로그인이 만료되었습니다. 다시 로그인해 주세요."
        ) from None
    except jwt.InvalidTokenError:
        raise _unauthorized() from None
    # refresh 토큰을 access 자리에 넣은 경우 차단
    if claims.get("typ") != TYP_ACCESS:
        raise _unauthorized()
    try:
        return int(claims["sub"])
    except (TypeError, ValueError):
        raise _unauthorized() from None


def _secret_bytes(settings: Settings) -> bytes | None:
    encoded = settings.jwt_secret_base64.get_secret_value().strip()
    if not encoded:
        return None
    try:
        return base64.b64decode(encoded, validate=True)
    except binascii.Error:
        return None


def _unauthorized() -> AppError:
    return AppError("UNAUTHORIZED", 401, "로그인이 필요합니다.")
