import asyncio

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.checkup.clients import (
    LabResultOutput,
    LabRow,
    PdfAnalyzeApiError,
    get_lab_result_client,
)
from app.checkup.rules import MAX_PDF_BYTES
from app.core.backend import get_backend_client
from app.core.config import get_settings
from app.main import create_app

URL = "/ai/checkups/lab-results"
AJAX = {"X-Requested-With": "XMLHttpRequest"}
COOKIE = {"Cookie": "access_token=member-7"}
PDF = b"%PDF-1.7\n" + b"0" * 16
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16
OUTPUT = LabResultOutput(
    is_lab_result=True,
    rows=[
        LabRow(name="Creatinine", value="1.2", unit="mg/dL", ref_min="0.5", ref_max="1.8"),
        LabRow(name="ALT", value="45", unit="U/L", ref_min="10", ref_max=None),
        LabRow(name="요비중", value="1.030", blood=False),
        LabRow(name=None, value="3"),
    ],
)


def fake_auth_check(request: httpx2.Request) -> httpx2.Response:
    """Java /internal/auth/check 흉내 : 쿠키 access_token=member-<번호>면 통과"""
    if "access_token=member-" in request.headers.get("cookie", ""):
        return httpx2.Response(200, json={"data": {"mbrSn": 7, "mbrAuthrtCd": "U"}})
    body = {"status": "error", "httpCode": 401, "code": "UNAUTHORIZED", "path": "/internal/x"}
    return httpx2.Response(401, json=body, headers={"set-cookie": "access_token=; Max-Age=0"})


class FakeLabClient:
    """behavior: ok·empty·not_lab·error·slow. 받은 PDF는 calls에 기록"""

    def __init__(self, behavior: str = "ok") -> None:
        self.behavior = behavior
        self.calls: list[bytes] = []

    async def read(self, pdf: bytes) -> LabResultOutput:
        self.calls.append(pdf)
        if self.behavior == "slow":
            await asyncio.sleep(1)
        if self.behavior == "empty":
            return LabResultOutput(is_lab_result=True)
        if self.behavior == "not_lab":
            return LabResultOutput(is_lab_result=False)
        if self.behavior == "error":
            raise PdfAnalyzeApiError("boom")
        return OUTPUT


@pytest.fixture
def lab() -> FakeLabClient:
    return FakeLabClient()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, lab: FakeLabClient):
    monkeypatch.setenv("BACKEND_BASE_URL", "http://backend.test")
    monkeypatch.setenv("PDF_ANALYZE_TIMEOUT_SEC", "0.05")
    get_settings.cache_clear()
    app = create_app()
    backend = httpx2.AsyncClient(transport=httpx2.MockTransport(fake_auth_check))
    app.dependency_overrides[get_backend_client] = lambda: backend
    app.dependency_overrides[get_lab_result_client] = lambda: lab
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def post(client: TestClient, data: bytes = PDF, name: str = "result.pdf", headers=None):
    headers = {**AJAX, **COOKIE} if headers is None else headers
    return client.post(URL, files={"file": (name, data, "application/pdf")}, headers=headers)


def test_PDF를_읽어_SCR_HLT_007_입력값_모양으로_돌려준다(client, lab) -> None:
    res = post(client)

    assert res.status_code == 200
    assert lab.calls == [PDF]
    data = res.json()["data"]
    # 이름은 백엔드 InspectionAnalysisItem(INSP_NVL)과 동일, 숫자는 JSON 숫자
    assert data["items"] == [
        {
            "inspArtclCd": "HLTC0030",
            "inspArtclDrctInptNm": None,
            "rsltNvl": 1.2,
            "unitNm": "mg/dL",
            "refLlmtNvl": 0.5,
            "refUplmtNvl": 1.8,
        },
        # 참고범위가 한쪽만 읽히면 둘 다 빈 값
        {
            "inspArtclCd": "HLTC0031",
            "inspArtclDrctInptNm": None,
            "rsltNvl": 45,
            "unitNm": "U/L",
            "refLlmtNvl": None,
            "refUplmtNvl": None,
        },
    ]
    # 혈액검사가 아닌 항목은 이름만 안내용으로
    assert data["excludedArtclNms"] == ["요비중"]


def test_인식_항목_0건은_200_빈_배열(client, lab) -> None:
    lab.behavior = "empty"
    res = post(client)

    assert res.status_code == 200
    assert res.json()["data"] == {"items": [], "excludedArtclNms": []}


def test_검사결과지가_아니면_422_NOT_LAB_RESULT(client, lab) -> None:
    lab.behavior = "not_lab"
    res = post(client)

    assert res.status_code == 422
    assert res.json()["code"] == "NOT_LAB_RESULT"


@pytest.mark.parametrize(
    ("data", "name", "code"),
    [
        (PNG, "result.png", "FILE_TYPE_NOT_ALLOWED"),
        (PNG, "result.pdf", "FILE_TYPE_NOT_ALLOWED"),
        (PDF, "result.jpg", "FILE_TYPE_NOT_ALLOWED"),
        (PDF + b"0" * MAX_PDF_BYTES, "result.pdf", "FILE_SIZE_EXCEEDED"),
    ],
    ids=["png", "png_as_pdf", "pdf_as_jpg", "over_10mb"],
)
def test_업로드_검증_실패는_400이고_LLM을_부르지_않는다(client, lab, data, name, code) -> None:
    res = post(client, data, name)

    assert res.status_code == 400
    assert res.json()["code"] == code
    assert lab.calls == []


def test_파일이_없으면_400_INVALID_REQUEST(client, lab) -> None:
    res = client.post(URL, headers={**AJAX, **COOKIE})

    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"
    assert lab.calls == []


def test_시간_초과는_504_PDF_ANALYZE_TIMEOUT(client, lab) -> None:
    lab.behavior = "slow"
    res = post(client)

    assert res.status_code == 504
    assert res.json()["code"] == "PDF_ANALYZE_TIMEOUT"


def test_외부_API_오류는_502_PDF_ANALYZE_API_ERROR(client, lab) -> None:
    lab.behavior = "error"
    res = post(client)

    assert res.status_code == 502
    assert res.json()["code"] == "PDF_ANALYZE_API_ERROR"


def test_LLM_키가_없으면_502_EXTERNAL_API_ERROR(app) -> None:
    # 가짜를 빼고 실제 의존성 : conftest가 키를 비웠다
    del app.dependency_overrides[get_lab_result_client]
    res = post(TestClient(app))

    assert res.status_code == 502
    assert res.json()["code"] == "EXTERNAL_API_ERROR"


def test_LLM_키가_없어도_업로드_검증이_먼저(app) -> None:
    del app.dependency_overrides[get_lab_result_client]
    res = post(TestClient(app), PNG, "result.png")

    assert res.status_code == 400
    assert res.json()["code"] == "FILE_TYPE_NOT_ALLOWED"


def test_인증_없으면_Java_401을_그대로_전달(client, lab) -> None:
    res = post(client, headers=AJAX)

    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHORIZED"
    assert res.json()["path"] == URL
    assert "access_token=" in res.headers["set-cookie"]
    assert lab.calls == []


def test_X_Requested_With가_없으면_403(client, lab) -> None:
    res = post(client, headers=COOKIE)

    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"
    assert lab.calls == []
