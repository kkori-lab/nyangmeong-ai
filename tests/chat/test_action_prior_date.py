"""추가-1 : 돌려받은 확인 카드의 날짜를 날짜 말 없는 메시지가 덮지 않는다 (SCR-AIM-012 2단계)"""

import pytest

from app.chat import rules
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_action import send
from tests.chat.test_messages import MessageJava, events
from tests.chat.test_register import CHOCO, TODAY
from tests.chat.test_tools import room_of, use_agent

WEIGHT = "HLTC0014"
FOOD = "MYPC0013"
DIRECT = "MYPC0019"
YESTERDAY_9 = "2026-09-28T09:00:00"


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


def weight_prior(**values) -> dict:
    base = {"petSn": CHOCO, "dailyRcdIdctCd": WEIGHT, "rcdDt": YESTERDAY_9, "rcdNvl": 4.2}
    return {"tool": "draft_daily_health_record", "input": base | values}


def weight_card(client, java, text: str, prior: dict, **raw) -> dict:
    # LLM은 설명대로 날짜를 말하지 않아도 오늘로 채운다(실측 2026-11-09 프론트 검증)
    args = {"daily_rcd_idct_cd": WEIGHT, "rcd_ymd": TODAY.isoformat(), "rcd_nvl": 4.5} | raw
    use_agent(client, FakeToolAgent("draft_daily_health_record", args))
    room = room_of(client, java, pet_sn=CHOCO)
    return events(send(client, room, text, action=prior))[-1][1]["action"]


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("4.5로 바꿔줘", False),
        ("4만원으로 바꿔 줘", False),
        ("어제로 바꿔 줘", True),
        ("10월 3일로 해 줘", True),
        ("다음 주 화요일", True),
        ("2026-10-01로", True),
    ],
)
def test_날짜_말이_있는지_판정해야_한다(text, said):
    assert rules.mentions_date(text) is said


def test_날짜를_말하지_않으면_돌려받은_카드의_날짜와_시간을_유지해야_한다(client, java):
    action = weight_card(client, java, "4.5로 바꿔줘", weight_prior())

    assert action["input"]["rcdDt"] == YESTERDAY_9
    assert action["input"]["rcdNvl"] == 4.5


def test_시간만_말하면_돌려받은_카드의_날짜에_그_시간을_써야_한다(client, java):
    action = weight_card(client, java, "8시 반으로 바꿔줘", weight_prior(), rcd_tm="08:30")

    assert action["input"]["rcdDt"] == "2026-09-28T08:30:00"


def test_날짜를_말하면_이_메시지의_날짜로_덮어써야_한다(client, java):
    action = weight_card(client, java, "오늘 8시 반으로 바꿔줘", weight_prior(), rcd_tm="08:30")

    assert action["input"]["rcdDt"] == f"{TODAY.isoformat()}T08:30:00"


def test_날짜_말이_없어도_LLM이_오늘이_아닌_날짜를_계산했으면_그_날짜를_써야_한다(client, java):
    # "하루 더 미뤄줘" : 날짜 말은 없지만 LLM이 카드 날짜에서 계산한 값
    action = weight_card(
        client, java, "하루 앞으로 당겨줘", weight_prior(), rcd_ymd="2026-09-27", rcd_tm="09:00"
    )

    assert action["input"]["rcdDt"] == "2026-09-27T09:00:00"


def test_돌려받은_카드에_날짜가_없으면_LLM이_채운_날짜를_써야_한다(client, java):
    prior = weight_prior()
    del prior["input"]["rcdDt"]

    action = weight_card(client, java, "8시 반에 쟀어", prior, rcd_tm="08:30")

    assert action["input"]["rcdDt"] == f"{TODAY.isoformat()}T08:30:00"


def test_지출_카드도_날짜를_말하지_않으면_돌려받은_지출_날짜를_유지해야_한다(client, java):
    use_agent(
        client,
        FakeToolAgent("draft_expense", {"expnd_ymd": TODAY.isoformat(), "expnd_amt": 40000}),
    )
    room = room_of(client, java)
    prior = {
        "tool": "draft_expense",
        "input": {
            "expndYmd": "2026-09-20",
            "expndClsfCd": FOOD,
            "expndInptMthCd": DIRECT,
            "lines": [{"expndAmt": 32000}],
        },
    }

    action = events(send(client, room, "4만원으로 바꿔 줘", action=prior))[-1][1]["action"]

    assert action["input"]["expndYmd"] == "2026-09-20"
    assert action["input"]["lines"] == [{"expndAmt": 40000}]


def test_돌려받은_카드가_없으면_LLM이_채운_오늘_날짜를_그대로_써야_한다(client, java):
    use_agent(
        client,
        FakeToolAgent("draft_expense", {"expnd_ymd": TODAY.isoformat(), "expnd_amt": 40000}),
    )
    room = room_of(client, java)

    action = events(send(client, room, "사료 4만원 적어 줘"))[-1][1]["action"]

    assert action["input"]["expndYmd"] == TODAY.isoformat()
