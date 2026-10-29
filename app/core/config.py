from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 환경변수가 .env.local보다 우선한다
    model_config = SettingsConfigDict(
        env_file=".env.local", env_file_encoding="utf-8", extra="ignore"
    )

    # Python→Java 내부 API 주소(인증 확인·대화 저장). 빈 값이면 /ai/** 전부 502
    backend_base_url: str = ""

    # OCR 분석 제한 시간(초). Java 제한 15초보다 짧게 둠 : Java가 먼저 끊는 일 방지
    ocr_timeout_sec: float = 12.0

    # LLM(Anthropic, 2026-10-28 결정). 비어 있으면 LLM이 필요한 API는 502
    llm_api_key: SecretStr = SecretStr("")
    # 2026-10-28 결정 : 일단 Haiku. 바꿀 때는 LLM_MODEL만 고친다
    llm_model: str = "claude-haiku-5-5"
    llm_timeout_sec: float = 10.0
    # FN-AIM-002-07 : 답변 첫 글자 제한·전체 제한(초)
    answer_first_token_sec: float = 10.0
    answer_total_sec: float = 60.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
