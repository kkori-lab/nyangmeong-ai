from datetime import datetime
from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


class AppError(Exception):
    """업무 오류. code = 백엔드 ErrorCode 상수 이름"""

    def __init__(self, code: str, http_code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.http_code = http_code
        self.message = message
        # 백엔드 ApiResponse.errorWithData와 동일 : 오류에도 data 동봉 (없으면 필드 제외)
        self.data = data


def success(data: Any = None, http_code: int = 200) -> JSONResponse:
    # 백엔드 ApiResponse와 동일 : null 필드 제외, 성공 응답은 path 없음
    return _build("success", http_code, "ok", None, None, data)


def error(code: str, http_code: int, message: str, path: str, data: Any = None) -> JSONResponse:
    return _build("error", http_code, message, path, code, data)


def _build(
    status: str, http_code: int, message: str, path: str | None, code: str | None, data: Any
) -> JSONResponse:
    body = {
        "timestamp": datetime.now(),
        "status": status,
        "httpCode": http_code,
        "message": message,
        "path": path,
        "code": code,
        "data": data,
    }
    body = {k: v for k, v in body.items() if v is not None}
    return JSONResponse(status_code=http_code, content=jsonable_encoder(body))
