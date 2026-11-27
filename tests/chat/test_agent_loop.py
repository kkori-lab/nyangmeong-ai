"""SCR-AIM-004·012 에이전트 ② 읽기 루프 엔진 (docs/design/agent.md 3절, 2026-11-26)
- 한 턴 도구 상한 TOOL_LIMIT번(읽기·카드·이동·사용법 합쳐), 넘으면 실행 안 함·agent_limit
- step 이벤트 : 읽기 직전마다 READ, 결과 뒤 카드를 만들 때 CARD. 저장 안 함
- 첫 이벤트 제한 : step이나 delta가 오면 첫 글자는 전체 제한까지"""

import asyncio
import re
from collections.abc import AsyncIterator
from datetime import date
from types import SimpleNamespace

import pytest

from app.chat import rules, service, tools, turnlog
from app.chat.clients import TOOL_LIMIT, ReadMore
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_answer_failure_log import _Repo, _turn
from tests.chat.test_messages import Answers, MessageJava, deltas, events, send
from tests.chat.test_parallel_tools import ManyAgent
from tests.chat.test_read_follow_mixed import _send
from tests.chat.test_read_tools import ANSWER, FakeToolReader, use_reader
from tests.chat.test_register import CHOCO
from tests.chat.test_tools import room_of, row_of, use_agent

TURN_LOGGER = "app.chat.turnlog"
SERVICE_LOGGER = "app.chat.service"
READS = ("list_expenses", "list_inspection_values", "list_care_items", "list_checkups")


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


def _follows(count: int) -> tuple[tuple[str, dict], ...]:
    return tuple((READS[no % len(READS)], {}) for no in range(count))


def _turn_tags(caplog) -> list[str]:
    lines = [
        dict(re.findall(r"(\w+)=(\S+)", r.getMessage()))
        for r in caplog.records
        if r.name == TURN_LOGGER and r.getMessage().startswith("턴 ")
    ]
    assert len(lines) == 1
    return lines[0]["tags"].split(",")


def _steps(evs) -> list[dict]:
    return [data for name, data in evs if name == "step"]


def _label(name: str) -> str:
    entry = tools.read_entry(name) or tools.card_entry(name)
    return entry.label or entry.name


# 도구 상한


def test_읽기_5단계는_차례로_실행되고_답이_저장되어야_한다(client, java):
    agent = FakeToolAgent("list_checkups", {}, follows=_follows(4))
    reader = FakeToolReader([{"ckupRcdSn": 7}])

    room, evs = _send(client, java, agent, "검진이랑 병원비랑 케어 다 알려 줘", reader)

    assert len(reader.calls) == 5
    assert all(isinstance(result, ReadMore) for result in agent.results[1:])
    assert deltas(evs).startswith(ANSWER)
    assert [m["cnvrsCn"] for m in java.ai_messages(room)][0].startswith(ANSWER)
    assert evs[-1][0] == "done"


def test_상한을_넘는_도구는_실행하지_않고_agent_limit_태그여야_한다(client, java, caplog):
    agent = FakeToolAgent("list_checkups", {}, follows=_follows(TOOL_LIMIT))
    reader = FakeToolReader([{"ckupRcdSn": 7}])

    with caplog.at_level("INFO", logger=TURN_LOGGER):
        _, evs = _send(client, java, agent, "검진이랑 병원비랑 케어 다 알려 줘", reader)

    assert len(reader.calls) == TOOL_LIMIT
    assert agent.results[TOOL_LIMIT] == rules.TOOL_LIMIT_REACHED
    assert turnlog.AGENT_LIMIT in _turn_tags(caplog)
    assert evs[-1][0] == "done"


def test_상한_안이면_agent_limit_태그가_없어야_한다(client, java, caplog):
    agent = FakeToolAgent("list_checkups", {}, follows=_follows(2))
    reader = FakeToolReader([{"ckupRcdSn": 7}])

    with caplog.at_level("INFO", logger=TURN_LOGGER):
        _send(client, java, agent, "검진이랑 병원비 알려 줘", reader)

    assert turnlog.AGENT_LIMIT not in _turn_tags(caplog)


def test_읽기_뒤_카드_1장은_지금처럼_나와야_한다(client, java):
    agent = FakeToolAgent(
        "list_care_items",
        {},
        follows=(*_follows(3), ("draft_care_completion", {"care_artcl_sn": 7})),
    )
    reader = FakeToolReader([{"careArtclSn": 7, "careArtclNm": "산책"}])

    _, evs = _send(client, java, agent, "산책 완료 체크하고 기록도 알려 줘", reader)

    assert len(reader.calls) == 4
    assert evs[-1][1]["action"]["tool"] == "draft_care_completion"


# step 이벤트


def test_READ_두_번이면_step_두_개가_intent_뒤_delta_앞에_와야_한다(client, java):
    agent = FakeToolAgent("list_checkups", {}, follows=(("list_expenses", {}),))
    reader = FakeToolReader([{"ckupRcdSn": 7}])

    room, evs = _send(client, java, agent, "검진이랑 병원비 알려 줘", reader)

    names = [name for name, _ in evs]
    assert names[0] == "intent"
    assert names[1:3] == ["step", "step"]
    assert names.index("delta") > 2
    assert _steps(evs) == [
        {"tool": "list_checkups", "label": _label("list_checkups"), "kind": "READ"},
        {"tool": "list_expenses", "label": _label("list_expenses"), "kind": "READ"},
    ]
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [ANSWER]


def test_결과_뒤_카드를_만들면_CARD_step이_와야_한다(client, java):
    card = "draft_care_completion"
    agent = FakeToolAgent("list_care_items", {}, follow_tool=card, follow_raw={"care_artcl_sn": 7})
    reader = FakeToolReader([{"careArtclSn": 7, "careArtclNm": "산책"}])

    _, evs = _send(client, java, agent, "산책 완료 체크해 줘", reader)

    assert [step["kind"] for step in _steps(evs)] == ["READ", "CARD"]
    assert _steps(evs)[1] == {"tool": card, "label": _label(card), "kind": "CARD"}


def test_도구_없는_답에는_step이_없어야_한다(client, java):
    use_agent(client, Answers(("반가워요.",)))
    room = room_of(client, java)

    evs = events(send(client, room, "오늘 어때?"))

    assert _steps(evs) == []


def test_이동에는_step이_없어야_한다(client, java):
    row = row_of("SCR-MYP-030")
    use_agent(client, FakeToolAgent("navigate", {"screen_num": row.no}))
    room = room_of(client, java)

    evs = events(send(client, room, "가계부 열어"))

    assert evs[0][1]["kind"] == "ROUTE"
    assert _steps(evs) == []


def test_step은_저장된_메시지에_남지_않아야_한다(client, java):
    agent = FakeToolAgent("list_checkups", {})
    reader = FakeToolReader([{"ckupRcdSn": 7}])

    room, evs = _send(client, java, agent, "검진 알려 줘", reader)

    assert len(_steps(evs)) == 1
    assert java.ai_messages(room)[0]["cnvrsCn"] == ANSWER


def test_한_응답_읽기_여럿이_상한을_넘으면_agent_limit_태그여야_한다(client, java, caplog):
    picks = tuple((READS[no % len(READS)], {}) for no in range(TOOL_LIMIT + 1))
    use_agent(client, ManyAgent(*picks))
    reader = use_reader(client, FakeToolReader([]))
    room = room_of(client, java, pet_sn=CHOCO)

    with caplog.at_level("INFO", logger=TURN_LOGGER):
        evs = events(send(client, room, "다 알려 줘"))

    assert len(reader.calls) == TOOL_LIMIT
    assert len(_steps(evs)) == TOOL_LIMIT
    assert turnlog.AGENT_LIMIT in _turn_tags(caplog)


# 첫 이벤트·전체 시간


ENTRY = SimpleNamespace(name="list_checkups", label="검진 기록")


async def _stepping(wait: float, chunks: tuple[str, ...] = ("답",)) -> AsyncIterator[str]:
    service._step(ENTRY, "READ")
    await asyncio.sleep(wait)
    for chunk in chunks:
        yield chunk


async def _silent(wait: float) -> AsyncIterator[str]:
    await asyncio.sleep(wait)
    yield "답"


def _run(stream: AsyncIterator[str], first: float, total: float) -> list:
    emitted: list = []
    asyncio.run(
        service._search_answer(
            _turn(), _Repo(), service.AnswerLimits(first, total), None, emitted.append, stream
        )
    )
    return emitted


def _failures(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("답변 실패")]


def test_step_뒤_첫_글자가_첫_이벤트_제한을_넘어도_전체_안이면_답해야_한다(caplog):
    with caplog.at_level("WARNING", logger=SERVICE_LOGGER):
        emitted = _run(_stepping(0.3), first=0.05, total=5)

    names = [name for name, _ in emitted]
    assert names[0] == "step"
    assert "delta" in names
    assert "error" not in names
    assert names[-1] == "done"
    assert emitted[0][1].model_dump(by_alias=True) == {
        "tool": "list_checkups",
        "label": "검진 기록",
        "kind": "READ",
    }
    assert _failures(caplog) == []


def test_step도_delta도_첫_이벤트_제한_안에_없으면_error여야_한다(caplog):
    with caplog.at_level("WARNING", logger=SERVICE_LOGGER):
        emitted = _run(_silent(1), first=0.05, total=5)

    assert [name for name, _ in emitted] == ["error"]
    lines = _failures(caplog)
    assert len(lines) == 1
    assert lines[0].startswith("답변 실패: 첫 글자 전 first_token_timeout ")


def test_step_뒤_전체_제한을_넘기면_첫_글자_전_error여야_한다(caplog):
    with caplog.at_level("WARNING", logger=SERVICE_LOGGER):
        emitted = _run(_stepping(1), first=0.05, total=0.2)

    assert [name for name, _ in emitted] == ["step", "error"]
    lines = _failures(caplog)
    assert len(lines) == 1
    assert lines[0].startswith("답변 실패: 첫 글자 전 total_timeout ")


def test_step_보내는_곳은_답변_스트림이_끝나면_비워져야_한다():
    _run(_stepping(0), first=1, total=5)

    assert service._STEP_SINK.get() is None


# 주 단위 집계


def test_agent_limit_태그_턴은_주_집계에_잡혀야_한다():
    line = (
        "10:00:00.000 [1] INFO app.chat.turnlog - 턴 room=7 kind=SEARCH reply=- "
        "tools=list_checkups reads=8 java=8 result=ok cards=0 tags=agent_limit "
        "prev=- retry=0 ms=9000\n"
    )

    weeks = turnlog.summarize([(date(2026, 11, 26), line)])

    week = next(iter(weeks.values()))
    assert week.tags == {turnlog.AGENT_LIMIT: 1}
    assert week.reads_max == 8


def test_표시_이름_없는_도구의_step은_영어_이름_대신_정보여야_한다():
    seen: list = []
    token = service._STEP_SINK.set(seen.append)
    try:
        service._step(SimpleNamespace(name="list_new_thing", label=None), "READ")
    finally:
        service._STEP_SINK.reset(token)

    assert [e.model_dump(by_alias=True) for e in seen] == [
        {"tool": "list_new_thing", "label": "정보", "kind": "READ"}
    ]
