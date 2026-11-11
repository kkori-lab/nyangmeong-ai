import asyncio
import json

import httpx2
import pytest
from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient

from app.chat.clients import (
    ANSWER_SYSTEM,
    AnthropicRegisterExtractor,
    AnthropicTitleGenerator,
    AnthropicToolAgent,
    get_anthropic_client,
    get_register_extractor,
    get_title_generator,
    get_tool_agent,
)
from app.core.config import Settings
from app.core.response import AppError

MODEL = "claude-haiku-5-5"
FIRST_MESSAGE = "우리 강아지가 어제부터 밥을 안 먹어요. 병원에 가야 할까요?"


def message(text: str, stop_reason: str = "end_turn") -> dict:
    """Anthropic Messages API 응답 흉내"""
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": MODEL,
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


class FakeAnthropic:
    """MockTransport로 Anthropic API를 흉내. 받은 요청 본문은 requests에 기록"""

    def __init__(self, respond):
        self.respond = respond
        self.requests: list[dict] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        return self.respond(request)

    def client(self) -> AsyncAnthropic:
        # 재시도 없이 : 실패 경우가 바로 드러나게
        return AsyncAnthropic(
            api_key="test-key",
            max_retries=0,
            http_client=DefaultAsyncHttpxClient(transport=httpx2.MockTransport(self.handler)),
        )


def replying(text: str, stop_reason: str = "end_turn") -> FakeAnthropic:
    return FakeAnthropic(lambda _: httpx2.Response(200, json=message(text, stop_reason)))


def server_error(_: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(500, json={"type": "error", "error": {"type": "api_error"}})


def timeout(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ReadTimeout("timeout", request=request)


def generate(fake: FakeAnthropic, first_message: str = FIRST_MESSAGE) -> str:
    return asyncio.run(AnthropicTitleGenerator(fake.client(), MODEL).generate(first_message))


# FN-AIM-011-11 제목 생성


def test_제목_생성은_첫_메시지_원문만_보내고_응답을_제목으로_쓴다():
    fake = replying("강아지 식욕 부진 상담")
    assert generate(fake) == "강아지 식욕 부진 상담"
    body = fake.requests[0]
    assert body["model"] == MODEL
    assert body["messages"] == [{"role": "user", "content": FIRST_MESSAGE}]
    # FN-AIM-011-16 : 시스템 프롬프트에도 반려동물 기록은 없다(고정 문구)
    assert isinstance(body["system"], str)
    assert body["output_config"]["effort"] == "low"


@pytest.mark.parametrize(
    "text",
    [
        '"강아지 식욕 부진 상담"',
        "강아지 식욕 부진 상담.",
        "\n「강아지 식욕 부진 상담」\n설명은 생략",
    ],
)
def test_제목은_첫_줄만_쓰고_따옴표와_마침표를_지운다(text):
    assert generate(replying(text)) == "강아지 식욕 부진 상담"


@pytest.mark.parametrize("respond", [server_error, timeout])
def test_제목_생성이_실패하면_첫_메시지_앞_30자를_쓴다(respond):
    assert generate(FakeAnthropic(respond)) == FIRST_MESSAGE[:30]


def test_제목_생성이_거절되면_첫_메시지_앞_30자를_쓴다():
    assert generate(replying("", stop_reason="refusal")) == FIRST_MESSAGE[:30]


def test_제목_응답이_비면_첫_메시지_앞_30자를_쓴다():
    assert generate(replying("  \n ")) == FIRST_MESSAGE[:30]


@pytest.mark.parametrize("text", ["가계부", " ㅋㅋㅋㅋ ", "가" * 15])
def test_짧은_첫_메시지는_LLM_없이_그대로_제목(text):
    # '가계부' → '가계부 작성 방법'처럼 뜻이 덧붙지 않게(2026-10-29)
    fake = replying("가계부 작성 방법")
    assert generate(fake, text) == text.strip()
    assert fake.requests == []


def test_15자를_넘으면_LLM으로_제목을_만든다():
    fake = replying("긴 제목")
    assert generate(fake, "가" * 16) == "긴 제목"
    assert len(fake.requests) == 1


# 키에 따른 선택 : 앱에는 실제 구현만 존재


def settings(key: str = "test-key") -> Settings:
    return Settings(_env_file=None, llm_api_key=key, llm_model=MODEL)


@pytest.mark.parametrize(
    "getter",
    [get_title_generator, get_tool_agent, get_register_extractor],
)
def test_키가_비면_LLM_클라이언트를_만들지_않고_502(getter):
    with pytest.raises(AppError) as raised:
        getter(settings(""))
    assert (raised.value.code, raised.value.http_code) == ("EXTERNAL_API_ERROR", 502)


def test_키가_있으면_Anthropic_구현을_쓴다():
    real = settings()
    assert isinstance(get_title_generator(real), AnthropicTitleGenerator)
    assert isinstance(get_tool_agent(real), AnthropicToolAgent)


def test_키가_비면_Anthropic_클라이언트도_502():
    with pytest.raises(AppError, match="외부 서비스"):
        get_anthropic_client(settings(""))


# FN-AIM-002-02 답변 스트리밍 흉내(도구 고르기 테스트가 씀)


def sse(texts, stop_reason: str = "end_turn") -> bytes:
    """Anthropic 스트리밍 응답(SSE) 흉내"""
    start = {
        "type": "message_start",
        "message": {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": MODEL,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 1},
        },
    }
    events = [
        ("message_start", start),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
    ]
    for text in texts:
        delta = {"type": "text_delta", "text": text}
        events.append(
            ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": delta})
        )
    events += [
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": 5},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    body = "".join(f"event: {n}\ndata: {json.dumps(d, ensure_ascii=False)}\n\n" for n, d in events)
    return body.encode()


def streaming(texts, stop_reason: str = "end_turn") -> FakeAnthropic:
    return FakeAnthropic(
        lambda _: httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=sse(texts, stop_reason)
        )
    )


CONTEXT = [
    {"role": "user", "content": "강아지 포도 먹어도 돼?"},
    {"role": "assistant", "content": "안 돼요."},
    {"role": "user", "content": "건포도는?"},
]


def test_답변_시스템_프롬프트는_개인_데이터와_진단을_제한한다():
    # FN-AIM-002-08·09
    assert "개인 데이터" in ANSWER_SYSTEM
    assert "진단" in ANSWER_SYSTEM
    assert "수의사" in ANSWER_SYSTEM


def test_등록_추출기도_키가_있으면_Anthropic_구현():
    assert isinstance(get_register_extractor(settings()), AnthropicRegisterExtractor)
