import pytest

from app.core.config import get_settings

# 각자 PC의 .env.local에 있는 외부 AI 키
AI_KEYS = ("LLM_API_KEY", "OPENAI_API_KEY", "GOOGLE_VISION_API_KEY")
# 개발 PC 값이 테스트에 새지 않게 : 테스트는 로그 파일을 만들지 않음
EMPTY_KEYS = (*AI_KEYS, "LOG_DIR")


@pytest.fixture(autouse=True)
def no_ai_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    # 키 비움 : 가짜를 끼우지 않은 테스트는 실제 API 대신 502로 실패
    for key in EMPTY_KEYS:
        monkeypatch.setenv(key, "")
    get_settings.cache_clear()
