import secrets
from typing import Annotated

from fastapi import Depends, Header

from app.core.config import Settings, get_settings
from app.core.response import AppError


def require_internal_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_internal_key: Annotated[str | None, Header()] = None,
) -> None:
    """내부 호출자 검사 : X-Internal-Key = INTERNAL_API_KEY"""
    expected = settings.internal_api_key.get_secret_value()
    # 설정이 빈 값일 때 빈 헤더 통과 방지
    if not expected or x_internal_key is None:
        raise _unauthorized()
    if not secrets.compare_digest(x_internal_key.encode(), expected.encode()):
        raise _unauthorized()


def _unauthorized() -> AppError:
    return AppError("UNAUTHORIZED", 401, "인증이 필요합니다.")
