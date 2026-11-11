"""SCR-AIM-012 2단계 쓰기 ② : 수정 확인 카드 4개 (READ -> CARD, PATCH)"""

import pytest

from app.chat import rules
from app.chat.service import ACTION_SHOWN, ACTION_TARGET_MISSING, DISCLAIMER
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_action import action_result, send
from tests.chat.test_messages import MessageJava, deltas, events
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import CHOCO, MUNG, TODAY
from tests.chat.test_tools import room_of, use_agent

FOOD = "MYPC0013"


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


def read_then(client, read_tool: str, rows: list[dict], tool: str, raw: dict) -> FakeToolAgent:
    use_reader(client, FakeToolReader(rows))
    return use_agent(client, FakeToolAgent(read_tool, {}, follow_tool=tool, follow_raw=raw))


# READ 다음 수정 카드


def test_일정_목록을_읽은_뒤_고른_일정_수정은_목록의_번호와_바꿀_칸만_카드에_실어야_한다(
    client, java
):
    agent = read_then(
        client,
        "list_my_care_schedules",
        [{"schdlSn": 31, "schdlNm": "예방접종", "schdlDt": "2026-10-01T15:00:00"}],
        "draft_schedule_update",
        {"schdl_sn": 31, "schdl_ymd": "2026-10-03", "schdl_tm": "15:00"},
    )
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "다음 병원 일정 모레로 미뤄줘"))

    assert evs[0][1]["kind"] == "SEARCH"
    assert agent.results[1] == ACTION_SHOWN
    action = evs[-1][1]["action"]
    assert action["tool"] == "draft_schedule_update"
    assert action["label"] == "일정 수정"
    assert action["call"] == {
        "method": "PATCH",
        "path": "/api/pets/{petSn}/care-schedules/{schdlSn}",
    }
    assert action["input"] == {
        "petSn": CHOCO,
        "schdlSn": 31,
        "schdlDt": "2026-10-03T15:00:00",
        "hrInptYn": True,
    }
    assert action["missing"] == []


def test_목록에_없는_번호로_고른_수정은_카드_없이_LLM에_찾지_못함을_돌려줘야_한다(client, java):
    agent = read_then(
        client,
        "list_my_care_schedules",
        [{"schdlSn": 31}],
        "draft_schedule_update",
        {"schdl_sn": 99, "schdl_nm": "검진"},
    )
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "일정 이름 검진으로 바꿔 줘"))

    assert agent.results[1] == ACTION_TARGET_MISSING
    assert evs[-1][1]["action"] is None
    assert deltas(evs) == "안내서대로 답할게요." + DISCLAIMER


def test_케어_항목_수정은_requiredIf로_직접_입력_주기의_일수를_물어야_한다(client, java):
    read_then(
        client,
        "list_care_items",
        [{"careArtclSn": 7, "careArtclNm": "발톱 깎기"}],
        "draft_care_item_update",
        {"care_artcl_sn": 7, "care_cycle_cd": "HLTC0042"},
    )
    room = room_of(client, java, pet_sn=CHOCO)

    action = events(send(client, room, "발톱 깎기 주기 바꿔 줘"))[-1][1]["action"]

    assert action["tool"] == "draft_care_item_update"
    assert action["input"] == {"petSn": CHOCO, "careArtclSn": 7, "careCycleCd": "HLTC0042"}
    assert action["missing"] == ["cycleDrctInptDayCnt"]


def test_지출_수정_카드에는_반려동물_칸이_없어야_한다(client, java):
    read_then(
        client,
        "list_expenses",
        [{"expndSn": 501, "expndAmt": 30000, "petSn": CHOCO}],
        "draft_expense_update",
        {"expnd_sn": 501, "expnd_amt": 32000, "expnd_clsf_cd": FOOD},
    )
    room = room_of(client, java)

    action = events(send(client, room, "어제 사료 산 거 3만 2천원으로 고쳐 줘"))[-1][1]["action"]

    assert action["tool"] == "draft_expense_update"
    assert action["call"] == {"method": "PATCH", "path": "/api/expenses/{expndSn}"}
    assert action["input"] == {"expndSn": 501, "expndAmt": 32000, "expndClsfCd": FOOD}
    assert (action["missing"], action["petChoices"], action["petNm"]) == ([], [], None)


# READ 없이 바로 고른 수정 도구


def test_READ_없이_고른_일정_수정은_카드_없이_안내_글을_고지_없이_저장해야_한다(client, java):
    use_agent(client, FakeToolAgent("draft_schedule_update", {"schdl_sn": 31, "schdl_nm": "검진"}))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "병원 일정 이름 검진으로 바꿔 줘"))

    message = "바꿀 일정을 찾지 못했어요. 이름이나 날짜를 넣어 다시 말해 주세요."
    assert evs[0][1]["kind"] == "SEARCH"
    assert evs[-1][1]["action"] is None
    assert deltas(evs) == message
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [message]


def test_돌려받은_수정_카드에_번호가_있으면_그_번호로_카드를_띄워야_한다(client, java):
    use_agent(client, FakeToolAgent("draft_schedule_update", {"schdl_tm": "15:00"}))
    room = room_of(client, java, pet_sn=CHOCO)
    prior = {
        "tool": "draft_schedule_update",
        "input": {"petSn": CHOCO, "schdlSn": 31, "schdlNm": "검진"},
    }

    evs = events(send(client, room, "아 3시로 바꿔줘", action=prior))

    assert evs[0][1]["kind"] == "ACTION"
    action = evs[-1][1]["action"]
    assert action["input"]["schdlSn"] == 31
    assert action["input"]["schdlNm"] == "검진"
    assert action["missing"] == []


def test_반려동물_정보_수정은_READ_없이_카드를_띄우고_경로_petSn은_반려동물_규칙으로(client, java):
    use_agent(client, FakeToolAgent("draft_pet_update", {"goal_bdwg": 4.0}))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "목표 체중 4kg로 바꿔 줘"))

    assert evs[0][1]["kind"] == "ACTION"
    action = evs[-1][1]["action"]
    assert action["tool"] == "draft_pet_update"
    assert action["call"] == {"method": "PATCH", "path": "/api/pets/{petSn}"}
    assert action["input"] == {"petSn": CHOCO, "goalBdwg": 4.0}
    assert action["missing"] == []


def test_반려동물을_정하지_못하면_반려동물_정보_수정도_petChoices로_되물어야_한다(client, java):
    use_agent(client, FakeToolAgent("draft_pet_update", {"goal_bdwg": 4.0}))
    room = room_of(client, java)

    action = events(send(client, room, "목표 체중 4kg로 바꿔 줘"))[-1][1]["action"]

    assert action["missing"] == ["petSn"]
    assert action["petChoices"] == [
        {"petSn": CHOCO, "petNm": "초코"},
        {"petSn": MUNG, "petNm": "뭉치"},
    ]


# 칸 검사 보강 : @Positive·@Pattern


@pytest.mark.parametrize(
    "raw",
    [{"pet_bdwg": 0}, {"pet_bdwg": -1.5}, {"chip_no": "abc123"}],
)
def test_양수가_아닌_체중이나_숫자가_아닌_칩_번호는_카드에서_비워야_한다(client, java, raw):
    use_agent(client, FakeToolAgent("draft_pet_update", raw))
    room = room_of(client, java, pet_sn=CHOCO)

    action = events(send(client, room, "초코 정보 바꿔 줘"))[-1][1]["action"]

    assert action["input"] == {"petSn": CHOCO}


@pytest.mark.parametrize("values", [{"petBdwg": 0}, {"chipNo": "abc"}])
def test_양수가_아닌_체중이나_숫자가_아닌_칩_번호의_결과는_400(client, java, values):
    room = room_of(client, java)

    res = action_result(client, room, "draft_pet_update", "DONE", {"petSn": CHOCO} | values)

    assert res.status_code == 400
    assert java.ai_messages(room) == []


# 결과 요약


@pytest.mark.parametrize(
    ("tool", "values", "message"),
    [
        (
            "draft_schedule_update",
            {"petSn": CHOCO, "schdlSn": 31, "schdlDt": "2026-10-07T15:00:00", "hrInptYn": True},
            "✔ 일정 수정 — 10-07(수) 15:00",
        ),
        (
            "draft_care_item_update",
            {"petSn": CHOCO, "careArtclSn": 7, "careArtclNm": "치카치카"},
            "✔ 케어 항목 수정 — 치카치카",
        ),
        (
            "draft_expense_update",
            {"expndSn": 501, "expndAmt": 32000, "expndClsfCd": FOOD},
            "✔ 지출 수정 — 사료 · 32,000",
        ),
        ("draft_pet_update", {"petSn": CHOCO, "goalBdwg": 4.0}, "✔ 반려동물 정보 수정 — 4"),
        # 바꾼 칸이 없으면 이름만
        ("draft_schedule_update", {"petSn": CHOCO, "schdlSn": 31}, "✔ 일정 수정"),
    ],
)
def test_수정_결과는_바꾼_칸만_요약해_저장해야_한다(client, java, tool, values, message):
    room = room_of(client, java)

    res = action_result(client, room, tool, "DONE", values)

    assert res.status_code == 201
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [message]


def test_수정_결과에_경로_번호가_비면_400(client, java):
    room = room_of(client, java)

    res = action_result(client, room, "draft_expense_update", "DONE", {"expndAmt": 32000})

    assert res.status_code == 400


# 안내 글의 대상 이름(tool_prompts.yaml target)


def test_찾지_못함_안내는_대상_이름으로_만든다(client, java):
    use_agent(client, FakeToolAgent("draft_expense_update", {"expnd_amt": 32000}))
    room = room_of(client, java)

    evs = events(send(client, room, "지출 3만 2천원으로 고쳐 줘"))

    assert deltas(evs) == "바꿀 지출 기록을 찾지 못했어요. 이름이나 날짜를 넣어 다시 말해 주세요."
