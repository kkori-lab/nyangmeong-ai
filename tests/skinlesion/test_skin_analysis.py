import asyncio
import io
from collections.abc import Sequence

import httpx2
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.backend import get_backend_client
from app.core.config import get_settings
from app.core.image import MAX_IMAGE_BYTES
from app.main import create_app
from app.skinlesion.clients import Finding, SkinJudgeApiError, SkinJudgement, get_skin_judge

URL = "/ai/skin-analyses"
AJAX = {"X-Requested-With": "XMLHttpRequest"}
COOKIE = {"Cookie": "access_token=member-7"}


def png(width: int = 2048, height: int = 1024) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (200, 150, 120)).save(out, "PNG")
    return out.getvalue()


PNG = png()


def fake_auth_check(request: httpx2.Request) -> httpx2.Response:
    """Java /internal/auth/check 흉내 : 쿠키 access_token=member-<번호>면 통과"""
    if "access_token=member-" in request.headers.get("cookie", ""):
        return httpx2.Response(200, json={"data": {"mbrSn": 7, "mbrAuthrtCd": "U"}})
    body = {"status": "error", "httpCode": 401, "code": "UNAUTHORIZED", "path": "/internal/x"}
    return httpx2.Response(401, json=body, headers={"set-cookie": "access_token=; Max-Age=0"})


class FakeSkinJudge:
    """result: 돌려줄 판정(None = 거절·깨진 출력) 또는 behavior slow·error. 받은 사진은 calls에"""

    def __init__(self) -> None:
        self.result: SkinJudgement | None = SkinJudgement(
            True, (Finding("hair_loss", "HIGH"), Finding("redness", "MEDIUM"))
        )
        self.behavior = "ok"
        self.calls: list[tuple[bytes, list[tuple[str, str]]]] = []

    async def judge(self, jpeg: bytes, lesions: Sequence[tuple[str, str]]) -> SkinJudgement | None:
        self.calls.append((jpeg, list(lesions)))
        if self.behavior == "slow":
            await asyncio.sleep(1)
        if self.behavior == "error":
            raise SkinJudgeApiError("boom")
        return self.result


@pytest.fixture
def judge() -> FakeSkinJudge:
    return FakeSkinJudge()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, judge: FakeSkinJudge):
    monkeypatch.setenv("BACKEND_BASE_URL", "http://backend.test")
    monkeypatch.setenv("SKIN_ANALYZE_TIMEOUT_SEC", "0.05")
    get_settings.cache_clear()
    app = create_app()
    backend = httpx2.AsyncClient(transport=httpx2.MockTransport(fake_auth_check))
    app.dependency_overrides[get_backend_client] = lambda: backend
    app.dependency_overrides[get_skin_judge] = lambda: judge
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def post(client: TestClient, data: bytes = PNG, name: str = "skin.png", headers=None):
    headers = {**AJAX, **COOKIE} if headers is None else headers
    return client.post(URL, files={"file": (name, data)}, headers=headers)


def test_피부분석_정상이면_등급_병변_안내문(client, judge):
    res = post(client)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["rslt"] == "ANALYZED"
    assert data["grade"] == "VISIT"
    assert data["findings"] == [
        {"lesionCd": "hair_loss", "lesionNm": "털 빠짐", "cnfdnc": "HIGH"},
        {"lesionCd": "redness", "lesionNm": "붉은 기·발진", "cnfdnc": "MEDIUM"},
    ]
    assert data["guide"]
    assert "수의사" in data["notice"]
    assert data["ruleVersion"]


def test_피부분석_판정기에_목록과_긴변_1024_JPEG를_보낸다(client, judge):
    post(client)
    jpeg, lesions = judge.calls[0]
    assert jpeg.startswith(b"\xff\xd8\xff")
    with Image.open(io.BytesIO(jpeg)) as opened:
        assert max(opened.size) == 1024
    assert ("normal", "이상 없음") in lesions


def test_피부분석_반려동물_피부가_아니면_NOT_PET_SKIN(client, judge):
    judge.result = SkinJudgement(False)
    data = post(client).json()["data"]
    assert data["rslt"] == "NOT_PET_SKIN"
    assert data["grade"] is None
    assert data["findings"] == []
    assert data["guide"]


@pytest.mark.parametrize(
    "result",
    [
        SkinJudgement(True, (Finding("hair_loss", "LOW"),)),  # LOW만
        SkinJudgement(True, (Finding("unknown_key", "HIGH"),)),  # 목록 밖 값
        SkinJudgement(True, ()),  # 병변 없음
        None,  # 거절·깨진 출력
    ],
    ids=["LOW만", "목록밖", "병변없음", "거절"],
)
def test_피부분석_판단하기_어려우면_200_UNCLEAR(client, judge, result):
    judge.result = result
    res = post(client)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["rslt"] == "UNCLEAR"
    assert data["grade"] is None
    assert data["findings"] == []


def test_피부분석_시간_초과는_504(client, judge):
    judge.behavior = "slow"
    res = post(client)
    assert res.status_code == 504
    assert res.json()["code"] == "SKIN_ANALYZE_TIMEOUT"


def test_피부분석_외부_API_오류는_502(client, judge):
    judge.behavior = "error"
    res = post(client)
    assert res.status_code == 502
    assert res.json()["code"] == "SKIN_ANALYZE_API_ERROR"


def test_피부분석_LLM_키가_없으면_502(app):
    # 가짜를 빼면 실제 의존성 : tests/conftest.py가 키를 비워 둠
    del app.dependency_overrides[get_skin_judge]
    res = post(TestClient(app))
    assert res.status_code == 502
    assert res.json()["code"] == "EXTERNAL_API_ERROR"


@pytest.mark.parametrize(
    ("data", "name", "code"),
    [
        (PNG, "skin.pdf", "FILE_TYPE_NOT_ALLOWED"),  # 확장자 불일치
        (b"%PDF-1.7\n0000", "skin.png", "FILE_TYPE_NOT_ALLOWED"),  # 실제 형식 불일치
        (b"\x89PNG\r\n\x1a\n" + b"0" * 16, "skin.png", "FILE_TYPE_NOT_ALLOWED"),  # 열 수 없음
        (b"\x89PNG\r\n\x1a\n" + b"0" * MAX_IMAGE_BYTES, "skin.png", "FILE_SIZE_EXCEEDED"),
    ],
    ids=["확장자", "실제형식", "열수없음", "10MB초과"],
)
def test_피부분석_업로드_검증_실패는_400이고_판정기를_안_부른다(client, judge, data, name, code):
    res = post(client, data, name)
    assert res.status_code == 400
    assert res.json()["code"] == code
    assert judge.calls == []


def test_피부분석_파일이_없으면_400(client, judge):
    res = client.post(URL, headers={**AJAX, **COOKIE})
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"
    assert judge.calls == []


def test_피부분석_쿠키가_없으면_401(client, judge):
    res = post(client, headers=AJAX)
    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHORIZED"
    assert judge.calls == []


def test_피부분석_X_Requested_With가_없으면_403(client, judge):
    res = post(client, headers=COOKIE)
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"
    assert judge.calls == []
