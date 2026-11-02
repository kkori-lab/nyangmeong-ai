import asyncio
import io
import json
from collections.abc import Callable

import httpx2
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.character.canvas import Layout
from app.character.clients import get_character_client
from app.character.repository import (
    CharacterFailure,
    JavaCharacterJobRepository,
)
from app.core.backend import BackendError, get_backend_client
from app.core.config import Settings, get_settings
from app.core.response import AppError
from app.main import create_app

BASE = "http://backend.test/internal/ai/characters"
COOKIE = "access_token=abc"
SETTINGS = Settings(backend_base_url="http://backend.test")
SHEETS_DATA = {
    "petSeCd": "PETC0002",
    "sheetFileSn": 50,
    "scale": 0.5,
    "originX": 10.5,
    "originY": 20,
    "items": [
        {"itemSn": 5, "atchFileSn": 51, "bakeFailed": False},
        {"itemSn": 6, "atchFileSn": None, "bakeFailed": False},
        {"itemSn": 7, "atchFileSn": None, "bakeFailed": True},
    ],
}

Handler = Callable[[httpx2.Request], httpx2.Response]


def ok(data: object, status: int = 200) -> httpx2.Response:
    return httpx2.Response(status, json={"data": data})


def make_repo(handler: Handler, requests: list[httpx2.Request] | None = None):
    def record(request: httpx2.Request) -> httpx2.Response:
        request.read()
        if requests is not None:
            requests.append(request)
        return handler(request)

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(record))
    return JavaCharacterJobRepository(client, SETTINGS, COOKIE)


# 호출마다 경로·메서드·쿠키 : 8개 모두 쿠키를 보낸다(Java 쿠키 인증)


def test_create_job은_쿠키와_함께_보내고_등록_정보를_돌려준다() -> None:
    requests: list[httpx2.Request] = []
    data = {
        "charCrtJobSn": 9,
        "petSeCd": "PETC0002",
        "vrtyNm": "코숏",
        "colrNm": "삼색",
        "chrcCn": "귀 접힘",
    }

    job = asyncio.run(make_repo(lambda _: ok(data, 201), requests).create_job(3))

    assert (job.char_crt_job_sn, job.pet_se_cd, job.vrty_nm) == (9, "PETC0002", "코숏")
    assert (job.colr_nm, job.chrc_cn) == ("삼색", "귀 접힘")
    request = requests[0]
    assert (request.method, str(request.url)) == ("POST", f"{BASE}/jobs")
    assert request.headers["cookie"] == COOKIE
    assert request.headers["x-requested-with"] == "XMLHttpRequest"
    assert json.loads(request.content) == {"petSn": 3}


def test_report_success는_쿠키와_함께_이미지_시트_배치값을_보낸다() -> None:
    requests: list[httpx2.Request] = []
    repo = make_repo(lambda _: ok({"pixelCharSn": 77}), requests)

    sn = asyncio.run(repo.report_success(9, b"IMAGE", b"SHEET", Layout(0.5, 10.5, 20.0)))

    assert sn == 77
    request = requests[0]
    assert (request.method, str(request.url)) == ("POST", f"{BASE}/jobs/9/success")
    assert request.headers["cookie"] == COOKIE
    assert request.headers["x-requested-with"] == "XMLHttpRequest"
    assert request.headers["content-type"].startswith("multipart/form-data")
    for part in (b'name="image"', b"IMAGE", b'name="sheet"', b"SHEET", b'name="originX"', b"10.5"):
        assert part in request.content


def test_report_failure는_쿠키와_함께_사유를_보낸다() -> None:
    requests: list[httpx2.Request] = []
    repo = make_repo(lambda _: httpx2.Response(200), requests)

    asyncio.run(repo.report_failure(9, CharacterFailure.SPEC_MISMATCH))

    request = requests[0]
    assert (request.method, str(request.url)) == ("POST", f"{BASE}/jobs/9/failure")
    assert request.headers["cookie"] == COOKIE
    assert json.loads(request.content) == {"failRsn": "CHARACTER_SPEC_MISMATCH"}


def test_list_bake_items는_번호와_엔진_키를_돌려준다() -> None:
    requests: list[httpx2.Request] = []
    data = [{"itemSn": 5, "engineItemKey": "round-glasses"}]

    targets = asyncio.run(make_repo(lambda _: ok(data), requests).list_bake_items())

    assert targets == {5: "round-glasses"}
    assert (requests[0].method, str(requests[0].url)) == ("GET", f"{BASE}/bake-items")
    assert requests[0].headers["cookie"] == COOKIE


def test_save_item_sheet는_쿠키와_함께_PUT으로_보낸다() -> None:
    requests: list[httpx2.Request] = []
    repo = make_repo(lambda _: httpx2.Response(200), requests)

    asyncio.run(repo.save_item_sheet(77, 5, b"WORN"))

    request = requests[0]
    assert (request.method, str(request.url)) == ("PUT", f"{BASE}/77/item-sheets/5")
    assert request.headers["cookie"] == COOKIE
    assert b'name="sheet"' in request.content and b"WORN" in request.content


def test_report_bake_failure는_쿠키와_함께_보낸다() -> None:
    requests: list[httpx2.Request] = []
    repo = make_repo(lambda _: httpx2.Response(200), requests)

    asyncio.run(repo.report_bake_failure(77, 5))

    request = requests[0]
    assert (request.method, str(request.url)) == ("POST", f"{BASE}/77/item-sheets/5/failure")
    assert request.headers["cookie"] == COOKIE


def sheets_handler(request: httpx2.Request) -> httpx2.Response:
    path = request.url.path
    if path.endswith("/sheets"):
        return ok(SHEETS_DATA)
    return httpx2.Response(200, content=f"FILE{path.rsplit('/', 1)[1]}".encode())


def test_find_sheets는_시트_파일을_내려받아_CharacterSheets로_바꾼다() -> None:
    requests: list[httpx2.Request] = []

    found = asyncio.run(make_repo(sheets_handler, requests).find_sheets(77, [5, 6, 7]))

    assert found.pet_se_cd == "PETC0002"
    assert found.sheet == b"FILE50"
    assert found.layout == Layout(0.5, 10.5, 20.0)
    assert found.sheets == {5: b"FILE51"}
    assert found.failed == frozenset({7})
    assert requests[0].url.params.get_list("itemSns") == ["5", "6", "7"]
    urls = {str(request.url) for request in requests[1:]}
    assert urls == {f"{BASE}/77/sheet-files/50", f"{BASE}/77/sheet-files/51"}
    assert all(request.headers["cookie"] == COOKIE for request in requests)


def test_find_sheets는_요청하지_않은_아이템을_버린다() -> None:
    found = asyncio.run(make_repo(sheets_handler).find_sheets(77, [6]))

    assert found.sheets == {}
    assert found.failed == frozenset()


# 오류 : 4xx 그대로, 5xx·연결 실패·응답 모양 불일치 502


def test_4xx는_본문과_함께_그대로_올린다() -> None:
    body = b'{"code":"PET_ACCESS_DENIED"}'
    repo = make_repo(lambda _: httpx2.Response(403, content=body))

    with pytest.raises(BackendError) as caught:
        asyncio.run(repo.create_job(3))

    assert (caught.value.status_code, caught.value.body) == (403, body)


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(500),
        httpx2.Response(200, json={"data": {"charCrtJobSn": "없음"}}),
        httpx2.Response(200, json={"data": {"charCrtJobSn": 9, "petSeCd": "PETC9999"}}),
    ],
    ids=["5xx", "번호 모양 불일치", "동물 코드 불일치"],
)
def test_5xx와_응답_모양_불일치는_502(response: httpx2.Response) -> None:
    repo = make_repo(lambda _: response)

    with pytest.raises(AppError) as caught:
        asyncio.run(repo.create_job(3))

    assert caught.value.http_code == 502


def test_연결_실패는_502() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    with pytest.raises(AppError) as caught:
        asyncio.run(make_repo(refuse).list_bake_items())

    assert caught.value.http_code == 502


def test_list_bake_items_목록이_아니면_502() -> None:
    with pytest.raises(AppError) as caught:
        asyncio.run(make_repo(lambda _: ok(None)).list_bake_items())

    assert caught.value.http_code == 502


def test_시트_파일이_비어_있으면_502() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return ok(SHEETS_DATA) if request.url.path.endswith("/sheets") else httpx2.Response(200)

    with pytest.raises(AppError) as caught:
        asyncio.run(make_repo(handler).find_sheets(77, [5]))

    assert caught.value.http_code == 502


# FN-MYP-011-06 : /preview가 Java 판정을 그대로 돌려준다


def png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (4, 4)).save(buffer, "PNG")
    return buffer.getvalue()


def java(sheets: httpx2.Response) -> Handler:
    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path == "/internal/auth/check":
            return ok({"mbrSn": 7, "mbrAuthrtCd": "MBRC0001"})
        if path.endswith("/bake-items"):
            return ok([])
        return sheets

    return handler


@pytest.mark.parametrize(
    ("status", "code"),
    [(403, "PET_ACCESS_DENIED"), (404, "PIXEL_CHARACTER_NOT_FOUND")],
)
def test_preview_Java_거절을_본문_그대로_돌려준다(
    monkeypatch: pytest.MonkeyPatch, status: int, code: str
) -> None:
    monkeypatch.setenv("BACKEND_BASE_URL", "http://backend.test")
    get_settings.cache_clear()
    app = create_app()
    rejected = httpx2.Response(status, json={"code": code})
    backend = httpx2.AsyncClient(transport=httpx2.MockTransport(java(rejected)))
    app.dependency_overrides[get_backend_client] = lambda: backend
    app.dependency_overrides[get_character_client] = lambda: None

    response = TestClient(app).post(
        "/ai/characters/77/preview",
        json={"itemSns": []},
        headers={"X-Requested-With": "XMLHttpRequest", "Cookie": COOKIE},
    )

    assert response.status_code == status
    assert response.json()["code"] == code
