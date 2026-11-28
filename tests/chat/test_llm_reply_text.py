"""고정 답 글을 LLM 글로 (2026-11-28, SCR-AIM-004·005·012 공통)
- decline·navigate : 도구 인자 message가 안내 글. 빠지거나 맞지 않으면 고정 글
- agent-continue 이어 갈 일 없음 : 진행 기록을 받은 LLM 글, 글이 없거나 실패하면 고정 글"""

import pytest

from app.chat import rules, tools
from app.chat.clients import ClassifyError
from app.chat.service import FALLBACK_MESSAGE, OUT_OF_SCOPE_MESSAGE, route_message
from app.core.config import get_settings
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_action import send
from tests.chat.test_action_multi import HEALTH, WEIGHT_RAW, done_of
from tests.chat.test_agent_continue import KEY, ContinueAgent, cont, first_turn
from tests.chat.test_messages import MessageJava, events
from tests.chat.test_register import TODAY
from tests.chat.test_tools import room_of, use_agent


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def fixed_env(monkeypatch):
    # test_agent_continue와 같은 오늘·이어 가기 키
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)
    monkeypatch.setenv("AGENT_STATE_KEY", KEY)
    get_settings.cache_clear()


OUT = "반려동물 케어나 앱 이용이라면 도와드릴게요. 궁금한 걸 다시 물어봐 주세요."


def _row():
    return next(row for row in rules.routing_table() if row.routable)


def _ai_texts(java, room: int) -> list[str]:
    return [m["cnvrsCn"] for m in java.ai_messages(room)]


# decline


def test_decline_스키마는_message를_필수로_보여야_한다():
    definition = next(d for d in tools.tool_definitions() if d["name"] == tools.DECLINE)

    schema = definition["input_schema"]

    assert "message" in schema["required"]
    assert schema["properties"]["message"]["type"] == "string"
    assert schema["properties"]["message"]["minLength"] == 1


@pytest.mark.parametrize("unclear", [False, True])
def test_decline에_글이_있으면_그_글을_저장하고_FALLBACK이어야_한다(client, java, unclear):
    use_agent(client, FakeToolAgent("decline", {"unclear": unclear, "message": OUT}))
    room = room_of(client, java)

    evs = events(send(client, room, "주식 추천해 줘"))

    assert evs[0][1]["kind"] == "FALLBACK"
    assert evs[-1][1]["message"]["cnvrsCn"] == OUT
    assert _ai_texts(java, room) == [OUT]


def test_decline의_긴_글도_자르지_않고_저장해야_한다(client, java):
    long = "가" * 500
    use_agent(client, FakeToolAgent("decline", {"unclear": False, "message": long}))
    room = room_of(client, java)

    send(client, room, "주식 추천해 줘")

    assert _ai_texts(java, room) == [long]


@pytest.mark.parametrize(
    ("unclear", "fixed"), [(False, OUT_OF_SCOPE_MESSAGE), (True, FALLBACK_MESSAGE)]
)
def test_decline_글이_공백이면_unclear대로_고정_글이어야_한다(client, java, unclear, fixed):
    use_agent(client, FakeToolAgent("decline", {"unclear": unclear, "message": "  "}))
    room = room_of(client, java)

    send(client, room, "주식 추천해 줘")

    assert _ai_texts(java, room) == [fixed]


@pytest.mark.parametrize(("unclear", "tag"), [(False, "out_of_scope"), (True, "fallback")])
def test_decline_LLM_글이어도_턴_기록_태그가_남아야_한다(client, java, caplog, unclear, tag):
    use_agent(client, FakeToolAgent("decline", {"unclear": unclear, "message": OUT}))
    room = room_of(client, java)

    with caplog.at_level("INFO", logger="app.chat.turnlog"):
        send(client, room, "주식 추천해 줘")

    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("턴 "))
    assert f"tags={tag}" in line


# navigate


def test_navigate_글에_화면명이_있으면_그_글을_저장해야_한다(client, java):
    row = _row()
    said = f"{row.name} 화면으로 옮겨 드릴게요."
    use_agent(client, FakeToolAgent("navigate", {"screen_num": row.no, "message": said}))
    room = room_of(client, java)

    evs = events(send(client, room, "거기 열어 줘"))

    assert evs[0][1]["kind"] == "ROUTE"
    assert evs[0][1]["scrNm"] == row.name
    assert _ai_texts(java, room) == [said]


@pytest.mark.parametrize("said", [None, "", "다른 화면으로 옮겨 드릴게요."])
def test_navigate_글이_없거나_화면명이_없으면_고정_글이어야_한다(client, java, said):
    row = _row()
    raw = {"screen_num": row.no} if said is None else {"screen_num": row.no, "message": said}
    use_agent(client, FakeToolAgent("navigate", raw))
    room = room_of(client, java)

    evs = events(send(client, room, "거기 열어 줘"))

    assert evs[0][1]["kind"] == "ROUTE"
    assert _ai_texts(java, room) == [route_message(row.name)]


# agent-continue 이어 갈 일 없음


def test_이어_갈_일_없음은_LLM_글을_저장해야_한다(client, java):
    said = "건강 일지 기록은 취소했어요. 다시 하려면 말해 주세요."
    agent = ContinueAgent((HEALTH, WEIGHT_RAW), [said])
    room, done = first_turn(client, java, agent)

    results = [{"tool": HEALTH, "status": "CANCELED"}]
    done2 = done_of(cont(client, room, done["pending"]["agentToken"], results))

    assert done2["message"]["cnvrsCn"] == said
    assert done2["pending"] is None
    assert agent.resumes[0].endswith(rules.AGENT_STOPPED_NOTE)


def test_이어_갈_일_없음에서_LLM이_도구를_고르면_고정_글이어야_한다(client, java):
    agent = ContinueAgent((HEALTH, WEIGHT_RAW), [(HEALTH, WEIGHT_RAW)])
    room, done = first_turn(client, java, agent)

    results = [{"tool": HEALTH, "status": "CANCELED"}]
    done2 = done_of(cont(client, room, done["pending"]["agentToken"], results))

    assert done2["message"]["cnvrsCn"] == rules.AGENT_STOPPED
    assert done2["action"] is None


class FailingStopAgent(ContinueAgent):
    async def resume(self, messages, notes, max_tokens, today):
        self.resumes.append(notes)
        raise ClassifyError("api_error")


def test_이어_갈_일_없음에서_LLM이_실패하면_고정_글이어야_한다(client, java):
    agent = FailingStopAgent((HEALTH, WEIGHT_RAW))
    room, done = first_turn(client, java, agent)

    results = [{"tool": HEALTH, "status": "CANCELED"}]
    done2 = done_of(cont(client, room, done["pending"]["agentToken"], results))

    assert done2["message"]["cnvrsCn"] == rules.AGENT_STOPPED
