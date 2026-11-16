import httpx2
import pytest
from fastapi.testclient import TestClient

from app.character.clients import CharacterApiError, get_character_client
from app.character.repository import (
    CharacterFailure,
    CharacterJob,
    JavaCharacterJobRepository,
    get_character_job_repository,
)
from app.character.service import BakeQueue, get_bake_queue
from app.core.backend import BackendError, get_backend_client
from app.core.config import Settings, get_settings
from app.core.response import AppError
from app.main import create_app
from tests.character.fakes import FakeCharacterJobRepository
from tests.character.test_create import FakeGenerator, _png

URL = "/ai/admin/characters/jobs/5/regenerate"
ADMIN = {"X-Requested-With": "XMLHttpRequest", "Cookie": "access_token=admin"}
MEMBER = {"X-Requested-With": "XMLHttpRequest", "Cookie": "access_token=member"}
PHOTO = b"\x89PNG\r\n\x1a\n" + b"0" * 16
INFO = CharacterJob(5, "PETC0002", "코리안숏헤어", "고등어", "귀 접힘")


def fake_auth_check(request: httpx2.Request) -> httpx2.Response:
    cookie = request.headers.get("cookie", "")
    if "access_token=admin" in cookie:
        return httpx2.Response(200, json={"data": {"mbrSn": 1, "mbrAuthrtCd": "USRC0005"}})
    if "access_token=" in cookie:
        return httpx2.Response(200, json={"data": {"mbrSn": 7, "mbrAuthrtCd": "USRC0001"}})
    return httpx2.Response(401, json={"code": "UNAUTHORIZED"})


class BakeCounter(BakeQueue):
    """굽기는 하지 않고 대기열에 담긴 작업만 센다"""

    def __init__(self) -> None:
        super().__init__()
        self.added = []

    def add(self, task) -> None:
        self.added.append(task)

    async def drain(self) -> None:
        return None


@pytest.fixture
def repo() -> FakeCharacterJobRepository:
    repo = FakeCharacterJobRepository()
    repo.regen_jobs[5] = INFO
    repo.original_photos[5] = PHOTO
    return repo


@pytest.fixture
def generator() -> FakeGenerator:
    return FakeGenerator(_png(512, 512))


@pytest.fixture
def queue() -> BakeCounter:
    return BakeCounter()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, repo, generator, queue):
    monkeypatch.setenv("BACKEND_BASE_URL", "http://backend.test")
    get_settings.cache_clear()
    app = create_app()
    backend = httpx2.AsyncClient(transport=httpx2.MockTransport(fake_auth_check))
    app.dependency_overrides[get_backend_client] = lambda: backend
    app.dependency_overrides[get_character_client] = lambda: generator
    app.dependency_overrides[get_character_job_repository] = lambda: repo
    app.dependency_overrides[get_bake_queue] = lambda: queue
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


# FN-MYP-010-23 : 관리자 무료 재생성 입구


def test_관리자가_부르면_202이고_시작_사진_생성_보고_순서로_처리한다(
    client: TestClient, repo: FakeCharacterJobRepository, generator: FakeGenerator
) -> None:
    response = client.post(URL, headers=ADMIN)

    assert response.status_code == 202
    assert repo.regen_calls == ["start", "photo"]
    [request] = generator.calls
    assert request.photo == PHOTO
    assert (request.pet_se_cd, request.vrty_nm, request.colr_nm, request.chrc_cn) == (
        "PETC0002",
        "코리안숏헤어",
        "고등어",
        "귀 접힘",
    )
    assert repo.jobs[5].image is not None
    assert repo.jobs[5].failure is None
    # 재생성 success에는 원본을 보내지 않는다(Java가 무시)
    assert repo.jobs[5].original is None


def test_관리자가_아니면_403이고_Java를_부르지_않는다(
    client: TestClient, repo: FakeCharacterJobRepository, generator: FakeGenerator
) -> None:
    response = client.post(URL, headers=MEMBER)

    assert response.status_code == 403
    assert repo.regen_calls == []
    assert generator.calls == []


def test_쿠키가_없으면_401이다(client: TestClient, repo: FakeCharacterJobRepository) -> None:
    response = client.post(URL, headers={"X-Requested-With": "XMLHttpRequest"})

    assert response.status_code == 401
    assert repo.regen_calls == []


def test_X_Requested_With가_없으면_403이다(
    client: TestClient, repo: FakeCharacterJobRepository
) -> None:
    response = client.post(URL, headers={"Cookie": "access_token=admin"})

    assert response.status_code == 403
    assert repo.regen_calls == []


def test_생성기가_없으면_502이고_Java를_부르지_않는다(
    app, client: TestClient, repo: FakeCharacterJobRepository
) -> None:
    del app.dependency_overrides[get_character_client]

    response = client.post(URL, headers=ADMIN)

    assert response.status_code == 502
    assert repo.regen_calls == []


# 생성 결과 보고


@pytest.mark.parametrize(
    ("generator", "reason"),
    [
        (FakeGenerator(_png(256, 256)), CharacterFailure.SPEC_MISMATCH),
        (FakeGenerator(CharacterApiError()), CharacterFailure.API_ERROR),
    ],
)
def test_규격_밖이거나_생성기가_실패하면_실패를_보고한다(
    client: TestClient, repo: FakeCharacterJobRepository, reason: CharacterFailure
) -> None:
    client.post(URL, headers=ADMIN)

    assert repo.jobs[5].failure == reason
    assert repo.jobs[5].image is None


@pytest.mark.parametrize("status", [404, 409])
def test_시작을_거절당하면_생성도_보고도_하지_않는다(
    client: TestClient, repo: FakeCharacterJobRepository, generator: FakeGenerator, status: int
) -> None:
    repo.regen_start_error = BackendError(status, b"{}", "application/json", [])

    response = client.post(URL, headers=ADMIN)

    assert response.status_code == 202
    assert repo.regen_calls == ["start"]
    assert generator.calls == []
    assert repo.jobs == {}


def test_원본_사진을_못_받으면_생성하지_않고_실패를_보고한다(
    client: TestClient, repo: FakeCharacterJobRepository, generator: FakeGenerator
) -> None:
    del repo.original_photos[5]

    client.post(URL, headers=ADMIN)

    assert generator.calls == []
    assert repo.jobs[5].failure == CharacterFailure.INPUT_ERROR


def test_성공하면_캐릭터_번호로_아이템_굽기를_대기열에_넣는다(
    client: TestClient, queue: BakeCounter
) -> None:
    client.post(URL, headers=ADMIN)

    assert queue.added
    assert {task.pixel_char_sn for task in queue.added} == {5}


def test_굽기_조회가_실패해도_예외가_밖으로_나가지_않는다(
    client: TestClient, repo: FakeCharacterJobRepository, queue: BakeCounter
) -> None:
    async def broken() -> dict:
        raise BackendError(401, b"{}", "application/json", [])

    repo.list_bake_items = broken  # type: ignore[method-assign]

    response = client.post(URL, headers=ADMIN)

    assert response.status_code == 202
    assert repo.jobs[5].image is not None
    assert queue.added == []


# Java 호출 : 쿠키·X-Requested-With, 응답 해석

SETTINGS = Settings(backend_base_url="http://backend.test")


def java(handler, cookie: str = "access_token=admin") -> JavaCharacterJobRepository:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return JavaCharacterJobRepository(client, SETTINGS, cookie)


@pytest.mark.anyio
async def test_regen_start는_등록_정보를_읽고_쿠키와_헤더를_싣는다() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        data = {"charCrtJobSn": 5, "petSeCd": "PETC0001", "vrtyNm": "말티즈", "colrNm": None}
        return httpx2.Response(200, json={"data": data})

    job = await java(handler).regen_start(5)

    assert job == CharacterJob(5, "PETC0001", "말티즈", None, None)
    [request] = seen
    assert request.method == "POST"
    assert request.url.path == "/internal/ai/characters/jobs/5/regen-start"
    assert request.headers["cookie"] == "access_token=admin"
    assert request.headers["x-requested-with"] == "XMLHttpRequest"


@pytest.mark.anyio
@pytest.mark.parametrize("status", [404, 409])
async def test_regen_start의_4xx는_그대로_전달한다(status: int) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json={"code": "ALREADY_PROCESSED"})

    with pytest.raises(BackendError) as error:
        await java(handler).regen_start(5)

    assert error.value.status_code == status


@pytest.mark.anyio
async def test_regen_start_응답_모양이_다르면_502다() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"data": {"charCrtJobSn": 5}})

    with pytest.raises(AppError) as error:
        await java(handler).regen_start(5)

    assert error.value.http_code == 502


@pytest.mark.anyio
async def test_original_photo는_바이트를_그대로_받는다() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, content=PHOTO, headers={"content-type": "image/png"})

    photo = await java(handler).fetch_original_photo(5)

    assert photo == PHOTO
    assert seen[0].method == "GET"
    assert seen[0].url.path == "/internal/ai/characters/jobs/5/original-photo"
    assert seen[0].headers["cookie"] == "access_token=admin"
