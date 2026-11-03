import asyncio
from datetime import datetime

import pytest

from app.chat.clients import Classified, ClassifiedKind
from app.chat.schemas import ROLE_AI, ConversationMessage, IntentKind
from app.chat.service import (
    FALLBACK_MESSAGE,
    OUT_OF_SCOPE_MESSAGE,
    judge,
    judge_intent,
    reply_fallback,
)
from tests.chat.fakes import FakeIntentClassifier


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
    intent = asyncio.run(judge_intent(text, False, FakeIntentClassifier()))
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


class OutOfScopeClassifier:
    # 서비스 범위 밖으로 답하는 분류기
    async def classify(self, text: str, hint=None) -> Classified:
        return Classified(ClassifiedKind.OUT_OF_SCOPE)


def test_범위_밖_안내_문구():
    assert OUT_OF_SCOPE_MESSAGE == (
        "반려동물 케어와 관련된 질문만 도와드릴 수 있어요. "
        "반려동물이나 서비스 이용에 관해 물어봐 주세요."
    )


@pytest.mark.parametrize("text", ["가계부 작성 방법 알려줘", "파이썬 코딩 알려줘"])
def test_서비스_범위_밖_질문은_FALLBACK이고_범위_안내를_저장(text):
    # 2026-10-30 추가 요청 : 의도는 FALLBACK 그대로(칩·연속 실패 카운트 같음), 문구만 다름
    repo = FakeRepository()
    judged = asyncio.run(judge(text, False, OutOfScopeClassifier()))
    asyncio.run(reply_fallback(repo, 3, judged.out_of_scope))

    assert judged.intent.kind is IntentKind.FALLBACK
    assert repo.added == [(3, ROLE_AI, OUT_OF_SCOPE_MESSAGE)]


def test_판단_못_함은_기존_폴백_문구():
    repo = FakeRepository()
    judged = asyncio.run(judge("ㅁㄴㅇㄹ", False, FakeIntentClassifier()))
    asyncio.run(reply_fallback(repo, 3, judged.out_of_scope))

    assert repo.added == [(3, ROLE_AI, FALLBACK_MESSAGE)]
