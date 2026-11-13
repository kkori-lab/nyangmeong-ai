"""'방금·지금·아까' 상대 일시 : 날짜는 오늘, 시각을 말하지 않았으면 지금 (2026-11-13 추가 요청)"""

from datetime import date, datetime

import pytest

from app.chat import catalog, clients, rules, tools
from tests.chat.fakes import FakeToolAgent, fake_catalog
from tests.chat.test_action import send
from tests.chat.test_messages import MessageJava, events
from tests.chat.test_register import TODAY
from tests.chat.test_tools import room_of, use_agent

HEALTH = "draft_daily_health_record"
WEIGHT = "HLTC0014"


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


def card(client, java, tool: str, text: str, args: dict) -> dict:
    use_agent(client, FakeToolAgent(tool, args))
    room = room_of(client, java)
    return events(send(client, room, text))[-1][1]["action"]


@pytest.mark.parametrize(
    "text", ["방금 산책했어", "지금 밥 줬어", "아까 체중 쟀어", "금방 약 먹였어"]
)
def test_방금_지금은_날짜_말로_본다(text):
    assert rules.mentions_now(text)
    assert rules.mentions_date(text)


def test_방금_말이_없으면_지금_말로_보지_않는다():
    assert not rules.mentions_now("내일 병원 일정 넣어줘")


def test_LLM이_날짜를_비운_방금_기록은_오늘_지금_시각으로_채운다(client, java):
    action = card(
        client,
        java,
        HEALTH,
        "초코 방금 체중 4.2kg 쟀어",
        {
            "daily_rcd_idct_cd": WEIGHT,
            "rcd_nvl": 4.2,
        },
    )

    assert action["input"]["rcdDt"].startswith(f"{TODAY.isoformat()}T")
    assert "rcdDt" not in action["missing"]


def test_아까_말한_시각은_그대로_쓴다(client, java):
    action = card(
        client,
        java,
        HEALTH,
        "초코 아까 3시에 체중 4.2kg 쟀어",
        {
            "daily_rcd_idct_cd": WEIGHT,
            "rcd_tm": "15:00",
            "rcd_nvl": 4.2,
        },
    )

    assert action["input"]["rcdDt"] == f"{TODAY.isoformat()}T15:00:00"


def test_지금_일정은_시간_입력으로_채운다(client, java):
    action = card(
        client,
        java,
        "draft_schedule",
        "초코 지금 병원 왔어 일정 넣어줘",
        {
            "schdl_knd_cd": "HLTC0059",
            "schdl_nm": "병원",
        },
    )

    assert action["input"]["schdlDt"].startswith(f"{TODAY.isoformat()}T")
    assert action["input"]["hrInptYn"] is True


def test_내일은_지금처럼_날짜만_둔다(client, java):
    tomorrow = date(2026, 9, 30).isoformat()
    action = card(
        client,
        java,
        "draft_schedule",
        "초코 내일 병원 일정 넣어줘",
        {
            "schdl_knd_cd": "HLTC0059",
            "schdl_nm": "병원",
            "schdl_ymd": tomorrow,
        },
    )

    assert action["input"]["schdlDt"] == f"{tomorrow}T00:00:00"
    assert action["input"]["hrInptYn"] is False


def test_fill_now는_다른_날짜와_말한_시각을_덮지_않는다():
    tools.use_catalog(fake_catalog())
    entry = tools.card_entry(HEALTH)
    now = datetime(2026, 9, 29, 14, 7, 30)

    assert catalog.fill_now(entry, {}, now) == {"rcd_ymd": "2026-09-29", "rcd_tm": "14:07"}
    assert catalog.fill_now(entry, {"rcd_ymd": "2026-09-28"}, now) == {"rcd_ymd": "2026-09-28"}
    assert catalog.fill_now(entry, {"rcd_tm": "09:00"}, now) == {
        "rcd_ymd": "2026-09-29",
        "rcd_tm": "09:00",
    }


def test_오늘이_실제_오늘이면_도구_system에_지금_시각을_보낸다(monkeypatch):
    now = datetime(2026, 9, 29, 14, 7, tzinfo=rules.KST)
    monkeypatch.setattr(rules, "now_kst", lambda: now)

    texts = [block["text"] for block in clients.tool_system_blocks(TODAY)]

    assert texts[1] == "오늘: 2026-09-29 (화)"
    assert texts[-1] == "지금 시각: 14:07"


def test_평가처럼_다른_날을_오늘로_주면_지금_시각은_빼고_보낸다(monkeypatch):
    monkeypatch.setattr(rules, "now_kst", lambda: datetime(2026, 11, 13, 9, 0, tzinfo=rules.KST))

    texts = [block["text"] for block in clients.tool_system_blocks(TODAY)]

    assert not any(text.startswith("지금 시각") for text in texts)
