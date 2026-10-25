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
