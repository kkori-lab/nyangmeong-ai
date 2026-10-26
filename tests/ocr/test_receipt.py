import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app
from app.ocr.clients import OcrApiError, get_ocr_client
from app.ocr.schemas import ReceiptOcrResponse

URL = "/internal/v1/ocr/receipt"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch):
    # 각자 PC의 .env.local 값과 무관하게 mock 모드로 기동
    monkeypatch.setenv("AI_MODE", "mock")
    monkeypatch.setenv("OCR_TIMEOUT_SEC", "0.05")
    get_settings.cache_clear()
    return create_app()


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def _post(client: TestClient, content: bytes = PNG):
    return client.post(URL, files={"file": ("r.png", content)})


def test_mock_응답이_ReceiptOcrResponse_모양이다(client: TestClient) -> None:
    response = _post(client)

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    data = body["data"]
    assert set(data) == {"hsptlNm", "ckupYmd", "recptAmt", "btmDscntAmt", "sections"}
    assert data["ckupYmd"] == "2026-10-20"
    # 읽지 못한 값 = null 유지
    assert data["btmDscntAmt"] is None
    section = data["sections"][0]
    assert set(section) == {"sectionNm", "sbttlAmt", "dscntAmt", "items", "drugs"}
    assert set(section["drugs"][0]) == {"mdcnNm", "mdcnDays", "mdcnUsage", "mdcnAmt"}


def test_이미지로_읽히지_않는_파일은_400(client: TestClient) -> None:
    response = _post(client, content=b"%PDF-1.4 not an image")

    assert response.status_code == 400
    assert response.json()["code"] == "FILE_TYPE_NOT_ALLOWED"


def test_file_파트가_없으면_400(client: TestClient) -> None:
    response = client.post(URL)

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize(
    "content",
    [b"\xff\xd8\xff\xe0" + b"0" * 8, PNG, b"RIFF\x00\x00\x00\x00WEBPVP8 "],
)
def test_jpg_png_webp_시그니처는_통과한다(client: TestClient, content: bytes) -> None:
    assert _post(client, content=content).status_code == 200


class _Fake:
    def __init__(self, behavior: str) -> None:
        self.behavior = behavior

    async def recognize(self, image: bytes) -> ReceiptOcrResponse:
        if self.behavior == "empty":
            return ReceiptOcrResponse()
        if self.behavior == "slow":
            await asyncio.sleep(1)
        raise OcrApiError("boom")


def test_추출_0건은_200_빈_값(app, client: TestClient) -> None:
    app.dependency_overrides[get_ocr_client] = lambda: _Fake("empty")

    response = _post(client)

    data = response.json()["data"]
    assert response.status_code == 200
    assert data["sections"] == []
    assert data["hsptlNm"] is None


def test_분석_시간_초과는_504_OCR_TIMEOUT(app, client: TestClient) -> None:
    app.dependency_overrides[get_ocr_client] = lambda: _Fake("slow")

    response = _post(client)

    assert response.status_code == 504
    assert response.json()["code"] == "OCR_TIMEOUT"


def test_외부_API_오류는_502_OCR_API_ERROR(app, client: TestClient) -> None:
    app.dependency_overrides[get_ocr_client] = lambda: _Fake("error")

    response = _post(client)

    assert response.status_code == 502
    assert response.json()["code"] == "OCR_API_ERROR"
