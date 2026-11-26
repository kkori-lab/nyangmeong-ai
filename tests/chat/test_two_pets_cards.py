"""두 마리 이름을 한 메시지에 (SCR-AIM-012, FN-AIM-012-04 보강, 2026-11-23)
- 반려동물 칸이 있고 번호 칸이 없는 새 등록 카드는 문장의 다른 이름마다 같은 값의 카드를 한 장씩
- 모두 3장을 넘으면 나누지 않고 한 장 + 말한 아이들 칩
- 고치기 : 같은 도구 카드가 여럿이면 이름이 나온 아이의 카드만, 이름이 없으면 모두"""

import pytest

from app.chat import rules, tools
from app.chat.repository import PetInfo
from app.chat.service import ACTION_EXECUTE_MESSAGE, _pet_groups, named_pets
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_action import WEIGHT, send
from tests.chat.test_action_multi import done_of, returned, send_actions
from tests.chat.test_messages import MessageJava
from tests.chat.test_register import TODAY
from tests.chat.test_tools import room_of, use_agent

HEALTH = "draft_daily_health_record"
CHOCO, BOM, NURI, DOG, CAT = 1, 21, 22, 11, 12
RAW = {"daily_rcd_idct_cd": WEIGHT, "rcd_ymd": TODAY.isoformat(), "rcd_tm": "08:00", "rcd_nvl": 30}


def pet(sn: int, nm: str, se: str, vrty: str) -> dict:
    return {"petSn": sn, "petNm": nm, "careArtclNms": [], "petSeNm": se, "vrtyNm": vrty}


@pytest.fixture
def java() -> MessageJava:
    java = MessageJava()
    java.pets = [
        pet(CHOCO, "초코", "강아지", "푸들"),
        pet(BOM, "봄이", "강아지", "말티즈"),
        pet(NURI, "누리", "고양이", "코숏"),
        pet(DOG, "까미", "강아지", "진돗개"),
        pet(CAT, "까미", "고양이", "페르시안"),
    ]
    return java


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


def two_cards(client, java) -> tuple[int, dict]:
    use_agent(client, FakeToolAgent(HEALTH, RAW))
    room = room_of(client, java)
    return room, done_of(send(client, room, "오늘 아침 8시 봄이랑 누리 체중 30 기록할까?"))


def test_다른_이름이_둘이면_이름마다_같은_값의_카드를_한_장씩_줘야_한다(client, java):
    _, done = two_cards(client, java)

    cards = done["actions"]
    assert [card["input"]["petSn"] for card in cards] == [BOM, NURI]
    assert [card["petNm"] for card in cards] == ["봄이", "누리"]
    assert [card["input"]["rcdNvl"] for card in cards] == [30, 30]
    assert all(card["missing"] == [] for card in cards)
    assert done["action"] == cards[0]
    lines = done["message"]["cnvrsCn"].split("\n")
    assert lines[1].startswith("1. 봄이 건강 일지 기록 — ")
    assert lines[2].startswith("2. 누리 건강 일지 기록 — ")


def test_이름이_넷이면_나누지_않고_한_장에_말한_아이들_칩이어야_한다(client, java):
    use_agent(client, FakeToolAgent(HEALTH, RAW))
    room = room_of(client, java)

    done = done_of(send(client, room, "오늘 아침 8시 초코 봄이 누리 까미 체중 30 기록해줘"))

    assert len(done["actions"]) == 1
    card = done["action"]
    assert card["missing"] == ["petSn"]
    assert [choice["petSn"] for choice in card["petChoices"]] == [CHOCO, BOM, NURI, DOG, CAT]


def test_한쪽_이름이_같은_이름_둘이면_그_카드만_칩이어야_한다(client, java):
    use_agent(client, FakeToolAgent(HEALTH, RAW))
    room = room_of(client, java)

    done = done_of(send(client, room, "오늘 아침 8시 봄이랑 까미 체중 30 기록해줘"))

    first, second = done["actions"]
    assert first["input"]["petSn"] == BOM
    assert second["missing"] == ["petSn"]
    assert [choice["petSn"] for choice in second["petChoices"]] == [DOG, CAT]
    assert done["message"]["cnvrsCn"].endswith(
        "2번: 까미가 둘이에요. 칩에서 고르거나 '강아지 까미'처럼 알려 주세요."
    )


def test_확인_말이면_나눈_카드_모두_실행을_지시해야_한다(client, java):
    room, done = two_cards(client, java)
    use_agent(client, FakeToolAgent(fail=True))

    confirm = done_of(send_actions(client, room, "등록해 줘", returned(done)))

    assert confirm["execute"] is True
    assert confirm["message"]["cnvrsCn"] == ACTION_EXECUTE_MESSAGE
    assert [card["input"]["petSn"] for card in confirm["actions"]] == [BOM, NURI]


def test_이름을_말해_고치면_그_아이의_카드만_바뀌어야_한다(client, java):
    room, done = two_cards(client, java)
    use_agent(client, FakeToolAgent(HEALTH, {"rcd_nvl": 40}))

    fixed = done_of(send_actions(client, room, "누리는 40이야", returned(done)))

    cards = fixed["actions"]
    assert [card["input"]["petSn"] for card in cards] == [BOM, NURI]
    assert [card["input"]["rcdNvl"] for card in cards] == [30, 40]
    assert [card["input"]["rcdDt"] for card in cards] == [f"{TODAY.isoformat()}T08:00:00"] * 2


def test_이름_없이_고치면_같은_도구_카드_모두_바뀌어야_한다(client, java):
    room, done = two_cards(client, java)
    use_agent(client, FakeToolAgent(HEALTH, {"rcd_nvl": 40}))

    fixed = done_of(send_actions(client, room, "둘 다 40이야", returned(done)))

    cards = fixed["actions"]
    assert [card["input"]["petSn"] for card in cards] == [BOM, NURI]
    assert [card["input"]["rcdNvl"] for card in cards] == [40, 40]


def test_수정_카드는_이름이_둘이어도_나누지_않아야_한다(client, java):
    use_agent(client, FakeToolAgent("draft_pet_update", {"pet_nm": "봄순이"}))
    room = room_of(client, java)

    done = done_of(send(client, room, "봄이랑 누리 이름 봄순이로 바꿔줘"))

    assert len(done["actions"]) == 1


def test_번호_칸이_있는_등록_도구는_나누지_않아야_한다(client, java):
    # 케어 완료 체크처럼 번호가 그 아이의 기록을 가리키면 나누면 남의 번호가 된다
    pets = [PetInfo(p["petSn"], p["petNm"]) for p in java.pets]
    named = named_pets(pets, "봄이랑 누리 양치 체크해줘")
    assert len(_pet_groups(tools.card_entry(HEALTH), named)) == 2
    assert _pet_groups(tools.card_entry("draft_care_completion"), named) == []
    assert _pet_groups(tools.card_entry("draft_pet_update"), named) == []
