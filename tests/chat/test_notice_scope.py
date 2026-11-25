"""바로 답 의료 고지 범위 (FN-AIM-002-03, 2026-11-25 SJM 피드백)
- 도구 없이 바로 쓴 답은 글에 건강 말이 있을 때만 고지("오늘 날씨 어때?"는 고지 없음)"""

import pytest

from app.chat import rules
from app.chat.service import DISCLAIMER
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_messages import MessageJava, deltas, events, names, send
from tests.chat.test_tools import room_of, use_agent


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("오늘 날씨 어때?", False),
        ("주말에 뭐 하지", False),
        ("혹시 비밀번호 변경은?", False),
        ("강아지가 토해요", True),
        ("강아지 포도 먹어도 돼?", True),
        ("고양이 예방접종 언제 맞아?", True),
        ("산책 얼마나 시켜야 돼?", True),
        ("털이 많이 빠져", True),
        ("눈곱이 껴요", True),
        ("설사를 해요", True),
    ],
)
def test_건강_말_판정(text, expected):
    # FN-AIM-002-03
    assert rules.is_health_topic(text) is expected


def direct(client, java, text: str) -> tuple[int, list]:
    # 도구 없이 바로 쓴 글 답(SEARCH)
    use_agent(client, FakeToolAgent(texts=("바로 쓴 ", "답이에요.")))
    room = room_of(client, java)
    evs = events(send(client, room, text))
    assert evs[0][1]["kind"] == "SEARCH"
    assert names(evs)[-1] == "done"
    return room, evs


def test_건강_말이_없는_바로_답에는_고지가_없다(client, java):
    room, evs = direct(client, java, "오늘 날씨 어때?")

    assert deltas(evs) == "바로 쓴 답이에요."
    assert java.ai_messages(room)[0]["cnvrsCn"] == "바로 쓴 답이에요."
    assert DISCLAIMER not in java.ai_messages(room)[0]["cnvrsCn"]


def test_건강_말이_있는_바로_답에는_고지가_붙는다(client, java):
    room, evs = direct(client, java, "강아지가 토해요")

    assert deltas(evs) == "바로 쓴 답이에요." + DISCLAIMER
    assert java.ai_messages(room)[0]["cnvrsCn"].endswith(DISCLAIMER)
