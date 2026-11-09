import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Protocol

import anthropic
import httpx2
from anthropic import AsyncAnthropic
from anthropic.types import Message
from fastapi import Depends
from pydantic import BaseModel, ValidationError

from app.chat import rules, tools
from app.core.config import Settings, get_settings
from app.core.llm import get_anthropic_client

logger = logging.getLogger(__name__)

HEAD_TITLE_LENGTH = 30
# 이 길이 이하의 첫 메시지는 LLM 없이 제목으로 사용 : 짧은 입력에 뜻이 덧붙는 것 방지
SHORT_TITLE_LENGTH = 15
# 분류·짧은 생성용 낮은 effort : thinking 토큰도 max_tokens에 포함
LLM_EFFORT = "low"
LLM_MAX_TOKENS = 1024
# 제목 앞뒤에서 지우는 따옴표·괄호
TITLE_QUOTES = "\"'“”‘’「」『』"


class TitleGenerator(Protocol):
    async def generate(self, first_message: str) -> str: ...

    # 실패·거절이면 빈 문자열 : 제목 그대로 유지
    async def summarize(self, question: str, answer: str) -> str: ...


def _head(text: str) -> str:
    return text.strip()[:HEAD_TITLE_LENGTH]


def _log_failure(task: str, started: float, reason: str) -> None:
    # 원문 제외 : 실패 종류와 소요 시간만 기록
    logger.warning("LLM %s 실패: %s (%.0fms)", task, reason, (time.monotonic() - started) * 1000)


def _failure_reason(error: anthropic.APIError) -> str:
    # 시간 초과·API 오류 구분 기록
    if isinstance(error, anthropic.APITimeoutError):
        return "timeout"
    if isinstance(error, anthropic.APIStatusError):
        return f"api_error {error.status_code}"
    return "api_error"


TITLE_SYSTEM = (
    "사용자가 반려동물 케어 앱의 AI 대화창에 처음 보낸 메시지를 보고 대화 제목을 만든다. "
    "한국어 한 줄, 20자 안팎으로 30자를 넘지 않게 쓴다. 따옴표·마침표·설명 없이 제목만 쓴다."
)

SUMMARY_TITLE_SYSTEM = (
    "반려동물 케어 앱의 AI 대화창에서 사용자의 첫 질문과 AI의 첫 답변을 보고 대화 제목을 만든다. "
    "질문에 없는 뜻을 덧붙이지 말고 대화가 다룬 내용을 요약한다. "
    "한국어 한 줄, 20자 안팎으로 30자를 넘지 않게 쓴다. 따옴표·마침표·설명 없이 제목만 쓴다."
)


class AnthropicTitleGenerator:
    # FN-AIM-011-11 : 첫 메시지만 전송 (FN-AIM-011-16 반려동물 기록 제외)
    # 실패해도 대화 생성 유지 : mock과 같은 앞 30자 사용
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

    async def summarize(self, question: str, answer: str) -> str:
        # 추가 요청(SCR-AIM-011) : 첫 답변까지 보고 제목 다시 생성, 실패하면 빈 문자열
        started = time.monotonic()
        content = f"질문:\n{question}\n\n답변:\n{answer}"
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=LLM_MAX_TOKENS,
                system=SUMMARY_TITLE_SYSTEM,
                messages=[{"role": "user", "content": content}],
                output_config={"effort": LLM_EFFORT},
            )
        except anthropic.APIError as error:
            _log_failure("제목 요약", started, _failure_reason(error))
            return ""
        if response.stop_reason == "refusal":
            _log_failure("제목 요약", started, "refusal")
            return ""
        text = next((block.text for block in response.content if block.type == "text"), "")
        title = _clean_title(text)
        logger.info(
            "LLM 제목 요약: 입력 %d자 → %d자 (%.0fms)",
            len(content),
            len(title),
            (time.monotonic() - started) * 1000,
        )
        return title


def _clean_title(text: str) -> str:
    # 첫 줄만, 앞뒤 따옴표·끝 마침표 제거
    line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return line.strip(TITLE_QUOTES).strip().rstrip(".").strip()


def get_title_generator(settings: Annotated[Settings, Depends(get_settings)]) -> TitleGenerator:
    return AnthropicTitleGenerator(get_anthropic_client(settings), settings.llm_model)


class ClassifiedKind(StrEnum):
    ROUTE = "ROUTE"
    SEARCH = "SEARCH"
    UNKNOWN = "UNKNOWN"
    # 서비스 범위 밖 질문(2026-10-30) : 폴백이지만 안내 문구가 다름
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    # 앱 기능의 위치·사용법 질문(2026-11-05) : 안내서 근거 답변, 응답 intent는 SEARCH
    GUIDE = "GUIDE"


@dataclass(frozen=True)
class Classified:
    kind: ClassifiedKind
    # ROUTE일 때 매핑표의 화면 ID·파라미터 : 매핑표에 없으면 서비스가 폐기
    scr_id: str | None = None
    param: str | None = None
    # SEARCH일 때 답과 관련된 화면(FN-AIM-002-04 연관 바로가기). 매핑표에 있는 행만
    related_scr_id: str | None = None
    related_param: str | None = None
    # GUIDE일 때 안내서 목차에서 고른 청크. 안내서에 없는 id는 None
    guide_id: str | None = None


class ClassifyError(Exception):
    """분류 LLM 장애(API 오류·시간 초과). reason은 로그용 실패 종류(원문 없음)"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class IntentClassifier(Protocol):
    # FN-AIM-004-02 : 룰 매칭에 실패한 입력에만 부르는 보조 분류. 장애면 ClassifyError
    # hint : 키워드에 걸린 질문꼴 입력의 룰 행(서비스 범위 확인용, 2026-10-30)
    async def classify(self, text: str, hint: rules.RouteRow | None = None) -> Classified: ...


class ClassifyOutput(BaseModel):
    # 구조화 출력 모양. route_num은 매핑표(data/routing.yaml)의 num
    kind: ClassifiedKind
    route_num: int | None = None
    # SEARCH·GUIDE일 때 답과 관련된 화면 번호(FN-AIM-002-04)
    related_num: int | None = None
    # GUIDE일 때 안내서 목차의 청크 번호(2단계 목차 선택)
    guide_id: str | None = None


@lru_cache
def classify_system() -> str:
    # 매핑표의 라우팅 대상 행만 : 고정 내용이라 매 요청 동일
    screens = "\n".join(
        f"{row.no}. {row.name}: {', '.join(row.keywords)}"
        for row in rules.routing_table()
        if row.routable
    )
    return (
        "반려동물 케어 앱 AI 대화창의 사용자 입력을 하나로 분류한다.\n"
        "서비스 범위: 반려동물의 건강·증상·질병·사료·간식·행동·훈련·미용·산책·병원·"
        "케어 일정, 반려동물 지출(가계부), 이 앱의 화면과 기능 사용법.\n"
        "병원·진료·미용·산책·사료·간식·예방접종·펫시터처럼 이 앱에서 반려동물 일로 읽히는 "
        "말과 알림·설정·게시판처럼 앱 기능을 가리키는 말은 그것만으로 범위 안이다. "
        "가계부·일정·지출처럼 앱 밖 일상에서도 쓰는 말은 "
        "반려동물(반려동물·강아지·고양이·우리 아이·반려동물 이름 등)이나 이 앱(앱·여기·"
        "이 화면 등)을 가리키는 말이 함께 없으면, 그 일반 방법·지식을 묻는 질문은 범위 밖이다. "
        "예: '가계부 작성 방법 알려줘'·'일정 관리 잘하는 법'은 OUT_OF_SCOPE,"
        "'강아지 가계부 쓰는 법 알려줘'·'앱에서 가계부 어떻게 써'·'병원 어디가 좋아?'는 범위 안.\n"
        "- ROUTE: 서비스 범위 안에서 아래 화면 중 하나로 가려는 요청. "
        "route_num에 그 화면 번호를 쓴다.\n"
        "- GUIDE: 서비스 범위 안에서 이 앱 기능의 위치나 사용 방법을 묻는 질문"
        "(예: '캐릭터 어디서 만들어?'·'가족 초대 어떻게 해?'·'알림 어디서 꺼?'). "
        "guide_id에 아래 안내서 목차에서 가장 맞는 번호 하나를, 맞는 것이 없으면 null을 쓴다. "
        "화면 키워드가 들어 있어도 그 기능의 위치·사용법을 물으면 ROUTE가 아니라 GUIDE.\n"
        "- SEARCH: 서비스 범위 안에서 답을 찾아 줘야 하는 그 밖의 질문"
        "(반려동물 건강·생활 정보 등).\n"
        "- OUT_OF_SCOPE: 뜻은 분명하지만 서비스 범위 밖인 질문·요청(반려동물·이 앱과 관계없는 "
        "일반 질문, 예: 집 가계부 쓰는 법·요리·코딩). "
        "화면 키워드가 들어 있어도 서비스 범위 밖이면 OUT_OF_SCOPE.\n"
        "- UNKNOWN: 그 밖의 입력(뜻 없는 글자, 욕설, 판단하기 어려운 것). "
        "확실하지 않으면 UNKNOWN.\n"
        "ROUTE가 아니면 route_num은 null. GUIDE가 아니면 guide_id는 null.\n"
        "SEARCH·GUIDE이고 답과 관련된 화면이 아래에 있으면 related_num에 그 번호를, "
        "없으면 null을 쓴다.\n\n"
        f"화면 목록(번호. 화면명: 키워드)\n{screens}\n\n"
        f"안내서 목차(번호 화면명 · 할 일)\n{_guide_toc()}"
    )


def _guide_toc() -> str:
    return "\n".join(
        f"- {chunk.id} {chunk.screen or '공통'} · {chunk.title}" for chunk in rules.guide_chunks()
    )


def classify_system_blocks(hint: rules.RouteRow | None = None) -> list[dict]:
    # 고정 규칙·목차(약 7,800토큰)는 캐시, 요청마다 다른 키워드 힌트는 캐시 뒤 블록
    blocks: list[dict] = [
        {"type": "text", "text": classify_system(), "cache_control": {"type": "ephemeral"}}
    ]
    note = _hint_note(hint)
    if note:
        blocks.append({"type": "text", "text": note.strip()})
    return blocks


def _routable_row(num: int | None) -> rules.RouteRow | None:
    return next((row for row in rules.routing_table() if row.no == num and row.routable), None)


def _route_of(num: int | None) -> Classified:
    # 매핑표에 없는 번호·라우팅 대상 아닌 행 : 판단 못 함 처리
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


def _guide_of(output: ClassifyOutput) -> Classified:
    # 목차에 없는 번호는 버림 : M1 결과도 없으면 서비스가 범위 안내
    related = _search_of(output.related_num)
    chunk = rules.find_guide(output.guide_id)
    return Classified(
        ClassifiedKind.GUIDE,
        related_scr_id=related.related_scr_id,
        related_param=related.related_param,
        guide_id=chunk.id if chunk else None,
    )


def _hint_note(hint: rules.RouteRow | None) -> str:
    # 키워드에 걸린 화면 알림 : 범위 안 이동이면 ROUTE, 범위 밖이면 OUT_OF_SCOPE
    if hint is None:
        return ""
    return (
        f"\n\n이 입력은 키워드로 {hint.no}번 화면({hint.name})에 걸렸다. "
        "키워드가 걸린 것만으로 범위 안이 아니다. 위 서비스 범위 규칙대로 범위 밖이면 OUT_OF_SCOPE."
        "범위 안에서 그 화면으로 가려는 요청이나 그 화면에 있는 내 기록을 묻는 질문"
        "(예: '이번 달 병원비 얼마 나왔어?')이면 ROUTE, "
        "그 화면 기능의 위치·사용법을 묻는 질문(예: '캐릭터 꾸미기 어디서 해?')이면 GUIDE, "
        "그 밖의 범위 안 질문이면 SEARCH."
    )


class AnthropicIntentClassifier:
    # FN-AIM-004-02 : API 오류·시간 초과 -> ClassifyError (error 이벤트, 2026-10-29 결정)
    # 거절·깨진 출력은 입력 탓으로 보고 UNKNOWN (FN-AIM-004-12 폴백)
    def __init__(self, client: AsyncAnthropic, model: str):
        self.client = client
        self.model = model

    async def classify(self, text: str, hint: rules.RouteRow | None = None) -> Classified:
        started = time.monotonic()
        try:
            response = await self.client.messages.parse(
                model=self.model,
                max_tokens=LLM_MAX_TOKENS,
                system=classify_system_blocks(hint),
                messages=[{"role": "user", "content": text}],
                output_config={"effort": LLM_EFFORT},
                output_format=ClassifyOutput,
            )
        except anthropic.APIError as error:
            reason = _failure_reason(error)
            _log_failure("의도 분류", started, reason)
            raise ClassifyError(reason) from error
        except ValidationError:
            # 거절·max_tokens 중단 시 JSON 비거나 깨짐
            _log_failure("의도 분류", started, "invalid_output")
            return Classified(ClassifiedKind.UNKNOWN)
        output = response.parsed_output
        if response.stop_reason == "refusal" or output is None:
            _log_failure("의도 분류", started, response.stop_reason or "no_output")
            return Classified(ClassifiedKind.UNKNOWN)
        # 목차 캐시 확인용 : input_tokens는 캐시 밖 토큰만 센다
        usage = response.usage
        logger.info(
            "LLM 의도 분류: 입력 %d자·%d토큰(캐시 읽기 %d·쓰기 %d) → %s (%.0fms)",
            len(text),
            usage.input_tokens,
            usage.cache_read_input_tokens or 0,
            usage.cache_creation_input_tokens or 0,
            output.kind,
            (time.monotonic() - started) * 1000,
        )
        if output.kind is ClassifiedKind.ROUTE:
            return _route_of(output.route_num)
        if output.kind is ClassifiedKind.SEARCH:
            return _search_of(output.related_num)
        if output.kind is ClassifiedKind.GUIDE:
            return _guide_of(output)
        return Classified(output.kind)


def get_intent_classifier(
    settings: Annotated[Settings, Depends(get_settings)],
) -> IntentClassifier:
    return AnthropicIntentClassifier(get_anthropic_client(settings), settings.llm_model)


class AnswerError(Exception):
    """답변 생성 실패. reason은 로그용 실패 종류(원문 없음)"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AnswerGenerator(Protocol):
    # FN-AIM-002-02 : 답변 조각 스트리밍, 실패 시 AnswerError
    # guide : 사용법 질문일 때 안내서에서 꺼낸 청크 글
    def stream(
        self, messages: list[dict], max_tokens: int, guide: str | None = None
    ) -> AsyncIterator[str]: ...


# FN-AIM-002-08·09 : 개인 데이터는 모른다고 보고 화면 안내, 진단 대신 수의사 상담 안내
# 의료 고지 문구는 서비스가 붙이므로 프롬프트에서 제외
PRIVATE_DATA_RULE = (
    "- 너는 사용자의 반려동물 기록, 일정, 다녀온 병원 같은 앱 안의 개인 데이터를 볼 수 없다. "
    "그런 내용을 물으면 추측하지 말고 앱의 해당 화면(케어 캘린더, 건강 기록 등)에서 "
    "확인하라고 안내한다.\n"
)
# 도구 흐름 : 건강 READ 도구 결과만 근거 (docs/design/tool-catalog.md 8절 4번)
TOOL_DATA_RULE = (
    "- 반려동물 기록·일정은 읽기 도구(get_·list_)로 받은 결과만 근거로 답한다. "
    "도구 없이 기록을 추측하지 않는다. 도구 결과에 없거나 불러오지 못했으면 "
    "앱의 해당 화면(케어 캘린더, 건강 기록 등)에서 확인하라고 안내한다.\n"
)
ANSWER_SYSTEM = (
    "너는 반려동물 케어 앱의 AI 매니저다. 반려동물 보호자의 질문에 한국어로 답한다.\n"
    f"{PRIVATE_DATA_RULE}"
    "- 진단이나 처방을 하지 않는다. 증상을 물으면 일반적인 정보를 주고 "
    "수의사 상담을 권한다. 응급으로 보이면 바로 동물병원에 가라고 먼저 말한다.\n"
    "- 답 끝에 의료 고지 문구를 따로 쓰지 않는다."
)

# FN-AIM-002-02 : 사용법 질문은 안내서에서 꺼낸 청크만 근거 (2026-11-05)
GUIDE_RULES = (
    "아래는 이 앱의 사용법 안내서에서 질문과 관련 있어 보이는 부분이다.\n"
    "- 앱 기능의 위치와 사용 방법은 이 안내서 내용만 근거로 답한다. "
    "메뉴·버튼 이름은 [ ] 안의 글자를 그대로 쓴다.\n"
    "- 준비 상태가 정상이 아닌 화면의 준비 중 기능은 곧 제공된다고 안내한다.\n"
    "- 안내서에 없는 기능이나 경로는 지어내지 않는다. 모른다고 말하고 "
    "고객센터의 FAQ나 1:1 문의를 안내한다.\n"
    "- 질문과 관계없는 항목은 쓰지 않는다. [6-1] 같은 항목 번호는 답에 쓰지 않는다.\n\n"
    "안내서\n"
)


def answer_system(guide: str | None) -> str | list[dict]:
    # 안내서는 둘째 블록 : 고정 문구인 첫 블록과 분리
    if guide is None:
        return ANSWER_SYSTEM
    return [
        {"type": "text", "text": ANSWER_SYSTEM},
        {"type": "text", "text": GUIDE_RULES + guide},
    ]


class AnthropicAnswerGenerator:
    # FN-AIM-002-02 : 대화 메시지 텍스트만 전송 (FN-AIM-011-16 반려동물 기록 제외)
    def __init__(self, client: AsyncAnthropic, model: str):
        self.client = client
        self.model = model

    async def stream(
        self, messages: list[dict], max_tokens: int, guide: str | None = None
    ) -> AsyncIterator[str]:
        started = time.monotonic()
        length = 0
        try:
            async with self.client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                system=answer_system(guide),
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
            # 스트림 도중 끊김 : SDK 오류로 감싸이지 않고 전파될 수 있음
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
    return AnthropicAnswerGenerator(get_anthropic_client(settings), settings.llm_model)


@dataclass(frozen=True)
class ToolDecision:
    """[도구 고르기 결과]
    - call : 고른 도구, None이면 글 답변(text) 또는 빈 응답
    - text : 글 답변 스트림(이미 시작한 호출의 나머지)
    - content : 응답 블록 원본 : 서버 도구 결과를 돌려줄 때 assistant 턴으로 다시 보냄"""

    call: tools.ToolCall | None = None
    text: AsyncIterator[str] | None = None
    content: tuple[dict, ...] = ()


class ReadMore(str):
    """follow 결과 글 : 이 결과 뒤 한 번 더 도구를 고를 수 있음 (READ 2번 뒤 수정 카드, 2단계 ②)"""


# 결과 답변 중 LLM이 고른 두 번째 도구 실행 : 결과 글, 읽기 도구가 아니면 None
FollowRead = Callable[[tools.ToolCall], Awaitable[str | None]]
# 결과 답변에서 도구를 고르는 최대 횟수 : 두 번째는 follow가 ReadMore를 줄 때만
FOLLOW_ROUNDS = 2


class ToolAgent(Protocol):
    # docs/design/tool-calling.md 4절 : 분류·목차 선택·등록 칸 추출을 도구 고르기 한 번으로
    # decide 장애면 ClassifyError, 글 스트림 장애면 AnswerError
    # answer의 follow : 있으면 결과를 본 LLM이 읽기 도구를 한 번 더 고름(한 턴 READ 최대 2번)
    async def decide(
        self, messages: list[dict], max_tokens: int, today: date, hint: rules.RouteRow | None = None
    ) -> ToolDecision: ...

    def answer(
        self,
        messages: list[dict],
        decision: ToolDecision,
        result: str,
        max_tokens: int,
        today: date,
        follow: FollowRead | None = None,
    ) -> AsyncIterator[str]: ...


TOOL_RULES = (
    "도구\n"
    "- 회원의 말에 맞는 도구가 있으면 그 도구 하나만 부른다. "
    "도구를 부를 때는 앞에 글을 쓰지 않는다.\n"
    "- 서비스 범위 안의 반려동물 건강·생활 정보 질문은 도구 없이 바로 답한다.\n"
    "- 두 도구가 다 맞아 보이면 도구 없이 무엇을 원하는지 짧게 되묻는다.\n"
    "- 도구 인자는 회원이 말한 것만 채우고 모르는 칸은 비운다.\n"
    "- 읽기 도구 결과를 받은 뒤 상세가 더 필요하면 읽기 도구를 한 번 더 부를 수 있다. "
    "번호 칸(…_sn)은 받은 결과에 나온 번호만 쓴다.\n"
)


@lru_cache
def tool_system() -> str:
    # 고정 내용 : 도구 정의와 함께 캐시(tools → system 순서로 캐시 앞부분)
    scope = classify_system().split("- ROUTE:", 1)[0].split("\n", 1)[1]
    guide_rules = GUIDE_RULES.removesuffix("\n\n안내서\n")
    return (
        f"{ANSWER_SYSTEM.replace(PRIVATE_DATA_RULE, TOOL_DATA_RULE)}\n\n{scope}\n{TOOL_RULES}\n"
        f"search_guide 결과로 받은 안내서로 답할 때\n{guide_rules}\n\n"
        f"화면 목록(번호. 화면명: 키워드)\n{tools.screen_list()}\n\n"
        f"안내서 목차(번호 화면명 · 할 일)\n{_guide_toc()}"
    )


def _tool_hint(hint: rules.RouteRow | None) -> str:
    if hint is None:
        return ""
    return (
        f"이 입력은 키워드로 '{hint.name}' 화면({hint.scr_id})에 걸렸다. "
        "키워드가 걸린 것만으로 범위 안이 아니다. 범위 밖이면 decline, "
        "그 화면으로 가려는 요청이나 그 화면에 있는 내 기록을 묻는 질문이면 navigate"
        "(건강 기록·일정·검진·약·지출의 내용을 묻는 질문에 맞는 읽기 도구가 있으면 그 도구), "
        "그 화면 기능의 위치·사용법을 묻는 질문이면 search_guide."
    )


def tool_system_blocks(today: date, hint: rules.RouteRow | None = None) -> list[dict]:
    # 오늘 날짜·키워드 힌트는 요청마다 달라 캐시 뒤 블록
    blocks: list[dict] = [
        {"type": "text", "text": tool_system(), "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": f"오늘: {today.isoformat()} ({rules.WEEKDAYS[today.weekday()]})"},
    ]
    note = _tool_hint(hint)
    if note:
        blocks.append({"type": "text", "text": note})
    return blocks


# 도구는 한 번에 하나 : 답 없는 질문이 이력에 둘이면 tool_use를 여럿 냄(2026-11-06 방 143 재현)
# none에는 붙일 수 없음(400 Extra inputs)
TOOL_CHOICE_AUTO = {"type": "auto", "disable_parallel_tool_use": True}
TOOL_CHOICE_NONE = {"type": "none"}


def _stream_failure(error: Exception) -> str:
    if isinstance(error, anthropic.APIError):
        return _failure_reason(error)
    return "timeout" if isinstance(error, httpx2.TimeoutException) else "network"


class AnthropicToolAgent:
    """[도구 고르기 LLM]
    - 스트리밍 한 번 : 첫 블록이 글이면 그대로 답변, 도구면 끝까지 받아 인자 검증
    - on_usage : 평가 스크립트의 토큰 집계용(앱은 없음)"""

    def __init__(
        self,
        client: AsyncAnthropic,
        model: str,
        on_usage: Callable[[str, object], None] | None = None,
    ):
        self.client = client
        self.model = model
        self.on_usage = on_usage

    def _request(self, messages: list[dict], max_tokens: int, system: list[dict]) -> dict:
        return {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "tools": list(tools.tool_definitions()),
            "messages": messages,
            "output_config": {"effort": LLM_EFFORT},
        }

    async def _events(self, request: dict) -> AsyncIterator[object]:
        # 원시 이벤트 뒤에 마지막으로 완성 메시지 : 글 스트림이 같은 호출을 이어 읽게
        async with self.client.messages.stream(**request) as stream:
            async for event in stream:
                yield event
            yield await stream.get_final_message()

    async def decide(
        self, messages: list[dict], max_tokens: int, today: date, hint: rules.RouteRow | None = None
    ) -> ToolDecision:
        started = time.monotonic()
        request = self._request(messages, max_tokens, tool_system_blocks(today, hint))
        request["tool_choice"] = TOOL_CHOICE_AUTO
        events = self._events(request)
        final = None
        try:
            async for event in events:
                if isinstance(event, Message):
                    final = event
                elif event.type == "content_block_start" and event.content_block.type == "text":
                    return ToolDecision(text=self._texts(events, started, "도구 답변"))
        except (anthropic.APIError, httpx2.HTTPError) as error:
            reason = _stream_failure(error)
            _log_failure("도구 고르기", started, reason)
            await events.aclose()
            raise ClassifyError(reason) from None
        if final is None or final.stop_reason == "refusal":
            _log_failure("도구 고르기", started, final.stop_reason if final else "no_output")
            return ToolDecision()
        self._log(final, "도구 고르기", started)
        use = next((block for block in final.content if block.type == "tool_use"), None)
        if use is None:
            return ToolDecision()
        call = tools.parse(use.name, use.input if isinstance(use.input, dict) else {}, use.id)
        content = tuple(block.model_dump(exclude_none=True) for block in final.content)
        logger.info("LLM 도구: %s 인자 %s", call.name, "통과" if call.args else "거부")
        return ToolDecision(call=call, content=content)

    async def _texts(
        self, events: AsyncIterator[object], started: float, task: str
    ) -> AsyncIterator[str]:
        length = 0
        try:
            async for event in events:
                if isinstance(event, Message):
                    if event.stop_reason == "refusal":
                        _log_failure(task, started, "refusal")
                        raise AnswerError("refusal")
                    if any(block.type == "tool_use" for block in event.content):
                        # 글 뒤 도구 : 1단계는 글만 사용, 평가에서 건수 확인
                        logger.warning("LLM %s: 글 뒤 도구 호출 무시", task)
                    self._log(event, task, started, length)
                elif event.type == "content_block_delta" and event.delta.type == "text_delta":
                    length += len(event.delta.text)
                    yield event.delta.text
        except (anthropic.APIError, httpx2.HTTPError) as error:
            reason = _stream_failure(error)
            _log_failure(task, started, reason)
            raise AnswerError(reason) from None
        finally:
            await events.aclose()

    async def answer(
        self,
        messages: list[dict],
        decision: ToolDecision,
        result: str,
        max_tokens: int,
        today: date,
        follow: FollowRead | None = None,
    ) -> AsyncIterator[str]:
        # 서버 도구 결과를 돌려준 뒤 같은 대화로 답변
        # follow 있음 : 첫 블록이 글이면 그대로, 도구면 실행 후 도구 없이(LLM 3번).
        # follow가 ReadMore를 주면 한 번 더 도구를 고를 수 있음(LLM 최대 4번)
        current = _with_result(messages, decision.content, decision.call, result)
        if follow is None:
            request = self._request(current, max_tokens, tool_system_blocks(today))
            request["tool_choice"] = TOOL_CHOICE_NONE
            events = self._events(request)
            async for text in self._texts(events, time.monotonic(), "도구 결과 답변"):
                yield text
            return
        for round_no in range(1, FOLLOW_ROUNDS + 1):
            request = self._request(current, max_tokens, tool_system_blocks(today))
            request["tool_choice"] = TOOL_CHOICE_AUTO
            started = time.monotonic()
            events = self._events(request)
            final = None
            try:
                async for event in events:
                    if isinstance(event, Message):
                        final = event
                    elif event.type == "content_block_start" and event.content_block.type == "text":
                        async for text in self._texts(events, started, "도구 결과 답변"):
                            yield text
                        return
            except (anthropic.APIError, httpx2.HTTPError) as error:
                reason = _stream_failure(error)
                _log_failure("도구 결과 답변", started, reason)
                raise AnswerError(reason) from None
            finally:
                await events.aclose()
            if final is None or final.stop_reason == "refusal":
                reason = (final.stop_reason if final else None) or "no_output"
                _log_failure("도구 결과 답변", started, reason)
                raise AnswerError(reason)
            self._log(final, "도구 결과 답변", started)
            use = next((block for block in final.content if block.type == "tool_use"), None)
            if use is None:
                raise AnswerError("no_output")
            call = tools.parse(use.name, use.input if isinstance(use.input, dict) else {}, use.id)
            logger.info(
                "LLM 결과 뒤 도구(%d): %s 인자 %s",
                round_no,
                call.name,
                "통과" if call.args else "거부",
            )
            second = await follow(call)
            content = tuple(block.model_dump(exclude_none=True) for block in final.content)
            current = _with_result(current, content, call, second or rules.READ_NOT_RUN)
            if not isinstance(second, ReadMore):
                break
        request = self._request(current, max_tokens, tool_system_blocks(today))
        request["tool_choice"] = TOOL_CHOICE_NONE
        async for text in self._texts(self._events(request), time.monotonic(), "도구 결과 답변"):
            yield text

    def _log(self, final: Message, task: str, started: float, length: int | None = None) -> None:
        usage = final.usage
        if self.on_usage is not None:
            self.on_usage(task, usage)
        logger.info(
            "LLM %s: %d토큰(캐시 읽기 %d·쓰기 %d) 출력 %d토큰%s %s (%.0fms)",
            task,
            usage.input_tokens,
            usage.cache_read_input_tokens or 0,
            usage.cache_creation_input_tokens or 0,
            usage.output_tokens,
            "" if length is None else f"·{length}자",
            final.stop_reason,
            (time.monotonic() - started) * 1000,
        )


def _with_result(
    messages: list[dict], content: tuple[dict, ...], call: tools.ToolCall | None, result: str
) -> list[dict]:
    # tool_use마다 tool_result 필수(없으면 Anthropic 400) : 실행한 도구만 결과, 나머지는 실행 안 함
    use_id = call.use_id if call is not None else ""
    ids = [block["id"] for block in content if block.get("type") == "tool_use"] or [use_id]
    results = [
        {
            "type": "tool_result",
            "tool_use_id": block_id,
            "content": result if block_id == use_id else rules.READ_NOT_RUN,
        }
        for block_id in ids
    ]
    return [
        *messages,
        {"role": "assistant", "content": list(content)},
        {"role": "user", "content": results},
    ]


def get_tool_agent(settings: Annotated[Settings, Depends(get_settings)]) -> ToolAgent:
    # 2026-11-09 결정 : 대화창 판정은 항상 도구 흐름(끄는 설정 없음)
    return AnthropicToolAgent(get_anthropic_client(settings), settings.llm_model)


class RegisterExtractor(Protocol):
    # FN-AIM-012-03 : 규칙으로 채우지 못한 칸의 보조 추출 (입력은 요청 문장과 오늘 날짜(KST)만)
    # 반환값은 검증 전 원본 (칸 이름 -> 값), 실패 시 빈 dict
    async def extract(self, text: str, today: date) -> dict: ...


class ExtractOutput(BaseModel):
    # 구조화 출력 모양. 모르는 칸은 null
    schdl_knd_cd: str | None = None
    schdl_ymd: str | None = None
    schdl_tm: str | None = None
    ckup_type_cd: str | None = None
    hsptl_nm: str | None = None
    schdl_nm: str | None = None
    care_artcl_nm: str | None = None
    care_zone_cd: str | None = None
    care_cycle_cd: str | None = None
    cycle_days: int | None = None
    last_cmptn_ymd: str | None = None


EXTRACT_SYSTEM = (
    "반려동물 케어 앱에서 보호자가 일정이나 반복 케어 항목을 등록해 달라고 한 문장에서 "
    "칸을 뽑는다. "
    "문장에 없는 칸은 추측하지 말고 null로 둔다. 날짜는 사용자 메시지의 오늘 날짜를 기준으로 "
    "YYYY-MM-DD, 시간은 24시간 HH:MM으로 쓴다.\n"
    "- schdl_knd_cd(일정 종류): HLTC0057 병원, HLTC0058 미용·목욕, HLTC0059 케어·투약, "
    "HLTC0060 기타\n"
    "- ckup_type_cd(병원일 때 검진유형): HLTC0001 정기검진, HLTC0002 예방접종, HLTC0003 질병진료, "
    "HLTC0004 검사, HLTC0005 기타 진료\n"
    "- hsptl_nm: 병원 이름. schdl_nm: 병원이 아닌 일정의 이름(40자 이내)\n"
    "- 주기가 있는 요청이면 일정이 아니라 케어 항목이다. care_artcl_nm: 항목명(40자 이내), "
    "care_zone_cd: HLTC0036 매일 / HLTC0037 주기, care_cycle_cd: HLTC0038 1주, HLTC0039 2주, "
    "HLTC0040 한달, HLTC0041 1년, HLTC0042 직접입력(cycle_days에 n일), "
    "last_cmptn_ymd: 마지막으로 한 날"
)


class AnthropicRegisterExtractor:
    # FN-AIM-012-03 : 반려동물 목록·기록 데이터 제외 (POL-006), 실패 시 빈 칸 (되물음)
    def __init__(self, client: AsyncAnthropic, model: str):
        self.client = client
        self.model = model

    async def extract(self, text: str, today: date) -> dict:
        started = time.monotonic()
        content = f"오늘: {today.isoformat()} ({'월화수목금토일'[today.weekday()]})\n요청: {text}"
        try:
            response = await self.client.messages.parse(
                model=self.model,
                max_tokens=LLM_MAX_TOKENS,
                system=EXTRACT_SYSTEM,
                messages=[{"role": "user", "content": content}],
                output_config={"effort": LLM_EFFORT},
                output_format=ExtractOutput,
            )
        except anthropic.APIError as error:
            _log_failure("등록 칸 추출", started, _failure_reason(error))
            return {}
        except ValidationError:
            _log_failure("등록 칸 추출", started, "invalid_output")
            return {}
        output = response.parsed_output
        if response.stop_reason == "refusal" or output is None:
            _log_failure("등록 칸 추출", started, response.stop_reason or "no_output")
            return {}
        values = output.model_dump(exclude_none=True)
        logger.info(
            "LLM 등록 칸 추출: 입력 %d자 → %d칸 (%.0fms)",
            len(text),
            len(values),
            (time.monotonic() - started) * 1000,
        )
        return values


def get_register_extractor(
    settings: Annotated[Settings, Depends(get_settings)],
) -> RegisterExtractor:
    return AnthropicRegisterExtractor(get_anthropic_client(settings), settings.llm_model)
