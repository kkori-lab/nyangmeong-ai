"""SCR-AIM-012 2단계 쓰기 ② : READ 2번 뒤 수정 카드, 0자 답변 안내 (검증 1회차 고친 곳)"""

import asyncio
from collections.abc import AsyncIterator

import pytest

from app.chat import rules, tools
from app.chat.clients import AnthropicToolAgent, ReadMore, ToolDecision
from app.chat.service import ACTION_SHOWN, READ_EMPTY_CARD_MESSAGE, READ_EMPTY_MESSAGE
from tests.chat.test_action import send
from tests.chat.test_llm_clients import MODEL, FakeAnthropic, sse
from tests.chat.test_messages import MessageJava, deltas, events
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import CHOCO, TODAY
from tests.chat.test_tools import CONTEXT, room_of, sse_response, tool_sse, use_agent

SCHEDULES = [{"schdlSn": 31, "schdlNm": "미용", "schdlDt": "2026-10-01T15:00:00"}]


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


class ChainAgent:
    """[가짜 도구 LLM] 첫 도구 뒤 follows를 차례로 follow에 넘기고 answer_chunks로 답한다"""

    def __init__(
        self, tool: str, follows: list[tuple[str, dict]], answer_chunks: tuple[str, ...] = ("",)
    ):
        self.tool = tool
        self.follows = follows
        self.answer_chunks = answer_chunks
        self.results: list[str | None] = []

    async def decide(self, messages, max_tokens, today, hint=None) -> ToolDecision:
        use = {"type": "tool_use", "id": "toolu_1", "name": self.tool, "input": {}}
        return ToolDecision(call=tools.parse(self.tool, {}, "toolu_1"), content=(use,))

    async def answer(
        self, messages, decision, result, max_tokens, today, follow=None
    ) -> AsyncIterator[str]:
        self.results.append(result)
        for index, (name, raw) in enumerate(self.follows):
            second = await follow(tools.parse(name, raw, f"toolu_{index + 2}"))
            self.results.append(second)
        for chunk in self.answer_chunks:
            yield chunk


# 서비스 : READ 2번 뒤 수정 카드


def test_READ_두_번_뒤에도_수정_카드를_고를_수_있어야_한다(client, java):
    agent = use_agent(
        client,
        ChainAgent(
            "list_my_care_schedules",
            [
                ("list_my_care_schedules", {}),
                ("draft_schedule_update", {"schdl_sn": 31, "schdl_ymd": "2026-10-03"}),
            ],
            ("카드를 확인해 주세요.",),
        ),
    )
    reader = use_reader(client, FakeToolReader(SCHEDULES))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "미용 예약 일정 모레로 미뤄줘"))

    assert len(reader.calls) == 2
    assert isinstance(agent.results[1], ReadMore)
    assert agent.results[2].startswith(ACTION_SHOWN.split("{summary}")[0])
    action = evs[-1][1]["action"]
    assert action["tool"] == "draft_schedule_update"
    assert action["input"]["schdlSn"] == 31


def test_네_번째_READ는_실행하지_않아야_한다(client, java):
    # 한 턴 READ 상한 2 → 3번(2026-11-13, 한 메시지 여러 일 ①)
    agent = use_agent(
        client,
        ChainAgent(
            "list_my_care_schedules",
            [("list_my_care_schedules", {}), ("list_care_items", {}), ("list_checkups", {})],
            ("일정이에요.",),
        ),
    )
    reader = use_reader(client, FakeToolReader(SCHEDULES))
    room = room_of(client, java, pet_sn=CHOCO)

    events(send(client, room, "일정 알려 줘"))

    assert len(reader.calls) == 3
    assert agent.results[3] is None


def test_카드를_띄운_뒤_고른_쓰기_도구는_실행하지_않아야_한다(client, java):
    raw = {"schdl_sn": 31, "schdl_nm": "검진"}
    agent = use_agent(
        client,
        ChainAgent(
            "list_my_care_schedules",
            [("draft_schedule_update", raw), ("draft_schedule_update", raw)],
            ("카드를 확인해 주세요.",),
        ),
    )
    use_reader(client, FakeToolReader(SCHEDULES))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "일정 이름 바꿔 줘"))

    assert agent.results[1].startswith(ACTION_SHOWN.split("{summary}")[0])
    assert agent.results[2:] == [None]
    assert evs[-1][1]["action"]["tool"] == "draft_schedule_update"


# 서비스 : 0자 답변은 오류 대신 안내 글


@pytest.mark.parametrize(
    ("follows", "message"),
    [
        ([("list_my_care_schedules", {})], READ_EMPTY_MESSAGE),
        (
            [("draft_schedule_update", {"schdl_sn": 31, "schdl_nm": "검진"})],
            READ_EMPTY_CARD_MESSAGE,
        ),
    ],
)
def test_READ_답변이_0자로_끝나면_오류_대신_안내_글을_저장해야_한다(client, java, follows, message):
    use_agent(client, ChainAgent("list_my_care_schedules", follows))
    use_reader(client, FakeToolReader(SCHEDULES))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "미용 일정 미뤄줘"))

    assert "error" not in [name for name, _ in evs]
    assert deltas(evs).startswith(message)
    assert java.ai_messages(room)[0]["cnvrsCn"].startswith(message)


# Anthropic 요청 : ReadMore면 한 번 더 도구를 고를 수 있음


def _read_decision() -> ToolDecision:
    use = {"type": "tool_use", "id": "toolu_1", "name": "list_my_care_schedules", "input": {}}
    return ToolDecision(call=tools.parse("list_my_care_schedules", {}, "toolu_1"), content=(use,))


def test_follow가_ReadMore를_주면_한_번_더_도구를_고를_수_있어야_한다():
    bodies = [
        tool_sse("list_my_care_schedules", {}),
        tool_sse("draft_schedule_update", {"schdl_sn": 31}),
        sse(["카드를 확인해 주세요."]),
    ]
    fake = FakeAnthropic(lambda _: sse_response(bodies[len(fake.requests) - 1]))
    calls: list[str] = []

    async def follow(call: tools.ToolCall) -> str | None:
        calls.append(call.name)
        return ReadMore("두 번째 목록") if len(calls) == 1 else ACTION_SHOWN

    async def run():
        agent = AnthropicToolAgent(fake.client(), MODEL)
        stream = agent.answer(CONTEXT, _read_decision(), "첫 목록", 4500, TODAY, follow)
        return [t async for t in stream]

    assert asyncio.run(run()) == ["카드를 확인해 주세요."]
    assert calls == ["list_my_care_schedules", "draft_schedule_update"]
    first, second, third = fake.requests
    assert first["tool_choice"]["type"] == "auto"
    assert second["tool_choice"]["type"] == "auto"
    assert third["tool_choice"] == {"type": "none"}


def test_ReadMore가_계속_와도_결과_뒤_도구는_세_번까지만_고른다():
    # 결과 뒤 도구 고르기 2 → 3라운드(2026-11-13, READ 상한 3번)
    bodies = [
        tool_sse("list_my_care_schedules", {}),
        tool_sse("list_care_items", {}),
        tool_sse("list_checkups", {}),
        sse(["답이에요."]),
    ]
    fake = FakeAnthropic(lambda _: sse_response(bodies[len(fake.requests) - 1]))

    async def follow(call: tools.ToolCall) -> str | None:
        return ReadMore("목록")

    async def run():
        agent = AnthropicToolAgent(fake.client(), MODEL)
        stream = agent.answer(CONTEXT, _read_decision(), "첫 목록", 4500, TODAY, follow)
        return [t async for t in stream]

    assert asyncio.run(run()) == ["답이에요."]
    assert len(fake.requests) == 4
    assert [r["tool_choice"]["type"] for r in fake.requests[:3]] == ["auto"] * 3
    assert fake.requests[3]["tool_choice"] == {"type": "none"}
