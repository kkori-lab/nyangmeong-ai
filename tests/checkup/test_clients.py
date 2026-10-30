import asyncio
import base64
import json

import httpx2
import pytest
from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient

from app.checkup.clients import (
    ClaudePdfClient,
    LabResultOutput,
    PdfAnalyzeApiError,
    get_lab_result_client,
)
from app.core.config import Settings

MODEL = "claude-haiku-5-5"
PDF = b"%PDF-1.7\n" + b"0" * 16
STRUCTURED = {
    "is_lab_result": True,
    "rows": [
        {
            "name": "CREA",
            "value": "1.2",
            "unit": "mg/dL",
            "ref_min": "0.5",
            "ref_max": "1.8",
            "blood": True,
        }
    ],
}


class FakeAnthropic:
    """MockTransport로 Anthropic API를 흉내 낸다. 받은 요청 본문을 requests에 남긴다"""

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


def read(llm: FakeAnthropic) -> LabResultOutput:
    return asyncio.run(ClaudePdfClient(llm.client(), MODEL, 5.0).read(PDF))


def test_PDF를_document_블록으로_보낸다() -> None:
    llm = llm_replying(json.dumps(STRUCTURED))
    read(llm)

    body = llm.requests[0]
    assert body["model"] == MODEL
    document = body["messages"][0]["content"][0]
    assert document["type"] == "document"
    assert document["source"]["media_type"] == "application/pdf"
    assert base64.b64decode(document["source"]["data"]) == PDF


def test_구조화_출력을_LabResultOutput으로_읽는다() -> None:
    output = read(llm_replying(json.dumps(STRUCTURED)))

    assert output.is_lab_result is True
    assert output.rows[0].name == "CREA"
    assert output.rows[0].ref_max == "1.8"


@pytest.mark.parametrize(
    "llm",
    [
        FakeAnthropic(lambda _: httpx2.Response(500, json={"type": "error"})),
        llm_replying("이건 JSON이 아님"),
        llm_replying(json.dumps(STRUCTURED), stop_reason="refusal"),
    ],
)
def test_API_오류·모양_오류·거절은_PdfAnalyzeApiError(llm: FakeAnthropic) -> None:
    with pytest.raises(PdfAnalyzeApiError):
        read(llm)


def test_API_시간_초과는_TimeoutError() -> None:
    def timeout(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    with pytest.raises(TimeoutError):
        read(FakeAnthropic(timeout))


def test_키가_없으면_None() -> None:
    assert get_lab_result_client(Settings(llm_api_key="")) is None


def test_키가_있으면_실제_클라이언트() -> None:
    client = get_lab_result_client(Settings(llm_api_key="test-key"))
    assert isinstance(client, ClaudePdfClient)
