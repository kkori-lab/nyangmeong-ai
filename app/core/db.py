from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import Settings

# Python 계정이 쓰는 테이블. 대화 2개는 읽기·쓰기, SYS_STNG(백엔드 소유)는 AI 설정값 읽기만
OWNED_TABLES = ("AI_CNVRS_ROOM", "AI_CNVRS_MSG")
READ_ONLY_TABLES = ("SYS_STNG",)


def database_url(settings: Settings) -> URL:
    # JDBC 접두어와 쿼리 문자열(serverTimezone 등)은 버리고 드라이버·문자셋을 정한다
    url = make_url(settings.db_url.removeprefix("jdbc:").split("?", 1)[0])
    return url.set(
        drivername="mysql+asyncmy",
        username=settings.db_username,
        password=settings.db_password.get_secret_value(),
        query={"charset": "utf8mb4"},
    )


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(database_url(settings), pool_pre_ping=True)
