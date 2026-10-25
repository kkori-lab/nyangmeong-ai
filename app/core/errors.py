from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core import response


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(response.AppError)
    async def _app_error(request: Request, exc: response.AppError) -> JSONResponse:
        return response.error(exc.code, exc.http_code, exc.message, request.url.path)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # 필드 상세 미반환 : 요청 본문에 영수증 원문 포함 가능
        message = "요청 값이 올바르지 않습니다."
        return response.error("INVALID_REQUEST", 400, message, request.url.path)
