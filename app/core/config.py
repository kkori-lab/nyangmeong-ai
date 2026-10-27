from enum import StrEnum
from functools import lru_cache

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

    # Python→Java 내부 API 주소(인증 확인·대화 저장). 빈 값이면 /ai/** 전부 502
    backend_base_url: str = ""

    # OCR 분석 제한 시간(초). Java 제한 15초보다 짧게 둠 : Java가 먼저 끊는 일 방지
    ocr_timeout_sec: float = 12.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
