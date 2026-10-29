import pytest

from app.core.config import get_settings

# 각자 PC의 .env.local에 있는 외부 AI 키
AI_KEYS = ("LLM_API_KEY", "OPENAI_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS")


@pytest.fixture(autouse=True)
def no_ai_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    # 키를 비워 둔다 : 가짜를 끼우지 않은 테스트는 실제 API 대신 502로 실패한다
    for key in AI_KEYS:
        monkeypatch.setenv(key, "")
    get_settings.cache_clear()
