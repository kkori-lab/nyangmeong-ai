import re
from collections.abc import AsyncIterator
from datetime import date

from app.chat.clients import Classified, ClassifiedKind
from app.chat.rules import RouteRow

TITLE_LENGTH = 30
# 가짜 분류기가 질문으로 보는 표현
QUESTION = re.compile(r"[?？]|뭐|왜|어떻게|알려|어때|될까|되나|나요|까요")


class FakeTitleGenerator:
    """LLM 없이 첫 메시지 앞부분을 제목으로 사용"""

    async def generate(self, first_message: str) -> str:
        return first_message.strip()[:TITLE_LENGTH]


class FakeIntentClassifier:
    """질문 표현이 있으면 검색, 아니면 판단 못 함. 받은 힌트 기록"""

    def __init__(self) -> None:
        self.hints: list[RouteRow | None] = []

    async def classify(self, text: str, hint: RouteRow | None = None) -> Classified:
        self.hints.append(hint)
        if QUESTION.search(text):
            return Classified(ClassifiedKind.SEARCH)
        return Classified(ClassifiedKind.UNKNOWN)


class FakeAnswerGenerator:
    """받은 컨텍스트 크기를 알리는 고정 문장을 몇 조각으로 분할"""

    async def stream(self, messages: list[dict], max_tokens: int) -> AsyncIterator[str]:
        for chunk in ("(가짜 답변) ", f"대화 메시지 {len(messages)}개를 받았습니다."):
            yield chunk


class FakeRegisterExtractor:
    """아무 칸도 채우지 않음(빈 칸은 되물음)"""

    async def extract(self, text: str, today: date) -> dict:
        return {}
