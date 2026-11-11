"""추가-3 : 수정 카드에서 날짜만 바꾸면 원래 시간을 써야 한다"""

import pytest

from app.chat import rules
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_action import send
from tests.chat.test_messages import MessageJava, events
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import CHOCO, TODAY
from tests.chat.test_tools import room_of, use_agent


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


def schedule_card(client, java, row: dict, raw: dict) -> dict:
    use_reader(client, FakeToolReader([row]))
    use_agent(
        client,
        FakeToolAgent(
            "list_my_care_schedules", {}, follow_tool="draft_schedule_update", follow_raw=raw
        ),
    )
    room = room_of(client, java, pet_sn=CHOCO)
    return events(send(client, room, "병원 일정 모레로 미뤄줘"))[-1][1]["action"]


@pytest.mark.parametrize(
    "row",
    [
        {"schdlSn": 31, "schdlDt": "2026-10-01T13:30:00", "hrInptYn": True},
        # 결과에 hrInptYn이 없어도 0시가 아니면 시간 입력으로 본다
        {"schdlSn": 31, "schdlDt": "2026-10-01T13:30:00"},
    ],
)
def test_날짜만_바꾸면_READ_결과의_원래_시간을_써야_한다(client, java, row):
    action = schedule_card(client, java, row, {"schdl_sn": 31, "schdl_ymd": "2026-10-03"})

    assert action["input"]["schdlDt"] == "2026-10-03T13:30:00"
    assert action["input"]["hrInptYn"] is True


def test_원래_시간이_미입력이면_0시_미입력_그대로여야_한다(client, java):
    row = {"schdlSn": 31, "schdlDt": "2026-10-01T00:00:00", "hrInptYn": False}

    action = schedule_card(client, java, row, {"schdl_sn": 31, "schdl_ymd": "2026-10-03"})

    assert action["input"]["schdlDt"] == "2026-10-03T00:00:00"
    assert action["input"]["hrInptYn"] is False


def test_시간을_말하면_그_시간을_써야_한다(client, java):
    row = {"schdlSn": 31, "schdlDt": "2026-10-01T13:30:00", "hrInptYn": True}
    raw = {"schdl_sn": 31, "schdl_ymd": "2026-10-03", "schdl_tm": "17:00"}

    action = schedule_card(client, java, row, raw)

    assert action["input"]["schdlDt"] == "2026-10-03T17:00:00"
    assert action["input"]["hrInptYn"] is True


def test_날짜를_바꾸지_않으면_일시_칸을_싣지_않아야_한다(client, java):
    row = {"schdlSn": 31, "schdlDt": "2026-10-01T13:30:00", "hrInptYn": True}

    action = schedule_card(client, java, row, {"schdl_sn": 31, "schdl_nm": "검진"})

    assert "schdlDt" not in action["input"]
    assert "hrInptYn" not in action["input"]


def test_돌려받은_카드에서_날짜만_바꾸면_카드의_원래_시간을_써야_한다(client, java):
    use_agent(client, FakeToolAgent("draft_schedule_update", {"schdl_ymd": "2026-10-04"}))
    room = room_of(client, java, pet_sn=CHOCO)
    prior = {
        "tool": "draft_schedule_update",
        "input": {
            "petSn": CHOCO,
            "schdlSn": 31,
            "schdlDt": "2026-10-03T13:30:00",
            "hrInptYn": True,
        },
    }

    action = events(send(client, room, "아니 하루 더 미뤄줘", action=prior))[-1][1]["action"]

    assert action["input"]["schdlDt"] == "2026-10-04T13:30:00"
    assert action["input"]["hrInptYn"] is True


def test_새_건강_일지_카드는_지금_규칙_그대로여야_한다(client, java):
    # 경로 번호 칸이 없는 카드 : 원래 값 개념 없음(날짜만, 오늘이면 지금 시각)
    use_agent(
        client,
        FakeToolAgent(
            "draft_daily_health_record",
            {"daily_rcd_idct_cd": "HLTC0014", "rcd_ymd": TODAY.isoformat(), "rcd_nvl": 4.2},
        ),
    )
    room = room_of(client, java)

    action = events(send(client, room, "초코 오늘 체중 4.2kg 기록해줘"))[-1][1]["action"]

    assert action["input"]["rcdDt"].startswith(f"{TODAY.isoformat()}T")
