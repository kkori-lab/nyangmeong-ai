"""frontend-dc ② (2026-11-27) : 바로 실행된 턴의 답에 확인 말을 안내하지 않기
- 답변 시스템 규칙 : '이 턴에 실행된다'고 적힌 카드는 확인 말 안내 대상이 아님
- 바로 실행 카드의 tool_result : 카드에서 확인하라거나 확인 말을 해 달라고 하지 않게
- 그래도 답이 확인 말을 안내하면 턴 기록 태그 run_confirm_text(바로 실행된 턴만)"""

import pytest

from app.chat import rules
from app.chat.clients import tool_system
from app.core.config import get_settings
from tests.chat.test_action_multi import HEALTH, WEIGHT_RAW
from tests.chat.test_agent_continue import KEY, READ, SIMPLE, ContinueAgent, first_turn
from tests.chat.test_messages import MessageJava
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import TODAY
from tests.chat.test_turn_log import turn_lines

FORBID = "카드에서 확인하라거나 확인 말을 해 달라고 하지 않는다"
ASKING = "체중 4.2kg 카드를 만들었어요. 카드에서 확인하신 뒤 '등록해 줘'라고 말해 주세요."


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


def test_답변_시스템_규칙에_바로_실행_카드는_확인_말_안내_대상이_아니라고_있어야_한다():
    assert "'이 턴에 실행된다'고 적힌 카드는 확인 말을 안내하지 않는다" in tool_system()


@pytest.mark.parametrize("text", [SIMPLE, "초코 오늘 8시 반 체중 4.2kg 기록하고 늘었는지 알려 줘"])
def test_READ_뒤_바로_실행_카드의_도구_결과는_확인_말을_금지해야_한다(client, java, text):
    agent = ContinueAgent(READ)
    agent.follows = ((HEALTH, WEIGHT_RAW),)
    use_reader(client, FakeToolReader([{"schdlSn": 5}]))

    _, done = first_turn(client, java, agent, text)

    shown = agent.results[1]
    assert done["execute"] is True
    assert "이 턴에 실행된다" in shown
    assert FORBID in shown
    assert "'등록해 줘'라고 말해" not in shown


@pytest.mark.parametrize(
    ("text", "found"),
    [
        (ASKING, True),
        ("맞으면 '수정해 줘'라고 말해 주세요.", True),
        ("'삭제해 줘' 라고 해 주세요.", True),
        ("체중 4.2kg 등록할게요.", False),
        ("등록해 줘라고 하셨어요", False),
    ],
)
def test_확인_말_안내_꼴을_찾아야_한다(text, found):
    assert rules.asks_confirm(text) is found


def test_바로_실행된_턴의_답이_확인_말을_안내하면_태그를_남겨야_한다(client, java, caplog):
    caplog.set_level("INFO")
    agent = ContinueAgent(READ, answer_chunks=(ASKING,))
    agent.follows = ((HEALTH, WEIGHT_RAW),)
    use_reader(client, FakeToolReader([{"schdlSn": 5}]))

    _, done = first_turn(client, java, agent, SIMPLE)

    assert done["execute"] is True
    assert "run_confirm_text" in turn_lines(caplog)[-1]["tags"]


def test_확인_카드_턴의_확인_말_안내는_태그가_없어야_한다(client, java, caplog):
    caplog.set_level("INFO")
    agent = ContinueAgent(READ, answer_chunks=(ASKING,))
    agent.follows = ((HEALTH, WEIGHT_RAW),)
    use_reader(client, FakeToolReader([{"schdlSn": 5}]))

    _, done = first_turn(client, java, agent, "초코 오늘 8시 반 체중 4.2kg")

    assert done["execute"] is False
    assert done["action"] is not None
    assert "run_confirm_text" not in turn_lines(caplog)[-1]["tags"]
