"""문장에 쓴 반려동물 이름이 목록에 없을 때 (SCR-AIM-004·012, 2026-11-26 추가-2)
- 쓰기 : 카드 없이 "'구름이'라는 아이는 등록돼 있지 않아요…" 안내 글
- 읽기 : 아는 이름이 하나도 없으면 Java READ 없이 안내, 일부만 없으면 있는 아이만 읽고 결과에 표시
- pet_name은 Java 카드 input에 싣지 않는다. 문장에 없는 이름(LLM이 지어냄)은 무시"""

import pytest

from app.chat import catalog, rules
from app.chat.repository import PetInfo
from app.chat.service import PET_UNKNOWN, READ_PET_UNKNOWN_NOTE, unknown_pets
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_action import send as send_action
from tests.chat.test_action_multi import HEALTH, WEIGHT_RAW, SequenceAgent, done_of
from tests.chat.test_messages import MessageJava, deltas, events, send
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import CHOCO, MUNG, TODAY
from tests.chat.test_tools import room_of, use_agent

WALK_RAW = {
    "daily_rcd_idct_cd": "HLTC0018",
    "rcd_ymd": TODAY.isoformat(),
    "rcd_tm": "08:30",
    "rcd_nvl": 30,
}
CLOUD = "구름이 오늘 8시 반 체중 4.2kg 기록하고 산책 30분도 기록해 줘"


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


def _unknown_message(name: str) -> str:
    return PET_UNKNOWN.format(names=name, pets="초코, 뭉치")


# 쓰기


def test_목록에_없는_이름의_쓰기_카드는_카드_없이_없는_아이라고_안내해야_한다(client, java):
    # Arrange
    agent = SequenceAgent(
        (HEALTH, WEIGHT_RAW | {"pet_name": "구름이"}),
        (HEALTH, WALK_RAW | {"pet_name": "구름이"}),
    )
    use_agent(client, agent)
    room = room_of(client, java)

    # Act
    evs = events(send_action(client, room, CLOUD))

    # Assert
    assert evs[0][1]["kind"] == "SEARCH"
    done = evs[-1][1]
    assert done["action"] is None
    assert done["actions"] in (None, [])
    assert deltas(evs) == _unknown_message("구름이")
    assert done["message"]["cnvrsCn"] == _unknown_message("구름이")


def test_목록에_있는_이름이면_카드를_주고_pet_name은_input에_없어야_한다(client, java):
    # Arrange
    use_agent(client, SequenceAgent((HEALTH, WEIGHT_RAW | {"pet_name": "초코"})))
    room = room_of(client, java)

    # Act
    done = done_of(send_action(client, room, "초코 오늘 8시 반 체중 4.2kg 기록해 줘"))

    # Assert
    assert done["action"]["tool"] == HEALTH
    assert done["action"]["input"]["petSn"] == CHOCO
    assert "pet_name" not in done["action"]["input"]
    assert "petName" not in done["action"]["input"]


def test_문장에_없는_pet_name은_지어낸_이름이라_무시해야_한다(client, java):
    # Arrange : 대화방 반려동물 이름을 LLM이 넣음
    use_agent(client, SequenceAgent((HEALTH, WEIGHT_RAW | {"pet_name": "구름이"})))
    room = room_of(client, java, pet_sn=CHOCO)

    # Act
    done = done_of(send_action(client, room, "오늘 8시 반 체중 4.2kg 기록해 줘"))

    # Assert
    assert done["action"]["tool"] == HEALTH
    assert done["action"]["input"]["petSn"] == CHOCO


# 읽기


def test_읽기에서_아는_이름이_없으면_Java를_부르지_않고_없는_아이라고_안내해야_한다(client, java):
    # Arrange
    agent = use_agent(client, FakeToolAgent("get_health_indicators", {"pet_name": "구름이"}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java)

    # Act
    evs = events(send(client, room, "구름이 요즘 체중 어때?"))

    # Assert
    assert evs[0][1]["kind"] == "SEARCH"
    assert reader.calls == []
    assert agent.results == []
    assert deltas(evs) == _unknown_message("구름이")


def test_읽기에서_일부만_없으면_있는_아이만_읽고_결과에_없는_아이를_적어야_한다(client, java):
    # Arrange
    agent = use_agent(client, FakeToolAgent("get_health_indicators", {"pet_name": "구름이, 뭉치"}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java)

    # Act
    events(send(client, room, "구름이랑 뭉치 요즘 체중 어때?"))

    # Assert
    assert reader.calls == [(f"/api/pets/{MUNG}/health-indicators", {})]
    assert agent.results[0].startswith(READ_PET_UNKNOWN_NOTE.format(names="구름이"))


# 이름 대조


@pytest.mark.parametrize(
    ("said", "text", "unknown"),
    [
        (["구름이"], "구름이 체중 기록해 줘", ["구름이"]),
        (["초코"], "초코 체중 기록해 줘", []),
        (["초코야"], "초코야 체중 기록해 줘", []),
        (["구름이"], "체중 기록해 줘", []),
        (["구름이", "뭉치"], "구름이랑 뭉치 체중", ["구름이"]),
        ([], "구름이 체중 기록해 줘", []),
    ],
)
def test_문장에_쓴_이름_중_목록에_없는_것만_골라야_한다(said, text, unknown):
    pets = [_pet(CHOCO, "초코"), _pet(MUNG, "뭉치")]

    assert unknown_pets(said, pets, text) == unknown


@pytest.mark.parametrize(
    ("raw", "names"),
    [
        ("구름이", ["구름이"]),
        ("구름이, 뭉치", ["구름이", "뭉치"]),
        ("구름이 랑 뭉치", ["구름이", "뭉치"]),
        ("", []),
        (None, []),
    ],
)
def test_pet_name_칸은_쉼표와_랑으로_나눠야_한다(raw, names):
    assert catalog.said_pet_names({catalog.PET_NAME: raw}) == names


def _pet(pet_sn: int, name: str) -> PetInfo:
    return PetInfo(pet_sn, name)
