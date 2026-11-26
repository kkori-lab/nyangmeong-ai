"""에이전트 ④ (SCR-AIM-004, 2026-11-26 추가 요청) : 같은 쓰기 도구 여러 번·pending 줄이기
- 새 명령에서 같은 쓰기 도구를 값만 달리 다시 고르면 쓰기 동사 수까지 카드를 같이 냄
- done.pending은 쓰기 뒤 묻는 말이 있거나 실행 안 한 쓰기가 남았을 때만"""

import pytest

from app.chat import rules
from app.core.config import get_settings
from tests.chat.test_action import send
from tests.chat.test_action_multi import HEALTH, WEIGHT_RAW, SequenceAgent, done_of
from tests.chat.test_messages import MessageJava
from tests.chat.test_register import CHOCO, TODAY
from tests.chat.test_tools import room_of, use_agent

KEY = "test-agent-key"
TWO_RECORDS = "초코 오늘 8시 반 체중 4.2kg 기록하고 산책 30분도 기록해 줘"
WALK_RAW = {
    "daily_rcd_idct_cd": "HLTC0018",
    "rcd_ymd": TODAY.isoformat(),
    "rcd_tm": "08:30",
    "rcd_nvl": 30,
}


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


def test_같은_도구를_값만_달리_두_번_말하면_첫_턴에_카드_두_장을_실행해야_한다(client, java):
    # Arrange
    use_agent(client, SequenceAgent((HEALTH, WEIGHT_RAW), (HEALTH, WALK_RAW)))
    room = room_of(client, java, pet_sn=CHOCO)

    # Act
    done = done_of(send(client, room, TWO_RECORDS))

    # Assert
    assert [card["tool"] for card in done["actions"]] == [HEALTH, HEALTH]
    assert [card["input"]["dailyRcdIdctCd"] for card in done["actions"]] == [
        "HLTC0014",
        "HLTC0018",
    ]
    assert done["execute"] is True
    assert done["pending"] is None


def test_쓰기_동사가_하나면_같은_도구를_값만_달리_다시_골라도_카드는_하나여야_한다(client, java):
    # Arrange
    use_agent(client, SequenceAgent((HEALTH, WEIGHT_RAW), (HEALTH, WALK_RAW)))
    room = room_of(client, java, pet_sn=CHOCO)

    # Act
    done = done_of(send(client, room, "초코 오늘 8시 반 체중 4.2kg이랑 산책 30분 기록해 줘"))

    # Assert
    assert [card["tool"] for card in done["actions"]] == [HEALTH]


def test_같은_도구를_같은_값으로_다시_고르면_카드는_하나여야_한다(client, java):
    # Arrange
    use_agent(client, SequenceAgent((HEALTH, WEIGHT_RAW), (HEALTH, WEIGHT_RAW)))
    room = room_of(client, java, pet_sn=CHOCO)

    # Act
    done = done_of(send(client, room, TWO_RECORDS))

    # Assert
    assert [card["tool"] for card in done["actions"]] == [HEALTH]


def test_쓰기가_남았는데_카드가_하나면_pending을_줘야_한다(client, java):
    # Arrange : 두 번째 고르기에서 도구 없음
    use_agent(client, SequenceAgent((HEALTH, WEIGHT_RAW)))
    room = room_of(client, java, pet_sn=CHOCO)

    # Act
    done = done_of(send(client, room, TWO_RECORDS))

    # Assert
    assert [card["tool"] for card in done["actions"]] == [HEALTH]
    assert done["execute"] is True
    assert done["pending"]["cards"] == 1


@pytest.mark.parametrize(
    ("text", "executed", "pending"),
    [
        (TWO_RECORDS, 2, False),
        (TWO_RECORDS, 1, True),
        ("코코 오늘 체중 4.2kg 기록하고 지난주보다 늘었는지 알려 줘", 1, True),
        ("코코 오늘 체중 4.2kg 기록하고 이번 주 일정 보여 줘", 1, True),
        (
            "코코 다음 주 화요일 오후 3시 병원 일정 잡고 그 일정 이름을 정기 검진으로 바꿔 줘",
            1,
            True,
        ),
        (
            "코코 다음 주 화요일 오후 3시 병원 일정 잡고 그 일정 이름을 정기 검진으로 바꿔 줘",
            2,
            False,
        ),
        ("검진기록 만들고 수치도 넣어 줘", 1, True),
        ("코코 오늘 산책 30분 기록해 줘", 1, False),
    ],
)
def test_묻는_말이_있거나_실행_안_한_쓰기가_남았을_때만_pending이어야_한다(text, executed, pending):
    assert rules.agent_pending(text, executed) is pending


@pytest.mark.parametrize(
    ("text", "count"),
    [
        (TWO_RECORDS, 2),
        ("코코 다음 주 화요일 오후 3시 병원 일정 잡고 그 일정 이름을 정기 검진으로 바꿔 줘", 2),
        ("코코 오늘 체중 4.2kg 기록하고 지난주보다 늘었는지 알려 줘", 1),
        ("코코 오늘 산책 30분 기록해 줘", 1),
    ],
)
def test_쓰기_동사_수는_잡고를_포함해_세야_한다(text, count):
    assert rules.write_count(text) == count
