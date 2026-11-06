import asyncio
import json
from datetime import date

import httpx2
import pytest

from app.chat import clients, rules, tools
from app.chat.clients import (
    AnthropicToolAgent,
    ClassifyError,
    ToolDecision,
    get_tool_agent,
    tool_system,
)
from app.chat.service import (
    DISCLAIMER,
    FALLBACK_MESSAGE,
    OUT_OF_SCOPE_MESSAGE,
    route_message,
)
from app.core.config import Settings
from app.core.response import AppError
from tests.chat.conftest import as_member
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_llm_clients import MODEL, FakeAnthropic, server_error, sse
from tests.chat.test_messages import MessageJava, deltas, events, names, send
from tests.chat.test_register import CHOCO, TODAY, Extractor, use_extractor

GUIDE_QUESTION = "픽셀 캐릭터 생성 어디서 해?"


def row_of(scr_id: str) -> rules.RouteRow:
    return next(r for r in rules.routing_table() if r.scr_id == scr_id and r.routable)


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


def use_agent(client, agent: FakeToolAgent) -> FakeToolAgent:
    client.app.dependency_overrides[clients.get_tool_agent] = lambda: agent
    return agent


def room_of(client, java, pet_sn: int | None = None) -> int:
    as_member(client, 1)
    return java.add_room(1, "제목", pet_sn=pet_sn, cn="안녕")


# 도구 정의(설계 3-5절)


def test_도구는_builtin_등록_READ이고_설명과_인자_스키마를_모델에서_뽑는다():
    defs = {d["name"]: d for d in tools.tool_definitions()}
    assert set(defs) == {
        "navigate",
        "search_guide",
        "draft_schedule",
        "draft_care_item",
        "decline",
    } | {
        "get_health_indicators",
        "list_care_completions",
        "list_care_items",
        "list_care_schedules",
        "list_checkups",
        "list_daily_health_records",
        "list_inspection_values",
        "list_observation_items",
        "list_prescriptions",
        "list_repeat_preventions",
        "get_checkup",
        "list_etc_inspections",
        "list_observation_cycles",
        "get_expense_statistics",
        "get_expense_total",
        "get_receipt",
        "list_expense_months",
        "list_expense_pets",
        "list_expenses",
    }
    for d in defs.values():
        assert "쓸 때:" in d["description"] and "말하는 법:" in d["description"]
        assert d["input_schema"]["type"] == "object"
        assert "title" not in d["input_schema"]


def test_navigate_인자는_매핑표의_라우팅_가능_행_번호만():
    # FN-AIM-004-08
    schema = next(d for d in tools.tool_definitions() if d["name"] == "navigate")["input_schema"]
    routable = [r.no for r in rules.routing_table() if r.routable]
    assert schema["properties"]["screen_num"]["enum"] == routable


def test_search_guide_인자는_안내서_목차_번호만():
    schema = next(d for d in tools.tool_definitions() if d["name"] == "search_guide")
    enum = schema["input_schema"]["properties"]["chunk_id"]["anyOf"][0]["enum"]
    assert enum == [chunk.id for chunk in rules.guide_chunks()]


def test_도구_system에는_답변_규칙_화면_목록_안내서_목차가_들어간다():
    system = tool_system()
    assert (
        clients.ANSWER_SYSTEM.replace(clients.PRIVATE_DATA_RULE, clients.TOOL_DATA_RULE) in system
    )
    assert clients.PRIVATE_DATA_RULE not in system
    assert tools.screen_list() in system
    assert "6-1" in system


# 인자 검증(설계 2절)


def test_매핑표에_없는_화면_번호는_인자_거부():
    missing = max(r.no for r in rules.routing_table()) + 1
    assert tools.parse("navigate", {"screen_num": missing}).args is None


def test_라우팅_대상_아닌_행은_인자_거부():
    hidden = next(r for r in rules.routing_table() if not r.routable)
    assert tools.parse("navigate", {"screen_num": hidden.no}).args is None


def test_매핑표의_화면_번호면_그_행():
    row = row_of("SCR-MYP-030")
    call = tools.parse("navigate", {"screen_num": row.no})
    assert tools.route_row(call) == row


def test_모르는_도구나_형식이_틀린_인자는_거부():
    assert tools.parse("delete_pet", {}).args is None
    assert tools.parse("navigate", {"screen_num": "가계부"}).args is None


def test_등록_도구_인자는_공통코드와_날짜를_다시_검증한다():
    # FN-AIM-012-03
    call = tools.parse(
        "draft_schedule",
        {
            "schdl_knd_cd": "HLTC9999",
            "schdl_ymd": "2026-02-30",
            "schdl_tm": "15:00",
            "hsptl_nm": "메이",
        },
    )
    assert tools.register_values(call) == {"schdl_tm": "15:00", "hsptl_nm": "메이"}


def test_케어_항목_도구_인자는_주기_코드를_남긴다():
    call = tools.parse(
        "draft_care_item",
        {"care_artcl_nm": "발톱 깎기", "care_zone_cd": "HLTC0037", "care_cycle_cd": "HLTC0039"},
    )
    values = tools.register_values(call)
    assert values == {
        "care_artcl_nm": "발톱 깎기",
        "care_zone_cd": "HLTC0037",
        "care_cycle_cd": "HLTC0039",
    }


def test_안내서_청크는_고른_목차를_앞에_M1_결과를_뒤에_3개까지():
    # FN-AIM-002-02
    call = tools.parse("search_guide", {"chunk_id": "C-3"})
    ids = tools.guide_ids(call, GUIDE_QUESTION)
    assert ids[0] == "C-3"
    assert ids[1:] == rules.search_guide(GUIDE_QUESTION)[:2]


def test_목차에_없는_청크는_버리고_M1_결과만():
    call = tools.parse("search_guide", {"chunk_id": "99-9"})
    assert tools.guide_ids(call, GUIDE_QUESTION) == rules.search_guide(GUIDE_QUESTION)


# 설정과 클라이언트


def settings(enabled: bool, key: str = "test-key") -> Settings:
    return Settings(_env_file=None, llm_api_key=key, llm_model=MODEL, chat_tool_agent=enabled)


def test_설정이_꺼져_있으면_도구_흐름_없음_키도_보지_않는다():
    assert get_tool_agent(settings(False, key="")) is None


def test_설정을_켜면_Anthropic_도구_구현():
    assert isinstance(get_tool_agent(settings(True)), AnthropicToolAgent)


def test_설정을_켜고_키가_비면_502():
    with pytest.raises(AppError) as raised:
        get_tool_agent(settings(True, key=""))
    assert (raised.value.code, raised.value.http_code) == ("EXTERNAL_API_ERROR", 502)


def test_기본_설정은_도구_흐름_꺼짐():
    assert Settings(_env_file=None).chat_tool_agent is False


# 도구별 SSE(응답 계약 그대로, 설계 6절)


def test_navigate는_ROUTE와_이동_안내_저장(client, java):
    row = row_of("SCR-MYP-030")
    agent = use_agent(client, FakeToolAgent("navigate", {"screen_num": row.no}))
    room = room_of(client, java)
    evs = events(send(client, room, "돈 쓴 거 정리한 데 보여 줘"))

    assert names(evs) == ["intent", "done"]
    assert (evs[0][1]["kind"], evs[0][1]["scrId"]) == ("ROUTE", "SCR-MYP-030")
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [route_message(row.name)]
    assert len(agent.decides) == 1


def test_search_guide는_안내서를_도구_결과로_돌려주고_SEARCH_답변과_바로가기(client, java):
    agent = use_agent(client, FakeToolAgent("search_guide", {"chunk_id": "6-1"}))
    room = room_of(client, java)
    evs = events(send(client, room, "캐릭터는 어디서 만들 수 있어요?"))

    assert evs[0][1]["kind"] == "SEARCH"
    assert deltas(evs) == "안내서대로 답할게요." + DISCLAIMER
    assert rules.find_guide("6-1").text in agent.results[0]
    assert evs[-1][1]["shortcut"]["scrId"] == "SCR-MYP-010"
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == ["안내서대로 답할게요." + DISCLAIMER]


def test_안내서_청크가_없으면_범위_안내(client, java):
    use_agent(client, FakeToolAgent("search_guide", {"chunk_id": None}))
    room = room_of(client, java)
    evs = events(send(client, room, "ㅁㄴㅇㄹ 어떻게 써?"))

    assert evs[0][1]["kind"] == "FALLBACK"
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [OUT_OF_SCOPE_MESSAGE]


def test_도구_없이_글이면_그_스트림을_SEARCH_답변으로(client, java):
    agent = use_agent(client, FakeToolAgent(texts=("포도는 ", "위험해요.")))
    room = room_of(client, java)
    evs = events(send(client, room, "강아지 포도 먹어도 돼?"))

    assert evs[0][1]["kind"] == "SEARCH"
    assert deltas(evs) == "포도는 위험해요." + DISCLAIMER
    assert evs[-1][1]["shortcut"] is None
    assert agent.results == []
    context = agent.decides[0][0]
    assert context[-1] == {"role": "user", "content": "강아지 포도 먹어도 돼?"}


def test_등록_도구는_추출기_없이_도구_인자로_카드(client, java):
    raw = {"schdl_knd_cd": "HLTC0057", "ckup_type_cd": "HLTC0002", "hsptl_nm": "메이 동물병원"}
    agent = use_agent(client, FakeToolAgent("draft_schedule", raw))
    extractor = use_extractor(client, Extractor({"hsptl_nm": "다른 병원"}))
    room = room_of(client, java, pet_sn=CHOCO)
    evs = events(send(client, room, "다음 주 화요일 오후 3시에 병원 가는 거 등록해 줘"))

    assert evs[0][1]["kind"] == "REGISTER"
    card = evs[-1][1]["card"]
    assert card["cardType"] == "SCHEDULE"
    assert (card["schdlYmd"], card["schdlTm"]) == ("2026-10-06", "15:00")
    assert (card["hsptlNm"], card["ckupTypeCd"]) == ("메이 동물병원", "HLTC0002")
    assert extractor.calls == []
    assert agent.decides[0][1] == TODAY


def test_등록_요청은_라우팅_키워드가_있어도_도구_고르기로(client, java):
    # FN-AIM-004-13
    agent = use_agent(client, FakeToolAgent("draft_schedule", {}))
    room = room_of(client, java, pet_sn=CHOCO)
    evs = events(send(client, room, "내일 3시 병원 예약 잡아줘"))

    assert evs[0][1]["kind"] == "REGISTER"
    assert agent.decides[0][2] is None


@pytest.mark.parametrize(
    ("unclear", "message"), [(False, OUT_OF_SCOPE_MESSAGE), (True, FALLBACK_MESSAGE)]
)
def test_decline은_범위_밖과_판단_못_함_문구를_나눈다(client, java, unclear, message):
    use_agent(client, FakeToolAgent("decline", {"unclear": unclear}))
    room = room_of(client, java)
    evs = events(send(client, room, "주식 추천해 줘"))

    assert evs[0][1]["kind"] == "FALLBACK"
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [message]


@pytest.mark.parametrize(
    ("tool", "raw"), [("navigate", {"screen_num": 999}), ("delete_pet", {}), (None, None)]
)
def test_인자_거부나_빈_응답은_판단_못_함(client, java, tool, raw):
    use_agent(client, FakeToolAgent(tool, raw))
    room = room_of(client, java)
    evs = events(send(client, room, "음"))

    assert evs[0][1]["kind"] == "FALLBACK"
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [FALLBACK_MESSAGE]


def test_룰_라우팅_문장은_도구_고르기를_부르지_않는다(client, java):
    # FN-AIM-002-10
    agent = use_agent(client, FakeToolAgent(fail=True))
    room = room_of(client, java)
    evs = events(send(client, room, "일정 등록할래"))

    assert (evs[0][1]["kind"], evs[0][1]["scrId"]) == ("ROUTE", "SCR-HLT-003")
    assert agent.decides == []


def test_키워드에_걸린_질문꼴은_힌트와_함께_도구_고르기(client, java):
    agent = use_agent(client, FakeToolAgent("decline", {}))
    room = room_of(client, java)
    events(send(client, room, "가계부 작성 방법 알려줘"))

    assert agent.decides[0][2] == rules.match_route("가계부 작성 방법 알려줘")


def test_도구_고르기_장애면_error_이벤트(client, java):
    use_agent(client, FakeToolAgent(fail=True))
    room = room_of(client, java)
    evs = events(send(client, room, "강아지 포도 먹어도 돼?"))

    assert names(evs) == ["error"]
    assert evs[0][1]["code"] == "EXTERNAL_API_ERROR"
    assert java.ai_messages(room) == []


def test_도구_고르기_장애여도_키워드에_걸린_질문은_ROUTE(client, java):
    use_agent(client, FakeToolAgent(fail=True))
    room = room_of(client, java)
    evs = events(send(client, room, "가계부 어떻게 봐?"))

    assert evs[0][1]["kind"] == "ROUTE"


def test_설정을_끄면_도구_고르기를_부르지_않는다(client, java):
    room = room_of(client, java)
    evs = events(send(client, room, "주식 추천해 줘"))

    assert evs[0][1]["kind"] == "FALLBACK"


# Anthropic 도구 호출(스트리밍)


def tool_sse(name: str, raw: dict) -> bytes:
    """Anthropic 스트리밍 tool_use 응답 흉내"""
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
    block = {"type": "tool_use", "id": "toolu_1", "name": name, "input": {}}
    delta = {"type": "input_json_delta", "partial_json": json.dumps(raw, ensure_ascii=False)}
    evs = [
        ("message_start", start),
        (
            "content_block_start",
            {"type": "content_block_start", "index": 0, "content_block": block},
        ),
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": delta}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
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


def sse_response(body: bytes) -> httpx2.Response:
    return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)


CONTEXT = [{"role": "user", "content": "가계부 보여 줘"}]


def decide(fake: FakeAnthropic, hint=None) -> ToolDecision:
    agent = AnthropicToolAgent(fake.client(), MODEL)
    return asyncio.run(agent.decide(CONTEXT, 4500, TODAY, hint=hint))


def test_도구_요청은_도구_정의와_캐시한_system과_오늘_날짜를_보낸다():
    row = row_of("SCR-MYP-030")
    fake = FakeAnthropic(lambda _: sse_response(tool_sse("navigate", {"screen_num": row.no})))
    decision = decide(fake)

    body = fake.requests[0]
    assert [t["name"] for t in body["tools"]] == [d["name"] for d in tools.tool_definitions()]
    assert body["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["system"][1]["text"] == "오늘: 2026-09-29 (화)"
    assert body["messages"] == CONTEXT
    assert decision.call.name == "navigate"
    assert tools.route_row(decision.call) == row
    assert decision.content[0]["type"] == "tool_use"


def test_키워드_힌트는_캐시_뒤_블록():
    fake = FakeAnthropic(lambda _: sse_response(tool_sse("decline", {})))
    decide(fake, hint=row_of("SCR-MYP-030"))
    assert "가계부" in fake.requests[0]["system"][2]["text"]


def test_첫_블록이_글이면_같은_호출의_글을_그대로_흘린다():
    fake = FakeAnthropic(lambda _: sse_response(sse(["포도는 ", "위험해요."])))

    async def run():
        decision = await AnthropicToolAgent(fake.client(), MODEL).decide(CONTEXT, 4500, TODAY)
        return decision, [text async for text in decision.text]

    decision, texts = asyncio.run(run())
    assert decision.call is None
    assert texts == ["포도는 ", "위험해요."]
    assert len(fake.requests) == 1


def test_도구_결과_답변은_tool_result를_붙이고_도구를_다시_쓰지_않는다():
    fake = FakeAnthropic(lambda _: sse_response(sse(["안내서대로요."])))
    use = {
        "type": "tool_use",
        "id": "toolu_1",
        "name": "search_guide",
        "input": {"chunk_id": "6-1"},
    }
    decision = ToolDecision(
        call=tools.parse("search_guide", use["input"], "toolu_1"), content=(use,)
    )

    async def run():
        agent = AnthropicToolAgent(fake.client(), MODEL)
        return [t async for t in agent.answer(CONTEXT, decision, "안내서 글", 4500, TODAY)]

    assert asyncio.run(run()) == ["안내서대로요."]
    body = fake.requests[0]
    assert body["tool_choice"] == {"type": "none"}
    assert body["messages"][1] == {"role": "assistant", "content": [use]}
    assert body["messages"][2]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "toolu_1",
        "content": "안내서 글",
    }


def test_도구_요청_API_오류는_ClassifyError():
    with pytest.raises(ClassifyError):
        decide(FakeAnthropic(server_error))


def test_사용량은_평가용_콜백에_넘긴다():
    usages = []
    fake = FakeAnthropic(lambda _: sse_response(tool_sse("decline", {})))
    agent = AnthropicToolAgent(fake.client(), MODEL, on_usage=lambda task, u: usages.append(task))
    asyncio.run(agent.decide(CONTEXT, 4500, date(2026, 9, 29)))
    assert usages == ["도구 고르기"]
