"""쓰기 카드 날짜 빠짐 (SCR-AIM-012, FN-AIM-012-02 보강, 2026-11-23)
- 도구 고르기 LLM이 date hook 날짜를 비우면 서버가 채운다
- 문장의 날짜 말이 하나면 그 날짜, 없으면 새 등록 기록 도구만 오늘. 일정은 빈 칸 그대로"""

from datetime import timedelta

import pytest

from app.chat import catalog, rules, tools
from tests.chat.fakes import FakeToolAgent, fake_catalog
from tests.chat.test_action import WEIGHT, send
from tests.chat.test_messages import MessageJava, events
from tests.chat.test_register import CHOCO, TODAY
from tests.chat.test_tools import room_of, use_agent

HEALTH = "draft_daily_health_record"
SCHEDULE = "draft_schedule"
SCHEDULE_UPDATE = "draft_schedule_update"
OBSERVATION = "draft_observation_cycle"


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


def action_of(client, java, tool: str, raw: dict, text: str, prior: dict | None = None) -> dict:
    use_agent(client, FakeToolAgent(tool, raw))
    room = room_of(client, java, pet_sn=CHOCO)
    return events(send(client, room, text, action=prior))[-1][1]["action"]


def test_LLM이_날짜를_비워도_오늘이라고_말했으면_오늘_지금으로_채워야_한다(client, java):
    raw = {"daily_rcd_idct_cd": WEIGHT, "rcd_nvl": 50}
    action = action_of(client, java, HEALTH, raw, "초코 오늘 체중 50 추가해줘")

    assert action["input"]["rcdDt"].startswith(f"{TODAY.isoformat()}T")
    assert action["missing"] == []


def test_날짜_말이_없는_새_건강_일지는_오늘로_채워야_한다(client, java):
    raw = {"daily_rcd_idct_cd": WEIGHT, "rcd_nvl": 4.2}
    action = action_of(client, java, HEALTH, raw, "초코 체중 4.2kg 기록해줘")

    assert action["input"]["rcdDt"].startswith(f"{TODAY.isoformat()}T")
    assert action["missing"] == []


def test_어제라고_말하고_시간이_있으면_어제_그_시간이어야_한다(client, java):
    raw = {"daily_rcd_idct_cd": WEIGHT, "rcd_tm": "08:00", "rcd_nvl": 4.2}
    action = action_of(client, java, HEALTH, raw, "초코 어제 아침 8시 체중 4.2kg 기록해줘")

    yesterday = TODAY - timedelta(days=1)
    assert action["input"]["rcdDt"] == f"{yesterday.isoformat()}T08:00:00"


def test_어제라고_말하고_시간이_없으면_기록_일시는_지금_규칙대로_빈_칸이다(client, java):
    raw = {"daily_rcd_idct_cd": WEIGHT, "rcd_nvl": 4.2}
    action = action_of(client, java, HEALTH, raw, "초코 어제 체중 4.2kg 기록해줘")

    assert "rcdDt" not in action["input"]
    assert action["missing"] == ["rcdDt"]


def test_LLM이_준_날짜는_덮지_않아야_한다(client, java):
    raw = {"daily_rcd_idct_cd": WEIGHT, "rcd_ymd": "2026-09-27", "rcd_tm": "09:00", "rcd_nvl": 4.2}
    action = action_of(client, java, HEALTH, raw, "초코 오늘 체중 4.2kg 기록해줘")

    assert action["input"]["rcdDt"] == "2026-09-27T09:00:00"


def test_날짜_말이_없는_일정_등록은_빈_칸_그대로여야_한다(client, java):
    raw = {"schdl_knd_cd": "HLTC0057", "ckup_type_cd": "HLTC0002", "hsptl_nm": "메이 동물병원"}
    action = action_of(client, java, SCHEDULE, raw, "초코 메이 동물병원 예방접종 잡아줘")

    assert "schdlDt" not in action["input"]
    assert "schdlDt" in action["missing"]


def test_LLM이_일정_날짜를_비워도_날짜_말이_있으면_그_날짜여야_한다(client, java):
    raw = {"schdl_knd_cd": "HLTC0057", "ckup_type_cd": "HLTC0002", "hsptl_nm": "메이 동물병원"}
    action = action_of(client, java, SCHEDULE, raw, "초코 10월 6일 메이 동물병원 예방접종 잡아줘")

    assert action["input"]["schdlDt"] == "2026-10-06T00:00:00"
    assert action["input"]["hrInptYn"] is False


def test_돌려받은_카드에_날짜가_있고_날짜_말이_없으면_카드_날짜를_유지해야_한다(client, java):
    prior = {
        "tool": HEALTH,
        "input": {
            "petSn": CHOCO,
            "dailyRcdIdctCd": WEIGHT,
            "rcdDt": "2026-09-27T08:00:00",
            "rcdNvl": 4.2,
        },
    }
    action = action_of(client, java, HEALTH, {"rcd_nvl": 4.5}, "4.5kg이었어", prior=prior)

    assert action["input"]["rcdDt"] == "2026-09-27T08:00:00"
    assert action["input"]["rcdNvl"] == 4.5


def test_문장의_날짜_말을_나온_순서대로_한_번씩_읽는다():
    yesterday = TODAY - timedelta(days=1)
    assert rules.said_dates("초코 오늘 체중 기록해줘", TODAY) == [TODAY]
    assert rules.said_dates("어제 체중 기록하고 10월 6일 병원", TODAY) == [
        yesterday,
        TODAY.replace(month=10, day=6),
    ]
    assert rules.said_dates("방금 산책 30분 다녀왔어", TODAY) == [TODAY]
    assert rules.said_dates("체중 4.2kg 기록해줘", TODAY) == []
    assert rules.said_dates("그저께 체중 기록해줘", TODAY) == [TODAY - timedelta(days=2)]


def test_fill_date는_날짜_말이_여럿이면_비워_두고_수정_도구는_오늘로_채우지_않는다():
    tools.use_catalog(fake_catalog())
    health = tools.card_entry(HEALTH)
    other = TODAY + timedelta(days=7)

    assert catalog.fill_date(health, {}, [TODAY, other], TODAY) == {}
    assert catalog.fill_date(health, {}, [other], TODAY) == {"rcd_ymd": other.isoformat()}
    assert catalog.fill_date(health, {}, [], TODAY) == {"rcd_ymd": TODAY.isoformat()}
    update = tools.card_entry(SCHEDULE_UPDATE)
    assert catalog.fill_date(update, {}, [], TODAY) == {}
    observation = tools.card_entry(OBSERVATION)
    ymd = next(n for n, r in observation.hook_roles.items() if r == "date:ymd")
    assert catalog.fill_date(observation, {}, [], TODAY) == {ymd: TODAY.isoformat()}
