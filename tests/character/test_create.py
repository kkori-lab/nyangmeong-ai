import struct
import zlib

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.character.clients import CharacterApiError, CharacterRequest, get_character_client
from app.character.repository import (
    CharacterFailure,
    CharacterJob,
    FakeCharacterJobRepository,
    get_character_job_repository,
)
from app.character.rules import matches_spec
from app.core.backend import BackendError, get_backend_client
from app.core.config import get_settings
from app.main import create_app

URL = "/ai/characters"
AJAX = {"X-Requested-With": "XMLHttpRequest"}
COOKIE = {"Cookie": "access_token=member-7"}
PHOTO = b"\x89PNG\r\n\x1a\n" + b"0" * 16
FORM = {"petSn": "3"}
JOB_INFO = {
    "pet_se_cd": "PETC0002",
    "vrty_nm": "코리안숏헤어",
    "colr_nm": "고등어",
    "chrc_cn": "귀 접힘",
}


def _png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = (b"\x00" + b"\x00" * (width * 4)) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def fake_auth_check(request: httpx2.Request) -> httpx2.Response:
    """Java /internal/auth/check 흉내 : 쿠키 access_token=member-<번호>면 통과"""
    if "access_token=member-" in request.headers.get("cookie", ""):
        return httpx2.Response(200, json={"data": {"mbrSn": 7, "mbrAuthrtCd": "U"}})
    return httpx2.Response(401, json={"status": "error", "httpCode": 401, "code": "UNAUTHORIZED"})


class FakeGenerator:
    """받은 요청을 calls에 남기고 result(PNG 또는 예외)를 돌려준다"""

    def __init__(self, result: bytes | Exception) -> None:
        self.result = result
        self.calls: list[CharacterRequest] = []

    async def generate(self, request: CharacterRequest) -> bytes:
        self.calls.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class InfoRepository(FakeCharacterJobRepository):
    """Java가 등록 정보를 돌려주는 가짜 작업 저장소"""

    async def create_job(self, pet_sn: int) -> CharacterJob:
        job = await super().create_job(pet_sn)
        saved = self.jobs[job.chrc_job_sn]
        saved.job = CharacterJob(job.chrc_job_sn, **JOB_INFO)
        return saved.job


class ConflictRepository(FakeCharacterJobRepository):
    """Java가 작업 생성을 409로 거절(이미 캐릭터 있음·생성 중)"""

    async def create_job(self, pet_sn: int) -> CharacterJob:
        raise BackendError(409, b'{"code":"CONFLICT"}', "application/json", [])


class BrokenReportRepository(InfoRepository):
    """결과 보고에서 Java 오류"""

    async def report_success(self, chrc_job_sn: int, image: bytes) -> None:
        raise BackendError(500, b"", None, [])


@pytest.fixture
def repo() -> FakeCharacterJobRepository:
    return InfoRepository()


@pytest.fixture
def generator() -> FakeGenerator:
    return FakeGenerator(_png(512, 512))


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, repo: FakeCharacterJobRepository, generator):
    monkeypatch.setenv("BACKEND_BASE_URL", "http://backend.test")
    get_settings.cache_clear()
    app = create_app()
    backend = httpx2.AsyncClient(transport=httpx2.MockTransport(fake_auth_check))
    app.dependency_overrides[get_backend_client] = lambda: backend
    app.dependency_overrides[get_character_client] = lambda: generator
    app.dependency_overrides[get_character_job_repository] = lambda: repo
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def post(client: TestClient, content: bytes = PHOTO, name: str = "p.png", **kwargs):
    headers = {**AJAX, **COOKIE, **kwargs.pop("headers", {})}
    data = kwargs.pop("data", FORM)
    return client.post(URL, files={"photo": (name, content)}, data=data, headers=headers)


# FN-MYP-010-09 : 202·작업 번호, 백그라운드 생성·보고


def test_요청하면_202와_작업_번호를_주고_응답_뒤_성공과_PNG를_보고한다(
    client: TestClient, repo: FakeCharacterJobRepository
) -> None:
    response = post(client)

    assert response.status_code == 202
    assert response.json()["data"] == {"chrcJobSn": 1}
    saved = repo.jobs[1]
    assert saved.pet_sn == 3
    assert matches_spec(saved.image)
    assert saved.failure is None


def test_생성기는_Java가_준_등록_정보로_생성한다(
    client: TestClient, generator: FakeGenerator
) -> None:
    post(client)

    [request] = generator.calls
    assert request.photo == PHOTO
    assert (request.pet_se_cd, request.vrty_nm, request.colr_nm, request.chrc_cn) == tuple(
        JOB_INFO.values()
    )


def test_요청에_보낸_등록_정보는_쓰지_않는다(client: TestClient, generator: FakeGenerator) -> None:
    post(client, data={**FORM, "vrtyNm": "조작한 품종", "petSeCd": "PETC0001"})

    assert generator.calls[0].vrty_nm == "코리안숏헤어"
    assert generator.calls[0].pet_se_cd == "PETC0002"


@pytest.mark.parametrize("repo", [ConflictRepository()])
def test_Java가_작업_생성을_거절하면_그대로_전달하고_생성하지_않는다(
    client: TestClient, generator: FakeGenerator
) -> None:
    response = post(client)

    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"
    assert generator.calls == []


def test_생성기가_없으면_502이고_작업을_만들지_않는다(
    app, client: TestClient, repo: FakeCharacterJobRepository
) -> None:
    del app.dependency_overrides[get_character_client]

    response = post(client)

    assert response.status_code == 502
    assert response.json()["code"] == "EXTERNAL_API_ERROR"
    assert repo.jobs == {}


# FN-MYP-010-17·18 : 규격 밖·생성기 오류는 실패 보고


@pytest.mark.parametrize(
    ("generator", "reason"),
    [
        (FakeGenerator(_png(256, 256)), CharacterFailure.SPEC_MISMATCH),
        (FakeGenerator(b"not a png"), CharacterFailure.SPEC_MISMATCH),
        (FakeGenerator(CharacterApiError()), CharacterFailure.API_ERROR),
    ],
)
def test_규격_밖이거나_생성기가_실패하면_실패를_보고하고_성공은_보고하지_않는다(
    client: TestClient, repo: FakeCharacterJobRepository, reason: CharacterFailure
) -> None:
    response = post(client)

    assert response.status_code == 202
    assert repo.jobs[1].failure == reason
    assert repo.jobs[1].image is None


@pytest.mark.parametrize("repo", [BrokenReportRepository()])
def test_결과_보고가_실패해도_요청은_202로_끝난다(client: TestClient) -> None:
    response = post(client)

    assert response.status_code == 202


def test_규격_검증은_캔버스_크기가_512x512인_PNG만_통과시킨다() -> None:
    assert matches_spec(_png(512, 512))
    assert not matches_spec(_png(512, 511))
    assert not matches_spec(b"\x89PNG\r\n\x1a\n")


# FN-MYP-010-08 : 업로드 검증은 Java·생성기를 부르지 않는다


@pytest.mark.parametrize(
    ("content", "name"),
    [
        (b"not an image", "p.png"),  # 이미지 아님
        (PHOTO, "p.jpg"),  # 확장자와 실제 형식 불일치
        (b"%PDF-1.7", "p.pdf"),  # PDF
    ],
)
def test_이미지가_아니거나_형식이_다르면_400_FILE_TYPE_NOT_ALLOWED(
    client: TestClient,
    repo: FakeCharacterJobRepository,
    generator: FakeGenerator,
    content: bytes,
    name: str,
) -> None:
    response = post(client, content=content, name=name)

    assert response.status_code == 400
    assert response.json()["code"] == "FILE_TYPE_NOT_ALLOWED"
    assert repo.jobs == {}
    assert generator.calls == []


def test_10MB를_넘으면_400_FILE_SIZE_EXCEEDED(
    client: TestClient, repo: FakeCharacterJobRepository, generator: FakeGenerator
) -> None:
    response = post(client, content=PHOTO + b"0" * (10 * 1024 * 1024))

    assert response.status_code == 400
    assert response.json()["code"] == "FILE_SIZE_EXCEEDED"
    assert repo.jobs == {}
    assert generator.calls == []


def test_petSn이_없으면_400_INVALID_REQUEST(
    client: TestClient, repo: FakeCharacterJobRepository, generator: FakeGenerator
) -> None:
    response = post(client, data={})

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"
    assert repo.jobs == {}
    assert generator.calls == []


# 인증·X-Requested-With


def test_쿠키가_없으면_401(client: TestClient, repo: FakeCharacterJobRepository) -> None:
    response = client.post(URL, files={"photo": ("p.png", PHOTO)}, data=FORM, headers=AJAX)

    assert response.status_code == 401
    assert repo.jobs == {}


def test_X_Requested_With가_없으면_403(
    client: TestClient, repo: FakeCharacterJobRepository
) -> None:
    response = client.post(URL, files={"photo": ("p.png", PHOTO)}, data=FORM, headers=COOKIE)

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    assert repo.jobs == {}


def test_이전_내부_경로는_없다(client: TestClient) -> None:
    response = client.post("/internal/v1/character/generate", headers=AJAX)

    assert response.status_code == 404
