"""없는 반려동물 안내 문구 조사 (SCR-AIM-004·012, 2026-11-27 추가 요청)
- 문장에 쓴 형태 : LLM이 "구름"을 넣어도 문장이 "구름이 …"면 "'구름이'라는"
- 받침 조사 : 마지막 이름이 받침으로 끝나면 "'구름'이라는"
"""

import pytest

from app.chat import rules
from app.chat.repository import PetInfo
from app.chat.service import (
    CARD_PET_UNKNOWN_NOTE,
    PET_UNKNOWN,
    READ_PET_UNKNOWN_NOTE,
    pet_unknown_text,
    unknown_pets,
)
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_action import send as send_action
from tests.chat.test_action_multi import HEALTH, WEIGHT_RAW, SequenceAgent
from tests.chat.test_messages import MessageJava, deltas, events, send
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import CHOCO, MUNG, TODAY
from tests.chat.test_tools import room_of, use_agent

PETS = "초코, 뭉치"


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


@pytest.mark.parametrize(
    ("said", "text", "unknown"),
    [
        (["구름"], "구름이 체중 기록해 줘", ["구름이"]),
        (["구름"], "구름은 체중 기록해 줘", ["구름"]),
        (["보리"], "보리이 체중 기록해 줘", ["보리"]),
        (["구름", "구름이"], "구름이 체중 기록해 줘", ["구름이"]),
    ],
)
def test_받침_있는_이름은_문장에_쓴_이_붙은_형태로_돌려줘야_한다(said, text, unknown):
    # Arrange
    pets = [PetInfo(CHOCO, "초코"), PetInfo(MUNG, "뭉치")]

    # Act
    result = unknown_pets(said, pets, text)

    # Assert
    assert result == unknown


@pytest.mark.parametrize(
    ("template", "unknown", "values", "expected"),
    [
        (PET_UNKNOWN, ["구름"], {"pets": PETS}, "'구름'이라는 아이는 등록돼 있지 않아요."),
        (PET_UNKNOWN, ["구름이"], {"pets": PETS}, "'구름이'라는 아이는 등록돼 있지 않아요."),
        (PET_UNKNOWN, ["보리", "구름"], {"pets": PETS}, "'보리', '구름'이라는 아이는"),
        (PET_UNKNOWN, ["구름", "보리"], {"pets": PETS}, "'구름', '보리'라는 아이는"),
        (READ_PET_UNKNOWN_NOTE, ["구름"], {}, "'구름'이라는 아이는 등록돼 있지 않음"),
        (CARD_PET_UNKNOWN_NOTE, ["구름"], {"pets": PETS}, "'구름'이라는 아이는 등록돼 있지 않아"),
    ],
)
def test_마지막_이름이_받침으로_끝나면_이라는을_붙여야_한다(template, unknown, values, expected):
    # Act
    text = pet_unknown_text(template, unknown, **values)

    # Assert
    assert text.startswith(expected)


def test_LLM이_이를_뺀_이름을_넣어도_쓰기_안내는_문장에_쓴_형태여야_한다(client, java):
    # Arrange
    use_agent(client, SequenceAgent((HEALTH, WEIGHT_RAW | {"pet_name": "구름"})))
    room = room_of(client, java)

    # Act
    evs = events(send_action(client, room, "구름이 오늘 8시 반 체중 4.2kg 기록해 줘"))

    # Assert
    assert deltas(evs) == PET_UNKNOWN.format(names="구름이", pets=PETS)


def test_문장에도_이가_없으면_쓰기_안내는_이라는이어야_한다(client, java):
    # Arrange
    use_agent(client, SequenceAgent((HEALTH, WEIGHT_RAW | {"pet_name": "구름"})))
    room = room_of(client, java)

    # Act
    evs = events(send_action(client, room, "구름 오늘 8시 반 체중 4.2kg 기록해 줘"))

    # Assert
    assert deltas(evs).startswith("'구름'이라는 아이는 등록돼 있지 않아요. 초코, 뭉치 중에서")


def test_읽기에서_일부만_없으면_결과_첫_줄이_받침에_맞아야_한다(client, java):
    # Arrange
    agent = use_agent(client, FakeToolAgent("get_health_indicators", {"pet_name": "구름, 뭉치"}))
    use_reader(client, FakeToolReader())
    room = room_of(client, java)

    # Act
    events(send(client, room, "구름 뭉치 요즘 체중 어때?"))

    # Assert
    assert agent.results[0].startswith("'구름'이라는 아이는 등록돼 있지 않음")
