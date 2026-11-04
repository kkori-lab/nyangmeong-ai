from datetime import date

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.core.backend import get_backend_client
from app.core.config import get_settings
from app.healthreport import rules
from app.healthreport.clients import get_report_generator
from app.healthreport.repository import get_health_report_repository
from app.healthreport.router import get_base_ymd
from app.healthreport.schemas import HealthReportInput, HealthReportSource, SavedReport
from app.main import create_app
from tests.healthreport.fakes import BASE_YMD, FakeGenerator, FakeRepository, sample_input

URL = "/ai/pets/3/health-report"
REFRESH_URL = "/ai/pets/3/health-report/refresh"
AJAX = {"X-Requested-With": "XMLHttpRequest"}
COOKIE = {"Cookie": "access_token=member-7"}


def fake_auth_check(request: httpx2.Request) -> httpx2.Response:
    """Java /internal/auth/check 흉내 : 쿠키 access_token=member-<번호>면 통과"""
    if "access_token=member-" in request.headers.get("cookie", ""):
        return httpx2.Response(200, json={"data": {"mbrSn": 7, "mbrAuthrtCd": "U"}})
    body = {"status": "error", "httpCode": 401, "code": "UNAUTHORIZED", "path": "/internal/x"}
    return httpx2.Response(401, json=body, headers={"set-cookie": "access_token=; Max-Age=0"})


def saved_for(data: HealthReportInput, base_ymd: date = BASE_YMD) -> SavedReport:
    return SavedReport(
        rpt_ttl="건강해요", tips=["잘 지내고 있어요"], input_hash=rules.input_hash(base_ymd, data)
    )


def source(
    data: HealthReportInput | None = None,
    report: SavedReport | None = None,
    rfrsh: bool = True,
    auto: bool = True,
) -> HealthReportSource:
    return HealthReportSource(
        input=data or sample_input(), report=report, rfrsh_psbl_yn=rfrsh, auto_rgnr_psbl_yn=auto
    )


@pytest.fixture
def gen() -> FakeGenerator:
    return FakeGenerator()


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository(source())


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, gen: FakeGenerator, repo: FakeRepository):
    monkeypatch.setenv("BACKEND_BASE_URL", "http://backend.test")
    monkeypatch.setenv("HEALTH_REPORT_TIMEOUT_SEC", "0.05")
    get_settings.cache_clear()
    app = create_app()
    backend = httpx2.AsyncClient(transport=httpx2.MockTransport(fake_auth_check))
    app.dependency_overrides[get_backend_client] = lambda: backend
    app.dependency_overrides[get_report_generator] = lambda: gen
    app.dependency_overrides[get_health_report_repository] = lambda: repo
    app.dependency_overrides[get_base_ymd] = lambda: BASE_YMD
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def get(client: TestClient, headers=None):
    return client.get(URL, headers={**AJAX, **COOKIE} if headers is None else headers)


def refresh(client: TestClient, headers=None):
    return client.post(REFRESH_URL, headers={**AJAX, **COOKIE} if headers is None else headers)


# ① 저장본 해시가 지금 입력과 같으면 그대로
def test_입력_해시가_같으면_LLM과_저장을_부르지_않고_저장본(client, gen, repo) -> None:
    data = sample_input()
    repo.source = source(data, saved_for(data), rfrsh=True)

    res = get(client)

    assert res.status_code == 200
    body = res.json()["data"]
    assert body["rptTtl"] == "건강해요"
    assert body["tips"] == ["잘 지내고 있어요"]
    assert body["staleYn"] is False
    assert body["dataLackYn"] is False
    assert body["rfrshPsblYn"] is True
    assert body["notice"] == rules.NOTICE
    assert gen.calls == []
    assert repo.saves == []
    assert repo.gets == [(3, BASE_YMD)]


# ② 기록 하나가 바뀌면 다시 생성
def test_기록_하나가_바뀌면_다시_생성하고_새_해시로_저장(client, gen, repo) -> None:
    old = sample_input(5.2)
    new = sample_input(4.6)
    repo.source = source(new, saved_for(old))

    res = get(client)

    assert res.status_code == 200
    body = res.json()["data"]
    assert body["petSn"] == 3
    assert body["baseYmd"] == "2026-11-04"
    assert body["rptTtl"] == "물을 조금 더 마시면 좋아요"
    assert body["tips"] == ["음수량이 평소보다 적어요", "ALT 수치는 수의사와 상담해 보세요"]
    assert body["notice"] == rules.NOTICE
    assert body["staleYn"] is False
    assert "crtDt" in body
    assert len(gen.calls) == 1
    assert len(repo.saves) == 1
    pet_sn, saved = repo.saves[0]
    assert pet_sn == 3
    assert saved.input_hash == rules.input_hash(BASE_YMD, new)
    assert saved.input_hash != rules.input_hash(BASE_YMD, old)
    assert saved.rfrsh_yn is False
    assert saved.base_ymd == BASE_YMD


# ③ 저장본이 없으면 ②와 같다
def test_저장본이_없으면_생성하고_저장(client, gen, repo) -> None:
    repo.source = source(sample_input(), None)

    res = get(client)

    assert res.status_code == 200
    assert len(gen.calls) == 1
    assert len(repo.saves) == 1
    assert repo.saves[0][1].rfrsh_yn is False


# ④ 기록이 같고 기준일만 다르면 다시 생성 (자정 갱신)
def test_기록이_같아도_기준일이_바뀌면_다시_생성(client, gen, repo) -> None:
    data = sample_input()
    repo.source = source(data, saved_for(data, date(2026, 11, 3)))

    res = get(client)

    assert res.status_code == 200
    assert len(gen.calls) == 1
    assert repo.saves[0][1].input_hash == rules.input_hash(BASE_YMD, data)


# ⑤ 저장 실패해도 200
def test_저장이_실패해도_리포트는_200(client, gen, repo) -> None:
    repo.save_fails = True

    res = get(client)

    assert res.status_code == 200
    assert res.json()["data"]["rptTtl"] == "물을 조금 더 마시면 좋아요"
    assert len(repo.saves) == 1


def test_14일_기록이_없으면_LLM과_저장_없이_데이터_부족(client, gen, repo) -> None:
    repo.source = source(HealthReportInput(pet_nm="나비"), None)

    res = get(client)

    assert res.status_code == 200
    body = res.json()["data"]
    assert body["dataLackYn"] is True
    assert body["rptTtl"] == rules.DATA_LACK_TITLE
    assert body["tips"] == rules.DATA_LACK_TIPS
    assert body["notice"] == rules.NOTICE
    assert gen.calls == []
    assert repo.saves == []


def test_자동_재생성_상한이면_LLM_없이_저장본을_stale로(client, gen, repo) -> None:
    repo.source = source(sample_input(4.6), saved_for(sample_input(5.2)), auto=False)

    res = get(client)

    assert res.status_code == 200
    body = res.json()["data"]
    assert body["staleYn"] is True
    assert body["rptTtl"] == "건강해요"
    assert gen.calls == []
    assert repo.saves == []


def test_새로고침_불가면_LLM_없이_409(client, gen, repo) -> None:
    data = sample_input()
    repo.source = source(data, saved_for(data), rfrsh=False)

    res = refresh(client)

    assert res.status_code == 409
    assert res.json()["code"] == "HEALTH_REPORT_REFRESH_LIMIT"
    assert gen.calls == []
    assert repo.saves == []


def test_새로고침은_입력이_같아도_다시_생성하고_rfrshYn_true(client, gen, repo) -> None:
    data = sample_input()
    repo.source = source(data, saved_for(data), rfrsh=True)

    res = refresh(client)

    assert res.status_code == 200
    body = res.json()["data"]
    assert body["rptTtl"] == "물을 조금 더 마시면 좋아요"
    assert body["rfrshPsblYn"] is False
    assert len(gen.calls) == 1
    assert repo.saves[0][1].rfrsh_yn is True


def test_Java_4xx는_본문_그대로_전달(monkeypatch, gen) -> None:
    def backend(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/internal/auth/check":
            return fake_auth_check(request)
        body = {"status": "error", "httpCode": 403, "code": "PET_ACCESS_DENIED", "path": "/x"}
        return httpx2.Response(403, json=body)

    monkeypatch.setenv("BACKEND_BASE_URL", "http://backend.test")
    get_settings.cache_clear()
    app = create_app()
    client_ = httpx2.AsyncClient(transport=httpx2.MockTransport(backend))
    app.dependency_overrides[get_backend_client] = lambda: client_
    app.dependency_overrides[get_report_generator] = lambda: gen

    res = get(TestClient(app))

    assert res.status_code == 403
    assert res.json()["code"] == "PET_ACCESS_DENIED"
    assert res.json()["path"] == URL
    assert gen.calls == []


def test_Java_입력_GET에_baseYmd와_쿠키를_보낸다(monkeypatch, gen) -> None:
    seen: list[httpx2.Request] = []
    data = sample_input()

    def backend(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/internal/auth/check":
            return fake_auth_check(request)
        seen.append(request)
        payload = source(data, saved_for(data)).model_dump(mode="json", by_alias=True)
        return httpx2.Response(200, json={"data": payload})

    monkeypatch.setenv("BACKEND_BASE_URL", "http://backend.test")
    get_settings.cache_clear()
    app = create_app()
    client_ = httpx2.AsyncClient(transport=httpx2.MockTransport(backend))
    app.dependency_overrides[get_backend_client] = lambda: client_
    app.dependency_overrides[get_report_generator] = lambda: gen
    app.dependency_overrides[get_base_ymd] = lambda: BASE_YMD

    res = get(TestClient(app))

    assert res.status_code == 200
    assert seen[0].url.path == "/internal/ai/pets/3/health-report-input"
    assert seen[0].url.params["baseYmd"] == "2026-11-04"
    assert "access_token=member-7" in seen[0].headers["cookie"]
    assert gen.calls == []


def test_LLM_시간_초과는_504(client, gen, repo) -> None:
    gen.behavior = "slow"

    res = get(client)

    assert res.status_code == 504
    assert res.json()["code"] == "HEALTH_REPORT_TIMEOUT"
    assert repo.saves == []


def test_LLM_오류는_502(client, gen, repo) -> None:
    gen.behavior = "error"

    res = get(client)

    assert res.status_code == 502
    assert res.json()["code"] == "HEALTH_REPORT_API_ERROR"
    assert repo.saves == []


def test_LLM_키가_없으면_생성이_필요할_때_502_EXTERNAL_API_ERROR(app, repo) -> None:
    app.dependency_overrides.pop(get_report_generator)

    res = get(TestClient(app))

    assert res.status_code == 502
    assert res.json()["code"] == "EXTERNAL_API_ERROR"


def test_LLM_키가_없어도_저장본은_돌려준다(app, repo) -> None:
    app.dependency_overrides.pop(get_report_generator)
    data = sample_input()
    repo.source = source(data, saved_for(data))

    res = get(TestClient(app))

    assert res.status_code == 200
    assert res.json()["data"]["rptTtl"] == "건강해요"


def test_인증_없으면_Java_401을_그대로_전달(client, gen, repo) -> None:
    res = get(client, headers=AJAX)

    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHORIZED"
    assert res.json()["path"] == URL
    assert "access_token=" in res.headers["set-cookie"]
    assert repo.gets == []
    assert gen.calls == []


def test_새로고침에_X_Requested_With가_없으면_403(client, gen, repo) -> None:
    res = refresh(client, headers=COOKIE)

    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"
    assert gen.calls == []
