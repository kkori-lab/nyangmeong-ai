from fastapi import FastAPI

from app.core import health


def create_app() -> FastAPI:
    app = FastAPI(title="냥멍케어 AI")
    app.include_router(health.router)
    return app


app = create_app()
