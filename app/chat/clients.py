import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Protocol

from fastapi import Depends

from app.core.config import AiMode, Settings, get_settings

MOCK_TITLE_LENGTH = 30
# mock 분류기가 질문으로 보는 표현
MOCK_QUESTION = re.compile(r"[?？]|뭐|왜|어떻게|알려|어때|될까|되나|나요|까요")


class TitleGenerator(Protocol):
    async def generate(self, first_message: str) -> str: ...


class MockTitleGenerator:
    # AI_MODE=mock 전용 : LLM 없이 첫 메시지 앞부분을 제목으로 쓴다
    async def generate(self, first_message: str) -> str:
        return first_message.strip()[:MOCK_TITLE_LENGTH]


def get_title_generator(settings: Annotated[Settings, Depends(get_settings)]) -> TitleGenerator:
    if settings.ai_mode is AiMode.MOCK:
        return MockTitleGenerator()
    # LLM 제공자는 Anthropic(2026-10-28 결정) : 키·모델 정한 뒤 연결
    raise NotImplementedError("제목 생성 real 모드는 아직 연결되지 않았습니다")


class ClassifiedKind(StrEnum):
    ROUTE = "ROUTE"
    SEARCH = "SEARCH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Classified:
    kind: ClassifiedKind
    # ROUTE일 때 매핑표의 화면 ID·파라미터. 매핑표에 없으면 서비스가 버린다
    scr_id: str | None = None
    param: str | None = None


class IntentClassifier(Protocol):
    # FN-AIM-004-02 : 룰 매칭에 실패한 입력에만 부르는 보조 분류
    async def classify(self, text: str) -> Classified: ...


class MockIntentClassifier:
    # AI_MODE=mock 전용 : 질문 표현이 있으면 검색, 아니면 판단 못 함
    async def classify(self, text: str) -> Classified:
        if MOCK_QUESTION.search(text):
            return Classified(ClassifiedKind.SEARCH)
        return Classified(ClassifiedKind.UNKNOWN)


def get_intent_classifier(
    settings: Annotated[Settings, Depends(get_settings)],
) -> IntentClassifier:
    if settings.ai_mode is AiMode.MOCK:
        return MockIntentClassifier()
    # LLM 제공자는 Anthropic(2026-10-28 결정) : 키·모델 정한 뒤 연결
    raise NotImplementedError("의도 분류 real 모드는 아직 연결되지 않았습니다")
