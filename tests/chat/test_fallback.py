import asyncio
from datetime import datetime

import pytest

from app.chat.clients import MockIntentClassifier
from app.chat.schemas import ROLE_AI, ConversationMessage, IntentKind
from app.chat.service import FALLBACK_MESSAGE, judge_intent, reply_fallback


class FakeRepository:
    def __init__(self) -> None:
        self.added: list[tuple[int, str, str]] = []

    async def add_message(self, room_sn: int, role_cd: str, cn: str) -> ConversationMessage:
        self.added.append((room_sn, role_cd, cn))
        return ConversationMessage(
            ai_cnvrs_msg_sn=10,
            role_cd=role_cd,
            cnvrs_cn=cn,
            msg_seq=len(self.added) + 1,
            reg_dt=datetime(2026, 10, 28, 10, 0),
        )


def fallback_flow(text: str, repo: FakeRepository, room_sn: int = 1):
    # SCR-AIM-002 메시지 전송이 할 순서 : 판정이 FALLBACK이면 안내 문구 저장
    intent = asyncio.run(judge_intent(text, False, MockIntentClassifier()))
    saved = None
    if intent.kind is IntentKind.FALLBACK:
        saved = asyncio.run(reply_fallback(repo, room_sn))
    return intent, saved


def test_안내_문구는_화면설계서_그대로():
    assert FALLBACK_MESSAGE == "질문을 이해하지 못했어요. 다시 입력하거나 아래에서 선택해 주세요."


def test_매칭_실패_입력은_FALLBACK이고_안내를_AI_역할로_한번_저장():
    # FN-AIM-005-01·02
    repo = FakeRepository()
    intent, saved = fallback_flow("ㅁㄴㅇㄹ", repo, room_sn=7)

    assert intent.kind is IntentKind.FALLBACK
    assert repo.added == [(7, ROLE_AI, FALLBACK_MESSAGE)]
    assert ROLE_AI == "AIMC0025"
    assert saved.role_cd == ROLE_AI
    assert saved.cnvrs_cn == FALLBACK_MESSAGE


@pytest.mark.parametrize("text", ["바보야", "꺼져", "멍청한 AI"])
def test_부적절_입력도_같은_폴백(text):
    # FN-AIM-005-07 : 별도 필터 없이 같은 문구
    repo = FakeRepository()
    intent, _ = fallback_flow(text, repo)

    assert intent.kind is IntentKind.FALLBACK
    assert repo.added == [(1, ROLE_AI, FALLBACK_MESSAGE)]


@pytest.mark.parametrize(
    "text", ["병원 찾아줘", "강아지가 포도 먹어도 돼?", "내일 3시 병원 일정 잡아줘"]
)
def test_매칭되면_폴백_문구를_저장하지_않는다(text):
    repo = FakeRepository()
    intent, saved = fallback_flow(text, repo)

    assert intent.kind is not IntentKind.FALLBACK
    assert saved is None
    assert repo.added == []
