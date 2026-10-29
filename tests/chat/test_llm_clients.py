import asyncio
import json

import httpx2
import pytest
from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient

from app.chat import rules
from app.chat.clients import (
    ANSWER_SYSTEM,
    AnswerError,
    AnthropicAnswerGenerator,
    AnthropicIntentClassifier,
    AnthropicTitleGenerator,
    Classified,
    ClassifiedKind,
    ClassifyError,
    MockAnswerGenerator,
    MockIntentClassifier,
    MockTitleGenerator,
    classify_system,
    get_answer_generator,
    get_anthropic_client,
    get_intent_classifier,
    get_title_generator,
)
from app.core.config import AiMode, Settings

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
    """MockTransport로 Anthropic API를 흉내 낸다. 받은 요청 본문을 requests에 남긴다"""

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


def classify(fake: FakeAnthropic, text: str = "근처에 아이 데리고 갈 곳") -> Classified:
    return asyncio.run(AnthropicIntentClassifier(fake.client(), MODEL).classify(text))


def classified(kind: str, route_num: int | None = None) -> FakeAnthropic:
    return replying(json.dumps({"kind": kind, "route_num": route_num}))


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


# FN-AIM-004-02 의도 분류


def test_분류가_SEARCH면_검색():
    assert classify(classified("SEARCH")) == Classified(ClassifiedKind.SEARCH)


def test_분류가_UNKNOWN이면_판단_못_함():
    assert classify(classified("UNKNOWN")) == Classified(ClassifiedKind.UNKNOWN)


def test_분류가_ROUTE면_매핑표_번호를_화면_ID와_파라미터로_바꾼다():
    row = next(r for r in rules.routing_table() if r.routable and r.param is not None)
    result = classify(classified("ROUTE", row.no))
    assert result == Classified(ClassifiedKind.ROUTE, scr_id=row.scr_id, param=row.param)


def test_라우팅_대상이_아닌_행이나_없는_번호면_판단_못_함():
    not_routable = next(r.no for r in rules.routing_table() if not r.routable)
    missing = max(r.no for r in rules.routing_table()) + 1
    for num in (not_routable, missing, None):
        assert classify(classified("ROUTE", num)).kind is ClassifiedKind.UNKNOWN


@pytest.mark.parametrize("respond", [server_error, timeout])
def test_분류_API가_실패하면_ClassifyError(respond):
    # 2026-10-29 결정 : 장애는 폴백(UNKNOWN)이 아니라 error 이벤트로 간다
    with pytest.raises(ClassifyError):
        classify(FakeAnthropic(respond))


def test_분류가_거절되면_판단_못_함():
    assert classify(replying("", stop_reason="refusal")).kind is ClassifiedKind.UNKNOWN


def test_분류_요청은_입력만_보내고_구조화_출력을_쓴다():
    fake = classified("SEARCH")
    classify(fake, "강아지 포도 먹어도 돼?")
    body = fake.requests[0]
    assert body["messages"] == [{"role": "user", "content": "강아지 포도 먹어도 돼?"}]
    assert body["system"] == classify_system()
    assert body["output_config"]["format"]["type"] == "json_schema"


def test_분류_프롬프트에는_라우팅_대상_행만_들어간다():
    system = classify_system()
    for row in rules.routing_table():
        line = f"\n{row.no}. {row.name}:"
        assert (line in system) is row.routable


# 모드별 선택


def settings(mode: AiMode, key: str = "test-key") -> Settings:
    return Settings(_env_file=None, ai_mode=mode, llm_api_key=key, llm_model=MODEL)


def test_mock_모드는_LLM을_부르지_않는_구현을_쓴다():
    assert isinstance(get_title_generator(settings(AiMode.MOCK, "")), MockTitleGenerator)
    assert isinstance(get_intent_classifier(settings(AiMode.MOCK, "")), MockIntentClassifier)


def test_real_모드는_Anthropic_구현을_쓴다():
    real = settings(AiMode.REAL)
    assert isinstance(get_title_generator(real), AnthropicTitleGenerator)
    assert isinstance(get_intent_classifier(real), AnthropicIntentClassifier)


def test_real_모드인데_키가_비면_오류():
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        get_anthropic_client(settings(AiMode.REAL, ""))


# FN-AIM-002-04 연관 바로가기


def test_검색이면서_연관_화면이_있으면_매핑표의_화면으로_바꾼다():
    row = next(r for r in rules.routing_table() if r.routable)
    fake = replying(json.dumps({"kind": "SEARCH", "route_num": None, "related_num": row.no}))
    result = classify(fake)
    assert result.kind is ClassifiedKind.SEARCH
    assert (result.related_scr_id, result.related_param) == (row.scr_id, row.param)


def test_연관_화면이_매핑표에_없으면_바로가기_없는_검색():
    missing = max(r.no for r in rules.routing_table()) + 1
    fake = replying(json.dumps({"kind": "SEARCH", "route_num": None, "related_num": missing}))
    assert classify(fake) == Classified(ClassifiedKind.SEARCH)


# FN-AIM-002-02 답변 스트리밍


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


def answer(fake: FakeAnthropic, messages=CONTEXT, max_tokens: int = 4500) -> list[str]:
    async def collect():
        generator = AnthropicAnswerGenerator(fake.client(), MODEL)
        return [chunk async for chunk in generator.stream(messages, max_tokens)]

    return asyncio.run(collect())


def test_답변은_조각을_차례로_내고_대화_텍스트만_보낸다():
    fake = streaming(["건포도도 ", "위험해요."])
    assert answer(fake) == ["건포도도 ", "위험해요."]
    body = fake.requests[0]
    assert body["model"] == MODEL
    assert body["stream"] is True
    assert body["max_tokens"] == 4500
    # FN-AIM-011-16 : 대화 메시지 텍스트만. 시스템 프롬프트는 고정 문구
    assert body["messages"] == CONTEXT
    assert body["system"] == ANSWER_SYSTEM


def test_답변_시스템_프롬프트는_개인_데이터와_진단을_제한한다():
    # FN-AIM-002-08·09
    assert "개인 데이터" in ANSWER_SYSTEM
    assert "진단" in ANSWER_SYSTEM
    assert "수의사" in ANSWER_SYSTEM


@pytest.mark.parametrize("respond", [server_error, timeout])
def test_답변_호출이_실패하면_AnswerError(respond):
    with pytest.raises(AnswerError):
        answer(FakeAnthropic(respond))


def test_답변이_거절되면_AnswerError():
    with pytest.raises(AnswerError, match="refusal"):
        answer(streaming(["부분"], stop_reason="refusal"))


def test_mock_답변은_LLM_없이_조각을_낸다():
    async def collect():
        return [c async for c in MockAnswerGenerator().stream(CONTEXT, 4500)]

    chunks = asyncio.run(collect())
    assert len(chunks) >= 3
    assert "3개" in "".join(chunks)


def test_답변_생성기도_모드별로_고른다():
    assert isinstance(get_answer_generator(settings(AiMode.MOCK, "")), MockAnswerGenerator)
    assert isinstance(get_answer_generator(settings(AiMode.REAL)), AnthropicAnswerGenerator)
