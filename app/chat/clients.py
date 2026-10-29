import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Protocol

import anthropic
import httpx2
from anthropic import AsyncAnthropic
from fastapi import Depends
from pydantic import BaseModel, ValidationError

from app.chat import rules
from app.core.config import AiMode, Settings, get_settings

logger = logging.getLogger(__name__)

MOCK_TITLE_LENGTH = 30
# 이 길이 이하의 첫 메시지는 LLM 없이 그대로 제목으로 쓴다(짧은 입력에 뜻이 덧붙지 않게)
SHORT_TITLE_LENGTH = 15
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
        if len(first_message.strip()) <= SHORT_TITLE_LENGTH:
            return first_message.strip()
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
    # SEARCH일 때 답과 관련된 화면(FN-AIM-002-04 연관 바로가기). 매핑표에 있는 행만
    related_scr_id: str | None = None
    related_param: str | None = None


class ClassifyError(Exception):
    """분류 LLM 장애(API 오류·시간 초과). reason은 로그용 실패 종류(원문 없음)"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class IntentClassifier(Protocol):
    # FN-AIM-004-02 : 룰 매칭에 실패한 입력에만 부르는 보조 분류. 장애면 ClassifyError
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
    # SEARCH일 때 답과 관련된 화면 번호(FN-AIM-002-04)
    related_num: int | None = None


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
        "ROUTE가 아니면 route_num은 null.\n"
        "SEARCH이고 답과 관련된 화면이 아래에 있으면 related_num에 그 번호를, "
        "없으면 null을 쓴다.\n\n"
        f"화면 목록(번호. 화면명: 키워드)\n{screens}"
    )


def _routable_row(num: int | None) -> rules.RouteRow | None:
    return next((row for row in rules.routing_table() if row.no == num and row.routable), None)


def _route_of(num: int | None) -> Classified:
    # 매핑표에 없는 번호나 라우팅 대상이 아닌 행은 판단 못 함으로 본다
    row = _routable_row(num)
    if row is None:
        return Classified(ClassifiedKind.UNKNOWN)
    return Classified(ClassifiedKind.ROUTE, scr_id=row.scr_id, param=row.param)


def _search_of(related_num: int | None) -> Classified:
    # 연관 화면 번호가 매핑표에 없으면 바로가기 없이 검색
    row = _routable_row(related_num)
    if row is None:
        return Classified(ClassifiedKind.SEARCH)
    return Classified(ClassifiedKind.SEARCH, related_scr_id=row.scr_id, related_param=row.param)


class AnthropicIntentClassifier:
    # FN-AIM-004-02 : API 오류·시간 초과는 ClassifyError(→ error 이벤트, 2026-10-29 결정).
    # 거절·깨진 출력은 입력 탓으로 보고 UNKNOWN(→ FN-AIM-004-12 폴백)
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
            reason = _failure_reason(error)
            _log_failure("의도 분류", started, reason)
            raise ClassifyError(reason) from error
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
        if output.kind is ClassifiedKind.SEARCH:
            return _search_of(output.related_num)
        return Classified(output.kind)


def get_intent_classifier(
    settings: Annotated[Settings, Depends(get_settings)],
) -> IntentClassifier:
    if settings.ai_mode is AiMode.MOCK:
        return MockIntentClassifier()
    return AnthropicIntentClassifier(get_anthropic_client(settings), settings.llm_model)


class AnswerError(Exception):
    """답변 생성 실패. reason은 로그용 실패 종류(원문 없음)"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AnswerGenerator(Protocol):
    # FN-AIM-002-02 : 답변을 생성되는 대로 조각으로 낸다. 실패하면 AnswerError
    def stream(self, messages: list[dict], max_tokens: int) -> AsyncIterator[str]: ...


class MockAnswerGenerator:
    # AI_MODE=mock 전용 : LLM 없이 받은 컨텍스트 크기를 알려 주는 고정 문장을 몇 조각으로 낸다
    async def stream(self, messages: list[dict], max_tokens: int) -> AsyncIterator[str]:
        for chunk in (
            "(mock 답변) ",
            f"대화 메시지 {len(messages)}개를 받았습니다. ",
            "실제 답변은 AI_MODE=real에서 나옵니다.",
        ):
            yield chunk


# FN-AIM-002-08·09 : 개인 데이터는 모른다고 보고 화면 안내, 진단 대신 수의사 상담 안내.
# 의료 고지 문구는 서비스가 붙이므로 여기서 쓰게 하지 않는다
ANSWER_SYSTEM = (
    "너는 반려동물 케어 앱의 AI 매니저다. 반려동물 보호자의 질문에 한국어로 답한다.\n"
    "- 너는 사용자의 반려동물 기록, 일정, 다녀온 병원 같은 앱 안의 개인 데이터를 볼 수 없다. "
    "그런 내용을 물으면 추측하지 말고 앱의 해당 화면(케어 캘린더, 건강 기록 등)에서 "
    "확인하라고 안내한다.\n"
    "- 진단이나 처방을 하지 않는다. 증상을 물으면 일반적인 정보를 주고 "
    "수의사 상담을 권한다. 응급으로 보이면 바로 동물병원에 가라고 먼저 말한다.\n"
    "- 답 끝에 의료 고지 문구를 따로 쓰지 않는다."
)


class AnthropicAnswerGenerator:
    # FN-AIM-002-02 : 대화 메시지 텍스트만 보낸다(FN-AIM-011-16 반려동물 기록은 보내지 않음)
    def __init__(self, client: AsyncAnthropic, model: str):
        self.client = client
        self.model = model

    async def stream(self, messages: list[dict], max_tokens: int) -> AsyncIterator[str]:
        started = time.monotonic()
        length = 0
        try:
            async with self.client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                system=ANSWER_SYSTEM,
                messages=messages,
                output_config={"effort": LLM_EFFORT},
            ) as stream:
                async for text in stream.text_stream:
                    length += len(text)
                    yield text
                final = await stream.get_final_message()
        except anthropic.APIError as error:
            reason = _failure_reason(error)
            _log_failure("답변", started, reason)
            raise AnswerError(reason) from None
        except httpx2.HTTPError as error:
            # 스트림 도중 끊김은 SDK 오류로 감싸이지 않고 올라올 수 있다
            reason = "timeout" if isinstance(error, httpx2.TimeoutException) else "network"
            _log_failure("답변", started, reason)
            raise AnswerError(reason) from None
        if final.stop_reason == "refusal":
            _log_failure("답변", started, "refusal")
            raise AnswerError("refusal")
        logger.info(
            "LLM 답변: 메시지 %d개 → %d자 %s (%.0fms)",
            len(messages),
            length,
            final.stop_reason,
            (time.monotonic() - started) * 1000,
        )


def get_answer_generator(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AnswerGenerator:
    if settings.ai_mode is AiMode.MOCK:
        return MockAnswerGenerator()
    return AnthropicAnswerGenerator(get_anthropic_client(settings), settings.llm_model)
