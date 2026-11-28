"""한 번에 도구 하나 제한 풀기 (SCR-AIM-004·012, 2026-11-26 팀 합의)
- 한 응답의 읽기 도구 여럿은 한 턴 TOOL_LIMIT까지 동시에 실행하고 결과를 tool_use id마다
- 같은 응답의 카드·이동은 읽은 뒤 다시 고르게(READ_LATER), 쓰기 도구 여럿은 카드 목록으로
- 결과 답변 라운드의 도구 여럿도 실행"""

import asyncio
import json

import pytest

from app.chat import rules, tools
from app.chat.clients import (
    TOOL_LIMIT,
    AnthropicToolAgent,
    ToolDecision,
    follow_all,
    with_result,
)
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_action import send
from tests.chat.test_action_multi import HEALTH, HOSPITAL, SCHEDULE, WEIGHT_RAW, done_of
from tests.chat.test_llm_clients import MODEL, FakeAnthropic, sse
from tests.chat.test_messages import MessageJava, events
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import CHOCO, TODAY
from tests.chat.test_tools import CONTEXT, room_of, sse_response, use_agent

CARE = "list_care_items"
CHECKUPS = "list_checkups"
RECORDS = "list_daily_health_records"
EXPENSES = "list_expenses"


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


def decision_of(*picks: tuple[str, dict]) -> ToolDecision:
    uses = tuple(
        {"type": "tool_use", "id": f"toolu_{no}", "name": name, "input": raw}
        for no, (name, raw) in enumerate(picks, start=1)
    )
    calls = tuple(tools.parse(use["name"], use["input"], use["id"]) for use in uses)
    return ToolDecision(call=calls[0], content=uses, calls=calls)


class ManyAgent(FakeToolAgent):
    """[가짜 도구 LLM] 첫 고르기에 한 응답 도구 여럿, 받은 decision(결과 포함) 기록"""

    def __init__(self, *picks: tuple[str, dict]) -> None:
        super().__init__()
        self.picks = picks
        self.decisions: list[ToolDecision] = []

    async def decide(self, messages, max_tokens, today) -> ToolDecision:
        self.decides.append((messages, today))
        if len(self.decides) > 1:
            return ToolDecision()
        return decision_of(*self.picks)

    async def answer(self, messages, decision, result, max_tokens, today, follow=None):
        self.decisions.append(decision)
        async for chunk in super().answer(messages, decision, result, max_tokens, today, follow):
            yield chunk


def sent_results(decision: ToolDecision, first: str) -> dict[str, str]:
    # answer가 Anthropic에 보낼 tool_result : id -> 글
    turns = with_result([], decision.content, decision.call, first, dict(decision.results))
    return {block["tool_use_id"]: block["content"] for block in turns[-1]["content"]}


def test_한_응답의_읽기_도구_둘은_둘_다_실행하고_결과를_id마다_보낸다(client, java):
    agent = use_agent(client, ManyAgent((CARE, {}), (CHECKUPS, {})))
    reader = use_reader(client, FakeToolReader([{"careArtclSn": 7}]))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "산책 항목이랑 검진 기록 같이 알려줘"))

    assert evs[0][1]["kind"] == "SEARCH"
    assert len(reader.calls) == 2
    results = sent_results(agent.decisions[0], agent.results[0])
    assert set(results) == {"toolu_1", "toolu_2"}
    assert "careArtclSn" in results["toolu_2"]


def test_한_응답의_읽기_도구가_상한을_넘으면_넘는_것은_실행하지_않는다(client, java):
    names = (CARE, CHECKUPS, RECORDS, EXPENSES)
    picks = tuple((names[no % len(names)], {}) for no in range(TOOL_LIMIT + 1))
    agent = use_agent(client, ManyAgent(*picks))
    reader = use_reader(client, FakeToolReader([]))
    room = room_of(client, java, pet_sn=CHOCO)

    events(send(client, room, "산책 항목이랑 검진이랑 일지랑 지출 다 알려줘"))

    assert len(reader.calls) == TOOL_LIMIT
    results = sent_results(agent.decisions[0], agent.results[0])
    assert results[f"toolu_{TOOL_LIMIT + 1}"] == rules.READ_NOT_RUN
    assert all(results[f"toolu_{no}"] != rules.READ_NOT_RUN for no in range(1, TOOL_LIMIT + 1))


def test_읽기_도구와_같이_고른_카드는_실행하지_않고_다시_고르게_한다(client, java):
    agent = use_agent(client, ManyAgent((CARE, {}), (HEALTH, WEIGHT_RAW)))
    reader = use_reader(client, FakeToolReader([]))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "산책 항목 알려주고 체중도 기록해줘"))

    assert len(reader.calls) == 1
    assert done["action"] is None
    results = sent_results(agent.decisions[0], agent.results[0])
    assert results["toolu_2"] == rules.READ_LATER


def test_한_응답의_쓰기_도구_둘은_카드_두_장이다(client, java):
    agent = use_agent(client, ManyAgent((HEALTH, WEIGHT_RAW), (SCHEDULE, HOSPITAL)))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "초코 오늘 8시 반 체중 4.2kg 병원 10월 6일 3시"))

    assert [card["tool"] for card in done["actions"]] == [HEALTH, SCHEDULE]
    # 이어 주는 말이 없으면 더 고르지 않음
    assert len(agent.decides) == 1


def test_한_응답의_같은_쓰기_도구_둘은_한_장만이다(client, java):
    other = WEIGHT_RAW | {"rcd_nvl": 4.5}
    use_agent(client, ManyAgent((HEALTH, WEIGHT_RAW), (HEALTH, other)))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "초코 오늘 8시 반 체중 4.2kg"))

    assert [card["tool"] for card in done["actions"]] == [HEALTH]


# 결과 답변 라운드


def test_follow_all은_읽기는_동시에_나머지는_차례로_순서대로_결과를_준다():
    started: list[str] = []
    gate = asyncio.Event()

    async def follow(call: tools.ToolCall) -> str | None:
        started.append(call.name)
        if call.name == CARE:
            # 두 읽기가 모두 시작해야 풀림 : 차례로 실행하면 끝나지 않음
            await asyncio.wait_for(gate.wait(), 1)
        elif call.name == CHECKUPS:
            gate.set()
        return f"{call.name} 결과"

    calls = [
        tools.parse(CARE, {}, "toolu_1"),
        tools.parse(HEALTH, WEIGHT_RAW, "toolu_2"),
        tools.parse(CHECKUPS, {}, "toolu_3"),
    ]

    outs = asyncio.run(follow_all(follow, calls))

    assert outs == [f"{CARE} 결과", f"{HEALTH} 결과", f"{CHECKUPS} 결과"]
    assert started[-1] == HEALTH


def tools_sse(picks: list[tuple[str, dict]]) -> bytes:
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
    evs: list[tuple[str, dict]] = [("message_start", start)]
    for index, (name, raw) in enumerate(picks):
        block = {"type": "tool_use", "id": f"toolu_{index + 2}", "name": name, "input": {}}
        delta = {"type": "input_json_delta", "partial_json": json.dumps(raw)}
        evs += [
            (
                "content_block_start",
                {"type": "content_block_start", "index": index, "content_block": block},
            ),
            (
                "content_block_delta",
                {"type": "content_block_delta", "index": index, "delta": delta},
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": index}),
        ]
    evs += [
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                "usage": {"output_tokens": 5},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    body = "".join(f"event: {n}\ndata: {json.dumps(d, ensure_ascii=False)}\n\n" for n, d in evs)
    return body.encode()


def test_결과_답변_라운드의_읽기_도구_둘도_둘_다_실행하고_결과를_id마다_보낸다():
    picks = [("get_checkup", {"ckup_rcd_sn": 7}), ("get_checkup", {"ckup_rcd_sn": 8})]
    bodies = [tools_sse(picks), sse(["두 검진 모두 ", "정상이에요."])]
    fake = FakeAnthropic(lambda _: sse_response(bodies[len(fake.requests) - 1]))
    calls: list[tools.ToolCall] = []

    async def follow(call: tools.ToolCall) -> str | None:
        calls.append(call)
        return f"{call.use_id} 상세"

    async def run():
        agent = AnthropicToolAgent(fake.client(), MODEL)
        first = decision_of((CHECKUPS, {}))
        stream = agent.answer(CONTEXT, first, "목록 결과", 4500, TODAY, follow)
        return [t async for t in stream]

    assert asyncio.run(run()) == ["두 검진 모두 ", "정상이에요."]
    assert [c.use_id for c in calls] == ["toolu_2", "toolu_3"]
    first, second = fake.requests
    assert first["tool_choice"] == {"type": "auto"}
    results = second["messages"][-1]["content"]
    assert [(r["tool_use_id"], r["content"]) for r in results] == [
        ("toolu_2", "toolu_2 상세"),
        ("toolu_3", "toolu_3 상세"),
    ]


def test_도구_고르기는_한_응답의_도구를_모두_calls로_준다():
    picks = [(CARE, {}), (CHECKUPS, {})]
    fake = FakeAnthropic(lambda _: sse_response(tools_sse(picks)))

    async def run():
        agent = AnthropicToolAgent(fake.client(), MODEL)
        return await agent.decide(CONTEXT, 4500, TODAY)

    decision = asyncio.run(run())

    assert [c.name for c in decision.all_calls()] == [CARE, CHECKUPS]
    assert decision.call.name == CARE
    assert "disable_parallel_tool_use" not in fake.requests[0]["tool_choice"]
