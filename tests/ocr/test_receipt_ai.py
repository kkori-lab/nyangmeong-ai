import asyncio

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.core.backend import get_backend_client
from app.core.config import get_settings
from app.core.response import AppError
from app.main import create_app
from app.ocr import service
from app.ocr.clients import OcrApiError, get_ocr_client
from app.ocr.repository import FakeReceiptRepository, ReceiptStatus, get_receipt_repository
from app.ocr.schemas import Line, ReceiptOcrResponse, Section

URL = "/ai/receipts"
AJAX = {"X-Requested-With": "XMLHttpRequest"}
COOKIE = {"Cookie": "access_token=member-7"}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16
JPG = b"\xff\xd8\xff\xe0" + b"0" * 8
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 "
FORM = {"petSn": "3", "ocrRqstSrcCd": "AIMC0026"}
RESULT = ReceiptOcrResponse(
    hsptl_nm="냥멍동물병원",
    recpt_amt=30000,
    sections=[Section(section_nm="미르", items=[Line(item_nm="진료비", item_amt=30000)])],
)


def fake_auth_check(request: httpx2.Request) -> httpx2.Response:
    """Java /internal/auth/check 흉내 : 쿠키 access_token=member-<번호>면 통과"""
    cookie = request.headers.get("cookie", "")
    if "access_token=member-" in cookie:
        mbr_sn = int(cookie.split("access_token=member-", 1)[1].split(";", 1)[0])
        return httpx2.Response(200, json={"data": {"mbrSn": mbr_sn, "mbrAuthrtCd": "U"}})
    return httpx2.Response(401, json={"status": "error", "httpCode": 401, "code": "UNAUTHORIZED"})


class FakeOcr:
    """behavior: ok·empty·error·slow. 받은 이미지를 calls에 남긴다"""

    def __init__(self, behavior: str = "ok", delay: float = 0.0) -> None:
        self.behavior = behavior
        self.delay = delay
        self.calls: list[bytes] = []

    async def recognize(self, image: bytes) -> ReceiptOcrResponse:
        self.calls.append(image)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.behavior == "empty":
            return ReceiptOcrResponse()
        if self.behavior == "error":
            raise OcrApiError("boom")
        return RESULT


class FailingRepository(FakeReceiptRepository):
    """원본 저장에서 Java 오류"""

    async def save_original(self, image: bytes, file_name: str, pet_sn: int, src_cd: str) -> int:
        raise AppError("EXTERNAL_API_ERROR", 502, "외부 서비스 호출에 실패했습니다.")


@pytest.fixture
def repo() -> FakeReceiptRepository:
    return FakeReceiptRepository()


@pytest.fixture
def ocr() -> FakeOcr:
    return FakeOcr()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, repo: FakeReceiptRepository, ocr: FakeOcr):
    monkeypatch.setenv("BACKEND_BASE_URL", "http://backend.test")
    monkeypatch.setenv("OCR_TIMEOUT_SEC", "0.05")
    get_settings.cache_clear()
    app = create_app()
    backend = httpx2.AsyncClient(transport=httpx2.MockTransport(fake_auth_check))
    app.dependency_overrides[get_backend_client] = lambda: backend
    app.dependency_overrides[get_ocr_client] = lambda: ocr
    app.dependency_overrides[get_receipt_repository] = lambda: repo
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def post(client: TestClient, content: bytes = PNG, name: str = "r.png", **kwargs):
    headers = {**AJAX, **COOKIE, **kwargs.pop("headers", {})}
    data = kwargs.pop("data", FORM)
    return client.post(URL, files={"file": (name, content)}, data=data, headers=headers)


# 성공·응답 모양


def test_분석_결과는_recptSn과_ocr로_감싼다(
    client: TestClient, repo: FakeReceiptRepository
) -> None:
    response = post(client)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["recptSn"] == 1
    assert set(data["ocr"]) == {"hsptlNm", "ckupYmd", "recptAmt", "btmDscntAmt", "sections"}
    assert data["ocr"]["hsptlNm"] == "냥멍동물병원"


def test_원본_바이트와_반려동물_출처를_Java에_저장하고_인식완료를_보고한다(
    client: TestClient, repo: FakeReceiptRepository
) -> None:
    post(client)

    saved = repo.receipts[1]
    assert saved.image == PNG
    assert (saved.pet_sn, saved.src_cd, saved.file_name) == (3, "AIMC0026", "r.png")
    assert saved.status is ReceiptStatus.RECOGNIZED
    assert saved.result == RESULT


@pytest.mark.parametrize(
    ("behavior", "delay", "http_code", "code", "status"),
    [
        # FN-AIM-010-01 : 추출 0건은 인식 실패(200 빈 응답)
        ("empty", 0.0, 200, None, ReceiptStatus.UNRECOGNIZED),
        # FN-AIM-008-07 : 15초 초과는 일시 오류(시간 초과)
        ("ok", 1.0, 504, "OCR_TIMEOUT", ReceiptStatus.TIMEOUT),
        # FN-AIM-010-01 : API 오류는 일시 오류(API)
        ("error", 0.0, 502, "OCR_API_ERROR", ReceiptStatus.API_ERROR),
    ],
)
def test_결과별_응답과_Java에_보고한_상태(
    app, repo: FakeReceiptRepository, behavior, delay, http_code, code, status
) -> None:
    app.dependency_overrides[get_ocr_client] = lambda: FakeOcr(behavior, delay)

    response = post(TestClient(app))

    assert response.status_code == http_code
    assert response.json().get("code") == code
    # FN-AIM-010-06 : 실패해도 원본은 저장돼 있다
    assert repo.receipts[1].image == PNG
    assert repo.receipts[1].status is status


def test_추출_0건_응답은_값이_null이고_구역이_빈_배열(app) -> None:
    app.dependency_overrides[get_ocr_client] = lambda: FakeOcr("empty")

    data = post(TestClient(app)).json()["data"]

    assert data["recptSn"] == 1
    assert data["ocr"]["hsptlNm"] is None
    assert data["ocr"]["sections"] == []


# FN-AIM-008-05 업로드 제약


@pytest.mark.parametrize(
    ("content", "name"),
    [(JPG, "r.jpg"), (JPG, "r.JPEG"), (PNG, "r.png"), (WEBP, "r.webp")],
)
def test_jpg_jpeg_png_webp는_통과한다(client: TestClient, content: bytes, name: str) -> None:
    assert post(client, content, name).status_code == 200


@pytest.mark.parametrize(
    ("content", "name"),
    [
        (b"hello", "r.png"),  # 확장자만 png
        (PNG, "r.txt"),  # 실제는 png, 확장자가 밖
        (JPG, "r.png"),  # 확장자와 실제 형식이 다름
        (b"%PDF-1.4", "r.pdf"),  # PDF는 받지 않는다
        (PNG, "noext"),
    ],
)
def test_형식이_맞지_않으면_400_FILE_TYPE_NOT_ALLOWED이고_Java_OCR을_부르지_않는다(
    client: TestClient, repo: FakeReceiptRepository, ocr: FakeOcr, content: bytes, name: str
) -> None:
    response = post(client, content, name)

    assert response.status_code == 400
    assert response.json()["code"] == "FILE_TYPE_NOT_ALLOWED"
    assert repo.receipts == {}
    assert ocr.calls == []


def test_10MB_초과는_400_FILE_SIZE_EXCEEDED이고_Java_OCR을_부르지_않는다(
    client: TestClient, repo: FakeReceiptRepository, ocr: FakeOcr
) -> None:
    big = PNG + b"0" * (10 * 1024 * 1024 + 1 - len(PNG))

    response = post(client, big)

    assert response.status_code == 400
    assert response.json()["code"] == "FILE_SIZE_EXCEEDED"
    assert repo.receipts == {}
    assert ocr.calls == []


def test_정확히_10MB는_통과한다(client: TestClient) -> None:
    exact = PNG + b"0" * (10 * 1024 * 1024 - len(PNG))
    assert post(client, exact).status_code == 200


@pytest.mark.parametrize(
    "data",
    [
        {"ocrRqstSrcCd": "AIMC0026"},  # petSn 없음
        {"petSn": "3"},  # 출처 없음
        {"petSn": "3", "ocrRqstSrcCd": "AIMC9999"},  # 허용값 밖
        {"petSn": "abc", "ocrRqstSrcCd": "AIMC0026"},
    ],
)
def test_폼_값이_없거나_틀리면_400_INVALID_REQUEST(
    client: TestClient, repo: FakeReceiptRepository, data: dict
) -> None:
    response = post(client, data=data)

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"
    assert repo.receipts == {}


# 인증


def test_쿠키가_없으면_401(client: TestClient, repo: FakeReceiptRepository) -> None:
    response = client.post(URL, files={"file": ("r.png", PNG)}, data=FORM, headers=AJAX)

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
    assert repo.receipts == {}


def test_X_Requested_With가_없으면_403(client: TestClient) -> None:
    response = client.post(URL, files={"file": ("r.png", PNG)}, data=FORM, headers=COOKIE)

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_쿠키가_없으면_OCR_키가_없어도_401(app) -> None:
    del app.dependency_overrides[get_ocr_client]

    response = TestClient(app).post(URL, files={"file": ("r.png", PNG)}, data=FORM, headers=AJAX)

    assert response.status_code == 401


def test_OCR_키가_없으면_502_EXTERNAL_API_ERROR(app) -> None:
    del app.dependency_overrides[get_ocr_client]

    response = post(TestClient(app))

    assert response.status_code == 502
    assert response.json()["code"] == "EXTERNAL_API_ERROR"


# FN-AIM-008-09 원본 저장 실패


def test_Java_원본_저장이_실패하면_OCR을_부르지_않는다(app, ocr: FakeOcr) -> None:
    app.dependency_overrides[get_receipt_repository] = lambda: FailingRepository()

    response = post(TestClient(app))

    assert response.status_code == 502
    assert ocr.calls == []


# 서비스 흐름 : 중복 차단·취소(연결 끊김)


async def _never_disconnected() -> bool:
    return False


def _analyze(ocr: FakeOcr, repo: FakeReceiptRepository, mbr_sn: int = 7, disconnected=None):
    return service.analyze_receipt(
        ocr,
        repo,
        mbr_sn,
        PNG,
        "r.png",
        3,
        "AIMC0026",
        5.0,
        disconnected or _never_disconnected,
    )


def test_같은_회원의_분석이_진행_중이면_409_OCR_IN_PROGRESS() -> None:
    # FN-AIM-008-06·013-04 : 중복 요청 차단
    repo = FakeReceiptRepository()
    ocr = FakeOcr(delay=0.1)

    async def run():
        return await asyncio.gather(
            _analyze(ocr, repo), _analyze(ocr, repo), return_exceptions=True
        )

    first, second = asyncio.run(run())

    assert first.recpt_sn == 1
    assert isinstance(second, AppError)
    assert (second.code, second.http_code) == ("OCR_IN_PROGRESS", 409)
    assert len(ocr.calls) == 1


def test_분석이_끝나면_다시_요청할_수_있다() -> None:
    repo = FakeReceiptRepository()

    async def run():
        await _analyze(FakeOcr(), repo)
        with pytest.raises(AppError):
            await _analyze(FakeOcr("error"), repo)
        return await _analyze(FakeOcr(), repo)

    assert asyncio.run(run()).recpt_sn == 3


def test_다른_회원은_동시에_분석할_수_있다() -> None:
    repo = FakeReceiptRepository()
    ocr = FakeOcr(delay=0.1)

    async def run():
        return await asyncio.gather(_analyze(ocr, repo, 7), _analyze(ocr, repo, 8))

    results = asyncio.run(run())

    assert {r.recpt_sn for r in results} == {1, 2}


def test_연결이_끊기면_분석을_멈추고_취소를_보고한다(monkeypatch: pytest.MonkeyPatch) -> None:
    # FN-AIM-008-07 : React [취소] = 요청 끊기
    monkeypatch.setattr(service, "DISCONNECT_POLL_SEC", 0.01)
    repo = FakeReceiptRepository()
    ocr = FakeOcr(delay=5.0)
    checks = 0

    async def disconnected_soon() -> bool:
        nonlocal checks
        checks += 1
        return checks > 2

    async def run():
        with pytest.raises(AppError) as error:
            await _analyze(ocr, repo, disconnected=disconnected_soon)
        return error.value

    error = asyncio.run(run())

    assert error.code == "OCR_CANCELED"
    assert repo.receipts[1].status is ReceiptStatus.CANCELED
    assert repo.receipts[1].image == PNG
    # 취소 뒤에는 다시 요청할 수 있다
    assert asyncio.run(_analyze(FakeOcr(), repo)).recpt_sn == 2


# FN-AIM-013-04 : 요청 출처 'AI 대화창'(AIMC0031, 2026-10-29 신설)


def test_AI_대화창_출처로_분석하면_Java에_그_출처로_저장한다(
    client: TestClient, repo: FakeReceiptRepository
) -> None:
    response = post(client, data={"petSn": "3", "ocrRqstSrcCd": "AIMC0031"})

    assert response.status_code == 200
    assert repo.receipts[1].src_cd == "AIMC0031"


@pytest.mark.parametrize("src_cd", ["AIMC0027", "AIMC0028"])
def test_가계부나_다른_그룹_코드는_400이고_Java_OCR을_부르지_않는다(
    client: TestClient, repo: FakeReceiptRepository, ocr: FakeOcr, src_cd: str
) -> None:
    response = post(client, data={"petSn": "3", "ocrRqstSrcCd": src_cd})

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"
    assert repo.receipts == {}
    assert ocr.calls == []
