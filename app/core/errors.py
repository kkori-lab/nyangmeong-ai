import json

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from app.core import response
from app.core.backend import BackendError


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(response.AppError)
    async def _app_error(request: Request, exc: response.AppError) -> JSONResponse:
        return response.error(exc.code, exc.http_code, exc.message, request.url.path)

    @app.exception_handler(BackendError)
    async def _backend_error(request: Request, exc: BackendError) -> Response:
        body = _hide_internal_path(exc.body, request.url.path)
        res = Response(body, status_code=exc.status_code, media_type=exc.content_type)
        for cookie in exc.set_cookies:
            res.headers.append("set-cookie", cookie)
        return res

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # 필드 상세 미반환 : 요청 본문에 영수증 원문 포함 가능
        message = "요청 값이 올바르지 않습니다."
        return response.error("INVALID_REQUEST", 400, message, request.url.path)


def _hide_internal_path(body: bytes, path: str) -> bytes:
    """Java 오류 본문의 path(/internal/...)를 React가 부른 경로로 바꾼다. path가 없으면 그대로"""
    try:
        data = json.loads(body)
    except ValueError:
        return body
    if not isinstance(data, dict) or "path" not in data:
        return body
    data["path"] = path
    return json.dumps(data, ensure_ascii=False).encode()
