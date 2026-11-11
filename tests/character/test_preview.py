import httpx2
import pytest
from fastapi.testclient import TestClient

from app.character import engine
from app.character.clients import CharacterApiError, get_character_client
from app.character.repository import (
    CharacterJob,
    get_character_job_repository,
)
from app.character.rules import matches_spec
from app.character.service import BakeQueue, get_bake_queue
from app.core.backend import get_backend_client
from app.core.config import get_settings
from app.main import create_app
from tests.character.fakes import FakeCharacterJobRepository, SavedJob
from tests.character.test_bake import LAYOUT, sheet

URL = "/ai/characters/1/preview"
HEADERS = {"X-Requested-With": "XMLHttpRequest", "Cookie": "access_token=member-7"}
SWEATER, HOODIE, TIE, BOOTS = 108, 111, 11, 21


def fake_auth_check(request: httpx2.Request) -> httpx2.Response:
    if "access_token=" not in request.headers.get("cookie", ""):
        return httpx2.Response(401, json={"code": "UNAUTHORIZED"})
    return httpx2.Response(200, json={"data": {"mbrSn": 7, "mbrAuthrtCd": "MBRC0001"}})


class BakeClient:
    def __init__(self) -> None:
        self.calls: list[int] = []
        self.error = False

    async def bake(self, bare: bytes, pet_se_cd, item: engine.BakeItem) -> bytes:
        self.calls.append(item.item_sn)
        if self.error:
            raise CharacterApiError
        return sheet(body=True)


@pytest.fixture
def repo() -> FakeCharacterJobRepository:
    fake = FakeCharacterJobRepository()
    saved = SavedJob(CharacterJob(1, "PETC0001"), 3, sheet=sheet(), layout=LAYOUT)
    fake.jobs[1] = saved
    return fake


@pytest.fixture
def generator() -> BakeClient:
    return BakeClient()


def make_client(monkeypatch, repo, generator) -> TestClient:
    monkeypatch.setenv("BACKEND_BASE_URL", "http://backend.test")
    get_settings.cache_clear()
    app = create_app()
    backend = httpx2.AsyncClient(transport=httpx2.MockTransport(fake_auth_check))
    queue = BakeQueue()
    app.dependency_overrides[get_backend_client] = lambda: backend
    app.dependency_overrides[get_character_job_repository] = lambda: repo
    app.dependency_overrides[get_character_client] = lambda: generator
    app.dependency_overrides[get_bake_queue] = lambda: queue
    return TestClient(app)


@pytest.fixture
def client(monkeypatch, repo, generator) -> TestClient:
    return make_client(monkeypatch, repo, generator)


def post(client: TestClient, item_sns: list[int], url: str = URL):
    return client.post(url, json={"itemSns": item_sns}, headers=HEADERS)


# FN-MYP-011-01·FN-MYP-010-13 : 합성 응답
def test_preview_맨몸은_빈_목록으로_512_PNG(client: TestClient) -> None:
    res = post(client, [])
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert matches_spec(res.content)


def test_preview_구운_아이템을_입힌_PNG(client: TestClient, repo) -> None:
    repo.jobs[1].item_sheets[SWEATER] = sheet(body=True)
    repo.jobs[1].item_sheets[TIE] = sheet(face=True)
    res = post(client, [SWEATER, TIE])
    assert res.status_code == 200
    assert matches_spec(res.content)
    assert res.content != post(client, []).content


# 오류
def test_preview_안_구운_아이템은_409_뒤_구워_둔다(client, generator, repo) -> None:
    res = post(client, [SWEATER])
    assert res.status_code == 409
    assert res.json()["code"] == "ITEM_BAKING"
    assert generator.calls == [SWEATER]
    assert post(client, [SWEATER]).status_code == 200


def test_preview_굽기_실패는_502(client, generator) -> None:
    generator.error = True
    assert post(client, [SWEATER]).status_code == 409
    res = post(client, [SWEATER])
    assert res.status_code == 502
    assert res.json()["code"] == "CHARACTER_API_ERROR"


def test_preview_시트가_깨져_합성하지_못하면_502(client, repo) -> None:
    repo.jobs[1].item_sheets[SWEATER] = b"not image"
    res = post(client, [SWEATER])
    assert res.status_code == 502
    assert res.json()["code"] == "CHARACTER_API_ERROR"


def test_preview_생성기가_없으면_502(monkeypatch, repo) -> None:
    client = make_client(monkeypatch, repo, None)
    res = post(client, [SWEATER])
    assert res.status_code == 502
    assert res.json()["code"] == "EXTERNAL_API_ERROR"


@pytest.mark.parametrize(
    "item_sns",
    [
        [BOOTS],  # 신발 미지원
        [999],  # 굽기 대상 아님
        [SWEATER, HOODIE],  # FN-MYP-010-13 : 같은 부위 2개
        [SWEATER, SWEATER],  # 같은 아이템 2번
    ],
)
def test_preview_입힐_수_없는_조합은_400(client: TestClient, item_sns: list[int]) -> None:
    res = post(client, item_sns)
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"


def test_preview_itemSns가_없으면_400(client: TestClient) -> None:
    res = client.post(URL, json={}, headers=HEADERS)
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"


def test_preview_캐릭터가_없으면_Java_404_그대로(client: TestClient) -> None:
    res = post(client, [], "/ai/characters/99/preview")
    assert res.status_code == 404
    assert res.json()["code"] == "PIXEL_CHARACTER_NOT_FOUND"


def test_preview_쿠키가_없으면_401(client: TestClient) -> None:
    res = client.post(URL, json={"itemSns": []}, headers={"X-Requested-With": "XMLHttpRequest"})
    assert res.status_code == 401


def test_preview_X_Requested_With가_없으면_403(client: TestClient) -> None:
    res = client.post(URL, json={"itemSns": []}, headers={"Cookie": "access_token=member-7"})
    assert res.status_code == 403
