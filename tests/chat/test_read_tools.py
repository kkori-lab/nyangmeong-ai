import asyncio
import json

import httpx2
import pytest

from app.chat import repository, rules, tools
from app.chat.clients import AnthropicToolAgent, ToolDecision
from app.chat.repository import JavaToolReader
from app.chat.service import DISCLAIMER, READ_NO_PET, READ_PET_ASK
from app.core.backend import external_error
from app.core.config import Settings
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_llm_clients import MODEL, FakeAnthropic, sse
from tests.chat.test_messages import MessageJava, deltas, events, send
from tests.chat.test_register import CHOCO, TODAY
from tests.chat.test_tools import CONTEXT, room_of, sse_response, tool_sse, use_agent

ANSWER = "안내서대로 답할게요."


class FakeToolReader:
    """[가짜 READ 실행]
    - data : 돌려줄 Java data, fail : 502
    - 받은 경로·query(calls) 기록"""

    def __init__(self, data: object = None, fail: bool = False) -> None:
        self.data = [] if data is None else data
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []

    async def read(self, path: str, params: dict) -> object:
        self.calls.append((path, params))
        if self.fail:
            raise external_error()
        return self.data


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


def use_reader(client, reader: FakeToolReader) -> FakeToolReader:
    client.app.dependency_overrides[repository.get_tool_reader] = lambda: reader
    return reader


# 실행 흐름


def test_READ_도구를_고르면_경로와_query로_Java를_부르고_결과로_SEARCH_답변해야_한다(client, java):
    raw = {"from_ymd": "2026-10-01", "to_ymd": "10월 말", "schdl_knd_cd": "HLTC0057", "size": 10}
    agent = use_agent(client, FakeToolAgent("list_care_schedules", raw))
    reader = use_reader(client, FakeToolReader([{"schdlNm": "병원"}]))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "이번 달 병원 일정 있어?"))

    assert evs[0][1]["kind"] == "SEARCH"
    assert reader.calls == [
        (
            "/api/pets/1/care-schedules",
            {"fromYmd": "2026-10-01", "schdlKndCd": "HLTC0057", "size": 10},
        )
    ]
    assert json.loads(agent.results[0]) == [{"schdlNm": "병원"}]
    assert deltas(evs) == ANSWER + DISCLAIMER
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [ANSWER + DISCLAIMER]


def test_참거짓_조건은_소문자_글자로_보내야_한다(client, java):
    use_agent(client, FakeToolAgent("list_care_items", {"main_expsr_yn": True}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java, pet_sn=CHOCO)

    events(send(client, room, "메인에 보이는 케어 뭐 있어?"))

    assert reader.calls == [("/api/pets/1/care-items", {"mainExpsrYn": "true"})]


def test_도구_결과에서_메모_같은_내용_칸은_중첩까지_지워야_한다(client, java):
    data = [
        {
            "schdlNm": "정기검진",
            "memoCn": "비밀 메모",
            "lastCycle": {"ckupMemoCn": "자유 입력", "obsrvSz": 1.5, "cyclCnt": 2},
        }
    ]
    agent = use_agent(client, FakeToolAgent("list_care_schedules", {}))
    use_reader(client, FakeToolReader(data))
    room = room_of(client, java, pet_sn=CHOCO)

    events(send(client, room, "다음 병원 언제야?"))

    assert json.loads(agent.results[0]) == [
        {"schdlNm": "정기검진", "lastCycle": {"obsrvSz": 1.5, "cyclCnt": 2}}
    ]


def test_Java_READ가_실패하면_불러오지_못함을_도구_결과로_넘겨야_한다(client, java):
    agent = use_agent(client, FakeToolAgent("get_health_indicators", {}))
    use_reader(client, FakeToolReader(fail=True))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "체중 어때?"))

    assert evs[0][1]["kind"] == "SEARCH"
    assert agent.results == [rules.READ_FAILED]
    assert deltas(evs) == ANSWER + DISCLAIMER


# 반려동물 결정


def test_문장_속_이름으로_반려동물을_정해야_한다(client, java):
    use_agent(client, FakeToolAgent("get_health_indicators", {}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java)

    events(send(client, room, "뭉치 요즘 체중 어때?"))

    assert reader.calls == [("/api/pets/2/health-indicators", {})]


def test_반려동물을_못_정하면_Java_READ를_부르지_않고_이름을_되물어야_한다(client, java):
    agent = use_agent(client, FakeToolAgent("get_health_indicators", {}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java)

    evs = events(send(client, room, "요즘 체중 어때?"))

    assert evs[0][1]["kind"] == "SEARCH"
    assert reader.calls == []
    assert agent.results == []
    assert deltas(evs) == READ_PET_ASK.format(names="초코, 뭉치") + DISCLAIMER


def test_반려동물이_없으면_등록을_안내해야_한다(client, java):
    java.pets = []
    use_agent(client, FakeToolAgent("get_health_indicators", {}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java)

    evs = events(send(client, room, "요즘 체중 어때?"))

    assert reader.calls == []
    assert deltas(evs) == READ_NO_PET + DISCLAIMER


def test_반려동물_목록을_못_받으면_error_이벤트여야_한다(client, java):
    java.context_status = 0
    use_agent(client, FakeToolAgent("get_health_indicators", {}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "체중 어때?"))

    assert [name for name, _ in evs] == ["intent", "error"]
    assert reader.calls == []


# 결과 크기·Java 호출


def test_결과가_길면_앞부분만_잘라_표시해야_한다():
    data = [{"schdlNm": "가" * 100}] * 100

    text = rules.read_result_text(data)

    assert len(text) == rules.READ_RESULT_MAX_CHARS + len(rules.READ_TRUNCATED)
    assert text.endswith(rules.READ_TRUNCATED)


def test_Java_READ는_브라우저_쿠키를_실어_공개_API_data를_읽어야_한다():
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={"status": "success", "data": [{"schdlSn": 1}]})

    backend = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    settings = Settings(_env_file=None, backend_base_url="http://backend.test")
    reader = JavaToolReader(backend, settings, "access_token=member-1")

    data = asyncio.run(reader.read("/api/pets/1/care-schedules", {"size": 10}))

    assert str(requests[0].url) == "http://backend.test/api/pets/1/care-schedules?size=10"
    assert requests[0].headers["cookie"] == "access_token=member-1"
    assert requests[0].headers["x-requested-with"] == "XMLHttpRequest"
    assert data == [{"schdlSn": 1}]


# 한 턴 READ 2번 : 목록 결과의 번호로 상세


def test_결과를_보고_읽기_도구를_한_번_더_고르면_앞_결과의_번호로_상세를_불러야_한다(client, java):
    agent = use_agent(
        client,
        FakeToolAgent(
            "list_checkups", {}, follow_tool="get_checkup", follow_raw={"ckup_rcd_sn": 7}
        ),
    )
    reader = use_reader(client, FakeToolReader([{"ckupRcdSn": 7, "hsptlNm": "메이"}]))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "마지막 검진 자세히 알려 줘"))

    assert reader.calls == [("/api/pets/1/checkups", {}), ("/api/pets/1/checkups/7", {})]
    assert len(agent.results) == 2
    assert json.loads(agent.results[1] or "") == [{"ckupRcdSn": 7, "hsptlNm": "메이"}]
    assert deltas(evs) == ANSWER + DISCLAIMER


def test_앞_결과에_없는_번호면_Java를_부르지_않고_불러오지_못함이어야_한다(client, java):
    agent = use_agent(
        client,
        FakeToolAgent(
            "list_checkups", {}, follow_tool="get_checkup", follow_raw={"ckup_rcd_sn": 99}
        ),
    )
    reader = use_reader(client, FakeToolReader([{"ckupRcdSn": 7}]))
    room = room_of(client, java, pet_sn=CHOCO)

    events(send(client, room, "마지막 검진 자세히 알려 줘"))

    assert reader.calls == [("/api/pets/1/checkups", {})]
    assert agent.results[1] == rules.READ_FAILED


def test_첫_도구가_앞_결과_없이_번호를_넣으면_Java를_부르지_않아야_한다(client, java):
    agent = use_agent(client, FakeToolAgent("get_checkup", {"ckup_rcd_sn": 7}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java, pet_sn=CHOCO)

    events(send(client, room, "7번 검진 알려 줘"))

    assert reader.calls == []
    assert agent.results == [rules.READ_FAILED]


def test_선택_번호_칸도_앞_결과에_없으면_조건에서_빼야_한다(client, java):
    use_agent(client, FakeToolAgent("list_prescriptions", {"ckup_rcd_sn": 3}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java, pet_sn=CHOCO)

    events(send(client, room, "약 뭐 먹어?"))

    assert reader.calls == [("/api/pets/1/prescriptions", {})]


def test_결과를_보고_읽기_도구가_아닌_도구를_고르면_실행하지_않아야_한다(client, java):
    agent = use_agent(
        client,
        FakeToolAgent("list_checkups", {}, follow_tool="draft_schedule", follow_raw={}),
    )
    reader = use_reader(client, FakeToolReader([{"ckupRcdSn": 7}]))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "검진 기록 알려 줘"))

    assert len(reader.calls) == 1
    assert agent.results[1] is None
    assert deltas(evs) == ANSWER + DISCLAIMER


# 가계부 READ


def test_가계부는_문장에_이름이_없으면_대화_펫_태그와_관계없이_전체를_불러야_한다(client, java):
    use_agent(client, FakeToolAgent("get_expense_total", {"start_ymd": "2026-11-01"}))
    reader = use_reader(client, FakeToolReader({"expndCnt": 2, "totalExpndAmt": 50000}))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "이번 달 가계부 얼마 썼어?"))

    assert reader.calls == [("/api/expenses/totals", {"startYmd": "2026-11-01"})]
    assert deltas(evs) == ANSWER + DISCLAIMER


def test_가계부는_문장_속_이름이_하나면_petSn_조건을_붙여야_한다(client, java):
    use_agent(client, FakeToolAgent("list_expenses", {}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java)

    events(send(client, room, "뭉치 지난달 지출 알려 줘"))

    assert reader.calls == [("/api/expenses", {"petSn": 2})]


def test_가계부는_이름이_둘이면_전체를_불러야_한다(client, java):
    use_agent(client, FakeToolAgent("list_expenses", {}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java)

    events(send(client, room, "초코랑 뭉치 지출 알려 줘"))

    assert reader.calls == [("/api/expenses", {})]


def test_반려동물_칸이_없는_가계부_도구는_반려동물_목록을_받지_않아야_한다(client, java):
    java.context_status = 0
    use_agent(client, FakeToolAgent("list_expense_months", {}))
    reader = use_reader(client, FakeToolReader([{"yearMonth": "2026-11"}]))
    room = room_of(client, java)

    evs = events(send(client, room, "가계부 언제부터 썼어?"))

    assert reader.calls == [("/api/expenses/months", {})]
    assert deltas(evs) == ANSWER + DISCLAIMER


def test_연월은_YYYY_MM만_보내야_한다(client, java):
    use_agent(client, FakeToolAgent("get_expense_statistics", {"year_month": "2026-11"}))
    reader = use_reader(client, FakeToolReader({"totalExpndAmt": 1}))
    room = room_of(client, java)

    events(send(client, room, "이번 달 한도 넘었어?"))

    assert reader.calls == [("/api/expenses/statistics", {"yearMonth": "2026-11"})]


def test_연월_형식이_틀리면_필수_칸이_비어_Java를_부르지_않아야_한다(client, java):
    agent = use_agent(client, FakeToolAgent("get_expense_statistics", {"year_month": "11월"}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java)

    events(send(client, room, "이번 달 한도 넘었어?"))

    assert reader.calls == []
    assert agent.results == [rules.READ_FAILED]


def test_지출_상세는_결과에_남겨야_한다(client, java):
    data = [{"expndSn": 1, "dtlMttr": "사료 2kg", "expndAmt": 30000, "recptSn": None}]
    agent = use_agent(client, FakeToolAgent("list_expenses", {}))
    use_reader(client, FakeToolReader(data))
    room = room_of(client, java)

    events(send(client, room, "사료 언제 샀어?"))

    assert json.loads(agent.results[0] or "") == data


def test_영수증은_지출_목록의_번호로_부르고_이름이_있어도_petSn을_붙이지_않아야_한다(client, java):
    agent = use_agent(
        client,
        FakeToolAgent("list_expenses", {}, follow_tool="get_receipt", follow_raw={"recpt_sn": 5}),
    )
    reader = use_reader(client, FakeToolReader([{"expndSn": 1, "petSn": 2, "recptSn": 5}]))
    room = room_of(client, java)

    events(send(client, room, "뭉치 병원비 영수증 내용 알려 줘"))

    assert reader.calls == [("/api/expenses", {"petSn": 2}), ("/api/receipts/5", {})]
    assert len(agent.results) == 2


# Anthropic 요청 : 결과 답변의 두 번째 도구


def _read_decision() -> ToolDecision:
    use = {"type": "tool_use", "id": "toolu_1", "name": "list_checkups", "input": {}}
    return ToolDecision(call=tools.parse("list_checkups", {}, "toolu_1"), content=(use,))


def test_follow가_있으면_결과_답변에서_고른_읽기_도구_결과를_붙여_다시_답해야_한다():
    bodies = [tool_sse("get_checkup", {"ckup_rcd_sn": 7}), sse(["7번 검진은 ", "메이병원이에요."])]
    fake = FakeAnthropic(lambda _: sse_response(bodies[len(fake.requests) - 1]))
    calls: list[tools.ToolCall] = []

    async def follow(call: tools.ToolCall) -> str | None:
        calls.append(call)
        return "상세 결과"

    async def run():
        agent = AnthropicToolAgent(fake.client(), MODEL)
        stream = agent.answer(CONTEXT, _read_decision(), "목록 결과", 4500, TODAY, follow)
        return [t async for t in stream]

    assert asyncio.run(run()) == ["7번 검진은 ", "메이병원이에요."]
    assert [c.name for c in calls] == ["get_checkup"]
    first, second = fake.requests
    assert first["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert second["tool_choice"] == {"type": "none"}
    assert second["messages"][3]["content"][0]["type"] == "tool_use"
    assert second["messages"][4]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "toolu_1",
        "content": "상세 결과",
    }


def test_follow가_있어도_첫_블록이_글이면_한_번만_불러야_한다():
    fake = FakeAnthropic(lambda _: sse_response(sse(["목록대로요."])))

    async def follow(call: tools.ToolCall) -> str | None:
        raise AssertionError("follow called")

    async def run():
        agent = AnthropicToolAgent(fake.client(), MODEL)
        stream = agent.answer(CONTEXT, _read_decision(), "목록 결과", 4500, TODAY, follow)
        return [t async for t in stream]

    assert asyncio.run(run()) == ["목록대로요."]
    assert len(fake.requests) == 1


def test_두_번째가_읽기_도구가_아니면_실행하지_않음을_도구_결과로_붙여야_한다():
    bodies = [tool_sse("decline", {}), sse(["받은 결과로요."])]
    fake = FakeAnthropic(lambda _: sse_response(bodies[len(fake.requests) - 1]))

    async def follow(call: tools.ToolCall) -> str | None:
        return None

    async def run():
        agent = AnthropicToolAgent(fake.client(), MODEL)
        stream = agent.answer(CONTEXT, _read_decision(), "목록 결과", 4500, TODAY, follow)
        return [t async for t in stream]

    assert asyncio.run(run()) == ["받은 결과로요."]
    assert fake.requests[1]["messages"][4]["content"][0]["content"] == rules.READ_NOT_RUN


# 재현(방 143, 2026-11-06) : 답 없는 질문 두 개가 이력에 있으면 LLM이 tool_use를 2개 낸다
# 첫 블록만 실행하고 tool_result를 1개만 보내면 Anthropic 400
# "tool_use ids were found without tool_result blocks immediately after"


def multi_tool_sse(calls: list[tuple[str, dict]]) -> bytes:
    """Anthropic 스트리밍 tool_use 여러 개 응답 흉내"""
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
    for index, (name, raw) in enumerate(calls):
        block = {"type": "tool_use", "id": f"toolu_{index + 1}", "name": name, "input": {}}
        delta = {"type": "input_json_delta", "partial_json": json.dumps(raw, ensure_ascii=False)}
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


def _unanswered_tool_uses(body: dict) -> set[str]:
    # assistant 메시지마다 바로 다음 user 메시지에 tool_result가 없는 tool_use id
    missing: set[str] = set()
    messages = body["messages"]
    for index, message in enumerate(messages):
        if message["role"] != "assistant" or not isinstance(message["content"], list):
            continue
        uses = {b["id"] for b in message["content"] if b.get("type") == "tool_use"}
        after = messages[index + 1]["content"] if index + 1 < len(messages) else []
        results = {b["tool_use_id"] for b in after if b.get("type") == "tool_result"}
        missing |= uses - results
    return missing


def test_도구_고르기가_tool_use를_여럿_내면_결과_답변_요청에_모두의_tool_result가_있어야_한다():
    calls = [("get_expense_total", {"start_ymd": "2026-11-01"}), ("list_expenses", {})]
    bodies = [multi_tool_sse(calls), sse(["지난달 지출은요."])]
    fake = FakeAnthropic(lambda _: sse_response(bodies[len(fake.requests) - 1]))
    two_questions = [
        {"role": "user", "content": "이번 달 가계부 얼마 썼어?"},
        {"role": "user", "content": "탄이 지난달 지출 목록 알려 줘"},
    ]

    async def run():
        agent = AnthropicToolAgent(fake.client(), MODEL)
        decision = await agent.decide(two_questions, 4500, TODAY)
        stream = agent.answer(two_questions, decision, "결과", 4500, TODAY)
        return [t async for t in stream]

    asyncio.run(run())

    assert _unanswered_tool_uses(fake.requests[1]) == set()


def test_결과_답변에서_tool_use를_여럿_내면_마지막_요청에_모두의_tool_result가_있어야_한다():
    calls = [("get_checkup", {"ckup_rcd_sn": 7}), ("list_prescriptions", {})]
    bodies = [multi_tool_sse(calls), sse(["상세는요."])]
    fake = FakeAnthropic(lambda _: sse_response(bodies[len(fake.requests) - 1]))

    async def follow(call: tools.ToolCall) -> str | None:
        return "상세 결과"

    async def run():
        agent = AnthropicToolAgent(fake.client(), MODEL)
        stream = agent.answer(CONTEXT, _read_decision(), "목록 결과", 4500, TODAY, follow)
        return [t async for t in stream]

    asyncio.run(run())

    assert _unanswered_tool_uses(fake.requests[1]) == set()
