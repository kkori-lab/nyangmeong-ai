from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.character import router as character_router
from app.chat import internal_router as chat_internal_router
from app.chat import router as chat_router
from app.core import health
from app.core.backend import create_backend_client
from app.core.config import get_settings
from app.core.crypto import check_key
from app.core.errors import register_error_handlers
from app.ocr import router as ocr_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 암호화 키가 있는데 형식이 틀리면 서버 시작에서 실패
    check_key(get_settings())
    app.state.backend_client = create_backend_client()
    yield
    await app.state.backend_client.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="냥멍케어 AI", lifespan=lifespan)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(ocr_router.router)
    app.include_router(character_router.router)
    app.include_router(chat_router.router)
    app.include_router(chat_internal_router.router)
    return app


app = create_app()
