import asyncio
import base64
import json
from datetime import date

import httpx2
import pytest
from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient

from app.core.config import Settings
from app.core.response import AppError
from app.ocr.clients import GoogleVisionOcrClient, OcrApiError, get_ocr_client
from app.ocr.schemas import ReceiptOcrResponse

MODEL = "claude-haiku-5-5"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16
RECEIPT_TEXT = (
    "냥멍동물병원\n2026-10-20\n[미르]\n진료비 30,000\n소염제 5일 1일 2회 15,000\n합계 45,000"
)
STRUCTURED = {
    "hsptl_nm": "냥멍동물병원",
    "ckup_ymd": "2026-10-20",
    "recpt_amt": 45000,
    "btm_dscnt_amt": None,
    "sections": [
        {
            "sectionNm": "미르",
            "sbttlAmt": 45000,
            "dscntAmt": None,
            "items": [{"itemNm": "진료비", "itemAmt": 30000}],
            "drugs": [
                {"mdcnNm": "소염제", "mdcnDays": 5, "mdcnUsage": "1일 2회", "mdcnAmt": 15000}
            ],
        }
    ],
}


def vision_ok(text: str):
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"responses": [{"fullTextAnnotation": {"text": text}}]})

    return handler


class FakeVision:
    """MockTransport로 Vision API를 흉내. 받은 요청은 requests에 기록"""

    def __init__(self, respond) -> None:
        self.respond = respond
        self.requests: list[httpx2.Request] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.respond(request)

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handler)


class FakeAnthropic:
    """MockTransport로 Anthropic API를 흉내. 받은 요청 본문은 requests에 기록"""

    def __init__(self, respond) -> None:
        self.respond = respond
        self.requests: list[dict] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        return self.respond(request)

    def client(self) -> AsyncAnthropic:
        return AsyncAnthropic(
            api_key="test-key",
            max_retries=0,
            http_client=DefaultAsyncHttpxClient(transport=httpx2.MockTransport(self.handler)),
        )


def llm_replying(text: str, stop_reason: str = "end_turn") -> FakeAnthropic:
    body = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": MODEL,
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    return FakeAnthropic(lambda _: httpx2.Response(200, json=body))


def recognize(vision: FakeVision, llm: FakeAnthropic) -> ReceiptOcrResponse:
    client = GoogleVisionOcrClient("vision-key", llm.client(), MODEL, 5.0, vision.transport())
    return asyncio.run(client.recognize(PNG))


def test_Vision에_키와_base64_이미지로_글자_인식을_요청한다() -> None:
    vision = FakeVision(vision_ok(RECEIPT_TEXT))
    recognize(vision, llm_replying(json.dumps(STRUCTURED)))

    request = vision.requests[0]
    assert request.url.host == "vision.googleapis.com"
    assert request.url.params["key"] == "vision-key"
    body = json.loads(request.content)["requests"][0]
    assert base64.b64decode(body["image"]["content"]) == PNG
    assert body["features"] == [{"type": "DOCUMENT_TEXT_DETECTION"}]


def test_Vision_글자를_LLM이_ReceiptOcrResponse로_정리한다() -> None:
    llm = llm_replying(json.dumps(STRUCTURED))
    result = recognize(FakeVision(vision_ok(RECEIPT_TEXT)), llm)

    assert result.hsptl_nm == "냥멍동물병원"
    assert result.ckup_ymd == date(2026, 10, 20)
    assert result.recpt_amt == 45000
    assert result.sections[0].section_nm == "미르"
    assert result.sections[0].drugs[0].mdcn_days == 5
    # LLM에는 Vision 글자만 전송
    assert llm.requests[0]["messages"][0]["content"] == RECEIPT_TEXT


PETSHOP_TEXT = "멍멍펫샵 강남점\n2026-10-21\n프리미엄 사료 2kg 32,000\n합계 32,000"
PETSHOP = {
    "hsptl_nm": None,
    "plcus_nm": "멍멍펫샵 강남점",
    "category": "사료",
    "ckup_ymd": "2026-10-21",
    "recpt_amt": 32000,
    "btm_dscnt_amt": None,
    "sections": [{"sectionNm": None, "items": [{"itemNm": "프리미엄 사료 2kg", "itemAmt": 32000}]}],
}


# FN-MYP-031-03 : 사용처·카테고리 추정


def test_펫샵_영수증은_사용처와_카테고리_코드를_채운다() -> None:
    result = recognize(FakeVision(vision_ok(PETSHOP_TEXT)), llm_replying(json.dumps(PETSHOP)))

    assert result.hsptl_nm is None
    assert result.expnd_plcus_nm == "멍멍펫샵 강남점"
    assert result.expnd_clsf_cd == "MYPC0013"
    assert result.ckup_ymd == date(2026, 10, 21)
    assert result.recpt_amt == 32000


def test_병원_영수증은_병원명과_사용처를_함께_채운다() -> None:
    structured = {**STRUCTURED, "plcus_nm": "냥멍동물병원", "category": "병원"}
    result = recognize(FakeVision(vision_ok(RECEIPT_TEXT)), llm_replying(json.dumps(structured)))

    assert (result.hsptl_nm, result.expnd_plcus_nm) == ("냥멍동물병원", "냥멍동물병원")
    assert result.expnd_clsf_cd == "MYPC0012"
    assert result.sections[0].drugs[0].mdcn_nm == "소염제"


def test_80자를_넘는_사용처는_앞_80자로_자른다() -> None:
    llm = llm_replying(json.dumps({**PETSHOP, "plcus_nm": "가" * 81}))
    result = recognize(FakeVision(vision_ok(PETSHOP_TEXT)), llm)

    assert result.expnd_plcus_nm == "가" * 80


@pytest.mark.parametrize("category", ["장난감", "", None])
def test_7종_밖이거나_없는_카테고리는_null(category) -> None:
    llm = llm_replying(json.dumps({**PETSHOP, "category": category}))
    assert recognize(FakeVision(vision_ok(PETSHOP_TEXT)), llm).expnd_clsf_cd is None


def test_사용처가_공백이면_null() -> None:
    llm = llm_replying(json.dumps({**PETSHOP, "plcus_nm": "  "}))
    assert recognize(FakeVision(vision_ok(PETSHOP_TEXT)), llm).expnd_plcus_nm is None


def test_날짜를_읽지_못하면_null() -> None:
    llm = llm_replying(json.dumps({**STRUCTURED, "ckup_ymd": "10-20"}))
    assert recognize(FakeVision(vision_ok(RECEIPT_TEXT)), llm).ckup_ymd is None


def test_Vision_글자가_비면_LLM을_부르지_않고_빈_응답() -> None:
    llm = llm_replying(json.dumps(STRUCTURED))
    result = recognize(FakeVision(vision_ok("  \n")), llm)

    assert result == ReceiptOcrResponse()
    assert llm.requests == []


@pytest.mark.parametrize(
    "respond",
    [
        lambda _: httpx2.Response(403, json={"error": {"code": 403}}),
        lambda _: httpx2.Response(500),
        lambda _: httpx2.Response(200, json={"responses": [{"error": {"code": 3}}]}),
        lambda _: httpx2.Response(200, text="not json"),
    ],
)
def test_Vision_오류는_OcrApiError(respond) -> None:
    with pytest.raises(OcrApiError):
        recognize(FakeVision(respond), llm_replying(json.dumps(STRUCTURED)))


def test_Vision_시간_초과는_TimeoutError() -> None:
    def timeout(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("timeout", request=request)

    with pytest.raises(TimeoutError):
        recognize(FakeVision(timeout), llm_replying(json.dumps(STRUCTURED)))


@pytest.mark.parametrize(
    "llm",
    [
        llm_replying("영수증이 아닙니다"),
        llm_replying("", stop_reason="refusal"),
        FakeAnthropic(lambda _: httpx2.Response(500, json={"type": "error"})),
    ],
)
def test_LLM_오류나_잘못된_JSON은_OcrApiError(llm: FakeAnthropic) -> None:
    with pytest.raises(OcrApiError):
        recognize(FakeVision(vision_ok(RECEIPT_TEXT)), llm)


def test_Vision_키가_비면_502_EXTERNAL_API_ERROR() -> None:
    settings = Settings(_env_file=None, llm_api_key="llm-key")
    with pytest.raises(AppError) as error:
        get_ocr_client(settings)
    assert error.value.code == "EXTERNAL_API_ERROR"


def test_LLM_키가_비면_502_EXTERNAL_API_ERROR() -> None:
    settings = Settings(_env_file=None, google_vision_api_key="vision-key")
    with pytest.raises(AppError) as error:
        get_ocr_client(settings)
    assert error.value.code == "EXTERNAL_API_ERROR"


def test_두_키가_있으면_Google_Vision_구현을_쓴다() -> None:
    settings = Settings(_env_file=None, llm_api_key="llm-key", google_vision_api_key="vision-key")
    assert isinstance(get_ocr_client(settings), GoogleVisionOcrClient)


# FN-AIM-008-06 : 최종 결제 금액은 결제 줄 금액 (이름은 바꾼 실제 영수증 모양)

TWO_PET_TEXT = (
    "냥멍동물병원\n2026-11-05\n[콩이]\n진료비 12,000\n수술 300,000\n소계 312,000\n"
    "[밤이]\n진료비 12,000\n수술 240,000\n소계 252,000\n"
    "청구금액 564,000\n절사 할인 -200,000\n결제요청금액 364,000"
)
TWO_PET = {
    "hsptl_nm": "냥멍동물병원",
    "ckup_ymd": "2026-11-05",
    "recpt_amt": 564000,
    "btm_dscnt_amt": 200000,
    "sections": [
        {"sectionNm": "콩이", "sbttlAmt": 312000, "items": []},
        {"sectionNm": "밤이", "sbttlAmt": 252000, "items": []},
    ],
}


def test_LLM이_청구금액을_골라도_결제_줄_금액으로_바꾼다() -> None:
    result = recognize(FakeVision(vision_ok(TWO_PET_TEXT)), llm_replying(json.dumps(TWO_PET)))

    assert result.recpt_amt == 364000
    assert result.btm_dscnt_amt == 200000


def test_LLM이_금액을_못_읽어도_결제_줄_금액을_쓴다() -> None:
    llm = llm_replying(json.dumps({**TWO_PET, "recpt_amt": None}))
    assert recognize(FakeVision(vision_ok(TWO_PET_TEXT)), llm).recpt_amt == 364000


def test_결제_줄이_없으면_LLM_값_그대로() -> None:
    llm = llm_replying(json.dumps({**STRUCTURED, "recpt_amt": 44000}))
    assert recognize(FakeVision(vision_ok(RECEIPT_TEXT)), llm).recpt_amt == 44000


def test_추출_0건은_결제_줄이_있어도_빈_응답() -> None:
    empty = {
        "hsptl_nm": None,
        "ckup_ymd": None,
        "recpt_amt": None,
        "btm_dscnt_amt": None,
        "sections": [],
    }
    result = recognize(FakeVision(vision_ok("결제금액 5,000")), llm_replying(json.dumps(empty)))
    assert result == ReceiptOcrResponse()


def test_LLM에_결제_줄_우선_지시를_보낸다() -> None:
    llm = llm_replying(json.dumps(STRUCTURED))
    recognize(FakeVision(vision_ok(RECEIPT_TEXT)), llm)

    system = llm.requests[0]["system"]
    assert "결제요청" in system
    assert "청구금액" in system
    assert "가장 아래" in system
