"""에이전트 ③ 검증 2차 고침 (2026-11-26)
- pending을 주는 READ 뒤 카드 턴 : 남은 일(비교 등)은 실행 결과를 받은 뒤에 답하게 카드 글을 줌
- 이어 가기 : 실행 전에 읽은 결과는 "쓰기 실행 전"으로 표시해 다시 읽게 함
- agent-continue : 방 확인(404)이 토큰 검사(400)보다 먼저"""

import pytest

from app.chat import rules
from app.core.config import get_settings
from tests.chat.test_action_multi import HEALTH, WEIGHT_RAW
from tests.chat.test_agent_continue import (
    KEY,
    READ,
    SIMPLE,
    ContinueAgent,
    cont,
    first_turn,
)
from tests.chat.test_messages import MessageJava, events, names
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import TODAY


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


@pytest.fixture(autouse=True)
def agent_key(monkeypatch):
    monkeypatch.setenv("AGENT_STATE_KEY", KEY)
    get_settings.cache_clear()


def read_then_card() -> ContinueAgent:
    agent = ContinueAgent(READ, [READ])
    agent.follows = ((HEALTH, WEIGHT_RAW),)
    return agent


def test_pending을_주는_READ_뒤_카드는_남은_일을_지금_답하지_않게_해야_한다(client, java):
    agent = read_then_card()
    use_reader(client, FakeToolReader([{"schdlSn": 5}]))

    _, done = first_turn(client, java, agent)

    shown = agent.results[1]
    assert "실행 결과를 받은 뒤 이어서" in shown
    assert "지금 답하지 않는다" in shown
    assert done["pending"] is not None


def test_단순_명령의_READ_뒤_카드는_지금처럼_실행_안내만이어야_한다(client, java):
    agent = read_then_card()
    use_reader(client, FakeToolReader([{"schdlSn": 5}]))

    first_turn(client, java, agent, SIMPLE)

    shown = agent.results[1]
    assert "이 턴에 실행된다" in shown
    assert "이어서" not in shown


def test_이어_가기에서_실행_전_READ는_다시_읽으라고_표시하고_다시_읽어야_한다(client, java):
    agent = read_then_card()
    agent.follows = ((HEALTH, WEIGHT_RAW),)
    reader = use_reader(client, FakeToolReader([{"schdlSn": 5}]))
    room, done = first_turn(client, java, agent)
    agent.follows = ()
    before = len(reader.calls)

    res = cont(client, room, done["pending"]["agentToken"], [{"tool": HEALTH, "status": "DONE"}])
    evs = events(res)

    notes = agent.resumes[0]
    stale = rules.AGENT_STALE_READ_NOTE.format(tool=READ[0])
    assert stale in notes
    assert f"읽기 {READ[0]} 결과:\n" not in notes
    assert "step" in names(evs)
    assert len(reader.calls) > before


def test_실행하지_않았으면_READ_결과를_그대로_둬야_한다(client, java):
    agent = read_then_card()
    use_reader(client, FakeToolReader([{"schdlSn": 5}]))
    fixed = {**WEIGHT_RAW, "rcd_nvl": 4.3}
    agent.resumed = [(HEALTH, fixed)]
    room, done = first_turn(client, java, agent)

    results = [{"tool": HEALTH, "status": "FAILED", "errors": [{"field": "rcdNvl"}]}]
    cont(client, room, done["pending"]["agentToken"], results)

    assert f"읽기 {READ[0]} 결과:\n" in agent.resumes[0]


def test_없는_방이면_토큰보다_먼저_404여야_한다(client, java):
    room, done = first_turn(client, java, ContinueAgent((HEALTH, WEIGHT_RAW)))

    res = cont(client, 9999, done["pending"]["agentToken"], [{"tool": HEALTH, "status": "DONE"}])

    assert res.status_code == 404


def test_내_방이면_고친_토큰은_400이어야_한다(client, java):
    room, done = first_turn(client, java, ContinueAgent((HEALTH, WEIGHT_RAW)))

    res = cont(client, room, "abc.def", [{"tool": HEALTH, "status": "DONE"}])

    assert res.status_code == 400
