from fastapi import FastAPI

from app.character import router as character_router
from app.core import health
from app.core.errors import register_error_handlers
from app.ocr import router as ocr_router


def create_app() -> FastAPI:
    app = FastAPI(title="냥멍케어 AI")
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(ocr_router.router)
    app.include_router(character_router.router)
    return app


app = create_app()
