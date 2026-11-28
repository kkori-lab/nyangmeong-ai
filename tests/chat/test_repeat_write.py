"""frontend-dc ③ (2026-11-27) : 같은 쓰기를 반복하면 바로 실행하지 않고 확인 카드로
- 이력(최근 턴) AI 메시지에 같은 결과 글(✔, 시각만 다름)이 있으면 execute·pending 없음,
  저장 글 앞줄 반복 안내
- 값이 다르거나 같은 글이 이력 밖이면 지금처럼 바로 실행
- 확인 말로 돌려받은 카드는 실행, READ 뒤 카드 길도 같은 판정"""

import pytest

from app.chat import rules
from app.chat.schemas import ROLE_AI, ROLE_USER
from app.core.config import get_settings
from tests.chat.fakes import FakeCardReplyAgent, FakeToolAgent
from tests.chat.test_action import action_result, send
from tests.chat.test_action_multi import HEALTH, WEIGHT_RAW, done_of, returned, send_actions
from tests.chat.test_agent_continue import KEY, READ, SIMPLE, ContinueAgent
from tests.chat.test_messages import MessageJava
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import CHOCO, TODAY
from tests.chat.test_tools import room_of, use_agent

SAID_MORE = "초코 오늘 8시 반 체중 4.2kg 기록하고 늘었는지 알려 줘"


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


def _saved_once(client, java, raw: dict = WEIGHT_RAW) -> int:
    # 첫 턴 바로 실행 -> React가 실행하고 action-result DONE으로 "✔ …" 저장
    use_agent(client, FakeToolAgent(HEALTH, raw))
    room = room_of(client, java, pet_sn=CHOCO)
    done = done_of(send(client, room, SIMPLE))
    assert done["execute"] is True
    card = done["action"]
    assert action_result(client, room, card["tool"], "DONE", card["input"]).status_code == 201
    assert java.rooms[room]["messages"][-1]["cnvrsCn"].startswith("✔ ")
    return room


def _again(client, room: int, raw: dict = WEIGHT_RAW, text: str = SIMPLE) -> dict:
    use_agent(client, FakeToolAgent(HEALTH, raw))
    return done_of(send(client, room, text))


def test_이력에_같은_결과_글이_있으면_바로_실행하지_않고_확인_카드여야_한다(client, java):
    room = _saved_once(client, java)

    done = _again(client, room)

    assert done["execute"] is False
    assert done.get("pending") is None
    assert done["action"]["tool"] == HEALTH
    message = done["message"]["cnvrsCn"]
    assert message.startswith(rules.WRITE_REPEAT_NOTICE)
    assert message.count("'등록해 줘'") == 1


def test_시각만_달라도_같은_기록으로_봐야_한다(client, java):
    room = _saved_once(client, java)

    done = _again(client, room, {**WEIGHT_RAW, "rcd_tm": "09:10"})

    assert done["execute"] is False


def test_값이_다르면_그대로_바로_실행해야_한다(client, java):
    room = _saved_once(client, java)

    done = _again(client, room, {**WEIGHT_RAW, "rcd_nvl": 4.5})

    assert done["execute"] is True


def test_같은_결과_글이_이력_밖이면_바로_실행해야_한다(client, java):
    room = _saved_once(client, java)
    messages = java.rooms[room]["messages"]
    for no in range(16):
        for role, cn in ((ROLE_USER, f"질문 {no}"), (ROLE_AI, f"답 {no}")):
            messages.append(
                {
                    "aiCnvrsMsgSn": 9000 + len(messages),
                    "roleCd": role,
                    "cnvrsCn": cn,
                    "msgSeq": len(messages) + 1,
                    "regDt": "2026-10-25T10:00:00",
                    "cmptnYn": True,
                }
            )

    done = _again(client, room)

    assert done["execute"] is True


def test_반복_확인_카드에_확인_말이면_실행해야_한다(client, java):
    room = _saved_once(client, java)
    done = _again(client, room)
    use_agent(client, FakeCardReplyAgent())

    confirmed = done_of(send_actions(client, room, "등록해 줘", returned(done)))

    assert confirmed["execute"] is True


def test_이어_가기_꼴_명령도_반복이면_pending_없이_확인_카드여야_한다(client, java):
    room = _saved_once(client, java)

    done = _again(client, room, text=SAID_MORE)

    assert done["execute"] is False
    assert done.get("pending") is None


def test_READ_뒤_카드_길도_반복이면_확인_카드로_알려야_한다(client, java, caplog):
    caplog.set_level("INFO")
    room = _saved_once(client, java)
    agent = ContinueAgent(READ)
    agent.follows = ((HEALTH, WEIGHT_RAW),)
    use_reader(client, FakeToolReader([{"schdlSn": 5}]))
    use_agent(client, agent)

    done = done_of(send(client, room, SIMPLE))

    shown = agent.results[1]
    assert done["execute"] is False
    assert done["action"]["tool"] == HEALTH
    assert rules.WRITE_REPEAT_SHOWN in shown
    assert "이 턴에 실행된다" not in shown
    assert "write_repeat" in caplog.text
