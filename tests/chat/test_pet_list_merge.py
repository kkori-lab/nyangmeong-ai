"""SCR-AIM-004 READ 결과 …Cn 칸 싣기·반려동물 수정 카드 알레르기·질환·특징 합치기 (2026-11-25)"""

import pytest

from app.chat import rules
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_messages import MessageJava, events, send
from tests.chat.test_read_tools import FakeToolReader, payload, use_reader
from tests.chat.test_register import CHOCO, TODAY
from tests.chat.test_tools import room_of, use_agent

PET = {"petSn": CHOCO, "petNm": "초코", "algyCn": "새우", "dssCn": "슬개골", "chrcCn": "겁이 많음"}


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


def pet_card(client, java, raw: dict, text: str, reader: FakeToolReader) -> dict:
    use_agent(client, FakeToolAgent("draft_pet_update", raw))
    use_reader(client, reader)
    room = room_of(client, java, pet_sn=CHOCO)
    return events(send(client, room, text))[-1][1]["action"]


# READ 결과


def test_반려동물_상세의_알레르기_질환_특징을_LLM에_넘겨야_한다(client, java):
    agent = use_agent(client, FakeToolAgent("get_pet", {}))
    use_reader(client, FakeToolReader(PET))
    room = room_of(client, java, pet_sn=CHOCO)

    events(send(client, room, "초코 알레르기 있어?"))

    result = payload(agent.results[0])
    assert result["algyCn"] == "새우"
    assert result["dssCn"] == "슬개골"
    assert result["chrcCn"] == "겁이 많음"


def test_READ_결과_글은_내용_칸을_빼지_않고_날짜에는_요일을_붙여야_한다():
    data = {"memoCn": "밥을 남김", "rcdDt": "2026-11-01", "items": [{"algyCn": "닭고기"}]}

    text = rules.read_result_text(data)

    assert '"memoCn": "밥을 남김"' in text
    assert '"algyCn": "닭고기"' in text
    assert "2026-11-01 (일)" in text


# 수정 카드 합치기


def test_알레르기를_넣어_달라면_지금_알레르기에_더해_카드에_실어야_한다(client, java):
    reader = FakeToolReader(PET)

    action = pet_card(client, java, {"algy_cn": "닭고기"}, "알레르기에 닭고기 넣어 줘", reader)

    assert reader.calls == [(f"/api/pets/{CHOCO}", {})]
    assert action["input"] == {"petSn": CHOCO, "algyCn": "새우,닭고기"}


def test_알레르기를_빼_달라면_그_항목만_빼야_한다(client, java):
    pet = PET | {"algyCn": "새우,닭고기"}

    action = pet_card(client, java, {"algy_cn": "새우"}, "새우 알레르기 빼 줘", FakeToolReader(pet))

    assert action["input"] == {"petSn": CHOCO, "algyCn": "닭고기"}


def test_알레르기를_바꿔_달라면_Java를_읽지_않고_말한_값만_실어야_한다(client, java):
    reader = FakeToolReader(PET)

    action = pet_card(client, java, {"algy_cn": "닭고기"}, "알레르기를 닭고기로 바꿔 줘", reader)

    assert reader.calls == []
    assert action["input"] == {"petSn": CHOCO, "algyCn": "닭고기"}


def test_질환과_특징도_같은_규칙으로_합쳐야_한다(client, java):
    raw = {"dss_cn": "피부염", "chrc_cn": "산책을 좋아함"}

    text = "질환에 피부염, 특징에 산책을 좋아함 추가해 줘"

    action = pet_card(client, java, raw, text, FakeToolReader(PET))

    assert action["input"]["dssCn"] == "슬개골,피부염"
    assert action["input"]["chrcCn"] == "겁이 많음,산책을 좋아함"


def test_목록_칸이_없는_수정은_Java를_읽지_않아야_한다(client, java):
    reader = FakeToolReader(PET)

    action = pet_card(client, java, {"goal_bdwg": 4.0}, "목표 체중 4kg로 바꿔 줘", reader)

    assert reader.calls == []
    assert action["input"] == {"petSn": CHOCO, "goalBdwg": 4.0}


def test_지금_값을_읽지_못하면_말한_값만_실은_카드를_그대로_띄워야_한다(client, java):
    action = pet_card(
        client, java, {"algy_cn": "닭고기"}, "알레르기에 닭고기 넣어 줘", FakeToolReader(fail=True)
    )

    assert action["input"] == {"petSn": CHOCO, "algyCn": "닭고기"}


@pytest.mark.parametrize(
    ("current", "said", "mode", "expected"),
    [
        ("새우, 닭고기", "닭 고기,소고기", rules.LIST_ADD, "새우,닭고기,소고기"),
        ("새우,닭고기", "새우, 닭고기", rules.LIST_REMOVE, ""),
        (None, "새우", rules.LIST_ADD, "새우"),
        ("새우", "소고기", rules.LIST_REPLACE, "소고기"),
    ],
)
def test_목록_합치기는_띄어쓰기만_다른_항목을_같게_보아야_한다(current, said, mode, expected):
    assert rules.merge_list(current, said, mode) == expected


@pytest.mark.parametrize(
    ("text", "mode"),
    [
        ("알레르기에 닭고기 넣어 줘", rules.LIST_ADD),
        ("새우 알레르기 없어졌어 빼 줘", rules.LIST_REMOVE),
        ("알레르기를 닭고기로 바꿔 줘", rules.LIST_REPLACE),
        ("닭고기 알레르기도 있어", rules.LIST_ADD),
        ("알레르기 닭고기", rules.LIST_ADD),
    ],
)
def test_목록_고치기_말을_더하기_빼기_바꾸기로_나눠야_한다(text, mode):
    assert rules.list_edit_mode(text) == mode
