import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.character import router as character_router
from app.chat import catalog, tools
from app.chat import router as chat_router
from app.checkup import router as checkup_router
from app.core import health, logs
from app.core.backend import create_backend_client
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.healthreport import router as healthreport_router
from app.ocr import router as ocr_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.backend_client = create_backend_client()
    # 도구 목록(docs/design/tool-catalog.md 4-2절) : 기동 때 1회, 실패면 뒤에서 다시 받기
    settings = get_settings()
    client = catalog.JavaToolCatalogClient(app.state.backend_client, settings)
    installed = await catalog.install(client)
    tools.use_catalog(installed)
    retry = None
    if installed.source == "snapshot" and settings.backend_base_url:
        retry = asyncio.create_task(catalog.retry(client, tools.use_catalog))
    yield
    if retry is not None:
        retry.cancel()
        with suppress(asyncio.CancelledError):
            await retry
    await app.state.backend_client.aclose()


def create_app() -> FastAPI:
    logs.configure(get_settings().log_dir)
    app = FastAPI(title="냥멍케어 AI", lifespan=lifespan)
    app.add_middleware(logs.RequestLogMiddleware)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(ocr_router.router)
    app.include_router(ocr_router.ai_router)
    app.include_router(character_router.router)
    app.include_router(checkup_router.router)
    app.include_router(healthreport_router.router)
    app.include_router(chat_router.me_router)
    app.include_router(chat_router.router)
    return app


app = create_app()
