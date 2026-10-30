import httpx2
import pytest
from fastapi.testclient import TestClient

from app.character.repository import FakeCharacterJobRepository, get_character_job_repository
from app.core.backend import get_backend_client
from app.core.config import get_settings
from app.main import create_app

URL = "/ai/characters"
HEADERS = {"X-Requested-With": "XMLHttpRequest", "Cookie": "access_token=member-7"}
PHOTO = b"\x89PNG\r\n\x1a\n" + b"0" * 16


def fake_auth_check(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(200, json={"data": {"mbrSn": 7, "mbrAuthrtCd": "U"}})


@pytest.fixture
def repo() -> FakeCharacterJobRepository:
    return FakeCharacterJobRepository()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, repo: FakeCharacterJobRepository) -> TestClient:
    # 생성기 미주입 : 실제 앱처럼 생성기가 아직 없는 상태
    monkeypatch.setenv("BACKEND_BASE_URL", "http://backend.test")
    get_settings.cache_clear()
    app = create_app()
    backend = httpx2.AsyncClient(transport=httpx2.MockTransport(fake_auth_check))
    app.dependency_overrides[get_backend_client] = lambda: backend
    app.dependency_overrides[get_character_job_repository] = lambda: repo
    return TestClient(app)


# FN-MYP-010-08 : 생성기가 없어도 업로드 검증 우선


def test_생성기가_없어도_PDF는_400_FILE_TYPE_NOT_ALLOWED(
    client: TestClient, repo: FakeCharacterJobRepository
) -> None:
    response = client.post(
        URL, files={"photo": ("p.pdf", b"%PDF-1.7")}, data={"petSn": "3"}, headers=HEADERS
    )

    assert response.status_code == 400
    assert response.json()["code"] == "FILE_TYPE_NOT_ALLOWED"
    assert repo.jobs == {}


def test_생성기가_없어도_petSn이_없으면_400_INVALID_REQUEST(
    client: TestClient, repo: FakeCharacterJobRepository
) -> None:
    response = client.post(URL, files={"photo": ("p.png", PHOTO)}, headers=HEADERS)

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"
    assert repo.jobs == {}


def test_생성기가_없으면_검증을_통과한_요청은_502이고_작업을_만들지_않는다(
    client: TestClient, repo: FakeCharacterJobRepository
) -> None:
    response = client.post(
        URL, files={"photo": ("p.png", PHOTO)}, data={"petSn": "3"}, headers=HEADERS
    )

    assert response.status_code == 502
    assert response.json()["code"] == "EXTERNAL_API_ERROR"
    assert repo.jobs == {}
