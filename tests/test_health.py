import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # 각자 PC의 .env.local 값과 관계없이 mock 모드로 띄운다
    monkeypatch.setenv("AI_MODE", "mock")
    get_settings.cache_clear()
    return TestClient(create_app())


def test_health_mock_모드로_응답한다(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "aiMode": "mock"}
