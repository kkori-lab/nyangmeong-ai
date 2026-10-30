import asyncio
import json
from datetime import date

import httpx2
import pytest

from app.core.backend import BackendError
from app.core.config import Settings
from app.core.response import AppError
from app.ocr import service
from app.ocr.repository import JavaReceiptRepository, ReceiptStatus
from app.ocr.schemas import Line, ReceiptOcrResponse, Section
from tests.ocr.fakes import FakeReceiptRepository

BASE = "http://backend.test"
COOKIE = "access_token=real-token"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16
RESULT = ReceiptOcrResponse(
    hsptl_nm="냥멍동물병원",
    ckup_ymd=date(2026, 10, 20),
    recpt_amt=30000,
    sections=[Section(section_nm="미르", items=[Line(item_nm="진료비", item_amt=30000)])],
)


class JavaStub:
    """Java 영수증 내부 API 흉내. 받은 요청은 requests에 기록, response 반환"""

    def __init__(self, response: httpx2.Response | None = None) -> None:
        self.response = response
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.response is not None:
            return self.response
        if request.url.path.endswith("/result"):
            return httpx2.Response(200, json={"data": {"recptSn": 9, "ocrPrcsSttsCd": "X"}})
        return httpx2.Response(201, json={"data": {"recptSn": 9}})


def _repo(stub, base_url: str = BASE, cookie: str | None = COOKIE) -> JavaReceiptRepository:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(stub))
    return JavaReceiptRepository(client, Settings(backend_base_url=base_url), cookie)


# FN-AIM-008-09·010-06·013-08 원본 저장


def test_원본은_multipart로_Java에_저장하고_recptSn을_받는다() -> None:
    stub = JavaStub()

    recpt_sn = asyncio.run(_repo(stub).save_original(PNG, "r.png", 3, "AIMC0031"))

    assert recpt_sn == 9
    request = stub.requests[0]
    assert (request.method, str(request.url)) == ("POST", f"{BASE}/internal/ai/receipts")
    assert request.headers["cookie"] == COOKIE
    assert request.headers["x-requested-with"] == "XMLHttpRequest"
    body = request.read()
    assert request.headers["content-type"].startswith("multipart/form-data")
    assert b'name="file"; filename="r.png"' in body
    assert b"Content-Type: image/png" in body
    assert PNG in body
    assert b'name="petSn"\r\n\r\n3\r\n' in body
    # ocrRqstSrcCd를 Java 이름으로 변환 전송
    assert b'name="ocrDmndSrcCd"\r\n\r\nAIMC0031\r\n' in body
    assert b"ocrRqstSrcCd" not in body


def test_쿠키가_없으면_Cookie_헤더를_보내지_않는다() -> None:
    stub = JavaStub()

    asyncio.run(_repo(stub, cookie=None).save_original(PNG, "r.png", 3, "AIMC0026"))

    assert "cookie" not in stub.requests[0].headers


def test_원본_저장의_Java_4xx는_그대로_전달한다() -> None:
    body = {"status": "error", "httpCode": 403, "code": "PET_ACCESS_DENIED"}
    stub = JavaStub(httpx2.Response(403, json=body))

    with pytest.raises(BackendError) as error:
        asyncio.run(_repo(stub).save_original(PNG, "r.png", 3, "AIMC0026"))

    assert error.value.status_code == 403
    assert json.loads(error.value.body)["code"] == "PET_ACCESS_DENIED"


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(500, json={"status": "error"}),
        httpx2.Response(201, json={"data": {}}),
        httpx2.Response(201, json={"data": {"recptSn": "x"}}),
    ],
)
def test_원본_저장의_5xx나_응답_모양이_다르면_502(response: httpx2.Response) -> None:
    with pytest.raises(AppError) as error:
        asyncio.run(_repo(JavaStub(response)).save_original(PNG, "r.png", 3, "AIMC0026"))

    assert (error.value.code, error.value.http_code) == ("EXTERNAL_API_ERROR", 502)


def test_Java_연결이_안_되면_502() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    with pytest.raises(AppError) as error:
        asyncio.run(_repo(refuse).save_original(PNG, "r.png", 3, "AIMC0026"))

    assert error.value.code == "EXTERNAL_API_ERROR"


# FN-AIM-008-07·010-01·013-04 상태 보고


def _report(status: ReceiptStatus, result: ReceiptOcrResponse | None) -> dict:
    stub = JavaStub()
    asyncio.run(_repo(stub).report_result(9, status, result))
    request = stub.requests[0]
    assert (request.method, str(request.url)) == ("POST", f"{BASE}/internal/ai/receipts/9/result")
    assert request.headers["cookie"] == COOKIE
    assert request.headers["x-requested-with"] == "XMLHttpRequest"
    return json.loads(request.read())


def test_인식은_ocrRslt와_camelCase_ocr를_보낸다() -> None:
    body = _report(ReceiptStatus.RECOGNIZED, RESULT)

    assert body["ocrRslt"] == "RECOGNIZED"
    assert body["ocr"]["hsptlNm"] == "냥멍동물병원"
    assert body["ocr"]["ckupYmd"] == "2026-10-20"
    assert body["ocr"]["recptAmt"] == 30000
    assert body["ocr"]["sections"][0]["items"][0] == {"itemNm": "진료비", "itemAmt": 30000}


def test_추출_0건은_UNRECOGNIZED와_빈_ocr를_보낸다() -> None:
    body = _report(ReceiptStatus.UNRECOGNIZED, ReceiptOcrResponse())

    assert body["ocrRslt"] == "UNRECOGNIZED"
    assert body["ocr"]["sections"] == []
    assert body["ocr"]["hsptlNm"] is None


@pytest.mark.parametrize(
    "status", [ReceiptStatus.TIMEOUT, ReceiptStatus.API_ERROR, ReceiptStatus.CANCELED]
)
def test_일시_오류와_취소는_ocr_없이_보낸다(status: ReceiptStatus) -> None:
    # 결과가 넘어와도 미전송
    assert _report(status, RESULT) == {"ocrRslt": status.value, "ocr": None}


def test_보고의_Java_4xx는_그대로_전달한다() -> None:
    body = {"status": "error", "httpCode": 409, "code": "ALREADY_PROCESSED"}
    stub = JavaStub(httpx2.Response(409, json=body))

    with pytest.raises(BackendError) as error:
        asyncio.run(_repo(stub).report_result(9, ReceiptStatus.RECOGNIZED, RESULT))

    assert error.value.status_code == 409


# 보고 실패 처리


class _Ocr:
    def __init__(self, behavior: str = "ok", delay: float = 0.0) -> None:
        self.behavior = behavior
        self.delay = delay

    async def recognize(self, image: bytes) -> ReceiptOcrResponse:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.behavior == "empty":
            return ReceiptOcrResponse()
        if self.behavior == "error":
            raise service.OcrApiError("boom")
        return RESULT


class FailingReport(FakeReceiptRepository):
    """원본 저장은 되고 상태 보고에서 Java 오류"""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error
        self.reported: list[ReceiptStatus] = []

    async def report_result(self, recpt_sn, status, result) -> None:
        self.reported.append(status)
        raise self.error


async def _never_disconnected() -> bool:
    return False


def _analyze(ocr: _Ocr, repo: FakeReceiptRepository, timeout_sec: float = 5.0, disconnected=None):
    return service.analyze_receipt(
        ocr,
        repo,
        7,
        PNG,
        "r.png",
        3,
        "AIMC0026",
        timeout_sec,
        disconnected or _never_disconnected,
    )


def _backend_409() -> BackendError:
    return BackendError(409, b'{"code":"ALREADY_PROCESSED"}', "application/json", [])


@pytest.mark.parametrize("behavior", ["ok", "empty"])
@pytest.mark.parametrize(
    "error",
    [_backend_409(), AppError("EXTERNAL_API_ERROR", 502, "x")],
    ids=["java-4xx", "502"],
)
def test_인식_0건_보고가_실패하면_결과를_주지_않고_그_오류를_낸다(behavior, error) -> None:
    repo = FailingReport(error)

    with pytest.raises(type(error)) as raised:
        asyncio.run(_analyze(_Ocr(behavior), repo))

    assert raised.value is error
    # 재요청 가능
    assert asyncio.run(_analyze(_Ocr(), FakeReceiptRepository())).recpt_sn == 1


@pytest.mark.parametrize(
    ("ocr", "timeout_sec", "code", "status"),
    [
        (_Ocr(delay=1.0), 0.05, "OCR_TIMEOUT", ReceiptStatus.TIMEOUT),
        (_Ocr("error"), 5.0, "OCR_API_ERROR", ReceiptStatus.API_ERROR),
    ],
)
@pytest.mark.parametrize(
    "error", [_backend_409(), AppError("EXTERNAL_API_ERROR", 502, "x")], ids=["java-4xx", "502"]
)
def test_실패_보고가_실패해도_원래_오류를_낸다(ocr, timeout_sec, code, status, error) -> None:
    repo = FailingReport(error)

    with pytest.raises(AppError) as raised:
        asyncio.run(_analyze(ocr, repo, timeout_sec))

    assert raised.value.code == code
    assert repo.reported == [status]


def test_취소_보고가_실패해도_취소로_끝난다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "DISCONNECT_POLL_SEC", 0.01)
    repo = FailingReport(AppError("EXTERNAL_API_ERROR", 502, "x"))

    async def disconnected() -> bool:
        return True

    with pytest.raises(AppError) as raised:
        asyncio.run(_analyze(_Ocr(delay=5.0), repo, disconnected=disconnected))

    assert raised.value.code == "OCR_CANCELED"
    assert repo.reported == [ReceiptStatus.CANCELED]
