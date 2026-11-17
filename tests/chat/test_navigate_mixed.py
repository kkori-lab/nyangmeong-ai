import pytest

from app.chat import rules, service, tools
from app.chat.clients import ToolDecision
from app.chat.schemas import IntentKind
from app.chat.service import DISCLAIMER, ROUTE_EMPTY_MESSAGE, ROUTE_SHOWN
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_messages import MessageJava, deltas, events, send
from tests.chat.test_read_tools import ANSWER, FakeToolReader, use_reader
from tests.chat.test_register import CHOCO
from tests.chat.test_tools import room_of, row_of, use_agent

# 이동 먼저 고른 섞인 메시지(2026-11-17) : 이동 뒤에 다른 일을 이어 말하면
# 화면을 옮기지 않고 바로가기 답변, 함께 물은 기록·사용법은 결과 뒤 도구로

TOTALS = "/api/expenses/totals"


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


def _send(client, java: MessageJava, agent: FakeToolAgent, text: str, reader: FakeToolReader):
    use_agent(client, agent)
    use_reader(client, reader)
    room = room_of(client, java, pet_sn=CHOCO)
    return room, events(send(client, room, text))


# 이어 말한 이동 판별


@pytest.mark.parametrize(
    "text",
    [
        "가계부 열어서 이번 달 지출 얼마인지 알려 줘",
        "일정 화면 가서 코코 이번 주 일정 보여 줘",
        "가계부 열어서 한도 설정은 어떻게 하는지 알려 줘",
    ],
)
def test_이동_말_뒤에_다른_일을_이어_말하면_참(text):
    assert rules.chains_after_move(text)


@pytest.mark.parametrize("text", ["가계부 열어 줘", "가계부 보여 줘", "가계부", "가계부 열어서"])
def test_이동만_말하면_거짓(text):
    assert not rules.chains_after_move(text)


# 답변 흐름


def test_이동을_먼저_골라도_이어_물은_지출은_결과_뒤_READ로_읽고_가계부_바로가기(client, java):
    row = row_of("SCR-MYP-030")
    agent = FakeToolAgent(
        "navigate",
        {"screen_num": row.no},
        follow_tool="get_expense_total",
        follow_raw={"start_ymd": "2026-11-01"},
    )
    reader = FakeToolReader({"expndCnt": 2, "totalExpndAmt": 50000})

    _, evs = _send(client, java, agent, "가계부 열어서 이번 달 지출 알려 줘", reader)

    assert evs[0][1]["kind"] == "SEARCH"
    assert all(data.get("kind") != "ROUTE" for _, data in evs)
    assert agent.results[0] == ROUTE_SHOWN.format(name=row.name)
    assert reader.calls == [(TOTALS, {"startYmd": "2026-11-01"})]
    assert evs[-1][0] == "done"
    assert evs[-1][1]["shortcut"]["scrId"] == "SCR-MYP-030"


def test_이동만_말하면_지금처럼_이동하고_답변_LLM을_부르지_않는다(client, java):
    row = row_of("SCR-MYP-030")
    agent = FakeToolAgent("navigate", {"screen_num": row.no})
    reader = FakeToolReader()

    _, evs = _send(client, java, agent, "가계부 열어 줘", reader)

    assert (evs[0][1]["kind"], evs[0][1]["scrId"]) == ("ROUTE", "SCR-MYP-030")
    assert agent.results == []
    assert reader.calls == []


def test_이어_말했지만_결과_뒤_도구_없이_글만_오면_글과_바로가기(client, java):
    row = row_of("SCR-MYP-030")
    agent = FakeToolAgent("navigate", {"screen_num": row.no})
    reader = FakeToolReader()

    _, evs = _send(client, java, agent, "가계부 열어서 뭐 하는지 알려 줘", reader)

    assert evs[0][1]["kind"] == "SEARCH"
    assert reader.calls == []
    # 고지 READ가 없으므로 고지 없음
    assert deltas(evs) == ANSWER
    assert DISCLAIMER not in deltas(evs)
    assert evs[-1][1]["shortcut"]["scrId"] == "SCR-MYP-030"


def test_이어_말한_답변이_0자면_고정_글과_바로가기(client, java):
    row = row_of("SCR-MYP-030")
    agent = FakeToolAgent("navigate", {"screen_num": row.no}, answer_chunks=())
    reader = FakeToolReader()

    _, evs = _send(client, java, agent, "가계부 열어서 이번 달 지출 알려 줘", reader)

    assert deltas(evs) == ROUTE_EMPTY_MESSAGE.format(name=row.name)
    assert evs[-1][1]["shortcut"]["scrId"] == "SCR-MYP-030"


def test_READ_실행이_없으면_이어_말해도_이동():
    row = row_of("SCR-MYP-030")
    agent = FakeToolAgent("navigate", {"screen_num": row.no})
    raw = {"screen_num": row.no}
    decision = ToolDecision(call=tools.parse("navigate", raw, "toolu_1"))

    judged = service._tool_judged(
        "가계부 열어서 이번 달 지출 알려 줘",
        [],
        agent,
        decision,
        100,
        rules.today_kst(),
        read=None,
    )

    assert judged.intent.kind == IntentKind.ROUTE
    assert judged.intent.scr_id == "SCR-MYP-030"
    assert judged.stream is None
