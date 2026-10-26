from enum import StrEnum
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AiMode(StrEnum):
    # mock이면 외부 AI API를 호출하지 않고 고정 응답을 돌려준다. 키 없이 개발·테스트할 때 쓴다
    MOCK = "mock"
    REAL = "real"


class AppProfile(StrEnum):
    # 백엔드 spring.profiles와 같은 이름. local은 내 PC DB, prod는 공용 DB
    LOCAL = "local"
    PROD = "prod"


class Settings(BaseSettings):
    # 환경변수가 .env.local보다 우선한다
    model_config = SettingsConfigDict(
        env_file=".env.local", env_file_encoding="utf-8", extra="ignore"
    )

    ai_mode: AiMode = AiMode.MOCK

    # 값을 빠뜨려도 공용 DB에 쓰지 않도록 기본은 local이다
    app_profile: AppProfile = AppProfile.LOCAL

    # mysql://호스트:포트/DB. 백엔드 JDBC 주소(jdbc:mysql://...)를 그대로 넣어도 된다
    local_db_url: str = ""
    local_db_username: str = ""
    local_db_password: SecretStr = SecretStr("")
    prod_db_url: str = ""
    prod_db_username: str = ""
    prod_db_password: SecretStr = SecretStr("")

    # Python→Java 내부 API 주소. 빈 값이면 /ai/** 전부 502
    backend_base_url: str = ""

    # 백엔드 app.crypto.aes-key-base64와 같은 값(대화 제목·본문 암호화)
    conversation_enc_key: SecretStr = SecretStr("")

    # OCR 분석 제한 시간(초). Java 제한 15초보다 짧게 둠 : Java가 먼저 끊는 일 방지
    ocr_timeout_sec: float = 12.0

    # app_profile에 맞는 DB 접속 정보. 코드는 이 세 속성만 읽는다
    @property
    def db_url(self) -> str:
        return self.prod_db_url if self.app_profile is AppProfile.PROD else self.local_db_url

    @property
    def db_username(self) -> str:
        if self.app_profile is AppProfile.PROD:
            return self.prod_db_username
        return self.local_db_username

    @property
    def db_password(self) -> SecretStr:
        if self.app_profile is AppProfile.PROD:
            return self.prod_db_password
        return self.local_db_password


@lru_cache
def get_settings() -> Settings:
    return Settings()
