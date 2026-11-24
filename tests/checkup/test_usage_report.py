import asyncio
import json

import httpx2
import pytest

from app.checkup.clients import (
    ClaudePdfClient,
    PdfAnalyzeApiError,
    get_lab_result_client,
)
from app.core.config import Settings
from app.core.usage import CallResult, ExternalApi
from tests.chat.test_usage_report import RecordingUsage, results
from tests.checkup.test_clients import MODEL, PDF, STRUCTURED, FakeAnthropic, llm_replying


def read(llm: FakeAnthropic, rec: RecordingUsage):
    return asyncio.run(ClaudePdfClient(llm.client(), MODEL, 5.0, rec).read(PDF))


# FN-ADM-082-03 : 검사결과지 분석 호출마다 SYSC0025, 검사결과지 아님도 성공


@pytest.mark.parametrize("is_lab", [True, False])
def test_분석_성공과_검사결과지_아님은_성공(is_lab):
    rec = RecordingUsage()
    read(llm_replying(json.dumps({**STRUCTURED, "is_lab_result": is_lab})), rec)

    assert results(rec) == [(ExternalApi.PDF, CallResult.SUCCESS, 200, None)]
    assert (rec.calls[0].input_tokens, rec.calls[0].output_tokens) == (10, 5)


def test_시간_초과는_SYSC0023():
    rec = RecordingUsage()

    def slow(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("timeout", request=request)

    with pytest.raises(TimeoutError):
        read(FakeAnthropic(slow), rec)
    assert results(rec) == [(ExternalApi.PDF, CallResult.TIMEOUT, None, "timeout")]


def test_API_오류는_SYSC0022와_상태_코드():
    rec = RecordingUsage()
    error = FakeAnthropic(lambda _: httpx2.Response(529, json={"type": "error"}))
    with pytest.raises(PdfAnalyzeApiError):
        read(error, rec)
    assert results(rec) == [(ExternalApi.PDF, CallResult.FAIL, 529, "api_error 529")]


@pytest.mark.parametrize(
    ("text", "stop_reason", "reason"),
    [
        ("not json", "end_turn", "invalid_output"),
        (json.dumps(STRUCTURED), "refusal", "refusal"),
    ],
)
def test_모양_오류와_거절은_SYSC0022(text, stop_reason, reason):
    rec = RecordingUsage()
    with pytest.raises(PdfAnalyzeApiError):
        read(llm_replying(text, stop_reason), rec)
    assert results(rec) == [(ExternalApi.PDF, CallResult.FAIL, None, reason)]


def test_의존성은_받은_통지기를_클라이언트에_넘긴다():
    rec = RecordingUsage()
    settings = Settings(_env_file=None, llm_api_key="test-key", llm_model=MODEL)
    client = get_lab_result_client(settings, rec)
    assert client._usage is rec
