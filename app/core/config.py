from enum import StrEnum
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AiMode(StrEnum):
    # mock이면 외부 AI API를 호출하지 않고 고정 응답을 돌려준다. 키 없이 개발·테스트할 때 쓴다
    MOCK = "mock"
    REAL = "real"


class Settings(BaseSettings):
    # 환경변수가 .env.local보다 우선한다
    model_config = SettingsConfigDict(
        env_file=".env.local", env_file_encoding="utf-8", extra="ignore"
    )

    ai_mode: AiMode = AiMode.MOCK

    # mysql://호스트:포트/DB. 백엔드 JDBC 주소(jdbc:mysql://...)를 그대로 넣어도 된다
    db_url: str = ""
    db_username: str = ""
    db_password: SecretStr = SecretStr("")


@lru_cache
def get_settings() -> Settings:
    return Settings()
