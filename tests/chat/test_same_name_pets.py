"""같은 이름 반려동물 구별 (SCR-AIM-012, FN-AIM-012-04 보강, 2026-11-23)
- register-context의 petSeNm·vrtyNm으로 문장 속 종·품종 말을 보고 좁힌다
- 못 정하면 칩을 같은 이름 아이들로만 줄이고 구별 예시로 되묻는다"""

import pytest

from app.chat import rules
from app.chat.clients import tool_system
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_action import WEIGHT, send
from tests.chat.test_action_multi import HOSPITAL, SequenceAgent
from tests.chat.test_messages import MessageJava, events
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import TODAY
from tests.chat.test_tools import room_of, use_agent

DOG = 11
CAT = 12


def pet(sn: int, nm: str, se: str, vrty: str) -> dict:
    return {"petSn": sn, "petNm": nm, "careArtclNms": [], "petSeNm": se, "vrtyNm": vrty}


@pytest.fixture
def java() -> MessageJava:
    java = MessageJava()
    java.pets = [
        pet(1, "초코", "강아지", "푸들"),
        pet(DOG, "까미", "강아지", "말티즈"),
        pet(CAT, "까미", "고양이", "코숏"),
    ]
    return java


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


def weight_agent() -> FakeToolAgent:
    args = {"daily_rcd_idct_cd": WEIGHT, "rcd_ymd": TODAY.isoformat(), "rcd_nvl": 4.2}
    return FakeToolAgent("draft_daily_health_record", args)


def test_종_말이_있으면_같은_이름_중_그_종의_아이로_정해야_한다(client, java):
    use_agent(client, weight_agent())
    room = room_of(client, java)

    action = events(send(client, room, "강아지 까미 오늘 체중 4.2kg 기록해줘"))[-1][1]["action"]

    assert action["input"]["petSn"] == DOG
    assert action["petNm"] == "까미"
    assert action["petChoices"] == []


@pytest.mark.parametrize("word", ["고양이", "냥이"])
def test_고양이_말로도_좁혀야_한다(client, java, word):
    use_agent(client, weight_agent())
    room = room_of(client, java)

    action = events(send(client, room, f"{word} 까미 오늘 체중 4.2kg 기록해줘"))[-1][1]["action"]

    assert action["input"]["petSn"] == CAT


def test_품종_이름이_있으면_그_아이로_정해야_한다(client, java):
    use_agent(client, weight_agent())
    room = room_of(client, java)

    action = events(send(client, room, "말티즈 까미 오늘 체중 4.2kg 기록해줘"))[-1][1]["action"]

    assert action["input"]["petSn"] == DOG


def test_못_정하면_칩을_같은_이름_아이들로만_보이고_구별_예시로_되물어야_한다(client, java):
    use_agent(client, weight_agent())
    room = room_of(client, java)

    evs = events(send(client, room, "까미 오늘 체중 4.2kg 기록해줘"))

    action = evs[-1][1]["action"]
    assert "petSn" not in action["input"]
    assert action["missing"] == ["petSn"]
    assert action["petChoices"] == [
        {"petSn": DOG, "petNm": "까미", "petSeNm": "강아지", "vrtyNm": "말티즈"},
        {"petSn": CAT, "petNm": "까미", "petSeNm": "고양이", "vrtyNm": "코숏"},
    ]
    text = evs[-1][1]["message"]["cnvrsCn"]
    assert text.endswith("까미가 둘이에요. 칩에서 고르거나 '강아지 까미'처럼 알려 주세요.")
    assert "비어 있어요" not in text


def test_다른_빈_칸이_있어도_어느_아이인지_먼저_묻고_나머지_빈_칸을_이어_물어야_한다(client, java):
    # 다른 날이라 기록 시각(rcdDt)도 빈 칸
    use_agent(
        client,
        FakeToolAgent(
            "draft_daily_health_record",
            {
                "daily_rcd_idct_cd": WEIGHT,
                "rcd_ymd": "2026-09-27",
                "rcd_nvl": 4.2,
            },
        ),
    )
    room = room_of(client, java)

    evs = events(send(client, room, "까미 그저께 체중 4.2kg 기록해줘"))

    action = evs[-1][1]["action"]
    assert action["missing"] == ["petSn", "rcdDt"]
    lines = evs[-1][1]["message"]["cnvrsCn"].split("\n")
    assert lines[-2] == "까미가 둘이에요. 칩에서 고르거나 '강아지 까미'처럼 알려 주세요."
    assert lines[-1].startswith("아직 ") and lines[-1].endswith(" 비어 있어요.")
    assert "반려동물" not in lines[-1]


def test_종이_같으면_품종으로_예시를_들어야_한다(client, java):
    java.pets[2] |= {"petSeNm": "강아지", "vrtyNm": "진돗개"}
    use_agent(client, weight_agent())
    room = room_of(client, java)

    evs = events(send(client, room, "까미 오늘 체중 4.2kg 기록해줘"))

    assert evs[-1][1]["message"]["cnvrsCn"].endswith("'말티즈 까미'처럼 알려 주세요.")


def test_칩_뒤_종을_말하면_돌려받은_카드의_반려동물이_정해져야_한다(client, java):
    use_agent(client, FakeToolAgent("draft_daily_health_record", {}))
    room = room_of(client, java)
    prior = {
        "tool": "draft_daily_health_record",
        "input": {"dailyRcdIdctCd": WEIGHT, "rcdDt": "2026-09-29T08:00:00", "rcdNvl": 4.2},
    }

    action = events(send(client, room, "강아지 까미", action=prior))[-1][1]["action"]

    assert action["input"]["petSn"] == DOG
    assert action["missing"] == []


def test_펫_태그_방이면_같은_이름이_걸려도_태그_아이로_정해야_한다(client, java):
    use_agent(client, weight_agent())
    room = room_of(client, java, pet_sn=DOG)

    action = events(send(client, room, "까미 오늘 체중 4.2kg 기록해줘"))[-1][1]["action"]

    assert action["input"]["petSn"] == DOG
    assert action["petChoices"] == []


def test_돌려받은_카드에_반려동물이_있으면_같은_이름이_걸려도_그_아이로_정해야_한다(client, java):
    use_agent(client, FakeToolAgent("draft_daily_health_record", {"rcd_nvl": 4.5}))
    room = room_of(client, java, pet_sn=DOG)
    prior = {
        "tool": "draft_daily_health_record",
        "input": {"petSn": CAT, "dailyRcdIdctCd": WEIGHT, "rcdDt": "2026-09-29T08:00:00"},
    }

    action = events(send(client, room, "까미 4.5kg이었어", action=prior))[-1][1]["action"]

    # 직전 카드(칩으로 고른 고양이 까미)가 펫 태그보다 먼저
    assert action["input"]["petSn"] == CAT
    assert action["missing"] == []


def test_태그_아이가_같은_이름_밖이면_칩을_보여야_한다(client, java):
    use_agent(client, weight_agent())
    room = room_of(client, java, pet_sn=1)

    action = events(send(client, room, "까미 오늘 체중 4.2kg 기록해줘"))[-1][1]["action"]

    assert action["missing"] == ["petSn"]
    assert [choice["petSn"] for choice in action["petChoices"]] == [DOG, CAT]


def test_펫_태그_방이어도_다른_이름끼리_여럿이면_태그로_정하지_않아야_한다(client, java):
    # 2026-11-23 : 다른 이름끼리 여럿이면 이름마다 카드. 까미 카드는 태그(초코)로 정하지 않음
    use_agent(client, weight_agent())
    room = room_of(client, java, pet_sn=1)

    actions = events(send(client, room, "초코랑 까미 체중 4.2kg 기록해줘"))[-1][1]["actions"]

    assert actions[0]["input"]["petSn"] == 1
    assert actions[1]["missing"] == ["petSn"]


def test_다른_이름끼리_여럿이면_좁히지_않고_이름마다_카드를_나눠야_한다(client, java):
    # 2026-11-23 : 초코 카드 + 까미 카드(같은 이름 둘이라 그 아이들 칩)
    use_agent(client, weight_agent())
    room = room_of(client, java)

    actions = events(send(client, room, "강아지 초코랑 까미 체중 4.2kg 기록해줘"))[-1][1]["actions"]

    assert actions[0]["input"]["petSn"] == 1
    assert actions[1]["missing"] == ["petSn"]
    assert [choice["petSn"] for choice in actions[1]["petChoices"]] == [DOG, CAT]


def test_도구_규칙은_쓰기_요청에_반려동물을_글로_되묻지_말라고_해야_한다():
    # 추가-3 : LLM이 앞 턴의 "…가 둘이에요" 되물음을 따라 카드 없이 글로 되물음(2026-11-23 화면)
    system = tool_system()
    assert "같은 이름의 아이가 여럿이어도 글로 되묻지 않고 쓰기 도구를 부른다" in system
    assert "'…가 둘이에요' 같은 되물음을 따라 쓰지 않는다" in system


def test_READ도_종_말로_같은_이름_중_그_아이만_읽어야_한다(client, java):
    use_agent(client, FakeToolAgent("get_health_indicators", {}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java)

    events(send(client, room, "고양이 까미 요즘 체중 어때?"))

    assert reader.calls == [(f"/api/pets/{CAT}/health-indicators", {})]


def test_종_품종_칸이_없는_Java_응답이면_지금처럼_칩에_이름만_보여야_한다(client, java):
    java.pets = [{"petSn": DOG, "petNm": "까미", "careArtclNms": []}]
    java.pets.append({"petSn": CAT, "petNm": "까미", "careArtclNms": []})
    use_agent(client, weight_agent())
    room = room_of(client, java)

    evs = events(send(client, room, "강아지 까미 오늘 체중 4.2kg 기록해줘"))

    action = evs[-1][1]["action"]
    assert action["petChoices"] == [
        {"petSn": DOG, "petNm": "까미"},
        {"petSn": CAT, "petNm": "까미"},
    ]
    assert evs[-1][1]["message"]["cnvrsCn"].endswith("까미가 둘이에요. 칩에서 골라 주세요.")


def test_카드가_여럿이면_같은_이름_되물음에_번호를_붙여야_한다(client, java):
    # 2026-11-23 : 여러 카드에서도 카드 하나일 때 문구, 남은 빈 칸은 이어서
    health = {"daily_rcd_idct_cd": "HLTC0014", "rcd_ymd": "2026-09-27", "rcd_nvl": 4.2}
    use_agent(
        client, SequenceAgent(("draft_daily_health_record", health), ("draft_schedule", HOSPITAL))
    )
    room = room_of(client, java)

    evs = events(
        send(client, room, "까미 그저께 체중 4.2kg 기록하고 10월 6일 3시 병원 일정도 잡아줘")
    )

    done = evs[-1][1]
    assert [card["missing"] for card in done["actions"]] == [["petSn", "rcdDt"], ["petSn"]]
    lines = done["message"]["cnvrsCn"].split("\n")
    assert lines[-3:] == [
        "1번: 까미가 둘이에요. 칩에서 고르거나 '강아지 까미'처럼 알려 주세요.",
        "아직 1번의 기록 날짜가 비어 있어요.",
        "2번: 까미가 둘이에요. 칩에서 고르거나 '강아지 까미'처럼 알려 주세요.",
    ]


def test_카드가_여럿이고_종_품종으로_못_가르면_칩에서_고르라고_해야_한다(client, java):
    java.pets = [{"petSn": DOG, "petNm": "까미", "careArtclNms": []}]
    java.pets.append({"petSn": CAT, "petNm": "까미", "careArtclNms": []})
    health = {"daily_rcd_idct_cd": "HLTC0014", "rcd_ymd": TODAY.isoformat(), "rcd_nvl": 4.2}
    use_agent(
        client, SequenceAgent(("draft_daily_health_record", health), ("draft_schedule", HOSPITAL))
    )
    room = room_of(client, java)

    evs = events(
        send(client, room, "까미 오늘 체중 4.2kg 기록하고 10월 6일 3시 병원 일정도 잡아줘")
    )

    lines = evs[-1][1]["message"]["cnvrsCn"].split("\n")
    assert lines[-2:] == [
        "1번: 까미가 둘이에요. 칩에서 골라 주세요.",
        "2번: 까미가 둘이에요. 칩에서 골라 주세요.",
    ]


def test_카드가_여럿이어도_같은_이름이_아닌_빈_칸은_지금_번호_줄이어야_한다(client, java):
    health = {"daily_rcd_idct_cd": "HLTC0014", "rcd_ymd": "2026-09-27", "rcd_nvl": 4.2}
    use_agent(
        client, SequenceAgent(("draft_daily_health_record", health), ("draft_schedule", HOSPITAL))
    )
    room = room_of(client, java)

    evs = events(
        send(client, room, "초코 그저께 체중 4.2kg 기록하고 10월 6일 3시 병원 일정도 잡아줘")
    )

    text = evs[-1][1]["message"]["cnvrsCn"]
    assert text.endswith("아직 1번의 기록 날짜가 비어 있어요. 말로 알려 주세요.")
    assert "둘이에요" not in text
