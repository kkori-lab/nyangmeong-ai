"""SCR-AIM-012 2단계 쓰기 ④ : 기존 등록 카드 2개(일정·케어 항목)의 확인 카드(ACTION) 전환"""

import pytest

from app.chat import rules
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_action import action_result, send
from tests.chat.test_messages import MessageJava, events
from tests.chat.test_register import CHOCO, MUNG, TODAY
from tests.chat.test_tools import room_of, use_agent

HOSPITAL = {
    "schdl_knd_cd": "HLTC0057",
    "ckup_type_cd": "HLTC0002",
    "hsptl_nm": "메이 동물병원",
    "schdl_ymd": "2026-10-06",
    "schdl_tm": "15:00",
}


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


def action_of(evs: list) -> dict:
    return evs[-1][1]["action"]


# 일정 등록


def test_병원_일정_요청은_일정_등록_API를_부르는_확인_카드여야_한다(client, java):
    use_agent(client, FakeToolAgent("draft_schedule", HOSPITAL))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "다음 주 화요일 3시 메이 동물병원 예방접종 등록해 줘"))

    assert evs[0][1]["kind"] == "ACTION"
    done = evs[-1][1]
    assert done["card"] is None
    assert done["message"]["cnvrsCn"].startswith("이렇게 할까요?")  # 2026-11-13
    action = done["action"]
    assert (action["tool"], action["label"]) == ("draft_schedule", "일정 등록")
    assert action["call"] == {"method": "POST", "path": "/api/pets/{petSn}/care-schedules"}
    values = action["input"]
    assert values["petSn"] == CHOCO
    assert (values["schdlDt"], values["hrInptYn"]) == ("2026-10-06T15:00:00", True)
    assert (values["hsptlNm"], values["ckupTypeCd"]) == ("메이 동물병원", "HLTC0002")
    assert action["missing"] == []
    # 카드는 저장하지 않음 : 되물음 글도 없음
    assert len(java.ai_messages(room)) == 1  # 카드 요약 글 (2026-11-13)


def test_일정_카드에는_출처_코드를_넣지_않아야_한다(client, java):
    # 2026-11-06 결정 : 출처 없이(Java 기본값). HLTC0067이면 케어미션 반영이 빠짐
    use_agent(client, FakeToolAgent("draft_schedule", HOSPITAL | {"schdl_src_cd": "HLTC0067"}))
    room = room_of(client, java, pet_sn=CHOCO)

    values = action_of(events(send(client, room, "6일 3시 병원 등록해 줘")))["input"]

    assert "schdlSrcCd" not in values


def test_시간을_말하지_않은_일정은_시간_입력_여부가_거짓이어야_한다(client, java):
    raw = {"schdl_knd_cd": "HLTC0058", "schdl_nm": "미용", "schdl_ymd": "2026-10-03"}
    use_agent(client, FakeToolAgent("draft_schedule", raw))
    room = room_of(client, java, pet_sn=CHOCO)

    values = action_of(events(send(client, room, "토요일에 미용 잡아줘")))["input"]

    assert values["hrInptYn"] is False
    assert values["schdlDt"].startswith("2026-10-03")


def test_반려동물을_정하지_못하면_빈_칸과_이름_칩이어야_한다(client, java):
    use_agent(client, FakeToolAgent("draft_schedule", HOSPITAL))
    room = room_of(client, java)

    action = action_of(events(send(client, room, "6일 3시 병원 등록해 줘")))

    assert "petSn" in action["missing"]
    assert [p["petSn"] for p in action["petChoices"]] == [CHOCO, MUNG]
    assert action["petNm"] is None


def test_문장_속_이름이_하나면_그_반려동물이어야_한다(client, java):
    use_agent(client, FakeToolAgent("draft_schedule", HOSPITAL))
    room = room_of(client, java)

    action = action_of(events(send(client, room, "뭉치 6일 3시 병원 등록해 줘")))

    assert (action["input"]["petSn"], action["petNm"]) == (MUNG, "뭉치")
    assert action["petChoices"] == []


def test_돌려받은_일정_카드와_같은_도구면_그_칸을_이어_써야_한다(client, java):
    use_agent(client, FakeToolAgent("draft_schedule", {"hsptl_nm": "행복 동물병원"}))
    room = room_of(client, java, pet_sn=CHOCO)
    prior = {
        "tool": "draft_schedule",
        "input": {
            "petSn": CHOCO,
            "schdlKndCd": "HLTC0057",
            "ckupTypeCd": "HLTC0002",
            "hsptlNm": "메이 동물병원",
            "schdlDt": "2026-10-06T15:00:00",
            "hrInptYn": True,
        },
    }

    action = action_of(events(send(client, room, "병원은 행복 동물병원으로", prior)))

    values = action["input"]
    assert values["hsptlNm"] == "행복 동물병원"
    assert (values["schdlKndCd"], values["schdlDt"]) == ("HLTC0057", "2026-10-06T15:00:00")
    assert action["missing"] == []


# 케어 항목 등록


def test_주기_케어_항목_요청은_케어_항목_등록_API를_부르는_확인_카드여야_한다(client, java):
    raw = {"care_artcl_nm": "산책", "care_zone_cd": "HLTC0037", "care_cycle_cd": "HLTC0039"}
    use_agent(client, FakeToolAgent("draft_care_item", raw))
    room = room_of(client, java, pet_sn=CHOCO)

    action = action_of(events(send(client, room, "초코 매주 산책 넣어줘")))

    assert (action["tool"], action["label"]) == ("draft_care_item", "케어 항목 등록")
    assert action["call"] == {"method": "POST", "path": "/api/pets/{petSn}/care-items"}
    assert action["input"]["careZoneCd"] == "HLTC0037"
    assert action["input"]["careCycleCd"] == "HLTC0039"
    assert action["missing"] == []
    assert action["notice"] is None


def test_직접입력_주기에_날_수가_없으면_빈_칸이어야_한다(client, java):
    raw = {"care_artcl_nm": "목욕", "care_zone_cd": "HLTC0037", "care_cycle_cd": "HLTC0042"}
    use_agent(client, FakeToolAgent("draft_care_item", raw))
    room = room_of(client, java, pet_sn=CHOCO)

    action = action_of(events(send(client, room, "초코 목욕 주기 넣어줘")))

    assert action["missing"] == ["cycleDrctInptDayCnt"]


def test_같은_이름_케어_항목이_있으면_안내_문구가_있어야_한다(client, java):
    # FN-AIM-012-08 : 뭉치에게 "발톱 깎기"가 있음(가짜 register-context), 띄어쓰기만 달라도 같음
    raw = {"care_artcl_nm": "발톱깎기", "care_zone_cd": "HLTC0036"}
    use_agent(client, FakeToolAgent("draft_care_item", raw))
    room = room_of(client, java, pet_sn=MUNG)

    action = action_of(events(send(client, room, "뭉치 매일 발톱깎기 넣어줘")))

    assert action["notice"] == "뭉치에게 '발톱깎기' 항목이 이미 있어요. 그래도 새로 등록할까요?"


def test_다른_반려동물이면_같은_이름이어도_안내_문구가_없어야_한다(client, java):
    raw = {"care_artcl_nm": "발톱 깎기", "care_zone_cd": "HLTC0036"}
    use_agent(client, FakeToolAgent("draft_care_item", raw))
    room = room_of(client, java, pet_sn=CHOCO)

    action = action_of(events(send(client, room, "초코 매일 발톱 깎기 넣어줘")))

    assert action["notice"] is None


# 결과 저장(action-result)


def test_병원_일정_등록_결과는_시간까지_요약_글로_저장해야_한다(client, java):
    room = room_of(client, java)
    values = {
        "petSn": CHOCO,
        "schdlKndCd": "HLTC0057",
        "schdlDt": "2026-10-06T15:00:00",
        "hrInptYn": True,
        "ckupTypeCd": "HLTC0002",
        "hsptlNm": "메이 동물병원",
    }

    res = action_result(client, room, "draft_schedule", "DONE", values)

    assert res.status_code == 201
    saved = java.ai_messages(room)[-1]["cnvrsCn"]
    assert saved.startswith("✔ 일정 등록 — ")
    assert " · 10-06(화) 15:00 · " in saved
    assert saved.endswith(" · 메이 동물병원")


def test_시간_없는_일정_등록_결과는_날짜만_요약해야_한다(client, java):
    room = room_of(client, java)
    values = {
        "petSn": CHOCO,
        "schdlKndCd": "HLTC0058",
        "schdlDt": "2026-10-03T00:00:00",
        "hrInptYn": False,
        "schdlNm": "미용",
    }

    res = action_result(client, room, "draft_schedule", "DONE", values)

    assert res.status_code == 201
    saved = java.ai_messages(room)[-1]["cnvrsCn"]
    assert " · 10-03(토) · 미용" in saved
    assert "00:00" not in saved


def test_케어_항목_등록_결과는_요약_글로_저장해야_한다(client, java):
    room = room_of(client, java)
    values = {
        "petSn": MUNG,
        "careArtclNm": "발톱 깎기",
        "careZoneCd": "HLTC0037",
        "careCycleCd": "HLTC0042",
        "cycleDrctInptDayCnt": 14,
    }

    res = action_result(client, room, "draft_care_item", "DONE", values)

    assert res.status_code == 201
    saved = java.ai_messages(room)[-1]["cnvrsCn"]
    assert saved.startswith("✔ 케어 항목 등록 — 발톱 깎기 · ")
    assert saved.endswith(" · 14")


def test_일정_등록_결과에_날짜가_비면_400(client, java):
    room = room_of(client, java)
    values = {"petSn": CHOCO, "schdlKndCd": "HLTC0058", "hrInptYn": False, "schdlNm": "미용"}

    res = action_result(client, room, "draft_schedule", "DONE", values)

    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize(
    ("status", "message"),
    [
        ("CANCELED", "취소됨 — 일정 등록 · 저장하지 않았어요."),
        ("FAILED", "실패 — 일정 등록 · 저장하지 못했어요."),
    ],
)
def test_일정_등록_취소와_실패는_고정_글로_저장해야_한다(client, java, status, message):
    room = room_of(client, java)

    res = action_result(client, room, "draft_schedule", status, {})

    assert res.status_code == 201
    assert java.ai_messages(room)[-1]["cnvrsCn"] == message
