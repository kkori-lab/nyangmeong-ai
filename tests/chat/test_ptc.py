"""프로그래밍식 도구 호출 시험 (SCR-AIM-004 추가 요청, 2026-11-26)

읽기 도구를 코드 실행 안에서 부르는 경로(LLM_PTC). 가짜 Anthropic·가짜 Java만 쓴다(AGENTS.md 5번)
"""

import asyncio
import json

from app.chat import service, tools, turnlog
from app.chat.clients import (
    PTC_CALL_LIMIT,
    PTC_RULES,
    TOOL_CHOICE_PTC,
    AnthropicToolAgent,
    ToolDecision,
    get_tool_agent,
    with_result,
)
from app.chat.repository import PetInfo
from app.core.config import Settings
from tests.chat.test_llm_clients import MODEL, FakeAnthropic, sse
from tests.chat.test_read_tools import FakeToolReader
from tests.chat.test_register import TODAY, Pets
from tests.chat.test_tools import CONTEXT, sse_response, tool_sse

CONTAINER = "container_1"
CODE = "import json\nprint(await list_checkups({}))"


def blocks_sse(blocks: list[dict], stop_reason: str, container: str | None = CONTAINER) -> bytes:
    """블록 여러 개 스트리밍 응답 흉내 : text·server_tool_use·tool_use(caller 포함)"""
    message = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": MODEL,
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 1},
    }
    if container is not None:
        message["container"] = {"id": container, "expires_at": "2026-11-26T12:00:00Z"}
    evs: list[tuple[str, dict]] = [("message_start", {"type": "message_start", "message": message})]
    for index, block in enumerate(blocks):
        if block["type"] == "text":
            start = {"type": "text", "text": ""}
            delta = {"type": "text_delta", "text": block["text"]}
        else:
            start = {**block, "input": {}}
            delta = {
                "type": "input_json_delta",
                "partial_json": json.dumps(block["input"], ensure_ascii=False),
            }
        evs += [
            (
                "content_block_start",
                {"type": "content_block_start", "index": index, "content_block": start},
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
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": 5},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(
        f"event: {n}\ndata: {json.dumps(d, ensure_ascii=False)}\n\n" for n, d in evs
    ).encode()


def server_use(code: str = CODE) -> dict:
    return {
        "type": "server_tool_use",
        "id": "srvtoolu_1",
        "name": "code_execution",
        "input": {"code": code},
    }


def code_use(use_id: str, name: str, raw: dict) -> dict:
    return {
        "type": "tool_use",
        "id": use_id,
        "name": name,
        "input": raw,
        "caller": {"type": tools.CODE_CALLER, "tool_id": "srvtoolu_1"},
    }


def paused(*calls: dict, text: str | None = None) -> bytes:
    head = [{"type": "text", "text": text}] if text else []
    return blocks_sse([*head, server_use(), *calls], "tool_use")


def scripted(*bodies: bytes) -> FakeAnthropic:
    fake = FakeAnthropic(lambda _: sse_response(bodies[len(fake.requests) - 1]))
    return fake


class CodeRecorder:
    def __init__(self) -> None:
        self.calls: list[tools.ToolCall] = []

    async def __call__(self, call: tools.ToolCall) -> str:
        self.calls.append(call)
        return f"결과 {call.name}"


def read_names() -> list[str]:
    return [d["name"] for d in tools.tool_definitions() if tools.read_entry(d["name"]) is not None]


def card_name() -> str:
    return next(
        d["name"] for d in tools.tool_definitions() if tools.card_entry(d["name"]) is not None
    )


# 도구 정의·설정


def test_꺼짐이면_도구_정의에_코드_실행과_allowed_callers가_없어야_한다():
    defs = tools.tool_definitions()
    assert all("allowed_callers" not in d for d in defs)
    assert all(d.get("type") != tools.CODE_CALLER for d in defs)


def test_켜면_읽기_도구에만_코드_호출을_허용하고_끝에_코드_실행_도구를_붙여야_한다():
    base = tools.tool_definitions()
    defs = tools.tool_definitions(tools.PTC_CODE)
    assert defs[-1] == {"type": tools.CODE_CALLER, "name": "code_execution"}
    assert [d["name"] for d in defs[:-1]] == [d["name"] for d in base]
    reads = set(read_names())
    assert reads
    for d in defs[:-1]:
        if d["name"] in reads:
            assert d["allowed_callers"] == [tools.CODE_CALLER]
        else:
            assert "allowed_callers" not in d
    both = tools.tool_definitions(tools.PTC_BOTH)
    assert next(d for d in both if d["name"] in reads)["allowed_callers"] == [
        "direct",
        tools.CODE_CALLER,
    ]


def test_LLM_PTC_설정으로_에이전트의_ptc가_정해져야_한다():
    off = Settings(llm_api_key="test-key", _env_file=None)
    on = Settings(llm_api_key="test-key", llm_ptc=True, _env_file=None)
    assert get_tool_agent(off).ptc is None
    assert get_tool_agent(on).ptc == tools.PTC_CODE


def test_꺼짐이면_요청이_지금과_같아야_한다():
    fake = scripted(tool_sse("decline", {}))
    asyncio.run(AnthropicToolAgent(fake.client(), MODEL).decide(CONTEXT, 4500, TODAY))
    body = fake.requests[0]
    assert body["tool_choice"] == {"type": "auto"}  # 2026-11-26 한 응답 도구 여럿
    assert "container" not in body
    assert PTC_RULES not in body["system"][0]["text"]
    assert all(t.get("type") != tools.CODE_CALLER for t in body["tools"])


# 호출 루프


def test_코드_안_도구를_모두_실행해_결과만_담아_컨테이너와_함께_다시_보내야_한다():
    first = paused(
        code_use("toolu_a", "list_checkups", {}), code_use("toolu_b", "list_prescriptions", {})
    )
    fake = scripted(first, sse(["두 기록을 ", "합쳤어요."]))
    code = CodeRecorder()

    async def run():
        agent = AnthropicToolAgent(fake.client(), MODEL, ptc=tools.PTC_CODE)
        decision = await agent.decide(CONTEXT, 4500, TODAY, code=code)
        return [t async for t in decision.text]

    assert asyncio.run(run()) == ["두 기록을 ", "합쳤어요."]
    assert [c.name for c in code.calls] == ["list_checkups", "list_prescriptions"]
    one, two = fake.requests
    assert one["tool_choice"] == TOOL_CHOICE_PTC
    assert PTC_RULES in one["system"][0]["text"]
    assert one["tools"][-1]["type"] == tools.CODE_CALLER
    assert "container" not in one
    assert two["container"] == CONTAINER
    assert two["tools"] == one["tools"]
    assistant, user = two["messages"][-2:]
    assert [b["type"] for b in assistant["content"]] == ["server_tool_use", "tool_use", "tool_use"]
    assert user["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_a", "content": "결과 list_checkups"},
        {"type": "tool_result", "tool_use_id": "toolu_b", "content": "결과 list_prescriptions"},
    ]


def test_코드_뒤_direct_도구는_왕복_기록과_컨테이너를_실어_돌려줘야_한다():
    fake = scripted(paused(code_use("toolu_a", "list_checkups", {})), tool_sse("decline", {}))
    code = CodeRecorder()

    async def run():
        agent = AnthropicToolAgent(fake.client(), MODEL, ptc=tools.PTC_CODE)
        return await agent.decide(CONTEXT, 4500, TODAY, code=code)

    decision = asyncio.run(run())
    assert decision.call.name == "decline"
    assert decision.container == CONTAINER
    assert [turn["role"] for turn in decision.history] == ["assistant", "user"]
    turns = with_result([*CONTEXT, *decision.history], decision.content, decision.call, "x")
    assert turns[-1]["content"][0]["tool_use_id"] == "toolu_1"


def test_코드가_불렀던_tool_use에는_다시_결과를_붙이지_않아야_한다():
    content = (server_use(), code_use("toolu_a", "list_checkups", {}))
    turns = with_result(CONTEXT, content, None, "x")
    assert turns[-1]["content"] == [{"type": "tool_result", "tool_use_id": "", "content": "x"}]


def test_글_뒤_코드_실행이면_글을_흘린_뒤_이어_가고_태그를_붙여야_한다():
    first = paused(code_use("toolu_a", "list_checkups", {}), text="확인해 볼게요. ")
    fake = scripted(first, sse(["검진은 한 번이에요."]))
    code = CodeRecorder()
    record = turnlog.start(1, "질문", None)

    async def run():
        agent = AnthropicToolAgent(fake.client(), MODEL, ptc=tools.PTC_CODE)
        decision = await agent.decide(CONTEXT, 4500, TODAY, code=code)
        return [t async for t in decision.text]

    try:
        assert asyncio.run(run()) == ["확인해 볼게요. ", "검진은 한 번이에요."]
    finally:
        turnlog.finish(record)
    assert [c.name for c in code.calls] == ["list_checkups"]
    assert turnlog.TEXT_THEN_CODE in record.tags
    assert fake.requests[1]["container"] == CONTAINER


def test_READ_결과_답변에서_코드_왕복은_라운드에_세지_않고_follow를_부르지_않아야_한다():
    use = {"type": "tool_use", "id": "toolu_1", "name": "list_checkups", "input": {}}
    decision = ToolDecision(call=tools.parse("list_checkups", {}, "toolu_1"), content=(use,))
    fake = scripted(
        paused(code_use("toolu_a", "get_checkup", {"ckup_rcd_sn": 7})), sse(["7번이에요."])
    )
    code = CodeRecorder()

    async def follow(call):
        raise AssertionError("follow called")

    async def run():
        agent = AnthropicToolAgent(fake.client(), MODEL, ptc=tools.PTC_CODE)
        stream = agent.answer(CONTEXT, decision, "목록", 4500, TODAY, follow, code=code)
        return [t async for t in stream]

    assert asyncio.run(run()) == ["7번이에요."]
    assert [c.name for c in code.calls] == ["get_checkup"]
    assert fake.requests[1]["container"] == CONTAINER
    assert fake.requests[1]["messages"][-1]["content"][0]["tool_use_id"] == "toolu_a"


# 서버 거부·상한


def follow_of(reader: FakeToolReader, text: str = "초코 검진 보여 줘") -> service._Follow:
    read = service.ReadDeps(reader=reader, contexts=Pets([PetInfo(1, "초코")]))
    return service._Follow(text, read, [], set(), [])


def test_코드에서_부른_쓰기_도구는_실행하지_않고_거부_글을_돌려줘야_한다():
    reader = FakeToolReader([])
    follow = follow_of(reader)
    name = card_name()
    result = asyncio.run(follow.code(tools.parse(name, {}, "toolu_a")))
    assert result == service.CODE_NOT_READ
    assert follow.cards == []
    assert reader.calls == []
    nav = asyncio.run(follow.code(tools.parse(tools.NAVIGATE, {"screen_num": 1}, "toolu_b")))
    assert nav == service.CODE_NOT_READ


def test_코드에서_부른_읽기_도구는_지금_READ대로_Java를_불러야_한다():
    reader = FakeToolReader([{"ckupRcdSn": 7}])
    follow = follow_of(reader)
    result = asyncio.run(follow.code(tools.parse("list_checkups", {}, "toolu_a")))
    assert reader.calls
    assert '"ckupRcdSn": 7' in result
    assert follow.seen
    assert follow.reads == 0


def test_코드_안_호출이_상한을_넘으면_Java를_부르지_않고_상한_글을_돌려줘야_한다():
    reader = FakeToolReader([{"ckupRcdSn": 7}])
    follow = follow_of(reader)
    follow.code_calls = PTC_CALL_LIMIT
    result = asyncio.run(follow.code(tools.parse("list_checkups", {}, "toolu_a")))
    assert result == service.CODE_LIMIT.format(limit=PTC_CALL_LIMIT)
    assert reader.calls == []


# 턴 기록


def test_턴_줄은_코드_안_호출이_있을_때만_code_칸을_쓰고_집계가_세야_한다():
    record = turnlog.TurnRecord(room=7, code=3)
    line = turnlog.format_turn(record)
    assert line.endswith(" code=3")
    assert " code=" not in turnlog.format_turn(turnlog.TurnRecord(room=7))
    logged = f"10:30:00.000 [1] INFO app.chat.turnlog - {line}"
    head, fields = turnlog.parse_line(logged)
    assert fields["code"] == "3"
    weeks = turnlog.summarize([(TODAY, logged), (TODAY, logged.replace(" code=3", ""))])
    stats = next(iter(weeks.values()))
    assert (stats.code, stats.code_turns, stats.turns) == (3, 1, 2)
    assert "코드 안 도구 호출: 3번" in turnlog.render(weeks)
