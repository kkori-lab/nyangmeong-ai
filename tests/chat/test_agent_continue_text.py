"""에이전트 ③ 검증 1회차 고침 : 바로 실행한 쓰기를 "아직 저장 전"이라고 안내하지 않기
- READ 뒤 카드가 이어 가기 꼴 명령으로 바로 실행되면 LLM에 주는 카드 글도 실행 안내
  (확인 말 안내 없음)
- 이어 가기에서 원래 문장의 쓰기를 다 실행했는데 같은 도구를 값만 바꿔 다시 고르면 이미 실행한 일
- 진행 기록은 '실행 완료'를 저장된 것으로 말하게 함"""

import pytest

from app.chat import rules
from app.core.config import get_settings
from tests.chat.test_action_multi import HEALTH, WEIGHT_RAW, done_of
from tests.chat.test_agent_continue import KEY, READ, ContinueAgent, cont, first_turn
from tests.chat.test_messages import MessageJava
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import TODAY

CHANGED = {**WEIGHT_RAW, "rcd_nvl": 4.5}


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


def test_READ_뒤_바로_실행하는_카드는_확인_말_대신_실행_안내를_LLM에_줘야_한다(client, java):
    agent = ContinueAgent(READ)
    agent.follows = ((HEALTH, WEIGHT_RAW),)
    use_reader(client, FakeToolReader([{"schdlSn": 5}]))

    _, done = first_turn(client, java, agent)

    shown = agent.results[1]
    assert "이 턴에 실행된다" in shown
    assert "'등록해 줘'" not in shown
    assert done["execute"] is True
    assert done["pending"] is not None


def test_키가_없으면_READ_뒤_카드는_지금처럼_확인_말_안내여야_한다(client, java, monkeypatch):
    monkeypatch.setenv("AGENT_STATE_KEY", "")
    get_settings.cache_clear()
    agent = ContinueAgent(READ)
    agent.follows = ((HEALTH, WEIGHT_RAW),)
    use_reader(client, FakeToolReader([{"schdlSn": 5}]))

    _, done = first_turn(client, java, agent)

    assert "'등록해 줘'" in agent.results[1]
    assert done["execute"] is False


def test_이어_가기에서_READ_뒤_같은_도구를_값만_바꿔_고르면_이미_실행한_일이어야_한다(client, java):
    agent = ContinueAgent((HEALTH, WEIGHT_RAW), [READ])
    agent.follows = ((HEALTH, CHANGED),)
    use_reader(client, FakeToolReader([{"schdlSn": 5}]))
    room, done = first_turn(client, java, agent)

    done2 = done_of(
        cont(client, room, done["pending"]["agentToken"], [{"tool": HEALTH, "status": "DONE"}])
    )

    assert done2["action"] is None
    assert done2["execute"] is False
    assert rules.AGENT_ALREADY_DONE in agent.results


def test_이어_가기_첫_고르기에서_같은_도구를_값만_바꿔도_이미_실행한_일이어야_한다(client, java):
    agent = ContinueAgent((HEALTH, WEIGHT_RAW), [(HEALTH, CHANGED)])
    room, done = first_turn(client, java, agent)

    done2 = done_of(
        cont(client, room, done["pending"]["agentToken"], [{"tool": HEALTH, "status": "DONE"}])
    )

    assert done2["action"] is None
    assert rules.AGENT_ALREADY_DONE in agent.results


def test_칸_오류_고치기는_같은_도구여도_이미_실행한_일이_아니어야_한다(client, java):
    agent = ContinueAgent((HEALTH, WEIGHT_RAW), [(HEALTH, CHANGED)])
    room, done = first_turn(client, java, agent)

    results = [{"tool": HEALTH, "status": "FAILED", "errors": [{"field": "rcdNvl"}]}]
    done2 = done_of(cont(client, room, done["pending"]["agentToken"], results))

    assert done2["action"]["tool"] == HEALTH


def test_진행_기록은_실행_완료를_저장된_일로_말하게_해야_한다(client, java):
    agent = ContinueAgent((HEALTH, WEIGHT_RAW), [READ])
    use_reader(client, FakeToolReader([{"schdlSn": 5}]))
    room, done = first_turn(client, java, agent)

    cont(client, room, done["pending"]["agentToken"], [{"tool": HEALTH, "status": "DONE"}])

    notes = agent.resumes[0]
    assert notes.endswith(rules.AGENT_NOTES_TAIL)
    assert "이미 저장된 것" in notes
    assert "저장 전이라거나" in notes
