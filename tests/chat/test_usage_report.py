import asyncio
import json
from datetime import date

import httpx2
import pytest

from app.chat.clients import (
    AnthropicImageIntentJudge,
    AnthropicRegisterExtractor,
    AnthropicTitleGenerator,
    AnthropicToolAgent,
    ClassifyError,
    ImageIntentError,
    get_image_intent_judge,
    get_register_extractor,
    get_title_generator,
    get_tool_agent,
)
from app.core.usage import CallResult, ExternalApi, ExternalCall
from tests.chat.test_llm_clients import (
    FIRST_MESSAGE,
    MODEL,
    FakeAnthropic,
    message,
    server_error,
    settings,
    sse,
    timeout,
)
from tests.chat.test_tools import CONTEXT, sse_response, tool_sse

TODAY = date(2026, 11, 24)


class RecordingUsage:
    """통지기 가짜 : 받은 호출 기록"""

    def __init__(self) -> None:
        self.calls: list[ExternalCall] = []

    def record(self, call: ExternalCall) -> None:
        self.calls.append(call)


def replying_with_usage(body: dict) -> FakeAnthropic:
    return FakeAnthropic(lambda _: httpx2.Response(200, json=body))


def with_cache(text: str, stop_reason: str = "end_turn") -> dict:
    body = message(text, stop_reason)
    body["usage"] = {
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_read_input_tokens": 300,
        "cache_creation_input_tokens": 40,
    }
    return body


def results(rec: RecordingUsage) -> list[tuple]:
    return [(c.api, c.result, c.http_status, c.fail_reason) for c in rec.calls]


# FN-ADM-112-01·02 AI 대화(SYSC0015) : 제목 생성·요약


def test_제목_생성_성공은_AI_대화_성공과_캐시_포함_입력_토큰():
    rec = RecordingUsage()
    fake = replying_with_usage(with_cache("강아지 식욕 부진 상담"))
    asyncio.run(AnthropicTitleGenerator(fake.client(), MODEL, rec).generate(FIRST_MESSAGE))

    assert results(rec) == [(ExternalApi.CHAT, CallResult.SUCCESS, 200, None)]
    assert (rec.calls[0].input_tokens, rec.calls[0].output_tokens) == (350, 5)


@pytest.mark.parametrize(
    ("respond", "expected"),
    [
        (server_error, (ExternalApi.CHAT, CallResult.FAIL, 500, "api_error 500")),
        (timeout, (ExternalApi.CHAT, CallResult.TIMEOUT, None, "timeout")),
    ],
)
def test_제목_생성_실패도_통지한다(respond, expected):
    rec = RecordingUsage()
    fake = FakeAnthropic(respond)
    asyncio.run(AnthropicTitleGenerator(fake.client(), MODEL, rec).generate(FIRST_MESSAGE))
    assert results(rec) == [expected]


def test_제목_생성_거절은_실패와_refusal():
    rec = RecordingUsage()
    fake = replying_with_usage(message("", "refusal"))
    asyncio.run(AnthropicTitleGenerator(fake.client(), MODEL, rec).generate(FIRST_MESSAGE))
    assert results(rec) == [(ExternalApi.CHAT, CallResult.FAIL, None, "refusal")]
    assert rec.calls[0].input_tokens == 10


def test_제목_요약도_AI_대화로_통지한다():
    rec = RecordingUsage()
    fake = replying_with_usage(message("포도 섭취 상담"))
    asyncio.run(AnthropicTitleGenerator(fake.client(), MODEL, rec).summarize("질문", "답변"))
    assert results(rec) == [(ExternalApi.CHAT, CallResult.SUCCESS, 200, None)]


def test_짧은_첫_메시지는_LLM을_부르지_않아_통지도_없다():
    rec = RecordingUsage()
    fake = replying_with_usage(message("x"))
    asyncio.run(AnthropicTitleGenerator(fake.client(), MODEL, rec).generate("안녕"))
    assert rec.calls == []


# 도구 고르기·도구 결과 답변


def test_도구_고르기_성공은_한_건():
    rec = RecordingUsage()
    fake = FakeAnthropic(lambda _: sse_response(tool_sse("decline", {})))
    agent = AnthropicToolAgent(fake.client(), MODEL, usage=rec)
    asyncio.run(agent.decide(CONTEXT, 4500, TODAY))

    assert results(rec) == [(ExternalApi.CHAT, CallResult.SUCCESS, 200, None)]
    assert rec.calls[0].output_tokens is not None


def test_도구_없이_글로_답하면_스트림을_다_읽은_뒤_한_건():
    rec = RecordingUsage()
    fake = FakeAnthropic(lambda _: sse_response(sse(["포도는 ", "위험해요."])))

    async def run():
        decision = await AnthropicToolAgent(fake.client(), MODEL, usage=rec).decide(
            CONTEXT, 4500, TODAY
        )
        before = len(rec.calls)
        texts = [text async for text in decision.text]
        return before, texts

    before, texts = asyncio.run(run())
    assert before == 0
    assert texts == ["포도는 ", "위험해요."]
    assert results(rec) == [(ExternalApi.CHAT, CallResult.SUCCESS, 200, None)]


def test_글_답변이_거절되면_실패_한_건():
    rec = RecordingUsage()
    fake = FakeAnthropic(lambda _: sse_response(sse(["음"], stop_reason="refusal")))

    async def run():
        decision = await AnthropicToolAgent(fake.client(), MODEL, usage=rec).decide(
            CONTEXT, 4500, TODAY
        )
        try:
            return [text async for text in decision.text]
        except Exception:
            return None

    asyncio.run(run())
    assert results(rec) == [(ExternalApi.CHAT, CallResult.FAIL, None, "refusal")]


def test_도구_고르기_API_오류는_실패_통지_뒤_ClassifyError():
    rec = RecordingUsage()
    fake = FakeAnthropic(server_error)
    agent = AnthropicToolAgent(fake.client(), MODEL, usage=rec)
    with pytest.raises(ClassifyError):
        asyncio.run(agent.decide(CONTEXT, 4500, TODAY))
    assert results(rec) == [(ExternalApi.CHAT, CallResult.FAIL, 500, "api_error 500")]


def test_도구_결과_답변도_AI_대화로_통지한다():
    rec = RecordingUsage()
    calls = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return sse_response(tool_sse("decline", {}))
        return sse_response(sse(["답변"]))

    fake = FakeAnthropic(respond)

    async def run():
        agent = AnthropicToolAgent(fake.client(), MODEL, usage=rec)
        decision = await agent.decide(CONTEXT, 4500, TODAY)
        return [t async for t in agent.answer(CONTEXT, decision, "결과", 4500, TODAY)]

    assert asyncio.run(run()) == ["답변"]
    assert [c.result for c in rec.calls] == [CallResult.SUCCESS, CallResult.SUCCESS]
    assert {c.api for c in rec.calls} == {ExternalApi.CHAT}


# FN-ADM-112-01·02 AI 분류(SYSC0024) : 등록 칸 추출·사진 용도 판단


def test_등록_칸_추출은_AI_분류로_통지한다():
    rec = RecordingUsage()
    fake = replying_with_usage(message(json.dumps({"schdl_ttl": "병원"})))
    asyncio.run(AnthropicRegisterExtractor(fake.client(), MODEL, rec).extract("병원 일정", TODAY))
    assert results(rec) == [(ExternalApi.CLASSIFY, CallResult.SUCCESS, 200, None)]


def test_등록_칸_추출_실패도_AI_분류로_통지한다():
    rec = RecordingUsage()
    fake = FakeAnthropic(timeout)
    asyncio.run(AnthropicRegisterExtractor(fake.client(), MODEL, rec).extract("병원 일정", TODAY))
    assert results(rec) == [(ExternalApi.CLASSIFY, CallResult.TIMEOUT, None, "timeout")]


def test_사진_용도_판단은_AI_분류로_통지한다():
    rec = RecordingUsage()
    fake = replying_with_usage(message(json.dumps({"kind": "CHARACTER"})))
    asyncio.run(AnthropicImageIntentJudge(fake.client(), MODEL, rec).judge(b"jpeg", None))
    assert results(rec) == [(ExternalApi.CLASSIFY, CallResult.SUCCESS, 200, None)]


def test_사진_용도_판단_API_오류는_실패_통지_뒤_ImageIntentError():
    rec = RecordingUsage()
    fake = FakeAnthropic(server_error)
    with pytest.raises(ImageIntentError):
        asyncio.run(AnthropicImageIntentJudge(fake.client(), MODEL, rec).judge(b"jpeg", None))
    assert results(rec) == [(ExternalApi.CLASSIFY, CallResult.FAIL, 500, "api_error 500")]


def test_사진_용도_판단_모양_오류는_실패_invalid_output():
    rec = RecordingUsage()
    fake = replying_with_usage(message(json.dumps({"kind": "NOPE"})))
    asyncio.run(AnthropicImageIntentJudge(fake.client(), MODEL, rec).judge(b"jpeg", None))
    assert results(rec) == [(ExternalApi.CLASSIFY, CallResult.FAIL, None, "invalid_output")]


@pytest.mark.parametrize(
    ("getter", "attr"),
    [
        (get_title_generator, "usage"),
        (get_tool_agent, "usage"),
        (get_register_extractor, "usage"),
        (get_image_intent_judge, "usage"),
    ],
)
def test_의존성은_받은_통지기를_클라이언트에_넘긴다(getter, attr):
    rec = RecordingUsage()
    assert getattr(getter(settings(), rec), attr) is rec
