"""확인 카드 빈 칸 되물음 다듬기 (SCR-AIM-013·012, 2026-11-24 frontend-66 요청)
- 사진(file) 칸은 React가 카드에 붙이므로 말로 묻지 않고, 사진 칸만 비면 확인 말에 실행 지시
- 빈 칸 이름에 Java 칸 이름(hrInptYn 등)을 쓰지 않는다
- lesion-card memoCn에 규칙 버전을 넣지 않는다(로그에만)"""

import logging
import re

import pytest

from app.chat import rules, service, tools
from app.chat.service import ACTION_ASK_PHOTO, ACTION_EXECUTE_MESSAGE, ACTION_EXECUTE_PHOTO_MESSAGE
from tests.chat.fakes import FakeCardReplyAgent, FakeToolAgent
from tests.chat.test_action import send
from tests.chat.test_action_chat_confirm import done_of
from tests.chat.test_lesion_card import NOW, analyzed, post
from tests.chat.test_messages import MessageJava
from tests.chat.test_register import CHOCO
from tests.chat.test_tools import room_of, use_agent

JAVA_NAME = re.compile(r"[A-Za-z0-9_\[\].]+")


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def now(monkeypatch):
    monkeypatch.setattr(rules, "now_kst", lambda: NOW)
    monkeypatch.setattr(rules, "today_kst", lambda: NOW.date())


def eye_card(client, room: int) -> dict:
    findings = [{"lesionCd": "discharge", "lesionNm": "눈곱", "cnfdnc": "HIGH"}]
    body = analyzed("EYE", grade="OBSERVE", findings=findings)
    return post(client, room, body).json()["data"]["action"]


def test_눈_카드에_확인_말이면_사진_칸만_비어도_실행을_지시한다(client, java):
    room = room_of(client, java, pet_sn=CHOCO)
    card = eye_card(client, room)
    assert card["missing"] == ["file"]
    agent = use_agent(client, FakeCardReplyAgent())

    done = done_of(send(client, room, "등록해 줘", action=card))

    assert len(agent.decides) == 1
    assert done["execute"] is True
    # 사진 칸만 빈 카드의 확인 말 : 버튼을 말하지 않는 사진 안내 (2026-11-24 LJS 결정)
    assert done["message"]["cnvrsCn"] == ACTION_EXECUTE_PHOTO_MESSAGE
    assert "file" not in done["message"]["cnvrsCn"]
    # 카드 missing에는 사진 칸을 그대로 둔다(React가 붙일 칸)
    assert done["action"]["missing"] == ["file"]


def test_피부_카드에_확인_말이면_부위만_한국어로_묻고_사진_칸은_묻지_않는다(client, java):
    room = room_of(client, java, pet_sn=CHOCO)
    card = post(client, room, analyzed()).json()["data"]["action"]
    use_agent(client, FakeCardReplyAgent())

    done = done_of(send(client, room, "등록해 줘", action=card))

    text = done["message"]["cnvrsCn"]
    assert done["execute"] is False
    assert text.startswith("아직 ")
    assert "file" not in text
    assert "obsrvRegnCd" not in text


def test_관찰_기록_카드도_사진_칸만_비면_확인_말에_실행을_지시한다(client, java):
    room = room_of(client, java, pet_sn=CHOCO)
    use_agent(client, FakeCardReplyAgent())
    prior = {
        "tool": "draft_observation_cycle",
        "input": {"petSn": CHOCO, "obsrvArtclSn": 5, "obsrvDt": "2026-11-24T09:00:00"},
    }

    done = done_of(send(client, room, "등록해 줘", action=prior))

    assert done["execute"] is True
    assert done["action"]["missing"] == ["file"]
    assert done["message"]["cnvrsCn"] == ACTION_EXECUTE_PHOTO_MESSAGE


def test_사진_칸이_없는_카드의_확인_말은_등록할게요_그대로(client, java):
    room = room_of(client, java, pet_sn=CHOCO)
    use_agent(client, FakeCardReplyAgent())
    prior = {"tool": "draft_expense_limit", "input": {"mmExpndLimAmt": 300000}}

    done = done_of(send(client, room, "등록해 줘", action=prior))

    assert done["execute"] is True
    assert done["message"]["cnvrsCn"] == ACTION_EXECUTE_MESSAGE


def test_대화로_만든_관찰_항목_카드_턴_글에_사진_안내가_있고_버튼_말은_없다(client, java):
    room = room_of(client, java, pet_sn=CHOCO)
    use_agent(client, FakeToolAgent("draft_observation_item", {"obsrv_artcl_nm": "털 빠짐"}))

    done = done_of(send(client, room, "초코 털 빠짐 관찰 항목 등록해 줘"))

    text = done["message"]["cnvrsCn"]
    assert "file" in done["action"]["missing"]
    assert ACTION_ASK_PHOTO in text.split("\n")
    assert "[확인]" not in text
    assert "버튼" not in text


def test_피부_분석_카드_턴_글에는_사진_안내가_없다(client, java):
    room = room_of(client, java, pet_sn=CHOCO)

    data = post(client, room, analyzed()).json()["data"]

    assert "file" in data["action"]["missing"]
    assert ACTION_ASK_PHOTO not in data["messages"][-1]["cnvrsCn"]


def test_날짜_없는_일정_카드의_되물음에_hrInptYn이_없다(client, java):
    room = room_of(client, java, pet_sn=CHOCO)
    use_agent(client, FakeCardReplyAgent())
    prior = {"tool": "draft_schedule", "input": {"petSn": CHOCO}}

    done = done_of(send(client, room, "등록해 줘", action=prior))

    text = done["message"]["cnvrsCn"]
    assert done["execute"] is False
    assert "hrInptYn" not in text
    assert "날짜" in text
    assert "schdlDt" in done["action"]["missing"]


def test_모든_카드_도구의_빈_칸_이름에_Java_칸_이름이_없다():
    entries = tools.active_catalog().entries
    names = entries.keys() if isinstance(entries, dict) else [e.name for e in entries]
    checked = 0
    for name in names:
        entry = tools.card_entry(name)
        if entry is None:
            continue
        card = service.action_card(entry, {}, [], [], None, None)
        said = service._missing_names(card)
        assert not [n for n in said if JAVA_NAME.fullmatch(n)], (name, said)
        lines = service._missing_lines([card])
        assert all(not re.search(r"[A-Za-z]{3,}", line) for line in lines), (name, lines)
        checked += 1
    assert checked >= 10


def test_lesion_card_메모에_규칙_버전이_없고_로그에만_남는다(client, java, caplog):
    room = room_of(client, java, pet_sn=CHOCO)
    caplog.set_level(logging.INFO)

    skin = post(client, room, analyzed()).json()["data"]["action"]["input"]["memoCn"]
    eye = eye_card(client, room)["input"]["memoCn"]

    assert skin == "피부 분석 참고: 탈모(높음)·비듬(보통), 진료 권장"
    assert eye == "눈 분석 참고: 눈곱(높음), 지켜보기"
    assert "규칙" not in skin + eye
    assert "2026-11-24-draft" in caplog.text
