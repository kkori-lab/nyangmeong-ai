from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 환경변수가 .env.local보다 우선
    model_config = SettingsConfigDict(
        env_file=".env.local", env_file_encoding="utf-8", extra="ignore"
    )

    # Python→Java 내부 API 주소(인증 확인·대화 저장) : 빈 값이면 /ai/** 전부 502
    backend_base_url: str = ""
    # 로그 파일 폴더(배포 서버 /home/ggorilab/logs) : 비면 콘솔에만
    log_dir: str = ""

    # FN-AIM-008-07 : OCR 분석 제한 시간(초), Vision·LLM 정리 합산
    ocr_timeout_sec: float = 15.0
    # Google Vision API 키 : 비면 영수증 분석 API 502
    google_vision_api_key: SecretStr = SecretStr("")
    # FN-HLT-005-04 : 검사결과지 PDF 분석 제한 시간(초) : LLM 한 번
    pdf_analyze_timeout_sec: float = 30.0
    # FN-MAN-006 : 메인 AI 건강분석 리포트 생성 제한 시간(초) : LLM 한 번
    health_report_timeout_sec: float = 20.0
    # 피부 병변 분석 제한 시간(초) : LLM 한 번 (docs/api/skinlesion.md)
    skin_analyze_timeout_sec: float = 20.0
    # 안구 병변 분석 제한 시간(초) : LLM 한 번 (docs/api/eyelesion.md)
    eye_analyze_timeout_sec: float = 20.0

    # 이미지 생성(OpenAI, 2026-10-28 결정) : 비면 캐릭터 생성 API 502
    openai_api_key: SecretStr = SecretStr("")
    character_image_model: str = "gpt-image-2"
    character_vision_model: str = "gpt-5-nano"
    # FN-MYP-010-09 : 외부 호출 한 번의 제한 시간(초), 백그라운드 생성
    character_timeout_sec: float = 180.0

    # LLM(Anthropic, 2026-10-28 결정) : 비면 LLM 필요 API 502
    llm_api_key: SecretStr = SecretStr("")
    # 2026-10-28 결정 : 일단 Haiku (변경은 LLM_MODEL만)
    llm_model: str = "claude-haiku-5-5"
    llm_timeout_sec: float = 10.0
    # FN-AIM-002-07 : 답변 첫 글자 제한·전체 제한(초)
    answer_first_token_sec: float = 10.0
    answer_total_sec: float = 60.0
    # 프로그래밍식 도구 호출 시험(2026-11-26) : 켜면 읽기 도구를 코드 실행 안에서 부름. 기본 꺼짐
    llm_ptc: bool = False
    # 에이전트 이어 가기 서명 키(docs/design/agent.md 4절, 2026-11-26)
    # 비면 프로세스마다 무작위 키(재시작 때 진행 중 토큰만 무효), 서버 여러 대면 같은 값(2026-11-27)
    agent_state_key: SecretStr = SecretStr("")


@lru_cache
def get_settings() -> Settings:
    return Settings()
