import asyncio
import json

import httpx2
import pytest

from app.core.config import Settings
from app.core.usage import CallResult, ExternalApi
from app.ocr.clients import GoogleVisionOcrClient, OcrApiError, get_ocr_client
from tests.chat.test_usage_report import RecordingUsage, results
from tests.ocr.test_clients import (
    MODEL,
    PNG,
    RECEIPT_TEXT,
    STRUCTURED,
    FakeAnthropic,
    FakeVision,
    llm_replying,
    vision_ok,
)


def recognize(vision: FakeVision, llm: FakeAnthropic, rec: RecordingUsage):
    client = GoogleVisionOcrClient(
        "vision-key", llm.client(), MODEL, 5.0, vision.transport(), usage=rec
    )
    return asyncio.run(client.recognize(PNG))


# FN-ADM-112-01 : 영수증 OCR(SYSC0016)은 Vision·LLM 호출마다 한 건


def test_성공은_Vision과_LLM_두_건():
    rec = RecordingUsage()
    recognize(FakeVision(vision_ok(RECEIPT_TEXT)), llm_replying(json.dumps(STRUCTURED)), rec)

    assert results(rec) == [
        (ExternalApi.OCR, CallResult.SUCCESS, 200, None),
        (ExternalApi.OCR, CallResult.SUCCESS, 200, None),
    ]
    vision, llm = rec.calls
    assert (vision.input_tokens, vision.output_tokens) == (None, None)
    assert (llm.input_tokens, llm.output_tokens) == (10, 5)


def test_Vision_글자가_비면_Vision_한_건만():
    rec = RecordingUsage()
    recognize(FakeVision(vision_ok("  ")), llm_replying(json.dumps(STRUCTURED)), rec)
    assert results(rec) == [(ExternalApi.OCR, CallResult.SUCCESS, 200, None)]


def raise_timeout(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ReadTimeout("timeout", request=request)


def raise_connect(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("down")


@pytest.mark.parametrize(
    ("respond", "error", "expected"),
    [
        (
            lambda _: httpx2.Response(403, json={"error": {"code": 403}}),
            OcrApiError,
            (ExternalApi.OCR, CallResult.FAIL, 403, "vision 403"),
        ),
        (
            lambda _: httpx2.Response(200, json={"responses": [{"error": {"code": 3}}]}),
            OcrApiError,
            (ExternalApi.OCR, CallResult.FAIL, 200, "vision error_response"),
        ),
        (
            lambda _: httpx2.Response(200, text="not json"),
            OcrApiError,
            (ExternalApi.OCR, CallResult.FAIL, 200, "vision invalid_output"),
        ),
        (raise_timeout, TimeoutError, (ExternalApi.OCR, CallResult.TIMEOUT, None, "timeout")),
        (
            raise_connect,
            OcrApiError,
            (ExternalApi.OCR, CallResult.FAIL, None, "network ConnectError"),
        ),
    ],
)
def test_Vision_실패는_한_건이고_LLM은_부르지_않는다(respond, error, expected):
    rec = RecordingUsage()
    llm = llm_replying(json.dumps(STRUCTURED))
    with pytest.raises(error):
        recognize(FakeVision(respond), llm, rec)
    assert results(rec) == [expected]
    assert llm.requests == []


@pytest.mark.parametrize(
    ("respond", "error", "expected"),
    [
        (raise_timeout, TimeoutError, (ExternalApi.OCR, CallResult.TIMEOUT, None, "timeout")),
        (
            lambda _: httpx2.Response(500, json={"type": "error"}),
            OcrApiError,
            (ExternalApi.OCR, CallResult.FAIL, 500, "api_error 500"),
        ),
    ],
)
def test_LLM_실패는_Vision_성공_뒤_한_건(respond, error, expected):
    rec = RecordingUsage()
    with pytest.raises(error):
        recognize(FakeVision(vision_ok(RECEIPT_TEXT)), FakeAnthropic(respond), rec)
    assert results(rec) == [(ExternalApi.OCR, CallResult.SUCCESS, 200, None), expected]


def test_의존성은_받은_통지기를_클라이언트에_넘긴다():
    rec = RecordingUsage()
    settings = Settings(
        _env_file=None, google_vision_api_key="vision-key", llm_api_key="k", llm_model=MODEL
    )
    assert get_ocr_client(settings, rec)._usage is rec
