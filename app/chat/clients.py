import logging
import re
import time
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Protocol

import anthropic
from anthropic import AsyncAnthropic
from fastapi import Depends
from pydantic import BaseModel, ValidationError

from app.chat import rules
from app.core.config import AiMode, Settings, get_settings

logger = logging.getLogger(__name__)

MOCK_TITLE_LENGTH = 30
# 분류·짧은 생성이라 낮은 effort. thinking 토큰도 max_tokens 안에서 쓴다
LLM_EFFORT = "low"
LLM_MAX_TOKENS = 1024
# 제목 앞뒤에서 지우는 따옴표·괄호
TITLE_QUOTES = "\"'“”‘’「」『』"
# mock 분류기가 질문으로 보는 표현
MOCK_QUESTION = re.compile(r"[?？]|뭐|왜|어떻게|알려|어때|될까|되나|나요|까요")


class TitleGenerator(Protocol):
    async def generate(self, first_message: str) -> str: ...


class MockTitleGenerator:
    # AI_MODE=mock 전용 : LLM 없이 첫 메시지 앞부분을 제목으로 쓴다
    async def generate(self, first_message: str) -> str:
        return first_message.strip()[:MOCK_TITLE_LENGTH]


def _head(text: str) -> str:
    return text.strip()[:MOCK_TITLE_LENGTH]


def _log_failure(task: str, started: float, reason: str) -> None:
    # 원문은 남기지 않는다 : 실패 종류와 소요 시간만
    logger.warning("LLM %s 실패: %s (%.0fms)", task, reason, (time.monotonic() - started) * 1000)


def _failure_reason(error: anthropic.APIError) -> str:
    # 시간 초과와 API 오류를 나눠 남긴다
    if isinstance(error, anthropic.APITimeoutError):
        return "timeout"
    if isinstance(error, anthropic.APIStatusError):
        return f"api_error {error.status_code}"
    return "api_error"


@lru_cache
def _anthropic_client(api_key: str, timeout_sec: float) -> AsyncAnthropic:
    return AsyncAnthropic(api_key=api_key, timeout=timeout_sec, max_retries=1)


def get_anthropic_client(settings: Settings) -> AsyncAnthropic:
    api_key = settings.llm_api_key.get_secret_value()
    if not api_key:
        raise RuntimeError("AI_MODE=real에는 .env.local의 LLM_API_KEY가 필요합니다")
    return _anthropic_client(api_key, settings.llm_timeout_sec)


TITLE_SYSTEM = (
    "사용자가 반려동물 케어 앱의 AI 대화창에 처음 보낸 메시지를 보고 대화 제목을 만든다. "
    "한국어 한 줄, 30자 안팎으로 쓴다. 따옴표·마침표·설명 없이 제목만 쓴다."
)


class AnthropicTitleGenerator:
    # FN-AIM-011-11 : 첫 메시지만 보낸다(FN-AIM-011-16 반려동물 기록은 보내지 않음).
    # 실패해도 대화 생성을 막지 않고 mock과 같은 앞 30자를 쓴다
    def __init__(self, client: AsyncAnthropic, model: str):
        self.client = client
        self.model = model

    async def generate(self, first_message: str) -> str:
        started = time.monotonic()
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=LLM_MAX_TOKENS,
                system=TITLE_SYSTEM,
                messages=[{"role": "user", "content": first_message}],
                output_config={"effort": LLM_EFFORT},
            )
        except anthropic.APIError as error:
            _log_failure("제목 생성", started, _failure_reason(error))
            return _head(first_message)
        if response.stop_reason == "refusal":
            _log_failure("제목 생성", started, "refusal")
            return _head(first_message)
        text = next((block.text for block in response.content if block.type == "text"), "")
        title = _clean_title(text)
        logger.info(
            "LLM 제목 생성: 입력 %d자 → %d자 (%.0fms)",
            len(first_message),
            len(title),
            (time.monotonic() - started) * 1000,
        )
        return title or _head(first_message)


def _clean_title(text: str) -> str:
    # 첫 줄만, 앞뒤 따옴표·끝 마침표를 지운다
    line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return line.strip(TITLE_QUOTES).strip().rstrip(".").strip()


def get_title_generator(settings: Annotated[Settings, Depends(get_settings)]) -> TitleGenerator:
    if settings.ai_mode is AiMode.MOCK:
        return MockTitleGenerator()
    return AnthropicTitleGenerator(get_anthropic_client(settings), settings.llm_model)


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


class ClassifyOutput(BaseModel):
    # 구조화 출력 모양. route_num은 매핑표(data/routing.yaml)의 num
    kind: ClassifiedKind
    route_num: int | None = None


@lru_cache
def classify_system() -> str:
    # 매핑표에서 라우팅 대상 행만 넣는다. 고정 내용이라 매 요청 같다
    screens = "\n".join(
        f"{row.no}. {row.name}: {', '.join(row.keywords)}"
        for row in rules.routing_table()
        if row.routable
    )
    return (
        "반려동물 케어 앱 AI 대화창의 사용자 입력을 하나로 분류한다.\n"
        "- ROUTE: 아래 화면 중 하나로 가려는 요청. route_num에 그 화면 번호를 쓴다.\n"
        "- SEARCH: 반려동물이나 앱에 관해 답을 찾아 줘야 하는 질문.\n"
        "- UNKNOWN: 그 밖의 입력(뜻 없는 글자, 욕설, 판단하기 어려운 것). "
        "확실하지 않으면 UNKNOWN.\n"
        "ROUTE가 아니면 route_num은 null.\n\n"
        f"화면 목록(번호. 화면명: 키워드)\n{screens}"
    )


def _route_of(num: int | None) -> Classified:
    # 매핑표에 없는 번호나 라우팅 대상이 아닌 행은 판단 못 함으로 본다
    row = next((row for row in rules.routing_table() if row.no == num and row.routable), None)
    if row is None:
        return Classified(ClassifiedKind.UNKNOWN)
    return Classified(ClassifiedKind.ROUTE, scr_id=row.scr_id, param=row.param)


class AnthropicIntentClassifier:
    # FN-AIM-004-02 : 실패하면 UNKNOWN(→ FN-AIM-004-12 폴백)
    def __init__(self, client: AsyncAnthropic, model: str):
        self.client = client
        self.model = model

    async def classify(self, text: str) -> Classified:
        started = time.monotonic()
        try:
            response = await self.client.messages.parse(
                model=self.model,
                max_tokens=LLM_MAX_TOKENS,
                system=classify_system(),
                messages=[{"role": "user", "content": text}],
                output_config={"effort": LLM_EFFORT},
                output_format=ClassifyOutput,
            )
        except anthropic.APIError as error:
            _log_failure("의도 분류", started, _failure_reason(error))
            return Classified(ClassifiedKind.UNKNOWN)
        except ValidationError:
            # 거절·max_tokens로 끊기면 JSON이 비거나 깨진다
            _log_failure("의도 분류", started, "invalid_output")
            return Classified(ClassifiedKind.UNKNOWN)
        output = response.parsed_output
        if response.stop_reason == "refusal" or output is None:
            _log_failure("의도 분류", started, response.stop_reason or "no_output")
            return Classified(ClassifiedKind.UNKNOWN)
        logger.info(
            "LLM 의도 분류: 입력 %d자 → %s (%.0fms)",
            len(text),
            output.kind,
            (time.monotonic() - started) * 1000,
        )
        if output.kind is ClassifiedKind.ROUTE:
            return _route_of(output.route_num)
        return Classified(output.kind)


def get_intent_classifier(
    settings: Annotated[Settings, Depends(get_settings)],
) -> IntentClassifier:
    if settings.ai_mode is AiMode.MOCK:
        return MockIntentClassifier()
    return AnthropicIntentClassifier(get_anthropic_client(settings), settings.llm_model)
