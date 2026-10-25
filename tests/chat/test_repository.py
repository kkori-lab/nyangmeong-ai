import pytest

from app.chat import repository
from app.chat.repository import SqlConversationRepository, get_conversation_repository
from app.core.config import get_settings


def test_저장소_의존성은_오버라이드_없이_만들어진다(monkeypatch: pytest.MonkeyPatch) -> None:
    # 엔진 생성은 DB에 붙지 않는다. 실서버에서 의존성 해결이 깨지는 회귀를 막는다
    monkeypatch.setenv("APP_PROFILE", "local")
    monkeypatch.setenv("LOCAL_DB_URL", "mysql://localhost:3306/test")
    monkeypatch.setenv("LOCAL_DB_USERNAME", "nm_ai")
    monkeypatch.setenv("LOCAL_DB_PASSWORD", "pw")
    get_settings.cache_clear()
    repository._engine.cache_clear()

    repo = get_conversation_repository()

    assert isinstance(repo, SqlConversationRepository)
    assert get_conversation_repository()._engine is repo._engine  # 엔진은 하나를 같이 쓴다
    repository._engine.cache_clear()
