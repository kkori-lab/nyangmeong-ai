import pytest
from fastapi.testclient import TestClient

from app.character.repository import CharacterJob
from app.character.rules import matches_spec
from app.core.backend import BackendError
from tests.character.fakes import FakeCharacterJobRepository, SavedJob
from tests.character.test_bake import LAYOUT, sheet
from tests.character.test_preview import (
    BOOTS,
    HEADERS,
    HOODIE,
    SWEATER,
    TIE,
    BakeClient,
    make_client,
    post,
)

URL = "/ai/characters/1/equipped-image"
_CHANGED = b'{"code":"EQUIPPED_ITEMS_CHANGED"}'
_NOT_FOUND = b'{"code":"PIXEL_CHARACTER_NOT_FOUND"}'


@pytest.fixture
def repo() -> FakeCharacterJobRepository:
    fake = FakeCharacterJobRepository()
    fake.jobs[1] = SavedJob(CharacterJob(1, "PETC0001"), 3, sheet=sheet(), layout=LAYOUT)
    return fake


@pytest.fixture
def generator() -> BakeClient:
    return BakeClient()


@pytest.fixture
def client(monkeypatch, repo, generator) -> TestClient:
    return make_client(monkeypatch, repo, generator, enabled=False)


@pytest.fixture
def baking(monkeypatch, repo, generator) -> TestClient:
    return make_client(monkeypatch, repo, generator, enabled=True)


def save(client: TestClient, item_sns: list[int], url: str = URL):
    return client.post(url, json={"itemSns": item_sns}, headers=HEADERS)


# FN-MYP-010-16·13 : 대표 이미지 저장
def test_equipped_image_구운_아이템을_입힌_PNG를_저장(client: TestClient, repo) -> None:
    repo.jobs[1].item_sheets[SWEATER] = sheet(body=True)
    repo.jobs[1].item_sheets[TIE] = sheet(face=True)
    res = save(client, [SWEATER, TIE])
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert "data" not in res.json()
    saved = repo.jobs[1]
    assert saved.equipped_item_sns == [SWEATER, TIE]
    assert matches_spec(saved.equipped_image)
    assert saved.equipped_image == post(client, [SWEATER, TIE]).content


def test_equipped_image_빈_목록이면_맨몸을_저장(client: TestClient, repo) -> None:
    res = save(client, [])
    assert res.status_code == 200
    assert repo.jobs[1].equipped_item_sns == []
    assert repo.jobs[1].equipped_image == post(client, []).content


# 오류 : 모두 저장하지 않음
def test_equipped_image_안_구운_아이템은_409_저장_안_함(client, repo, generator) -> None:
    res = save(client, [SWEATER])
    assert res.status_code == 409
    assert res.json()["code"] == "ITEM_BAKING"
    assert repo.jobs[1].equipped_image is None
    assert generator.calls == []


def test_equipped_image_굽기가_켜져_있으면_409_뒤_구워_둔다(baking, repo, generator) -> None:
    res = save(baking, [SWEATER])
    assert res.status_code == 409
    assert generator.calls == [SWEATER]
    assert repo.jobs[1].equipped_image is None
    assert save(baking, [SWEATER]).status_code == 200
    assert repo.jobs[1].equipped_item_sns == [SWEATER]


def test_equipped_image_굽기_실패는_502_저장_안_함(baking, repo, generator) -> None:
    generator.error = True
    assert save(baking, [SWEATER]).status_code == 409
    res = save(baking, [SWEATER])
    assert res.status_code == 502
    assert res.json()["code"] == "CHARACTER_API_ERROR"
    assert repo.jobs[1].equipped_image is None


def test_equipped_image_시트가_깨져_합성하지_못하면_502(client, repo) -> None:
    repo.jobs[1].item_sheets[SWEATER] = b"not image"
    res = save(client, [SWEATER])
    assert res.status_code == 502
    assert res.json()["code"] == "CHARACTER_API_ERROR"
    assert repo.jobs[1].equipped_image is None


def test_equipped_image_생성기가_없으면_502(monkeypatch, repo) -> None:
    client = make_client(monkeypatch, repo, None, enabled=True)
    res = save(client, [SWEATER])
    assert res.status_code == 502
    assert res.json()["code"] == "EXTERNAL_API_ERROR"
    assert repo.jobs[1].equipped_image is None


@pytest.mark.parametrize(
    "item_sns",
    [
        [BOOTS],  # 신발 미지원
        [999],  # 굽기 대상 아님
        [SWEATER, HOODIE],  # FN-MYP-010-13 : 같은 부위 2개
    ],
)
def test_equipped_image_입힐_수_없는_조합은_400(client, repo, item_sns: list[int]) -> None:
    res = save(client, item_sns)
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"
    assert repo.jobs[1].equipped_image is None


# Java 4xx 그대로
def test_equipped_image_착용_목록이_바뀌었으면_Java_409_그대로(client, repo) -> None:
    repo.equip_error = BackendError(409, _CHANGED, "application/json", [])
    res = save(client, [])
    assert res.status_code == 409
    assert res.json()["code"] == "EQUIPPED_ITEMS_CHANGED"


def test_equipped_image_저장_단계_Java_404_그대로(client, repo) -> None:
    repo.equip_error = BackendError(404, _NOT_FOUND, "application/json", [])
    res = save(client, [])
    assert res.status_code == 404
    assert res.json()["code"] == "PIXEL_CHARACTER_NOT_FOUND"


def test_equipped_image_캐릭터가_없으면_Java_404_그대로(client: TestClient) -> None:
    res = save(client, [], "/ai/characters/99/equipped-image")
    assert res.status_code == 404
    assert res.json()["code"] == "PIXEL_CHARACTER_NOT_FOUND"


# 인증
def test_equipped_image_쿠키가_없으면_401(client: TestClient, repo) -> None:
    res = client.post(URL, json={"itemSns": []}, headers={"X-Requested-With": "XMLHttpRequest"})
    assert res.status_code == 401
    assert repo.jobs[1].equipped_image is None


def test_equipped_image_X_Requested_With가_없으면_403(client: TestClient, repo) -> None:
    res = client.post(URL, json={"itemSns": []}, headers={"Cookie": "access_token=member-7"})
    assert res.status_code == 403
    assert repo.jobs[1].equipped_image is None
