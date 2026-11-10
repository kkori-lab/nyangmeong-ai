import asyncio
import logging

import httpx2
from fastapi.testclient import TestClient

from app.chat import catalog, tools
from app.core.backend import TIMEOUT_SEC, call_backend, create_backend_client, external_error
from app.core.config import Settings, get_settings
from app.main import create_app
from tests.chat.fakes import FakeToolCatalogClient, fake_catalog_json

LOGGER = "app.chat.catalog"


class FlakyCatalogClient(FakeToolCatalogClient):
    """앞의 fails번은 502, 그 뒤엔 Java 목록"""

    def __init__(self, fails: int) -> None:
        super().__init__()
        self.fails = fails

    async def fetch(self) -> catalog.ToolCatalogResponse:
        self.calls += 1
        if self.calls <= self.fails:
            raise external_error()
        return catalog.ToolCatalogResponse.model_validate(self.response)


class Sleeps:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, sec: float) -> None:
        self.waits.append(sec)


def test_도구_목록_호출만_제한_시간을_20초로_늘려야_한다():
    timeouts: dict[str, dict] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        timeouts[request.url.path] = request.extensions["timeout"]
        if request.url.path == catalog.CATALOG_PATH:
            return httpx2.Response(200, json={"status": "success", "data": fake_catalog_json()})
        return httpx2.Response(200, json={"status": "success", "data": None})

    backend = httpx2.AsyncClient(transport=httpx2.MockTransport(handler), timeout=TIMEOUT_SEC)
    settings = Settings(_env_file=None, backend_base_url="http://backend.test")

    async def run() -> None:
        await catalog.JavaToolCatalogClient(backend, settings).fetch()
        await call_backend(backend, settings, "GET", "/internal/other")

    asyncio.run(run())

    assert catalog.CATALOG_TIMEOUT_SEC == 20.0
    assert timeouts[catalog.CATALOG_PATH]["read"] == 20.0
    assert timeouts["/internal/other"]["read"] == TIMEOUT_SEC == 3.0
    assert create_backend_client().timeout.read == 3.0


def test_기동_실패_로그에_이유와_제한_시간을_남겨야_한다(caplog):
    class TimeoutClient(FakeToolCatalogClient):
        async def fetch(self) -> catalog.ToolCatalogResponse:
            try:
                raise httpx2.ReadTimeout("slow")
            except httpx2.ReadTimeout as error:
                raise external_error() from error

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        installed = asyncio.run(catalog.install(TimeoutClient()))

    assert installed.source == "snapshot"
    assert "Java 받기 실패(제한 시간 초과 ReadTimeout, 20초), 스냅샷으로" in caplog.text


def test_응답_모양이_다르면_첫_오류_위치를_남겨야_한다(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        asyncio.run(catalog.install(FakeToolCatalogClient(response={"tools": 1})))

    assert "Java 받기 실패(응답 모양 다름" in caplog.text


def test_다시_받기가_두_번_실패한_뒤_성공하면_Java_목록으로_바꾸고_멈춰야_한다(caplog):
    client = FlakyCatalogClient(fails=2)
    used: list[catalog.Catalog] = []
    sleeps = Sleeps()

    with caplog.at_level(logging.INFO, logger=LOGGER):
        result = asyncio.run(catalog.retry(client, used.append, sleep=sleeps))

    assert result is not None and result.source == "java"
    assert used == [result]
    assert client.calls == 3
    assert sleeps.waits == [30.0, 30.0, 30.0]
    assert "다시 받기 1/10 실패(AppError)" in caplog.text
    assert "다시 받기 2/10 실패" in caplog.text
    assert "도구 목록: java" in caplog.text


def test_다시_받기가_모두_실패하면_스냅샷을_유지하고_포기를_경고해야_한다(caplog):
    client = FakeToolCatalogClient(fail=True)
    used: list[catalog.Catalog] = []

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        result = asyncio.run(catalog.retry(client, used.append, sleep=Sleeps()))

    assert result is None
    assert used == []
    assert client.calls == catalog.RETRY_ATTEMPTS == 10
    assert "다시 받기 10/10 실패" in caplog.text
    assert "다시 받기 10번 모두 실패, 스냅샷 유지" in caplog.text


def _start(monkeypatch, client: FakeToolCatalogClient, retried: list) -> None:
    monkeypatch.setenv("BACKEND_BASE_URL", "http://backend.test")
    get_settings.cache_clear()
    monkeypatch.setattr(catalog, "JavaToolCatalogClient", lambda *args: client)

    async def fake_retry(client, use):
        retried.append(client)
        await asyncio.Event().wait()

    monkeypatch.setattr(catalog, "retry", fake_retry)


def test_기동_때_받기에_성공하면_다시_받지_않아야_한다(monkeypatch):
    retried: list = []
    _start(monkeypatch, FakeToolCatalogClient(), retried)

    with TestClient(create_app()):
        active = tools.active_catalog()

    get_settings.cache_clear()
    assert active is not None and active.source == "java"
    assert retried == []


def test_기동_때_실패하면_뒤에서_다시_받고_종료_때_취소해야_한다(monkeypatch):
    retried: list = []
    tasks: list[asyncio.Task] = []
    _start(monkeypatch, FakeToolCatalogClient(fail=True), retried)
    real_create_task = asyncio.create_task

    def create_task(coro):
        task = real_create_task(coro)
        tasks.append(task)
        return task

    monkeypatch.setattr(asyncio, "create_task", create_task)

    with TestClient(create_app()) as http:
        http.get("/health")
        active = tools.active_catalog()

    get_settings.cache_clear()
    assert active is not None and active.source == "snapshot"
    assert len(retried) == 1
    assert len(tasks) == 1 and tasks[0].cancelled()
