import asyncio
import json
import logging

import httpx2
import pytest
from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient

from app.healthreport.clients import ClaudeReportGenerator, HealthReportApiError, ReportOutput
from tests.healthreport.fakes import sample_input

MODEL = "claude-haiku-5-5"
GOOD = json.dumps({"title": "건강해요", "tips": ["산책 꾸준해요"]}, ensure_ascii=False)


class FakeAnthropic:
    """MockTransport로 Anthropic API를 흉내. 응답을 차례로 돌려주고 받은 요청 본문을 기록"""

    def __init__(self, *responders) -> None:
        self.responders = list(responders)
        self.requests: list[dict] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        return self.responders[min(len(self.requests), len(self.responders)) - 1](request)

    def client(self) -> AsyncAnthropic:
        return AsyncAnthropic(
            api_key="test-key",
            max_retries=0,
            http_client=DefaultAsyncHttpxClient(transport=httpx2.MockTransport(self.handler)),
        )


def reply(text: str, stop_reason: str = "end_turn", output_tokens: int = 5):
    body = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": MODEL,
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": output_tokens},
    }
    return lambda _: httpx2.Response(200, json=body)


def generate(llm: FakeAnthropic) -> ReportOutput:
    return asyncio.run(ClaudeReportGenerator(llm.client(), MODEL, 5.0).generate(sample_input()))


def test_effort_low·max_tokens_2048·json_schema로_요청한다() -> None:
    llm = FakeAnthropic(reply(GOOD))
    output = generate(llm)

    assert output.title == "건강해요"
    body = llm.requests[0]
    assert body["max_tokens"] == 2048
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert "title" in body["output_config"]["format"]["schema"]["properties"]


def test_max_tokens로_잘리면_한_번_다시_요청해_성공한다() -> None:
    llm = FakeAnthropic(reply('{"title": "건강', "max_tokens", 2048), reply(GOOD))

    assert generate(llm).tips == ["산책 꾸준해요"]
    assert len(llm.requests) == 2


def test_빈_title이면_다시_요청한다() -> None:
    llm = FakeAnthropic(reply(json.dumps({"title": " ", "tips": []})), reply(GOOD))

    assert generate(llm).title == "건강해요"
    assert len(llm.requests) == 2


def test_모양_오류가_두_번이면_오류이고_로그엔_앞_80자만(caplog: pytest.LogCaptureFixture) -> None:
    text = "가" * 80 + "나" * 20
    llm = FakeAnthropic(reply(text, output_tokens=77))

    with caplog.at_level(logging.WARNING), pytest.raises(HealthReportApiError):
        generate(llm)

    assert len(llm.requests) == 2
    failures = [r.getMessage() for r in caplog.records if "모양 오류" in r.getMessage()]
    assert len(failures) == 2
    assert "stop_reason=end_turn" in failures[0]
    assert "output_tokens=77" in failures[0]
    assert "글 100자" in failures[0]
    assert "가" * 80 in failures[0]
    assert "나" not in failures[0]


def test_거절은_다시_요청하지_않는다() -> None:
    llm = FakeAnthropic(reply(GOOD, "refusal"))

    with pytest.raises(HealthReportApiError):
        generate(llm)
    assert len(llm.requests) == 1


def test_API_오류는_다시_요청하지_않는다() -> None:
    llm = FakeAnthropic(lambda _: httpx2.Response(500, json={"type": "error"}))

    with pytest.raises(HealthReportApiError):
        generate(llm)
    assert len(llm.requests) == 1


def test_시간_초과는_다시_요청하지_않고_TimeoutError() -> None:
    def timeout(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    llm = FakeAnthropic(timeout)
    with pytest.raises(TimeoutError):
        generate(llm)
    assert len(llm.requests) == 1
