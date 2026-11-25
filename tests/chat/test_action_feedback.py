"""사람 확인 피드백 2차 (SCR-AIM-012, 2026-11-25 SJM 피드백)
- 카드·결과 요약의 수치 단위(체중 kg 등, 코드 칸 이름으로)
- 회원이 말한 수를 Java 소수 자리로 반올림했으면 카드 턴 글에 알림
- 실행 실패(Java 400 칸 오류) 저장 글은 Java 칸 이름·문구 대신 칸 표시 이름으로"""

import pytest

from app.chat import rules
from app.chat.service import ACTION_FAILED_FIX_UNNAMED
from tests.chat.conftest import AJAX
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_action import WEIGHT, action_result, send
from tests.chat.test_action_chat_confirm import done_of
from tests.chat.test_messages import MessageJava
from tests.chat.test_register import CHOCO, TODAY
from tests.chat.test_tools import room_of, use_agent

HEALTH = "draft_daily_health_record"
MEAL = "HLTC0015"
WATER = "HLTC0016"
WALK = "HLTC0018"
RECORDED = {"petSn": CHOCO, "dailyRcdIdctCd": WEIGHT, "rcdDt": "2026-09-29T08:30:00"}


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


def card_text(client, java, said: str, **raw) -> str:
    args = {"daily_rcd_idct_cd": WEIGHT, "rcd_ymd": TODAY.isoformat(), "rcd_tm": "08:30"} | raw
    use_agent(client, FakeToolAgent(HEALTH, args))
    room = room_of(client, java, pet_sn=CHOCO)
    return done_of(send(client, room, said))["message"]["cnvrsCn"]


@pytest.mark.parametrize(
    ("code", "value", "expected"),
    [
        (WEIGHT, 4.57, "· 4.57kg"),
        (MEAL, 120, "· 120g"),
        (WATER, 300, "· 300ml"),
        (WALK, 30, "· 30분"),
    ],
)
def test_일지_카드_요약에_항목별_단위가_붙는다(client, java, code, value, expected):
    text = card_text(client, java, "기록해 줘", daily_rcd_idct_cd=code, rcd_nvl=value)

    assert text.splitlines()[1].endswith(expected)


def test_말한_수를_반올림했으면_카드_턴_글에_알린다(client, java):
    text = card_text(client, java, "탄이 체중 4.567kg로 바꿔줘", rcd_nvl=4.567)

    lines = text.splitlines()
    assert lines[1].endswith("· 4.57kg")
    assert "소수 둘째 자리까지라 4.57kg로 적을게요." in lines


def test_반려동물_정보_수정_몸무게에도_kg와_반올림_알림이_붙는다(client, java):
    # 코드 칸이 없는 수치 칸(petBdwg) : LLM 칸 설명의 단위 "kg 숫자만" (검증 1회차)
    use_agent(client, FakeToolAgent("draft_pet_update", {"pet_bdwg": 4.567}))
    room = room_of(client, java, pet_sn=CHOCO)

    text = done_of(send(client, room, "초코 체중 4.567kg로 바꿔줘"))["message"]["cnvrsCn"]

    lines = text.splitlines()
    assert lines[1].endswith("— 4.57kg")
    assert "소수 둘째 자리까지라 4.57kg로 적을게요." in lines


def test_반올림하지_않았으면_알림이_없다(client, java):
    text = card_text(client, java, "체중 4.5kg 기록해 줘", rcd_nvl=4.5)

    assert "자리까지라" not in text


def test_결과_요약에도_단위가_붙는다(client, java):
    room = room_of(client, java)
    values = RECORDED | {"dailyRcdIdctCd": WATER, "rcdNvl": 300}

    res = action_result(client, room, HEALTH, "DONE", values)

    assert res.json()["data"]["cnvrsCn"].endswith("· 300ml")


def result(client, java, status: str, values: dict, errors: list[dict]) -> str:
    room = room_of(client, java)
    body = {"tool": HEALTH, "status": status, "input": values, "errors": errors}
    res = client.post(f"/ai/conversations/{room}/action-result", json=body, headers=AJAX)
    assert res.status_code == 201
    return res.json()["data"]["cnvrsCn"]


def test_실행_실패_글은_칸_표시_이름으로_다시_확인을_안내한다(client, java):
    errors = [{"field": "rcdNvl", "message": "입력값이 올바르지 않습니다"}]

    text = result(client, java, "FAILED", RECORDED | {"rcdNvl": 250}, errors)

    head = "실패 — 건강 일지 기록 · 체중 · 09-29(화) 08:30 · 250kg · 저장하지 못했어요."
    assert text.startswith(head)
    assert text.endswith("다시 확인해 주세요.")
    assert text != f"{head} {ACTION_FAILED_FIX_UNNAMED}"
    assert "rcdNvl" not in text
    assert "입력값이 올바르지 않습니다" not in text


def test_실행_실패_칸에_표시_이름이_없으면_입력값을_확인하라고_한다(client, java):
    errors = [{"field": "lines[0].idmptDmndId", "message": "공백일 수 없습니다"}]

    text = result(client, java, "FAILED", RECORDED | {"rcdNvl": 250}, errors)

    assert text.endswith(ACTION_FAILED_FIX_UNNAMED)
    assert "idmptDmndId" not in text
    assert "공백일 수 없습니다" not in text


def test_errors가_없으면_실패_글은_그대로(client, java):
    text = result(client, java, "FAILED", RECORDED | {"rcdNvl": 250}, [])

    assert text.endswith("저장하지 못했어요.")


def test_DONE에_온_errors는_무시한다(client, java):
    text = result(client, java, "DONE", RECORDED | {"rcdNvl": 4.2}, [{"field": "rcdNvl"}])

    assert text == "✔ 건강 일지 기록 — 체중 · 09-29(화) 08:30 · 4.2kg"
