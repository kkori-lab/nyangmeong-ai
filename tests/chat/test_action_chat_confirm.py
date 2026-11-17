"""확인 카드를 모달 대신 채팅으로 확인 (SCR-AIM-012 2단계, 2026-11-13 추가 요청)
- 카드 턴 : 카드 요약 글을 AI 메시지로 저장(done.message), 카드는 done.action 그대로
- 다음 턴 : 돌려받은 카드 + 확인 말이면 LLM 없이 done.execute, 취소 말이면 카드 없이 끝냄"""

import pytest

from app.chat import rules
from app.chat.service import (
    ACTION_DROP_MESSAGE,
    ACTION_EXECUTE_MESSAGE,
)
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_action import send
from tests.chat.test_messages import MessageJava, events
from tests.chat.test_register import CHOCO, TODAY
from tests.chat.test_tools import room_of, use_agent

HEALTH = "draft_daily_health_record"
WEIGHT = "HLTC0014"
FULL = {
    "petSn": CHOCO,
    "dailyRcdIdctCd": WEIGHT,
    "rcdDt": "2026-09-29T08:30:00",
    "rcdNvl": 4.2,
}


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


def done_of(response) -> dict:
    evs = events(response)
    assert evs[-1][0] == "done"
    return evs[-1][1]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("등록해 줘", rules.ACTION_CONFIRM),
        ("응", rules.ACTION_CONFIRM),
        ("네 저장해주세요!", rules.ACTION_CONFIRM),
        ("그래 등록해", rules.ACTION_CONFIRM),
        ("ㅇㅇ", rules.ACTION_CONFIRM),
        ("좋아요~", rules.ACTION_CONFIRM),
        ("아니", rules.ACTION_CANCEL),
        ("취소해 줘", rules.ACTION_CANCEL),
        ("등록하지 마", rules.ACTION_CANCEL),
        ("아니 취소해", rules.ACTION_CANCEL),
        ("4.5로 바꿔줘", None),
        ("응 근데 4.5로 바꿔줘", None),
        ("수정해 줘", None),
        ("", None),
    ],
)
def test_확인_취소_말을_가린다(text, kind):
    assert rules.action_reply_kind(text) == kind


def test_카드_턴은_요약과_확인_말_안내를_저장한다(client, java):
    use_agent(
        client,
        FakeToolAgent(
            HEALTH,
            {"daily_rcd_idct_cd": WEIGHT, "rcd_ymd": TODAY.isoformat(), "rcd_tm": "08:30"}
            | {"rcd_nvl": 4.2},
        ),
    )
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "초코 오늘 8시 반 체중 4.2kg 기록해줘"))

    text = done["message"]["cnvrsCn"]
    assert text.startswith("이렇게 할까요?\n초코 건강 일지 기록 — 체중 · 09-29(화) 08:30 · 4.2")
    assert "'등록해 줘'" in text
    assert done["action"]["tool"] == HEALTH
    assert done["execute"] is False
    assert java.ai_messages(room)[-1]["cnvrsCn"] == text


def test_빈_칸이_있는_카드_턴은_빈_칸을_말로_묻는다(client, java):
    use_agent(client, FakeToolAgent(HEALTH, {"daily_rcd_idct_cd": WEIGHT, "rcd_nvl": 4.2}))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "초코 체중 4.2kg 기록해줘"))

    assert done["action"]["missing"] == ["rcdDt"]
    assert "아직 기록 날짜가 비어 있어요" in done["message"]["cnvrsCn"]


def test_확인_말은_LLM_없이_실행을_지시한다(client, java):
    agent = FakeToolAgent(fail=True)
    use_agent(client, agent)
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "등록해 줘", action={"tool": HEALTH, "input": FULL}))

    assert agent.decides == []
    assert done["execute"] is True
    assert done["message"]["cnvrsCn"] == ACTION_EXECUTE_MESSAGE
    assert done["action"]["input"] == FULL
    assert done["action"]["missing"] == []
    assert done["action"]["call"]["method"]


def test_빈_칸이_남은_카드에_확인_말이면_실행하지_않고_빈_칸을_묻는다(client, java):
    use_agent(client, FakeToolAgent(fail=True))
    room = room_of(client, java, pet_sn=CHOCO)
    prior = {"tool": HEALTH, "input": {k: v for k, v in FULL.items() if k != "rcdDt"}}

    done = done_of(send(client, room, "응", action=prior))

    assert done["execute"] is False
    assert done["action"]["missing"] == ["rcdDt"]
    assert done["message"]["cnvrsCn"].startswith("아직 기록 날짜")


def test_취소_말은_카드_없이_끝낸다(client, java):
    agent = FakeToolAgent(fail=True)
    use_agent(client, agent)
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "아니 취소해", action={"tool": HEALTH, "input": FULL}))

    assert agent.decides == []
    assert done["action"] is None
    assert done["execute"] is False
    assert done["message"]["cnvrsCn"] == ACTION_DROP_MESSAGE


def test_돌려받은_카드가_없으면_확인_말도_지금_흐름이다(client, java):
    agent = FakeToolAgent(texts=["무엇을 등록할까요?"])
    use_agent(client, agent)
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "등록해 줘"))

    assert len(agent.decides) == 1
    assert done["execute"] is False


def test_칸을_고치는_말은_지금처럼_도구_흐름으로_간다(client, java):
    agent = FakeToolAgent(HEALTH, {"daily_rcd_idct_cd": WEIGHT, "rcd_nvl": 4.5})
    use_agent(client, agent)
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "4.5로 바꿔줘", action={"tool": HEALTH, "input": FULL}))

    assert len(agent.decides) == 1
    assert done["action"]["input"]["rcdNvl"] == 4.5
    assert done["execute"] is False
    assert "4.5" in done["message"]["cnvrsCn"]
