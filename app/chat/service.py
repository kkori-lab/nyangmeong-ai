import asyncio
import io
import logging
import re
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel
from pydantic.alias_generators import to_camel

from app.chat import catalog, rules, tools
from app.chat.clients import (
    READ_LIMIT,
    AnswerError,
    ClassifyError,
    ImageIntentError,
    ImageIntentJudge,
    ReadMore,
    RegisterExtractor,
    TitleGenerator,
    ToolAgent,
    ToolDecision,
    with_result,
)
from app.chat.repository import (
    AiSettings,
    ConversationRepository,
    PetInfo,
    RegisterContextRepository,
    RouteRepository,
    ToolReader,
)
from app.chat.schemas import (
    ROLE_AI,
    ROLE_USER,
    ActionCard,
    ActionDraft,
    ActionResultRequest,
    ActionStatus,
    AnswerDone,
    CardType,
    CheckupCardRequest,
    CheckupCardResult,
    CheckupLabItem,
    CheckupNoCardReason,
    CheckupResult,
    ConversationCreateRequest,
    ConversationDetail,
    ConversationMessage,
    ConversationSummary,
    ImageIntentJudgement,
    ImageIntentKind,
    ImageIntentResult,
    Intent,
    IntentKind,
    PetChoice,
    ReceiptResult,
    ReceiptResultRequest,
    RegisterCard,
    RegisterDraft,
    RegisterResult,
    RegisterResultRequest,
    StreamError,
)
from app.core.backend import BackendError, external_error, failure_reason
from app.core.image import validate_upload
from app.core.pdf import is_pdf_name, validate_pdf
from app.core.response import AppError

logger = logging.getLogger(__name__)

# FN-AIM-004-09 : 매핑표를 다시 받는 간격 (2026-11-10 LJS 결정, 관리자 수정은 최대 10초 뒤 반영)
ROUTE_TTL_SEC = 10.0


class RouteCache:
    """[라우팅 매핑표 캐시]
    - 대화 요청 때 받은 지 10초가 지났으면 그 요청의 쿠키로 다시 받음(타이머 없음, 워커마다)
    - Java 실패면 마지막 성공본, 처음부터 실패면 스냅샷(rules.routing_table)"""

    def __init__(
        self, ttl_sec: float = ROUTE_TTL_SEC, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.ttl_sec = ttl_sec
        self.clock = clock
        self._checked_at: float | None = None

    def reset(self) -> None:
        self._checked_at = None
        rules.use_routes(None)

    async def refresh(self, routes: RouteRepository) -> None:
        now = self.clock()
        if self._checked_at is not None and now - self._checked_at < self.ttl_sec:
            return
        # 실패해도 다음 확인은 10초 뒤 : Java가 느릴 때 요청마다 기다리지 않게
        self._checked_at = now
        try:
            rows = rules.route_rows(await routes.get_routes())
        except (AppError, BackendError) as error:
            logger.warning("라우팅 매핑표 받기 실패: %s", type(error).__name__)
            return
        # 이동할 행이 없으면 navigate enum이 비어 LLM 요청이 깨짐 : 앞의 표 유지
        if not any(row.routable for row in rows):
            logger.warning("라우팅 매핑표에 이동할 행 없음: %d행", len(rows))
            return
        rules.use_routes(rows)


route_cache = RouteCache()

# FN-AIM-011-11 : 생성 제목 30자 이내 (Java 저장 상한 200보다 짧게, 2026-10-30 LJS 결정)
MAX_TITLE_LENGTH = 30
DEFAULT_TITLE = "새 대화"
# FN-AIM-005-02 : 화면설계서 SCR-AIM-005 ② 문구
FALLBACK_MESSAGE = "질문을 이해하지 못했어요. 다시 입력하거나 아래에서 선택해 주세요."
# 서비스 범위 밖 질문 안내 (2026-10-30 LJS 추가 요청, 화면설계서 밖 문구)
OUT_OF_SCOPE_MESSAGE = (
    "반려동물 케어와 관련된 질문만 도와드릴 수 있어요. "
    "반려동물이나 서비스 이용에 관해 물어봐 주세요."
)
# FN-AIM-002-03 : 화면설계서 SCR-AIM-002 ② 문구, 본문 끝에 붙여 저장
DISCLAIMER = "\n\n※ 참고 정보이며 의료 진단이 아닙니다. 이상 징후가 있다면 수의사와 상담하세요."
# FN-AIM-002-07 : 화면설계서 SCR-AIM-002 처리 조건 문구
ANSWER_ERROR_MESSAGE = "일시적으로 답변할 수 없어요"
# READ 도구 : 반려동물을 못 정하면 Java 미호출, 고정 문구로 되물음 (2026-11-06 LJS 결정)
READ_PET_ASK = "어느 아이의 기록을 볼까요? {names} 중에서 이름을 넣어 다시 물어봐 주세요."
READ_NO_PET = "등록된 반려동물이 없어요. 반려동물을 먼저 등록해 주세요."
# READ 도구 : 한 번에 읽는 반려동물 상한과 Java 동시 호출 수 (2026-11-09 LJS 결정)
READ_MAX_PETS = 10
READ_CONCURRENCY = 4
# READ 결과 글의 마리별 머리줄 : LLM이 "선택된 반려동물 기준" 같은 말을 지어내지 않게
READ_PET_LABEL = "조회한 반려동물: {name}"
# READ 결과를 본 LLM이 쓰기 도구를 고른 경우의 tool_result : 카드는 done.action으로
# 결과 뒤 navigate의 결과 글 : 화면은 옮기지 않고 답 아래 바로가기 버튼(done.shortcut)
ROUTE_SHOWN = (
    "화면을 옮기지 않음. 답 아래에 '{name}' 바로가기 버튼을 보여 줌. "
    "답 끝에 그 버튼으로 갈 수 있다고 한 문장으로 안내한다."
)
# 이동 먼저 고른 섞인 메시지에서 답변이 0자일 때 : 화면 바로가기 안내
ROUTE_EMPTY_MESSAGE = "'{name}' 바로가기를 눌러 주세요."
ACTION_SHOWN = (
    "확인 카드를 만듦(아직 저장 안 됨). 카드 내용: {summary}. "
    "회원이 대화로 '등록해 줘'라고 말해야 저장된다. 카드 내용을 그대로 보여 주고, "
    "맞으면 '등록해 줘'라고 말해 달라고 한두 문장으로 안내한다."
)
# 확인 카드를 모달 대신 채팅으로 확인 (2026-11-13) : 카드 턴의 저장 글과 다음 턴의 확인·취소
ACTION_ASK_TEMPLATE = "이렇게 할까요?\n{summary}"
ACTION_ASK_MISSING = "아직 {names} 비어 있어요. 말로 알려 주세요."
# FN-AIM-012-04 : 같은 이름 반려동물이라 못 정함(칩이 모두 같은 이름)
ACTION_ASK_SAME_PET = "{name} {count}. 칩에서 고르거나 '{hint} {pet}'처럼 알려 주세요."
ACTION_ASK_SAME_PET_CHIP = "{name} {count}. 칩에서 골라 주세요."
ACTION_ASK_MISSING_REST = "아직 {names} 비어 있어요."
# 빈 반려동물 칸의 이름(되물음 글)
PET_LABEL = "반려동물"
ACTION_ASK_CONFIRM = "맞으면 '등록해 줘'라고 말해 주세요. 바꿀 내용은 말로 알려 주시면 고칠게요."
ACTION_EXECUTE_MESSAGE = "등록할게요."
ACTION_DROP_MESSAGE = "등록하지 않았어요."
# 한 메시지 여러 명령 ② (2026-11-19) : 한 메시지 확인 카드 최대 수(READ 상한과 같음)
ACTION_MAX_CARDS = 3
# 쓰기 카드 뒤 이어 주는 말이 있을 때 남은 쓰기 도구를 이어 고르는 tool_result
ACTION_CHAINED = (
    "확인 카드를 만듦(아직 저장 안 됨). 이 메시지에 다른 쓰기 요청(기록·등록·수정)이 남았으면 "
    "그 쓰기 도구를 부르고, 남은 것이 없으면 아무 글도 쓰지 않고 끝낸다."
)
# 카드가 둘 이상일 때 : 번호 붙은 요약 줄, 빈 칸은 카드 번호로
ACTION_ASK_LINE = "{no}. {summary}"
ACTION_ASK_MISSING_NO = "아직 {no}번의 {names} 비어 있어요. 말로 알려 주세요."
# 카드 여럿에서 같은 이름 반려동물이라 못 정함 : 카드 하나일 때 문구에 번호, 남은 빈 칸은 이어서
ACTION_ASK_SAME_PET_NO = "{no}번: {line}"
ACTION_ASK_MISSING_REST_NO = "아직 {no}번의 {names} 비어 있어요."
# 수정 도구(경로 번호 칸) : 번호를 이 턴 READ 결과에서 못 정하면 카드 없이 (SCR-AIM-012 2단계 ②)
ACTION_TARGET_MISSING = (
    "바꿀 대상을 이 턴 읽기 결과에서 찾지 못해 카드를 띄우지 않음. "
    "어떤 것을 바꿀지 이름이나 날짜를 넣어 다시 말해 달라고 한두 문장으로 안내한다."
)
TARGET_MISSING_MESSAGE = "바꿀 {target}을 찾지 못했어요. 이름이나 날짜를 넣어 다시 말해 주세요."
# 등록 도구의 본문 필수 번호 칸(관찰 기록의 obsrvArtclSn)을 못 정함 (SCR-AIM-012 2단계 ③)
ACTION_ADD_TARGET_MISSING = (
    "기록할 대상을 이 턴 읽기 결과에서 찾지 못해 카드를 띄우지 않음. "
    "어떤 것에 기록할지 이름을 넣어 다시 말해 달라고 한두 문장으로 안내한다."
)
ADD_TARGET_MISSING_MESSAGE = "기록할 {target}을 찾지 못했어요. 이름을 넣어 다시 말해 주세요."
# READ 답변이 오류 없이 0자로 끝남(실측 2026-11-09, READ 2번 뒤) : 오류 대신 안내 글
READ_EMPTY_CARD_MESSAGE = "카드 내용이 맞으면 '등록해 줘'라고 말해 주세요."
READ_EMPTY_MESSAGE = "요청을 처리하지 못했어요. 이름이나 날짜를 넣어 다시 말해 주세요."
# 확인 카드 문구의 동사 (2026-11-20) : 위 문구는 등록 기준. 카드가 모두 수정(PATCH)이면 "수정",
# 등록·수정이 섞이면 "진행" (수정 카드에 "'등록해 줘'"를 안내해 LLM이 앞 안내를 잘못이라고 함)
ACTION_VERB_ADD = "등록"
ACTION_VERB_UPDATE = "수정"
ACTION_VERB_MIXED = "진행"


def action_verb(methods: Sequence[str]) -> str:
    """카드 call.method 목록 -> 확인 문구 동사(등록·수정·진행)"""
    kinds = {method.upper() == "PATCH" for method in methods}
    if kinds == {True}:
        return ACTION_VERB_UPDATE
    return ACTION_VERB_MIXED if len(kinds) > 1 else ACTION_VERB_ADD


def _worded(message: str, cards: Sequence[ActionCard]) -> str:
    # 등록 기준 문구를 카드 종류의 동사로
    verb = action_verb([card.call.method for card in cards])
    return message.replace(ACTION_VERB_ADD, verb)


async def _fixed(text: str) -> AsyncIterator[str]:
    yield text


def _target_missing(entry: "catalog.CatalogEntry") -> str:
    target = entry.target or entry.label or "대상"
    if entry.call.method == "PATCH":
        return TARGET_MISSING_MESSAGE.format(target=target)
    return ADD_TARGET_MISSING_MESSAGE.format(target=target)


def _target_missing_note(entry: "catalog.CatalogEntry") -> str:
    # 읽기 결과를 본 LLM에 주는 tool_result 글
    return ACTION_TARGET_MISSING if entry.call.method == "PATCH" else ACTION_ADD_TARGET_MISSING


# SSE 이벤트 하나 : (이름, 내용)
Event = tuple[str, BaseModel | dict]


async def create_conversation(
    repo: ConversationRepository, titles: TitleGenerator, request: ConversationCreateRequest
) -> ConversationSummary:
    # FN-AIM-011-11 : 제목은 첫 메시지로 1회 생성, 30자 제한은 서버에서 적용
    title = _cut_title(await titles.generate(request.cnvrs_cn)) or DEFAULT_TITLE
    # FN-AIM-011-07·14 : 방과 첫 메시지 함께 저장 (Java 단일 트랜잭션)
    return await repo.create_room(request.pet_sn, title, request.cnvrs_cn)


def _cut_title(text: str) -> str:
    # 30자에서 자른 뒤 끝 공백 제거
    return text.strip()[:MAX_TITLE_LENGTH].rstrip()


async def list_conversations(
    repo: ConversationRepository, pet_sn: int | None
) -> list[ConversationSummary]:
    # FN-AIM-011-08·09
    return await repo.list_rooms(pet_sn)


async def get_conversation(repo: ConversationRepository, room_sn: int) -> ConversationDetail:
    # FN-AIM-011-10 : 남의 방은 Java가 없는 방과 같은 404 응답
    return await repo.get_room(room_sn)


async def delete_conversation(repo: ConversationRepository, room_sn: int) -> None:
    # FN-AIM-011-13 : 물리 삭제
    await repo.delete_room(room_sn)


@dataclass(frozen=True)
class Judged:
    intent: Intent
    # SEARCH일 때 연관 바로가기(FN-AIM-002-04)
    shortcut: Intent | None = None
    # FALLBACK일 때 서비스 범위 밖 질문 여부 : 안내 문구만 다름
    out_of_scope: bool = False
    # 사용법 질문일 때 답변 근거로 쓸 안내서 청크 id (SEARCH로 응답)
    guide_ids: tuple[str, ...] = ()
    # 도구 흐름(tool calling 1단계) : 이미 시작한 답변 스트림, 등록 도구 인자
    stream: AsyncIterator[str] | None = None
    ai_values: dict | None = None
    # 고른 등록·쓰기 도구 이름 : 빈 칸을 Java 도구 목록 규칙으로 판정
    tool: str | None = None
    # ACTION : 검증한 확인 카드 input(Java 칸, petSn 제외)
    action: dict | None = None
    # ACTION : LLM 값이 규칙 밖이라 비운 칸(되물음)
    rejected: tuple[str, ...] = ()
    # SEARCH(READ) : 결과를 본 뒤 고른 쓰기 도구의 확인 카드, 답변 스트림이 채움
    cards: list[ActionCard] | None = None
    # FN-AIM-002-03 : 의료 고지 여부. 사용법 답변은 False
    notice: bool = True
    # SEARCH(READ) : 성공한 고지 READ(도구 notice) 이름, 답변 스트림이 채움. 하나라도 있을 때만 고지
    notice_reads: set[str] | None = None
    # SEARCH(READ) : 결과 뒤 고른 이동·사용법 도구의 바로가기, 답변 스트림이 채움. 앞이 우선
    follow_shortcuts: list[Intent] | None = None
    # ACTION : 이어 고른 쓰기 도구의 (도구, 검증한 input). 첫 카드는 tool·action (여러 명령 ②)
    more: tuple[tuple[str, dict, tuple[str, ...]], ...] = ()
    # ACTION 고치기 : 돌려받은 같은 도구 카드가 여럿(반려동물별로 나눈 카드)일 때
    # 그 카드마다 (목록 번호, 검증한 input, 비운 칸). 어느 카드를 고칠지는 _action_reply가 정함
    per_prior: tuple[tuple[int, dict, tuple[str, ...]], ...] = ()


def _guide_shortcut(chunk_id: str) -> Intent | None:
    # FN-AIM-002-04 : 첫 청크 화면이 라우팅 대상이면 그 화면, 아니면 바로가기 없음
    chunk = rules.find_guide(chunk_id)
    row = rules.find_route(chunk.scr_id, chunk.param) if chunk and chunk.scr_id else None
    return row.to_intent() if row is not None else None


async def judge_tools(
    text: str,
    context: list[dict],
    agent: ToolAgent,
    max_tokens: int,
    today: date,
    first_token_sec: float,
    read: "ReadDeps | None" = None,
    prior: ActionDraft | None = None,
    now: datetime | None = None,
    priors: Sequence[ActionDraft] = (),
) -> Judged:
    """도구 흐름 판정(docs/design/tool-calling.md 4절)
    - priors : 돌려받은 확인 카드 목록(여러 명령 ②). 있으면 prior 대신 같은 도구 카드를 바탕으로"""
    if rules.is_placeholder(text):
        # 추가 요청(2026-11-09) : LLM은 자리 표시 글에 글로 되물어 decline을 안 고름(실측)
        return Judged(Intent(kind=IntentKind.FALLBACK))
    row = None
    # FN-AIM-004-13 : 등록 요청은 라우팅 키워드보다 먼저, 칸은 도구 인자로
    if not rules.is_register_request(text):
        # 추가 요청(2026-11-06) : 키워드에 걸린 문장은 질문꼴이 아니어도 힌트와 함께 도구 고르기
        # FN-AIM-002-10 : 도구 고르기 장애·시간 초과면 그 행으로 이동(LLM 장애와 무관)
        row = rules.match_route(text)
    try:
        async with asyncio.timeout(first_token_sec):
            decision = await agent.decide(context, max_tokens, today, hint=row)
    except (ClassifyError, TimeoutError) as error:
        if isinstance(error, TimeoutError):
            # LLM 오류(ClassifyError)는 클라이언트가 로그, 시간 초과는 취소라 여기서 한 줄
            logger.warning(
                "도구 고르기 시간 초과(%g초): %s",
                first_token_sec,
                "행 이동" if row is not None else "일시 오류",
            )
        if row is not None:
            return Judged(row.to_intent())
        raise ClassifyError("tool_decide") from None
    judged = _tool_judged(
        text, context, agent, decision, max_tokens, today, read, prior, now, priors
    )
    if judged.intent.kind is IntentKind.ACTION and rules.chains_more(text):
        judged = await _chain_cards(
            text, context, agent, decision, judged, max_tokens, today, first_token_sec, now, priors
        )
    return judged


async def _chain_cards(
    text: str,
    context: list[dict],
    agent: ToolAgent,
    decision: ToolDecision,
    judged: Judged,
    max_tokens: int,
    today: date,
    first_token_sec: float,
    now: datetime | None,
    priors: Sequence[ActionDraft],
) -> Judged:
    # 한 메시지 여러 명령 ② : 쓰기 카드 결과를 돌려주고 남은 쓰기 도구를 이어 고름(최대 3장)
    # 같은 도구·쓰기 아닌 도구·글·장애면 거기서 멈추고 모은 카드만
    # 이어 고르기 전체가 첫 글자 제한 안
    picked = [judged.tool]
    more: list[tuple[str, dict, tuple[str, ...]]] = []
    messages = context
    current = decision
    try:
        async with asyncio.timeout(first_token_sec):
            while len(picked) < ACTION_MAX_CARDS:
                messages = with_result(messages, current.content, current.call, ACTION_CHAINED)
                current = await agent.decide(messages, max_tokens, today)
                call = current.call
                if call is None:
                    if current.text is not None:
                        await _drop_text(current.text)
                    break
                if call.args is None or tools.card_entry(call.name) is None:
                    logger.info("이어 고른 도구 쓰기 아님: %s", call.name)
                    break
                if call.name in picked:
                    logger.info("같은 쓰기 도구 두 번 버림: %s", call.name)
                    break
                card = tools.card_entry(call.name)
                nxt = _card_judged(text, call, card, today, None, now, priors)
                if nxt.intent.kind is not IntentKind.ACTION:
                    logger.info("이어 고른 쓰기 도구 대상 번호 없음: %s", call.name)
                    break
                picked.append(call.name)
                more.append((call.name, nxt.action or {}, nxt.rejected))
    except (ClassifyError, TimeoutError) as error:
        logger.warning(
            "쓰기 이어 고르기 실패(%s): 카드 %d장으로", type(error).__name__, len(picked)
        )
    if more:
        logger.info("한 메시지 쓰기 카드 %d장: %s", len(picked), ", ".join(picked))
    return replace(judged, more=tuple(more))


async def _drop_text(stream: AsyncIterator[str]) -> None:
    # 이어 고르기에서 LLM이 글을 씀 : 첫 조각만 읽고 닫아 스트림을 끝냄
    try:
        async for _ in stream:
            break
    except AnswerError:
        pass
    finally:
        aclose = getattr(stream, "aclose", None)
        if aclose is not None:
            await aclose()


def _prior_for(
    tool: str, prior: ActionDraft | None, priors: Sequence[ActionDraft]
) -> ActionDraft | None:
    # 돌려받은 카드 중 같은 도구 : 목록이 있으면 목록에서, 없으면 prior
    found = next((draft for draft in priors if draft.tool == tool), None)
    if found is not None or priors:
        return found
    return prior if prior is not None and prior.tool == tool else None


def _tool_judged(
    text: str,
    context: list[dict],
    agent: ToolAgent,
    decision: ToolDecision,
    max_tokens: int,
    today: date,
    read: "ReadDeps | None" = None,
    prior: ActionDraft | None = None,
    now: datetime | None = None,
    priors: Sequence[ActionDraft] = (),
) -> Judged:
    # 도구 -> intent 값 (설계 6절). CARD 도구는 ACTION(등록 카드 2개도 ④부터)
    call = decision.call
    if call is None:
        if decision.text is not None:
            # FN-AIM-002-03 : 인사·잡담에 대한 바로 답은 고지 없음(추가 요청 2026-11-09)
            notice = not rules.is_small_talk(text)
            # FN-AIM-002-04 : 질문 글이 룰 키워드에 걸리면 그 행을 바로가기로, 인사·잡담 제외
            shortcut = _keyword_shortcut(text) if notice else None
            return Judged(
                Intent(kind=IntentKind.SEARCH), shortcut, stream=decision.text, notice=notice
            )
        return Judged(Intent(kind=IntentKind.FALLBACK))
    if call.args is None:
        logger.info("도구 인자 거부: %s", call.name)
        return Judged(Intent(kind=IntentKind.FALLBACK))
    if call.name == tools.NAVIGATE:
        row = tools.route_row(call)
        if row is not None and read is not None and rules.chains_after_move(text):
            return _route_mixed(text, context, agent, decision, row, max_tokens, today, read)
        return Judged(row.to_intent())
    if call.name == tools.DECLINE:
        return Judged(Intent(kind=IntentKind.FALLBACK), out_of_scope=not call.args.unclear)
    card = tools.card_entry(call.name)
    if card is not None:
        return _card_judged(text, call, card, today, prior, now, priors)
    entry = tools.read_entry(call.name)
    if entry is not None:
        if read is None:
            logger.info("READ 도구 실행 불가: %s", call.name)
            return Judged(Intent(kind=IntentKind.FALLBACK))
        # Java 호출은 답변 스트림 안 : 첫 글자 제한이 Java 호출까지 덮음
        cards: list[ActionCard] = []
        notice_reads: set[str] = set()
        shortcuts: list[Intent] = []
        stream = _read_answer(
            text,
            context,
            agent,
            decision,
            entry,
            max_tokens,
            today,
            read,
            cards,
            notice_reads,
            shortcuts,
        )
        return Judged(
            Intent(kind=IntentKind.SEARCH),
            _read_shortcut(entry, text),
            stream=stream,
            cards=cards,
            notice_reads=notice_reads,
            follow_shortcuts=shortcuts,
        )
    ids = tuple(tools.guide_ids(call, text))
    if not ids:
        logger.info("사용법 안내: 안내서 청크 없음")
        return Judged(Intent(kind=IntentKind.FALLBACK), out_of_scope=True)
    logger.info("사용법 안내: 도구 %d개 %s", len(ids), ",".join(ids))
    shortcut = _guide_shortcut(ids[0])
    guide = guide_text(ids) or ""
    if read is None:
        stream = agent.answer(context, decision, guide, max_tokens, today)
        # FN-AIM-002-03 : 사용법 안내는 건강 관련 응답이 아님
        return Judged(
            Intent(kind=IntentKind.SEARCH), shortcut, guide_ids=ids, stream=stream, notice=False
        )
    # 사용법을 먼저 골라도 함께 물은 기록은 결과 뒤 도구로 읽음(2026-11-13 추가-5)
    # 고지는 결과 뒤 고지 READ가 성공했을 때만(사용법만이면 notice_reads가 비어 고지 없음)
    cards: list[ActionCard] = []
    notice_reads: set[str] = set()
    shortcuts: list[Intent] = []
    follow = _Follow(text, read, cards, notice_reads, shortcuts)
    stream = agent.answer(context, decision, guide, max_tokens, today, follow)
    return Judged(
        Intent(kind=IntentKind.SEARCH),
        shortcut,
        guide_ids=ids,
        stream=stream,
        cards=cards,
        notice_reads=notice_reads,
        follow_shortcuts=shortcuts,
    )


def _card_judged(
    text: str,
    call: tools.ToolCall,
    card: "catalog.CatalogEntry",
    today: date,
    prior: ActionDraft | None,
    now: datetime | None,
    priors: Sequence[ActionDraft] = (),
) -> Judged:
    # 쓰기 도구 -> ACTION. 돌려받은 카드와 같은 도구면 그 input을 바탕으로 이 메시지 칸을 덮어씀
    match = _prior_for(call.name, prior, priors)
    base = match.values if match is not None else None
    args = call.args.model_dump(exclude_none=True) if call.args is not None else {}
    if now is not None and rules.mentions_now(text):
        # '방금·지금' : LLM이 비운 날짜·시각을 오늘·지금으로 (2026-11-13)
        args = catalog.fill_now(card, args, now)
    # LLM이 비운 날짜 : 문장의 날짜 말, 없으면 새 등록 기록 도구만 오늘 (2026-11-23)
    args = catalog.fill_date(card, args, rules.said_dates(text, today), today)
    values, rejected = _card_values(text, card, args, base, today, now)
    if catalog.missing_target_ids(card, values):
        # 경로·본문 필수 번호 칸은 카드에서 고를 수 없음 : 안내 글(SEARCH), 고지 없음
        logger.info("쓰기 도구 대상 번호 없음: %s", call.name)
        stream = _fixed(_target_missing(card))
        return Judged(Intent(kind=IntentKind.SEARCH), stream=stream, notice=False)
    # 반려동물별로 나눈 같은 도구 카드가 여럿이면 카드마다 그 input을 바탕으로 (2026-11-23)
    same = [no for no, draft in enumerate(priors) if draft.tool == call.name]
    per_prior = (
        tuple((no, *_card_values(text, card, args, priors[no].values, today, now)) for no in same)
        if len(same) > 1
        else ()
    )
    return Judged(
        Intent(kind=IntentKind.ACTION),
        tool=call.name,
        action=values,
        rejected=rejected,
        per_prior=per_prior,
    )


def _card_values(
    text: str,
    card: "catalog.CatalogEntry",
    args: dict,
    base: dict | None,
    today: date,
    now: datetime | None,
) -> tuple[dict, tuple[str, ...]]:
    # 도구 인자 -> 검증한 카드 input과 비운 칸. base는 돌려받은 카드 input
    if base:
        # 추가-1 : 날짜를 말하지 않았으면 돌려받은 카드의 날짜를 유지
        date_said = rules.mentions_date(text)
        args = catalog.keep_prior_dates(card, args, base, date_said, today)
    values = catalog.card_input(card, args, now, {}, base)
    return values, tuple(_rejected(card, args, values))


def _route_mixed(
    text: str,
    context: list[dict],
    agent: ToolAgent,
    decision: ToolDecision,
    row: rules.RouteRow,
    max_tokens: int,
    today: date,
    read: "ReadDeps",
) -> Judged:
    # 이동 먼저 고른 섞인 메시지(2026-11-17) : 이동 뒤에 다른 일을 이어 말하면 화면을 옮기지 않고
    # 바로가기를 붙인 답변으로, 함께 물은 기록·사용법은 결과 뒤 도구로 (사용법 경로와 같은 규칙)
    # 고지는 결과 뒤 고지 READ가 성공했을 때만. 바로가기는 고른 화면이 앞(결과 뒤 이동이면 그 화면)
    logger.info("이동 뒤 이어 말함: 바로가기 답변 %s", row.scr_id)
    intent = row.to_intent()
    cards: list[ActionCard] = []
    notice_reads: set[str] = set()
    shortcuts: list[Intent] = [intent]
    follow = _Follow(text, read, cards, notice_reads, shortcuts)
    answer = agent.answer(
        context, decision, ROUTE_SHOWN.format(name=row.name), max_tokens, today, follow
    )
    return Judged(
        Intent(kind=IntentKind.SEARCH),
        intent,
        stream=_or_fixed(answer, ROUTE_EMPTY_MESSAGE.format(name=row.name), cards),
        cards=cards,
        notice_reads=notice_reads,
        follow_shortcuts=shortcuts,
    )


async def _or_fixed(
    answer: AsyncIterator[str], empty: str, cards: list[ActionCard]
) -> AsyncIterator[str]:
    # 답변이 0자면 고정 글(카드가 있으면 카드 확인 안내)
    produced = False
    try:
        async for chunk in answer:
            if chunk:
                produced = True
            yield chunk
    finally:
        await answer.aclose()
    if not produced:
        logger.info("이동 섞인 답변 0자: 바로가기 안내로")
        yield _worded(READ_EMPTY_CARD_MESSAGE, cards) if cards else empty


@dataclass(frozen=True)
class ReadDeps:
    reader: ToolReader
    contexts: RegisterContextRepository
    # 대화의 펫 태그. null이면 "전체"
    room_pet: int | None = None
    # 쓰기 도구 datetime 칸 : 날짜만 오면 오늘은 이 시각
    now: datetime | None = None
    # 돌려받은 확인 카드 : READ 뒤 같은 쓰기 도구를 고르면 그 input을 바탕으로 (2026-11-23)
    priors: tuple[ActionDraft, ...] = ()


class _ReadPets:
    """한 턴 READ의 반려동물 : 목록은 처음 필요할 때 한 번만 받는다"""

    def __init__(self, text: str, read: ReadDeps) -> None:
        self.compact = re.sub(r"\s+", "", text)
        self.read = read
        self._pets: list[PetInfo] | None = None
        # 앞 READ 결과의 번호 칸 값이 어느 반려동물 것인지 : (칸 이름, 값) -> petSn
        self.owner: dict[tuple[str, int], int] = {}

    async def pets(self) -> list[PetInfo]:
        if self._pets is None:
            try:
                self._pets = await self.read.contexts.get_pets()
            except (AppError, BackendError) as error:
                # 추가 요청 : 답변 실패(read_pets)의 Java 쪽 이유 한 줄
                logger.warning("READ 반려동물 목록 실패: %s", failure_reason(error))
                raise AnswerError("read_pets") from None
        return self._pets

    def named(self, pets: list[PetInfo]) -> list[PetInfo]:
        return named_pets(pets, self.compact)

    def targets(self, pets: list[PetInfo]) -> list[PetInfo]:
        """읽을 반려동물 : 문장 속 이름들 > 펫 태그 방의 그 아이 > 모든 아이"""
        named = self.named(pets)
        if named:
            return named
        tagged = [p for p in pets if p.pet_sn == self.read.room_pet]
        return tagged or pets


def _same_name_kind(pet: PetInfo, pets: list[PetInfo]) -> str:
    """같은 이름 반려동물 READ 구별 (2026-11-23) : 이름이 또 있는 아이만 "강아지·말티즈".
    종·품종이 없으면 빈 글자(이름만)"""
    if not any(p.pet_nm == pet.pet_nm and p.pet_sn != pet.pet_sn for p in pets):
        return ""
    return "·".join(part for part in (pet.pet_se_nm, pet.vrty_nm) if part)


def _pet_list_name(pet: PetInfo, pets: list[PetInfo]) -> str:
    # 여러 아이 일정 이름표 : "연탄(petSn 1006, 강아지·말티즈)", 이름이 안 겹치면 번호만
    kind = _same_name_kind(pet, pets)
    return f"{pet.pet_nm}(petSn {pet.pet_sn}{', ' + kind if kind else ''})"


@dataclass
class _ReadOutcome:
    # ask : Java 미호출 되물음 문구, result : tool_result 글
    ask: str | None = None
    result: str = ""


async def _read_once(
    entry: "catalog.CatalogEntry",
    call: tools.ToolCall | None,
    pets: _ReadPets,
    seen: dict[str, set[int]],
    notice_reads: set[str] | None = None,
    rows: "catalog.Rows | None" = None,
) -> _ReadOutcome:
    args = call.args if call is not None else None
    values = args.model_dump(exclude_none=True) if args is not None else {}
    today = pets.read.now.date() if pets.read.now is not None else rules.today_kst()
    values = catalog.fill_default_period(entry, values, today)
    targets: list[PetInfo | None] = [None]
    if "pet" in entry.hooks:
        # 읽을 반려동물 : 이름 > 펫 태그 > 모두. 상한을 넘으면 Java 미호출·이름 되물음
        found = await pets.pets()
        chosen = pets.targets(found)
        if not chosen or len(chosen) > READ_MAX_PETS:
            names = ", ".join(p.pet_nm for p in found)
            return _ReadOutcome(ask=READ_PET_ASK.format(names=names) if found else READ_NO_PET)
        # 앞 결과의 번호로 상세를 읽을 때는 그 번호가 나온 아이만
        owners = {
            pets.owner[(name, value)]
            for name, value in catalog.to_java(entry, values).items()
            if (name, value) in pets.owner
        }
        targets = [p for p in chosen if not owners or p.pet_sn in owners] or chosen
    elif "pet_filter" in entry.hooks:
        # 가계부 : 문장 속 이름이 하나면 그 반려동물, 아니면 전체(공용 지출 포함, 2026-11-06 결정)
        named = pets.named(await pets.pets())
        targets = [named[0] if len(named) == 1 else None]
    pet_sns = None
    label = None
    if "pet_list" in entry.hooks:
        # 여러 아이 일정 : Java 1번 호출. 모두면 petSns를 비워 Java가 양육 중인 전체를 준다
        found = await pets.pets()
        if not found:
            return _ReadOutcome(ask=READ_NO_PET)
        chosen = pets.targets(found)
        if len(chosen) < len(found):
            pet_sns = ",".join(str(p.pet_sn) for p in chosen)
        # 결과 행에는 petSn만 있어 이름표를 붙인다
        names = ", ".join(_pet_list_name(p, found) for p in chosen)
        label = READ_PET_LABEL.format(name=names)
    requests = [
        catalog.read_request(entry, values, p.pet_sn if p else None, seen, pet_sns) for p in targets
    ]
    if any(request is None for request in requests):
        logger.info("READ 도구 필수 칸 없음: %s", entry.name)
        return _ReadOutcome(result=rules.READ_FAILED)
    gate = asyncio.Semaphore(READ_CONCURRENCY)

    async def fetch(request: tuple[str, dict]) -> object | None:
        async with gate:
            try:
                return await pets.read.reader.read(*request)
            except (AppError, BackendError) as error:
                logger.info("READ 도구 Java 실패: %s %s", entry.name, type(error).__name__)
                return None

    started = time.perf_counter()
    datas = await asyncio.gather(*(fetch(r) for r in requests if r is not None))
    logger.info(
        "READ 도구 시간: %s Java %d번 %dms",
        entry.name,
        len(requests),
        (time.perf_counter() - started) * 1000,
    )
    if all(data is None for data in datas):
        return _ReadOutcome(result=rules.READ_FAILED)
    limit = rules.READ_RESULT_MAX_CHARS // len(targets)
    blocks = []
    for pet, data in zip(targets, datas, strict=True):
        if data is None:
            text = rules.READ_FAILED
        else:
            for key, ids in catalog.seen_ids(data).items():
                seen.setdefault(key, set()).update(ids)
                if pet is not None:
                    pets.owner.update({(key, value): pet.pet_sn for value in ids})
            if rows is not None:
                catalog.seen_rows(data, rows)
            text = rules.read_result_text(catalog.drop_result_fields(entry, data), limit)
        if "pet" in entry.hooks and pet is not None:
            kind = _same_name_kind(pet, await pets.pets())
            name = f"{pet.pet_nm}({kind})" if kind else pet.pet_nm
            text = READ_PET_LABEL.format(name=name) + "\n" + text
        elif label is not None:
            text = label + "\n" + text
        blocks.append(text)
    if notice_reads is not None and entry.notice:
        notice_reads.add(entry.name)
    return _ReadOutcome(result="\n\n".join(blocks))


async def _read_answer(
    text: str,
    context: list[dict],
    agent: ToolAgent,
    decision: ToolDecision,
    entry: "catalog.CatalogEntry",
    max_tokens: int,
    today: date,
    read: ReadDeps,
    cards: list[ActionCard] | None = None,
    notice_reads: set[str] | None = None,
    shortcuts: list[Intent] | None = None,
) -> AsyncIterator[str]:
    follow = _Follow(text, read, cards, notice_reads, shortcuts)
    # 되물음·실패만이거나 고지 READ가 아니면 notice_reads가 비어 고지 없음(FN-AIM-002-03)
    first = await _read_once(
        entry, decision.call, follow.pets, follow.seen, notice_reads, follow.rows
    )
    if first.ask is not None:
        yield first.ask
        return
    follow.reads = 1

    answer = agent.answer(context, decision, first.result, max_tokens, today, follow)
    produced = False
    try:
        async for chunk in answer:
            if chunk:
                produced = True
            yield chunk
    finally:
        await answer.aclose()
    if not produced:
        logger.info("READ 답변 0자: 안내 글로")
        yield _worded(READ_EMPTY_CARD_MESSAGE, cards) if cards else READ_EMPTY_MESSAGE


class _Follow:
    """결과 답변 중 LLM이 고른 도구 실행(FollowRead). READ 답변·사용법 답변이 같이 쓴다
    - 쓰기 도구 : 번호 칸은 이 턴 READ 결과 값만, 카드 1개로 끝냄(목록→완료 체크)
    - 이동·사용법 : 화면을 옮기지 않고 바로가기(한 메시지 여러 일 ①)
    - 읽기 도구 : 한 턴 최대 READ_LIMIT번, 반려동물을 못 정하면 불러오지 못함"""

    def __init__(
        self,
        text: str,
        read: ReadDeps,
        cards: list[ActionCard] | None,
        notice_reads: set[str] | None,
        shortcuts: list[Intent] | None,
    ) -> None:
        self.text = text
        self.read = read
        self.pets = _ReadPets(text, read)
        # 번호 칸은 이 턴 READ 결과에 나온 값만 (catalog.read_request)
        self.seen: dict[str, set[int]] = {}
        # 번호별 원래 행 : 수정 카드가 날짜만 바꿀 때 원래 시간을 씀(추가-3)
        self.rows: catalog.Rows = {}
        self.cards = cards
        self.notice_reads = notice_reads
        self.shortcuts = shortcuts
        self.reads = 0

    async def __call__(self, call: tools.ToolCall) -> str | None:
        card = tools.card_entry(call.name)
        if card is not None and call.args is not None and self.cards is not None:
            if self.cards:
                logger.info("쓰기 도구 두 번째 실행 안 함: %s", call.name)
                return None
            found = await self.pets.pets() if _uses_pets(card) else []
            raw = call.args.model_dump(exclude_none=True)
            # 돌려받은 같은 도구 카드가 있으면 그 input에 이 턴 값을 덮어씀(검사 수치 카드 검진기록)
            prior = next((d for d in self.read.priors if d.tool == call.name), None)
            base = prior.values if prior is not None else None
            values = catalog.card_input(card, raw, self.read.now, self.seen, base, self.rows)
            if catalog.missing_target_ids(card, values):
                logger.info("쓰기 도구 대상 번호 없음: %s", call.name)
                return _target_missing_note(card)
            named = self.pets.named(found)
            rejected = _rejected(card, raw, values)
            draft_pet = base.get(catalog.PET_SN) if base else None
            shown = action_card(card, values, found, named, draft_pet, self.read.room_pet, rejected)
            self.cards.append(shown)
            return _worded(ACTION_SHOWN, [shown]).format(summary=action_summary(shown))
        if call.name in (tools.NAVIGATE, tools.SEARCH_GUIDE) and call.args is not None:
            return _follow_screen(call, self.text, self.shortcuts)
        entry = tools.read_entry(call.name)
        if entry is None or call.args is None or self.reads >= READ_LIMIT:
            logger.info("결과 뒤 도구 실행 안 함: %s", call.name)
            return None
        self.reads += 1
        outcome = await _read_once(entry, call, self.pets, self.seen, self.notice_reads, self.rows)
        if outcome.ask is not None:
            return rules.READ_FAILED
        # READ 뒤에도 쓰기 카드는 한 번 고를 수 있게 (2단계 ②, 목록 두 번 → 수정 카드)
        return ReadMore(outcome.result)


def _follow_screen(call: tools.ToolCall, text: str, shortcuts: list[Intent] | None) -> str | None:
    # 결과 뒤 navigate : 그 화면 바로가기(안내서 화면보다 우선), search_guide : 안내서 글을 결과로
    # 라운드가 남으면 이어서 도구를 고를 수 있게 ReadMore. READ 횟수에는 세지 않음
    if call.name == tools.NAVIGATE:
        row = tools.route_row(call)
        if row is None:
            logger.info("결과 뒤 이동 화면 없음: %s", call.name)
            return None
        if shortcuts is not None:
            shortcuts.insert(0, row.to_intent())
        logger.info("결과 뒤 이동은 바로가기로: %s", row.scr_id)
        return ReadMore(ROUTE_SHOWN.format(name=row.name))
    ids = tuple(tools.guide_ids(call, text))
    guide = guide_text(ids) if ids else None
    if guide is None:
        logger.info("결과 뒤 사용법 안내: 안내서 청크 없음")
        return None
    logger.info("결과 뒤 사용법 안내: 도구 %d개 %s", len(ids), ",".join(ids))
    shortcut = _guide_shortcut(ids[0])
    if shortcut is not None and shortcuts is not None:
        shortcuts.append(shortcut)
    return ReadMore(guide)


def guide_text(ids: tuple[str, ...]) -> str | None:
    chunks = [chunk for chunk in map(rules.find_guide, ids) if chunk is not None]
    return "\n\n".join(chunk.text for chunk in chunks) or None


def _keyword_shortcut(text: str) -> Intent | None:
    row = rules.match_route(text)
    return None if row is None else row.to_intent()


def _read_shortcut(entry: catalog.CatalogEntry, text: str) -> Intent | None:
    # FN-AIM-002-04 : 첫 READ 도구의 화면, 매핑표에 그 행이 없으면 질문 글 룰 키워드
    row = rules.find_route(entry.screen, None) if entry.screen else None
    return row.to_intent() if row is not None else _keyword_shortcut(text)


def route_message(scr_nm: str) -> str:
    # 받침(ㄹ 제외)이 있으면 '으로', 없으면 '로'
    last = scr_nm.rstrip()[-1:]
    jong = (ord(last) - 0xAC00) % 28 if "가" <= last <= "힣" else 0
    particle = "으로" if jong not in (0, 8) else "로"
    return f"{scr_nm}{particle} 이동할게요"


async def reply_fallback(
    repo: ConversationRepository, room_sn: int, out_of_scope: bool = False
) -> ConversationMessage:
    # FN-AIM-005-02·07 : 실패 사유는 묻지 않고, 부적절 입력도 같은 문구. AI 역할 메시지로 저장
    # 서비스 범위 밖 질문만 범위 안내 문구 (2026-10-30)
    message = OUT_OF_SCOPE_MESSAGE if out_of_scope else FALLBACK_MESSAGE
    return await repo.add_message(room_sn, ROLE_AI, message)


@dataclass(frozen=True)
class Turn:
    room_sn: int
    # 답할 사용자 메시지
    question: ConversationMessage
    messages: list[ConversationMessage]
    # 대화의 펫 태그(FN-AIM-012-04). null이면 "전체"
    pet_sn: int | None = None
    # FN-AIM-012-05·10 : React가 돌려보낸 가장 최근 카드
    draft: RegisterDraft | None = None
    # 2단계 쓰기 : React가 돌려보낸 가장 최근 확인 카드
    action: ActionDraft | None = None
    # 한 메시지 여러 명령 ② : React가 돌려보낸 확인 카드 목록. 있으면 action 대신
    actions: tuple[ActionDraft, ...] = ()

    def priors(self) -> list[ActionDraft]:
        if self.actions:
            return list(self.actions)
        return [self.action] if self.action is not None else []


@dataclass(frozen=True)
class AnswerLimits:
    # FN-AIM-002-07 : 첫 글자 제한·전체 제한(초)
    first_token_sec: float
    total_sec: float


async def prepare_turn(
    repo: ConversationRepository,
    room_sn: int,
    cn: str | None,
    draft: RegisterDraft | None = None,
    action: ActionDraft | None = None,
    actions: Sequence[ActionDraft] | None = None,
) -> Turn:
    # ① 사용자 메시지 선저장 : 실패 시(남의 방·없는 방 포함) LLM 미호출
    if cn is not None:
        await repo.add_message(room_sn, ROLE_USER, cn)
    room = await repo.get_room(room_sn)
    question = next((m for m in reversed(room.messages) if m.role_cd == ROLE_USER), None)
    if question is None:
        raise AppError("INVALID_REQUEST", 400, "답할 메시지가 없습니다.")
    return Turn(room_sn, question, room.messages, room.pet_sn, draft, action, tuple(actions or ()))


def build_context(messages: list[ConversationMessage], question_seq: int, turns: int) -> list[dict]:
    # FN-AIM-002-11·011-15 : 현재 대화의 답할 메시지까지, 미완료 답변 제외, 최근 turns턴(질문+답변)
    usable = [m for m in messages if m.msg_seq <= question_seq and m.cmptn_yn]
    recent = usable[-turns * 2 :]
    # Messages API는 사용자 메시지로 시작 필수
    while recent and recent[0].role_cd != ROLE_USER:
        recent = recent[1:]
    # 저장된 답변의 고지는 떼고 넘김 : 모델이 따라 써 고지가 두 번 붙는 것 방지
    return [
        {"role": "user", "content": m.cnvrs_cn}
        if m.role_cd == ROLE_USER
        else {"role": "assistant", "content": m.cnvrs_cn.removesuffix(DISCLAIMER)}
        for m in recent
    ]


# 브라우저 연결이 끊겨도 답변 생성·저장을 끝까지 하도록 별도 작업으로 분리 (architecture.md)
_running: set[asyncio.Task] = set()


async def answer_turn(
    turn: Turn,
    repo: ConversationRepository,
    agent: ToolAgent,
    ai: AiSettings,
    limits: AnswerLimits,
    register: "RegisterDeps | None" = None,
    titles: TitleGenerator | None = None,
    reader: ToolReader | None = None,
) -> AsyncIterator[Event]:
    queue: asyncio.Queue[Event | None] = asyncio.Queue()
    task = asyncio.create_task(
        _run_turn(turn, repo, agent, ai, limits, queue.put_nowait, register, titles, reader)
    )
    _running.add(task)
    task.add_done_callback(_running.discard)
    while (event := await queue.get()) is not None:
        yield event


async def _run_turn(
    turn: Turn,
    repo: ConversationRepository,
    agent: ToolAgent,
    ai: AiSettings,
    limits: AnswerLimits,
    emit: Callable[[Event | None], None],
    register: "RegisterDeps | None" = None,
    titles: TitleGenerator | None = None,
    reader: ToolReader | None = None,
) -> None:
    try:
        text = turn.question.cnvrs_cn
        card = None
        priors = turn.priors()
        if register is not None and priors:
            # 돌려받은 확인 카드 + 확인·취소 말 : LLM 없이 실행 지시·취소 (2026-11-13)
            # 여러 명령 ② : 카드가 여럿이면 확인 말 한 번에 모두, 취소 말이면 모두 버림
            reply = rules.action_reply_kind(text)
            if reply is not None:
                await _action_answer(reply, turn, priors, repo, register, emit)
                return
        if register is not None and turn.draft is not None:
            # FN-AIM-012-05·10 : 초안이 있으면 이 메시지로 칸 채움·수정
            # 뽑힌 칸이 없으면 일반 판정
            card = await build_card(text, turn.pet_sn, turn.draft, register)
        if card is not None:
            judged = Judged(Intent(kind=IntentKind.REGISTER))
        else:
            # 항상 이 흐름(2026-11-09) : 분류·목차 선택·등록 칸 추출을 도구 고르기 한 번으로
            context = build_context(turn.messages, turn.question.msg_seq, ai.context_turns)
            today = register.today if register is not None else rules.today_kst()
            now = datetime.combine(today, datetime.now(rules.KST).time())
            read = (
                ReadDeps(reader, register.contexts, turn.pet_sn, now, tuple(priors))
                if reader is not None and register is not None
                else None
            )
            judged = await judge_tools(
                text,
                context,
                agent,
                ai.max_tokens,
                today,
                limits.first_token_sec,
                read,
                turn.action,
                now,
                priors,
            )
        emit(("intent", judged.intent))
        kind = judged.intent.kind
        if kind is IntentKind.SEARCH:
            if judged.stream is None:
                # 도구 흐름의 SEARCH는 늘 답변 스트림을 줌 : 없으면 일시 오류
                raise RuntimeError("SEARCH 판정에 답변 스트림 없음")
            answer = await _search_answer(
                turn,
                repo,
                limits,
                judged.shortcut,
                emit,
                judged.stream,
                judged.cards,
                _notice(judged),
                judged.follow_shortcuts,
            )
            if answer is not None and titles is not None and _is_first_answer(turn):
                await _retitle(repo, titles, turn, answer)
        elif kind is IntentKind.FALLBACK:
            fallback = await reply_fallback(repo, turn.room_sn, judged.out_of_scope)
            emit(("done", AnswerDone(message=fallback)))
        elif kind is IntentKind.ROUTE:
            # 이동은 React 담당 : 다시 열어도 답이 남게 이동 안내 저장 (2026-10-29 결정)
            move = route_message(judged.intent.scr_nm or "")
            emit(("done", AnswerDone(message=await _save(repo, turn.room_sn, move, True))))
        elif kind is IntentKind.REGISTER and register is not None:
            card = card or await build_card(
                text, turn.pet_sn, None, register, judged.ai_values, judged.tool
            )
            await _register_reply(repo, turn.room_sn, card, emit)
        elif kind is IntentKind.ACTION and register is not None:
            cards = await _action_reply(text, turn, judged, register)
            # 카드 요약을 글로 저장 : 모달 대신 채팅으로 확인, 다음 턴 맥락에도 남음 (2026-11-13)
            saved = await _save(repo, turn.room_sn, action_ask_message(cards), True)
            emit(("done", AnswerDone(message=saved, action=cards[0], actions=cards)))
        else:
            # RECEIPT는 SCR-AIM-013에서 잇는다
            emit(("done", AnswerDone()))
    except ClassifyError:
        # 분류 LLM 장애는 폴백이 아닌 일시 오류 (2026-10-29 결정), 원인 로그는 분류기에서 기록
        emit(("error", StreamError(code="EXTERNAL_API_ERROR", message=ANSWER_ERROR_MESSAGE)))
    except Exception:
        logger.exception("대화 응답 처리 실패")
        emit(("error", StreamError(code="EXTERNAL_API_ERROR", message=ANSWER_ERROR_MESSAGE)))
    finally:
        emit(None)


async def _search_answer(
    turn: Turn,
    repo: ConversationRepository,
    limits: AnswerLimits,
    shortcut: Intent | None,
    emit: Callable[[Event | None], None],
    stream: AsyncIterator[str],
    cards: list[ActionCard] | None = None,
    notice: Callable[[], bool] = lambda: True,
    follow_shortcuts: list[Intent] | None = None,
) -> str | None:
    # FN-AIM-002-02·07 : 완료면 고지 전 본문 반환(제목 요약용), 실패·미완료면 None
    # follow_shortcuts : 결과 뒤 고른 이동·사용법 화면, 스트림이 끝난 뒤 첫 READ 화면보다 우선
    # stream : 도구 흐름이 이미 시작한 답변 스트림
    loop = asyncio.get_running_loop()
    started_at = loop.time()
    deadline = started_at + limits.total_sec
    first_deadline = started_at + limits.first_token_sec
    try:
        # 첫 글자 전 실패 : 미저장·안내, 사용자 메시지는 남아 [다시 시도]로 재호출
        reason = "empty"
        try:
            async with asyncio.timeout_at(min(deadline, first_deadline)):
                first = await anext(stream, None)
        except TimeoutError:
            first = None
            reason = "total_timeout" if deadline <= first_deadline else "first_token_timeout"
        except AnswerError as error:
            first = None
            reason = error.reason
        if first is None:
            # 추가 요청 : 실패 이유 한 줄(원문 없음)
            logger.warning(
                "답변 실패: 첫 글자 전 %s room=%d (%.0fms)",
                reason,
                turn.room_sn,
                (loop.time() - started_at) * 1000,
            )
            emit(("error", StreamError(code="EXTERNAL_API_ERROR", message=ANSWER_ERROR_MESSAGE)))
            return None
        chunks = [first]
        emit(("delta", {"text": first}))
        complete = False
        try:
            async with asyncio.timeout_at(deadline):
                async for text in stream:
                    chunks.append(text)
                    emit(("delta", {"text": text}))
            complete = True
        except (TimeoutError, AnswerError) as error:
            # 전체 시간 초과·도중 오류 : 부분 답변을 미완료로 저장
            logger.warning(
                "답변 미완료: 도중 %s room=%d %d자 (%.0fms)",
                error.reason if isinstance(error, AnswerError) else "total_timeout",
                turn.room_sn,
                sum(len(c) for c in chunks),
                (loop.time() - started_at) * 1000,
            )
    finally:
        await stream.aclose()
    body = "".join(chunks)
    text = body
    if complete and notice():
        # FN-AIM-002-03 : 건강 관련 응답만 고지를 본문 끝에 포함해 저장, 미완료 답변 제외
        emit(("delta", {"text": DISCLAIMER}))
        text += DISCLAIMER
    message = await _save(repo, turn.room_sn, text, complete)
    action = cards[0] if cards else None
    if follow_shortcuts:
        shortcut = follow_shortcuts[0]
    # FN-AIM-002-04 : 확인 카드가 같이 나가는 턴은 바로가기 없음
    shortcut = None if action is not None else shortcut
    actions = [action] if action is not None else None
    done = AnswerDone(message=message, shortcut=shortcut, action=action, actions=actions)
    emit(("done", done))
    return body if complete else None


def _notice(judged: Judged) -> Callable[[], bool]:
    # FN-AIM-002-03 : READ 답변은 스트림이 끝난 뒤 고지 READ(도구 notice)가 하나라도 성공했는지로
    # 일정·케어 항목·일지 등 기록만 읽어 주는 READ는 고지 없음(2026-11-11)
    def decide() -> bool:
        if not judged.notice:
            return False
        return judged.notice_reads is None or bool(judged.notice_reads)

    return decide


def _is_first_answer(turn: Turn) -> bool:
    # 의도 종류는 메시지에 없음 : 방의 첫 AI 메시지일 때만 (한 방에 1회)
    return not any(m.role_cd == ROLE_AI for m in turn.messages)


async def _retitle(
    repo: ConversationRepository, titles: TitleGenerator, turn: Turn, answer: str
) -> None:
    # 추가 요청(SCR-AIM-011) : 첫 SEARCH 답변 뒤 질문·답변 요약으로 제목 1회 교체
    # done 뒤 실행 : 실패해도 이미 보낸 답변 유지, 제목은 그대로 (error 이벤트 없음)
    try:
        summary = await titles.summarize(turn.question.cnvrs_cn, answer)
        title = _cut_title(summary)
        if title:
            await repo.update_title(turn.room_sn, title)
    except Exception as error:
        logger.warning("대화 제목 교체 실패: room=%d (%s)", turn.room_sn, type(error).__name__)


async def _save(
    repo: ConversationRepository, room_sn: int, text: str, complete: bool
) -> ConversationMessage | None:
    # 저장 실패해도 이미 보낸 답변 유지 (1,000자 상한 없음, 2026-10-28 결정)
    try:
        return await repo.add_message(room_sn, ROLE_AI, text, cmptn_yn=complete)
    except (AppError, BackendError) as error:
        logger.warning(
            "AI 답변 저장 실패: %d자 cmptnYn=%s (%s)", len(text), complete, type(error).__name__
        )
        return None


@dataclass(frozen=True)
class RegisterDeps:
    contexts: RegisterContextRepository
    extractor: RegisterExtractor
    today: date


# 카드 종류별로 남기는 칸
_SCHEDULE_FIELDS = (
    "schdl_knd_cd",
    "schdl_ymd",
    "schdl_tm",
    "ckup_type_cd",
    "hsptl_nm",
    "schdl_nm",
    "memo_cn",
)
_CARE_FIELDS = ("care_artcl_nm", "care_zone_cd", "care_cycle_cd", "cycle_days", "last_cmptn_ymd")
_DRAFT_FIELDS = _SCHEDULE_FIELDS + _CARE_FIELDS
# FN-AIM-012-08 : 같은 이름 케어 항목 안내(10-01 확정 문구)
DUPLICATE_NOTICE = "{pet}에게 '{name}' 항목이 이미 있어요. 그래도 새로 등록할까요?"
# FN-AIM-012-11 : 화면설계서 SCR-AIM-012 ④ 문구(디자인 v5)
CANCELED_MESSAGE = "취소됨 — 등록하지 않았어요."
_CYCLE_LABELS = {
    rules.CYCLE_1W: "1주마다",
    rules.CYCLE_2W: "2주마다",
    rules.CYCLE_MONTH: "한달마다",
    rules.CYCLE_YEAR: "1년마다",
}


def _missing(values: dict) -> list[str]:
    # FN-AIM-012-05 : 필수 칸. 병원 = 검진유형·병원명, 그 외 = 일정명(FN-AIM-012-12와 같은 기준)
    if values.get("care_zone_cd"):
        required = ["care_artcl_nm"]
        if values["care_zone_cd"] == rules.ZONE_PERIODIC:
            required.append("care_cycle_cd")
            if values.get("care_cycle_cd") == rules.CYCLE_CUSTOM:
                required.append("cycle_days")
    else:
        required = ["schdl_knd_cd", "schdl_ymd"]
        if values.get("schdl_knd_cd") == rules.SCHEDULE_HOSPITAL:
            required += ["ckup_type_cd", "hsptl_nm"]
        elif values.get("schdl_knd_cd"):
            required.append("schdl_nm")
    return [name for name in required if not values.get(name)]


def _draft_values(draft: RegisterDraft) -> dict:
    return draft.model_dump(include=set(_DRAFT_FIELDS), exclude_none=True)


def _answer_fill(text: str, draft: RegisterDraft, pet_names: list[str]) -> dict:
    # 되물음에 답만 한 경우("발톱 깎기", "산책", "기타") : 물었던 이름 칸에 이 답 채움
    missing = _missing(_draft_values(draft))
    answer = rules.care_item_name(text, 0, pet_names)
    if not answer:
        return {}
    if "care_artcl_nm" in missing:
        return {"care_artcl_nm": answer}
    if "schdl_knd_cd" in missing and answer.startswith("기타"):
        return {"schdl_knd_cd": rules.SCHEDULE_ETC}
    if "schdl_nm" in missing:
        return {"schdl_nm": answer}
    return {}


# FN-AIM-012-04 : 같은 이름 반려동물을 좁히는 종 말. "개"는 "두 개"·"개월"과 겹쳐 쓰지 않는다
SPECIES_WORDS = {"강아지": ("강아지", "댕댕이", "멍멍이"), "고양이": ("고양이", "냥이")}


def named_pets(pets: list[PetInfo], text: str) -> list[PetInfo]:
    """문장 속 이름에 걸린 반려동물. 같은 이름이 여럿이면 문장의 품종 이름 > 종 말로 좁힌다
    (FN-AIM-012-04 보강, 2026-11-23). 다른 이름끼리 여럿("초코랑 까미")은 좁히지 않는다"""
    compact = re.sub(r"\s+", "", text)
    named = [pet for pet in pets if pet.pet_nm in compact]
    if len(named) < 2 or len({pet.pet_nm for pet in named}) > 1:
        return named
    by_vrty = [p for p in named if p.vrty_nm and re.sub(r"\s+", "", p.vrty_nm) in compact]
    named = by_vrty or named
    said = {se for se, words in SPECIES_WORDS.items() if any(word in compact for word in words)}
    by_se = [pet for pet in named if pet.pet_se_nm in said]
    return by_se or named


def pet_choices(pets: list[PetInfo], named: list[PetInfo]) -> list[PetChoice]:
    # 못 정했을 때 칩 : 이름이 여러 마리에 걸렸으면 그 아이들만, 아니면 양육 반려동물 전부
    shown = named if len(named) > 1 else pets
    return [
        PetChoice(pet_sn=p.pet_sn, pet_nm=p.pet_nm, pet_se_nm=p.pet_se_nm, vrty_nm=p.vrty_nm)
        for p in shown
    ]


def _pick_pet(
    pets: list[PetInfo], named: list[PetInfo], draft_pet: int | None, room_pet: int | None
) -> PetInfo | None:
    # FN-AIM-012-04 : 반려동물은 항상 서버 규칙으로 결정, None이면 이름 칩으로 되물음
    if len(named) == 1:
        return named[0]
    if named:
        # 같은 이름 여럿 : 그 안에 직전 카드 반려동물 > 펫 태그가 있으면 그 아이(2026-11-23 추가-1)
        # 다른 이름끼리 여럿("초코랑 까미")은 두 마리를 말한 것이라 정하지 않는다
        if len({pet.pet_nm for pet in named}) > 1:
            return None
        same = {pet.pet_sn: pet for pet in named}
        return same.get(draft_pet) or same.get(room_pet)
    by_sn = {pet.pet_sn: pet for pet in pets}
    if draft_pet in by_sn:
        return by_sn[draft_pet]
    if len(pets) == 1:
        return pets[0]
    return by_sn.get(room_pet)


async def build_card(
    text: str,
    room_pet: int | None,
    draft: RegisterDraft | None,
    deps: RegisterDeps,
    ai_values: dict | None = None,
    tool: str | None = None,
) -> RegisterCard | None:
    # FN-AIM-012-02~08·10. 초안이 있는데 이 메시지에서 뽑힌 칸이 없으면 None(일반 판정으로)
    pets = await deps.contexts.get_pets()
    names = [pet.pet_nm for pet in pets]
    named = named_pets(pets, text)
    parsed = rules.parse_register(text, deps.today, names).values()
    if draft is None:
        values = parsed
    else:
        found = parsed or _answer_fill(text, draft, names)
        if not found and not named:
            return None
        values = _draft_values(draft) | found
    if _missing(values) and ai_values is not None:
        # 도구 흐름 : 도구 인자가 AI 보충 값(추출기 미호출)
        for name, value in ai_values.items():
            values.setdefault(name, value)
    elif _missing(values):
        # FN-AIM-012-03 : 빈 칸만 AI 보충, 반려동물 목록 제외
        try:
            raw = await deps.extractor.extract(text, deps.today)
        except Exception:
            logger.exception("등록 칸 추출 실패")
            raw = {}
        for name, value in rules.clean_ai_fields(raw).values().items():
            values.setdefault(name, value)
    if values.get("schdl_knd_cd") == rules.SCHEDULE_HOSPITAL:
        values.pop("schdl_nm", None)
    care = tool == tools.DRAFT_CARE_ITEM or bool(values.get("care_zone_cd"))
    keep = _CARE_FIELDS if care else _SCHEDULE_FIELDS
    values = {name: value for name, value in values.items() if name in keep}
    pet = _pick_pet(pets, named, draft.pet_sn if draft else None, room_pet)
    empty = tools.register_missing(tool, values)
    missing = (["pet_sn"] if pet is None else []) + (_missing(values) if empty is None else empty)
    card = RegisterCard(
        card_type=CardType.ASK if missing else CardType.CARE_ITEM if care else CardType.SCHEDULE,
        pet_sn=pet.pet_sn if pet else None,
        pet_nm=pet.pet_nm if pet else None,
        pet_choices=[] if pet else pet_choices(pets, named),
        missing=[to_camel(name) for name in missing],
        **values,
    )
    if care:
        last = card.last_cmptn_ymd or deps.today
        card.nxtm_prnmnt_ymd = rules.next_due(
            card.care_zone_cd, card.care_cycle_cd, card.cycle_days, last
        )
        if pet is not None and _same_name(card.care_artcl_nm, pet.care_artcl_nms):
            card.duplicate_name = True
            card.notice = DUPLICATE_NOTICE.format(pet=pet.pet_nm, name=card.care_artcl_nm)
    return card


def _same_name(name: str | None, existing: tuple[str, ...]) -> bool:
    # 띄어쓰기만 다른 이름도 동일 이름 처리 ("발톱깎기" = "발톱 깎기")
    if not name:
        return False
    return re.sub(r"\s+", "", name) in {re.sub(r"\s+", "", n) for n in existing}


def ask_message(card: RegisterCard) -> str:
    # FN-AIM-012-05 : 빈 칸만 묻는다. 병원 문구는 화면설계서 SCR-AIM-012 ⑦
    missing = set(card.missing)
    parts = []
    if "petSn" in missing:
        target = "케어 항목" if card.care_zone_cd else "일정"
        parts.append(f"어느 아이의 {target}인가요? 아래에서 골라 주세요.")
    if "careArtclNm" in missing:
        parts.append("어떤 케어 항목인가요?")
    if "careZoneCd" in missing:
        parts.append("매일 하나요, 주기마다 하나요?")
    if missing & {"careCycleCd", "cycleDays"}:
        parts.append("얼마나 자주 하나요? (예: 매주, 2주마다, 한달마다)")
    if "schdlKndCd" in missing:
        parts.append("어떤 일정인가요? (병원 / 미용·목욕 / 케어·투약 / 기타)")
    if "schdlYmd" in missing:
        parts.append("날짜는 언제인가요?")
    if {"hsptlNm", "ckupTypeCd"} <= missing:
        parts.append("어느 병원인가요? 검진 종류도 알려 주세요. (예: 정기검진, 예방접종)")
    elif "hsptlNm" in missing:
        parts.append("어느 병원인가요?")
    elif "ckupTypeCd" in missing:
        parts.append("검진 종류를 알려 주세요. (예: 정기검진, 예방접종)")
    if "schdlNm" in missing:
        parts.append("일정 이름을 알려 주세요.")
    return " ".join(parts)


async def _register_reply(
    repo: ConversationRepository,
    room_sn: int,
    card: RegisterCard,
    emit: Callable[[Event | None], None],
) -> None:
    # FN-AIM-012-05·06·07 : 되물음은 AI 메시지로 저장, 미리보기 카드는 미저장
    # (결과만 텍스트 요약으로 저장, FN-AIM-012-16)
    message = None
    if card.card_type is CardType.ASK:
        message = await _save(repo, room_sn, ask_message(card), True)
    emit(("done", AnswerDone(message=message, card=card)))


def _md(day: date) -> str:
    return f"{day:%m-%d}({rules.WEEKDAYS[day.weekday()]})"


def result_message(request: RegisterResultRequest) -> str:
    # FN-AIM-012-16 : 카드 결과를 담은 텍스트 요약, 다시 열면 버튼 없이 이 글만 표시
    card = request.card
    if card.card_type is CardType.ASK or not card.pet_nm or _missing(_draft_values(card)):
        raise AppError("INVALID_REQUEST", 400, "등록 카드의 칸이 비어 있습니다.")
    if request.result is RegisterResult.CANCELED:
        return CANCELED_MESSAGE
    if card.card_type is CardType.SCHEDULE:
        hospital = card.schdl_knd_cd == rules.SCHEDULE_HOSPITAL
        label = rules.code_name(card.ckup_type_cd) if hospital else card.schdl_nm
        when = _md(card.schdl_ymd) + (f" {card.schdl_tm}" if card.schdl_tm else "")
        return f"✔ 등록됨 — {card.pet_nm} {label} · {when}"
    if card.care_zone_cd == rules.ZONE_DAILY:
        cycle = "매일"
    else:
        cycle = _CYCLE_LABELS.get(card.care_cycle_cd) or f"{card.cycle_days}일마다"
    text = f"✔ 등록됨 — {card.pet_nm} {card.care_artcl_nm} · {cycle}"
    if card.nxtm_prnmnt_ymd:
        text += f" · 다음 예정일 {_md(card.nxtm_prnmnt_ymd)}"
    return text


async def save_register_result(
    repo: ConversationRepository, room_sn: int, request: RegisterResultRequest
) -> ConversationMessage:
    # FN-AIM-012-11·16 : 등록(React → Java)과 취소의 결과를 AI 메시지로 저장
    return await repo.add_message(room_sn, ROLE_AI, result_message(request))


RECEIPT_PREFIX = "영수증 분석 — "
RECEIPT_MESSAGES = {
    ReceiptResult.FAILED: "영수증을 읽지 못했어요",
    ReceiptResult.ERROR: "일시적인 오류로 분석하지 못했어요",
    ReceiptResult.CANCELED: "취소했어요",
}


def receipt_result_message(request: ReceiptResultRequest) -> str:
    # FN-AIM-013-09 : 결과 요약 한 줄, 다시 열면 버튼 없이 이 글만 표시
    if request.result is not ReceiptResult.RECOGNIZED:
        return RECEIPT_PREFIX + RECEIPT_MESSAGES[request.result]
    parts = []
    if request.hsptl_nm:
        parts.append(request.hsptl_nm)
    if request.ckup_ymd:
        parts.append(f"{request.ckup_ymd.month}월 {request.ckup_ymd.day}일")
    if request.recpt_amt is not None:
        parts.append(f"{request.recpt_amt:,}원")
    return RECEIPT_PREFIX + (", ".join(parts) or "결과를 확인해 주세요")


async def save_receipt_result(
    repo: ConversationRepository, room_sn: int, request: ReceiptResultRequest
) -> list[ConversationMessage]:
    # FN-AIM-013-02 : 함께 보낸 텍스트는 의도 판정 없이 사용자 메시지로 저장 (분석에는 미사용)
    saved = []
    if request.cnvrs_cn is not None:
        saved.append(await repo.add_message(room_sn, ROLE_USER, request.cnvrs_cn))
    saved.append(await repo.add_message(room_sn, ROLE_AI, receipt_result_message(request)))
    return saved


def _rejected(entry: "catalog.CatalogEntry", values: dict, card: dict) -> list[str]:
    # LLM 값이 Java 칸 규칙 밖이라 카드에서 비운 칸 : 되물음(배열·번호·날짜 hook 칸 제외)
    plain = {name: value for name, value in values.items() if name not in entry.hook_roles}
    found: list[str] = []
    for name, value in catalog.to_java(entry, plain).items():
        param = entry.params.get(name)
        skip = param is None or param.type == catalog.ARRAY or catalog.is_id(name)
        if skip or name == catalog.PET_SN:
            continue
        if value != "" and card.get(name) is None:
            found.append(name)
    return found


def action_card(
    entry: "catalog.CatalogEntry",
    values: dict,
    pets: list[PetInfo],
    named: list[PetInfo],
    draft_pet: int | None,
    room_pet: int | None,
    rejected: Sequence[str] = (),
) -> ActionCard:
    """확인 카드(2단계 쓰기) : Java 칸 그대로 + 검증한 input + 빈 필수 칸"""
    values = dict(values)
    pet = None
    choices: list[PetChoice] = []
    if "line_pet" in entry.hooks and len(named) == 1:
        # 배열 첫 줄의 petSn(지출 등록) : 문장 속 이름이 하나면 그 번호, 아니면 그대로(비면 공용)
        for array in catalog.mapped_arrays(entry):
            rows = values.get(array) or [{}]
            values[array] = [rows[0] | {catalog.PET_SN: named[0].pet_sn}, *rows[1:]]
    if "pet" in entry.hooks:
        # FN-AIM-012-04 규칙 : 못 정하면 이름 칩
        pet = _pick_pet(pets, named, draft_pet, room_pet)
        if pet is not None:
            values[catalog.PET_SN] = pet.pet_sn
        else:
            choices = pet_choices(pets, named)
    notice = None
    name = values.get("careArtclNm")
    warn = "same_name_warning" in entry.hooks and pet is not None and isinstance(name, str)
    # FN-AIM-012-08 : 같은 반려동물에 같은 이름의 케어 항목이 있으면 안내
    if warn and _same_name(name, pet.care_artcl_nms):
        notice = DUPLICATE_NOTICE.format(pet=pet.pet_nm, name=name)
    same_name = pet is not None and values.get("petNm") == pet.pet_nm
    if entry.call.method.upper() == "PATCH" and same_name:
        # 수정 카드는 바꿀 칸만 : 지금 이름과 같은 새 이름은 뺀다(요약 "탄이 … 수정 — 탄이" 막기)
        values.pop("petNm")
    missing = catalog.missing(entry, values)
    missing += [name for name in rejected if name not in missing]
    return ActionCard.model_validate(
        {
            "tool": entry.name,
            "domain": entry.domain,
            "label": entry.label,
            "call": entry.call.model_dump(exclude_none=True),
            "params": catalog.card_params(entry),
            "rules": catalog.card_rules(entry),
            "input": values,
            "missing": missing,
            "petChoices": choices,
            "petNm": pet.pet_nm if pet else None,
            "notice": notice,
        }
    )


async def _action_reply(
    text: str, turn: Turn, judged: Judged, register: RegisterDeps
) -> list[ActionCard]:
    # 카드는 미저장 : 결과만 action-result로 텍스트 요약 저장
    entry = tools.card_entry(judged.tool)
    if entry is None:
        raise AppError("INVALID_REQUEST", 400, "모르는 도구입니다.")
    picked = [(entry, judged.action or {}, judged.rejected)]
    for tool, values, rejected in judged.more:
        more = tools.card_entry(tool)
        if more is not None:
            picked.append((more, values, rejected))
    priors = turn.priors()
    # 고치기(여러 명령 ②) : 고른 도구가 모두 돌려받은 목록 안이면 나머지 카드는 그대로
    prior_tools = [draft.tool for draft in priors]
    keep = len(priors) > 1 and all(item.name in prior_tools for item, *_ in picked)
    used = [item for item, *_ in picked]
    if keep:
        used += [e for draft in priors if (e := tools.card_entry(draft.tool)) is not None]
    pets = await register.contexts.get_pets() if any(_uses_pets(e) for e in used) else []
    named = named_pets(pets, text)
    if keep:
        return _kept_cards(picked, judged, priors, pets, named, turn.pet_sn)
    # 두 마리 이상 이름 : 새 등록 카드를 이름마다 한 장씩 (2026-11-23). 넘치면 나누지 않음
    groups = [_pet_groups(item, named) for item, *_ in picked]
    if sum(len(group) or 1 for group in groups) > ACTION_MAX_CARDS:
        groups = [[] for _ in picked]
    cards: list[ActionCard] = []
    for (item, values, rejected), group in zip(picked, groups, strict=True):
        prior = next((draft for draft in priors if draft.tool == item.name), None)
        draft_pet = prior.values.get(catalog.PET_SN) if prior is not None else None
        for pets_of in group or [named]:
            cards.append(action_card(item, values, pets, pets_of, draft_pet, turn.pet_sn, rejected))
    if len(cards) > len(picked):
        logger.info("반려동물별 쓰기 카드 %d장", len(cards))
    return cards


def _pet_groups(entry: "catalog.CatalogEntry", named: list[PetInfo]) -> list[list[PetInfo]]:
    # 문장 속 다른 이름이 둘 이상이면 이름별 반려동물 묶음(같은 이름 여럿은 한 묶음), 아니면 빈 목록
    # 반려동물 칸이 있는 새 등록 카드(POST)이고 번호 칸(…Sn, petSn 제외)이 없는 도구만 나눈다
    # 케어 완료 체크·관찰 기록처럼 번호가 그 아이의 기록을 가리키는 도구는 나누면 남의 번호가 됨
    if "pet" not in entry.hooks or entry.call.method.upper() != "POST":
        return []
    if any(catalog.is_id(name) for name in entry.params):
        return []
    by_name: dict[str, list[PetInfo]] = {}
    for pet in named:
        by_name.setdefault(pet.pet_nm, []).append(pet)
    return list(by_name.values()) if len(by_name) > 1 else []


def _kept_cards(
    picked: list[tuple["catalog.CatalogEntry", dict, tuple[str, ...]]],
    judged: Judged,
    priors: list[ActionDraft],
    pets: list[PetInfo],
    named: list[PetInfo],
    room_pet: int | None,
) -> list[ActionCard]:
    # 고치기(여러 명령 ②) : 고른 도구의 카드만 바뀌고 나머지 카드는 그대로 목록으로
    # 같은 도구 카드가 여럿이면(반려동물별) 이름이 나온 아이의 카드만, 없으면 모두 (2026-11-23)
    per_prior = {no: (values, rejected) for no, values, rejected in judged.per_prior}
    named_sns = {pet.pet_sn for pet in named}
    targets = {no for no in per_prior if priors[no].values.get(catalog.PET_SN) in named_sns} or set(
        per_prior
    )
    built: dict[str, ActionCard] = {}
    merged: list[ActionCard] = []
    for no, draft in enumerate(priors):
        spec = next((item for item in picked if item[0].name == draft.tool), None)
        draft_pet = draft.values.get(catalog.PET_SN)
        if spec is None or (no in per_prior and no not in targets):
            found = _prior_card(draft, pets, room_pet)
        elif no in per_prior:
            values, rejected = per_prior[no]
            # 이름으로 고른 카드면 그 이름, 아니면 카드의 반려동물 그대로
            own = [pet for pet in named if pet.pet_sn == draft_pet] if named_sns else []
            found = action_card(spec[0], values, pets, own, draft_pet, room_pet, rejected)
        else:
            if draft.tool not in built:
                entry, values, rejected = spec
                built[draft.tool] = action_card(
                    entry, values, pets, named, draft_pet, room_pet, rejected
                )
            found = built[draft.tool]
        if found is not None:
            merged.append(found)
    return merged


def _prior_card(draft: ActionDraft, pets: list[PetInfo], room_pet: int | None) -> ActionCard | None:
    # 돌려받은 카드 input을 다시 검증한 카드(Java 규칙 밖 값·목록 밖 칸은 버림), 모르는 도구면 None
    entry = tools.card_entry(draft.tool)
    if entry is None:
        return None
    values = catalog.card_input(entry, {}, None, {}, draft.values)
    return action_card(entry, values, pets, [], draft.values.get(catalog.PET_SN), room_pet)


def action_summary(card: ActionCard) -> str:
    """카드 input 요약 한 줄 : action-result 요약과 같은 글(번호·petSn·참거짓·파일 칸 빼고)"""
    entry = tools.card_entry(card.tool)
    label = card.label or card.tool
    if entry is None:
        return label
    values = {name: value for name, value in card.values.items() if value is not None}
    clock = values.get(catalog.HR_INPUT) is not False
    parts = [
        _input_text(param, values[name], clock, _count_word(entry.name, name))
        for name, param in entry.params.items()
        if name in values and name not in entry.fixed and _summarized(name, param)
    ]
    parts = [part for part in parts if part]
    head = f"{card.pet_nm} " if card.pet_nm else ""
    return f"{head}{label}" + (f" — {' · '.join(parts)}" if parts else "")


def action_ask_message(card: ActionCard | list[ActionCard]) -> str:
    """확인 카드 턴의 저장 글 : 요약 + 빈 칸 안내 또는 확인 말 안내
    - 카드가 둘 이상이면 번호 붙은 요약 줄, 빈 칸은 카드 번호로 (여러 명령 ②)"""
    cards = card if isinstance(card, list) else [card]
    if len(cards) == 1:
        summary = action_summary(cards[0])
    else:
        summary = "\n".join(
            ACTION_ASK_LINE.format(no=no, summary=action_summary(item))
            for no, item in enumerate(cards, start=1)
        )
    lines = [ACTION_ASK_TEMPLATE.format(summary=summary)]
    missing = _missing_lines(cards)
    lines.extend(missing or [_worded(ACTION_ASK_CONFIRM, cards)])
    return "\n".join(lines)


def _missing_lines(cards: list[ActionCard]) -> list[str]:
    # 빈 칸 되물음 줄 : 카드 하나면 지금 문구, 여럿이면 빈 칸이 있는 카드마다 번호로
    if len(cards) == 1:
        if not cards[0].missing:
            return []
        names = _missing_names(cards[0])
        same = _same_pet_line(cards[0])
        if same is None:
            return [ACTION_ASK_MISSING.format(names=_names_subject(names))]
        # 같은 이름이라 못 정함 : 어느 아이인지 먼저, 나머지 빈 칸은 이어서 (추가-2)
        rest = [name for name in names if name != PET_LABEL]
        if not rest:
            return [same]
        return [same, ACTION_ASK_MISSING_REST.format(names=_names_subject(rest))]
    lines: list[str] = []
    for no, item in enumerate(cards, start=1):
        if not item.missing:
            continue
        names = _missing_names(item)
        same = _same_pet_line(item)
        if same is None:
            lines.append(ACTION_ASK_MISSING_NO.format(no=no, names=_names_subject(names)))
            continue
        # 같은 이름이라 못 정함 : 카드 하나일 때처럼 어느 아이인지 먼저 (2026-11-23)
        lines.append(ACTION_ASK_SAME_PET_NO.format(no=no, line=same))
        rest = [name for name in names if name != PET_LABEL]
        if rest:
            lines.append(ACTION_ASK_MISSING_REST_NO.format(no=no, names=_names_subject(rest)))
    return lines


def _same_pet_line(card: ActionCard) -> str | None:
    # 반려동물 칸이 비었고 칩이 모두 같은 이름일 때 : 무엇으로 구별할지 예시
    if catalog.PET_SN not in card.missing:
        return None
    choices = card.pet_choices
    if len(choices) < 2 or len({choice.pet_nm for choice in choices}) > 1:
        return None
    pet = choices[0].pet_nm
    counts = {2: "둘이에요", 3: "셋이에요", 4: "넷이에요"}
    count = counts.get(len(choices), f"{len(choices)}마리예요")
    name = _names_subject([pet])
    hints = [
        [choice.pet_se_nm for choice in choices],
        [choice.vrty_nm for choice in choices],
    ]
    hint = next((h[0] for h in hints if all(h) and len(set(h)) == len(h)), None)
    if hint is None:
        return ACTION_ASK_SAME_PET_CHIP.format(name=name, count=count)
    return ACTION_ASK_SAME_PET.format(name=name, count=count, hint=hint, pet=pet)


def _missing_names(card: ActionCard) -> list[str]:
    # 빈 Java 칸 -> 도구 설명의 LLM 칸 설명 앞부분("기록 날짜"), 없으면 Java 칸 이름
    entry = tools.card_entry(card.tool)
    prompt = catalog.tool_prompts().get(card.tool)
    by_java = {java: name for name, java in entry.to_java_name.items()} if entry else {}
    roles = entry.hook_roles if entry else {}
    ymd = next((name for name, role in roles.items() if role == "date:ymd"), None)
    names: list[str] = []
    for java in card.missing:
        if java == catalog.PET_SN:
            names.append(PET_LABEL)
            continue
        key = re.sub(r"\[\d+\]", "[]", java)
        llm = by_java.get(key)
        param = entry.params.get(java) if entry else None
        if llm is None and param is not None and param.type == "datetime":
            llm = ymd
        desc = prompt.params[llm].description if prompt and llm in prompt.params else ""
        # "기록 날짜 YYYY-MM-DD. …" -> "기록 날짜" : 형식 표기(영문·숫자)와 괄호·마침표 뒤는 뗀다
        name = re.split(r"[.(:,]|\s+(?=[A-Z0-9])", desc, maxsplit=1)[0].strip() or java
        if name not in names:
            names.append(name)
    return names


def _names_subject(names: list[str]) -> str:
    # "기록 날짜, 반려동물" + 이/가 (마지막 글자 받침 기준)
    joined = ", ".join(names)
    last = joined[-1] if joined else ""
    batchim = "가" <= last <= "힣" and (ord(last) - ord("가")) % 28 != 0
    return joined + ("이" if batchim else "가")


async def _action_answer(
    reply: str,
    turn: Turn,
    priors: list[ActionDraft],
    repo: ConversationRepository,
    register: RegisterDeps,
    emit: Callable[[Event | None], None],
) -> None:
    # 확인 말 : 빈 칸이 없으면 React에 실행 지시(execute), 있으면 빈 칸 되물음. 취소 말 : 카드 버림
    # 여러 명령 ② : 카드가 여럿이면 모두 빈 칸이 없을 때만 실행 지시, 취소 말은 모두 버림
    entries = [e for draft in priors if (e := tools.card_entry(draft.tool)) is not None]
    emit(("intent", Intent(kind=IntentKind.ACTION)))
    verb = action_verb([entry.call.method for entry in entries])
    if reply == rules.ACTION_CANCEL or not entries:
        drop = ACTION_DROP_MESSAGE.replace(ACTION_VERB_ADD, verb)
        saved = await _save(repo, turn.room_sn, drop, True)
        emit(("done", AnswerDone(message=saved)))
        return
    pets = await register.contexts.get_pets() if any(_uses_pets(e) for e in entries) else []
    cards = [card for draft in priors if (card := _prior_card(draft, pets, turn.pet_sn))]
    missing = _missing_lines(cards)
    if missing:
        saved = await _save(repo, turn.room_sn, "\n".join(missing), True)
        emit(("done", AnswerDone(message=saved, action=cards[0], actions=cards)))
        return
    logger.info("확인 카드 실행 지시: %s", ", ".join(card.tool for card in cards))
    execute = ACTION_EXECUTE_MESSAGE.replace(ACTION_VERB_ADD, verb)
    saved = await _save(repo, turn.room_sn, execute, True)
    done = AnswerDone(message=saved, action=cards[0], actions=cards, execute=True)
    emit(("done", done))


def _uses_pets(entry: "catalog.CatalogEntry") -> bool:
    # 반려동물 목록이 필요한 카드 : 카드의 petSn(pet) 또는 배열 줄의 petSn(line_pet)
    return "pet" in entry.hooks or "line_pet" in entry.hooks


ACTION_FAILED_MESSAGE = "실패 — {label} · 저장하지 못했어요."
ACTION_CANCELED_MESSAGE = "취소됨 — {label} · 저장하지 않았어요."
# 배열 칸이 2줄 이상이면 펼치지 않고 줄 수로 (2026-11-24)
ARRAY_COUNT = "{count}건"


def _count_word(tool: str, name: str) -> str | None:
    # 배열 칸 줄 수 말 : 검사 수치는 줄 수와 상관없이 "혈액검사 N항목"(checkup-card와 같은 말)
    if (tool, name) == (INSPECTION_TOOL, INSPECTION_ROWS):
        return CHECKUP_COUNT
    return None


def _input_text(
    param: "catalog.CatalogItemParam",
    value: object,
    clock: bool = True,
    count: str | None = None,
) -> str:
    if param.type == catalog.ARRAY:
        # 배열 : 1줄이면 값(번호·uuid·petSn·참거짓 칸 빼고)을 " / "로 펼치고,
        # 2줄 이상이거나 줄 수 말(count)이 있으면 줄 수만
        items = value if isinstance(value, list) else []
        if count is not None or len(items) > 1:
            return (count or ARRAY_COUNT).format(count=len(items))
        rows = []
        for row in items:
            parts = [
                _input_text(rule, row[name])
                for name, rule in (param.items or {}).items()
                if _summarized(name, rule) and row.get(name) is not None
            ]
            if parts:
                rows.append(" / ".join(parts))
        return ", ".join(rows)
    if param.type == "code":
        return next((code.nm for code in param.codes or () if code.cd == value), str(value))
    if param.type == "date":
        return _md(date.fromisoformat(str(value)))
    if param.type == "datetime":
        moment = datetime.fromisoformat(str(value))
        # hrInptYn false : 시간을 입력하지 않은 칸이라 날짜만
        return f"{_md(moment.date())} {moment:%H:%M}" if clock else _md(moment.date())
    if param.type in ("long", "int"):
        return f"{value:,}"
    if param.type == "decimal":
        return f"{value:g}"
    return str(value)


def action_result_message(request: ActionResultRequest, head: Sequence[str] = ()) -> str:
    # 확인 카드 결과 요약 : 도구 표시 이름 + input(번호 칸·참거짓 제외). 저장 글은 서버가 정함
    entry, values = _result_values(request)
    return _result_text(request.status, entry, values, head)


def _result_values(request: ActionResultRequest) -> tuple["catalog.CatalogEntry", dict]:
    # action-result 검사 : 모르는 도구·규칙 밖 값·DONE인데 필수 칸 빔이면 400
    entry = tools.card_entry(request.tool)
    if entry is None:
        raise AppError("INVALID_REQUEST", 400, "모르는 도구입니다.")
    # 파일 칸 : React가 Java로 보낸 파일은 Python이 받지 않음(input에 와도 버림)
    values = {
        name: value
        for name, value in request.values.items()
        if value is not None
        and not (name in entry.params and entry.params[name].type == catalog.FILE)
    }
    if catalog.invalid_input(entry, values):
        raise AppError("INVALID_REQUEST", 400, "허용되지 않는 값이 있습니다.")
    if request.status is ActionStatus.DONE and catalog.missing(entry, values, files=False):
        raise AppError("INVALID_REQUEST", 400, "확인 카드의 필수 칸이 비어 있습니다.")
    return entry, values


def _result_text(
    status: ActionStatus, entry: "catalog.CatalogEntry", values: dict, head: Sequence[str]
) -> str:
    # DONE "✔ <label> — <요약>", CANCELED·FAILED "<말> — <label> · <요약> · <끝말>"
    # (요약이 없으면 label만)
    label = entry.label or entry.name
    clock = values.get(catalog.HR_INPUT) is not False
    texts = (
        _input_text(param, values[name], clock, _count_word(entry.name, name))
        for name, param in entry.params.items()
        if name in values and name not in entry.fixed and _summarized(name, param)
    )
    parts = [*head, *(text for text in texts if text)]
    summary = " · ".join(parts)
    if status is ActionStatus.CANCELED:
        return ACTION_CANCELED_MESSAGE.format(label=f"{label} · {summary}" if parts else label)
    if status is ActionStatus.FAILED:
        return ACTION_FAILED_MESSAGE.format(label=f"{label} · {summary}" if parts else label)
    return f"✔ {label}" + (f" — {summary}" if parts else "")


def _summarized(name: str, param: "catalog.CatalogItemParam") -> bool:
    # 요약 글에 넣는 칸 : 번호·petSn·참거짓·파일·generated(uuid) 칸은 뺀다
    return (
        not catalog.is_id(name)
        and name != catalog.PET_SN
        and param.type not in ("boolean", catalog.FILE)
        and not param.generated
    )


async def save_action_result(
    repo: ConversationRepository,
    reader: ToolReader,
    contexts: RegisterContextRepository,
    room_sn: int,
    request: ActionResultRequest,
) -> ConversationMessage:
    # 실행(React -> Java 공개 API)·취소·실패의 결과를 AI 메시지로 저장
    # 검사 수치 저장은 반려동물 이름·검진기록(검진일 병원)을 앞에 붙인다(Java 읽기는 이 도구만)
    entry, values = _result_values(request)
    head = []
    if entry.name == INSPECTION_TOOL:
        head = await _inspection_head(reader, contexts, values)
    text = _result_text(request.status, entry, values, head)
    return await repo.add_message(room_sn, ROLE_AI, text)


async def _inspection_head(
    reader: ToolReader, contexts: RegisterContextRepository, values: dict
) -> list[str]:
    """검사 수치 저장 결과 글 앞부분 : ["탄이", "12-14(월) 검증병원D"]
    - Java 저장은 이미 끝났으므로 읽기 실패·못 찾음이면 그 부분만 빼고 저장한다"""
    pet_sn = values.get(catalog.PET_SN)
    if not isinstance(pet_sn, int):
        return []
    head: list[str] = []
    try:
        pets = await contexts.get_pets()
    except (AppError, BackendError) as exc:
        logger.warning("검사 수치 결과 글: 반려동물 조회 실패: %s", exc)
        pets = []
    name = next((pet.pet_nm for pet in pets if pet.pet_sn == pet_sn), None)
    if name:
        head.append(name)
    record_sn = values.get(CHECKUP_SN)
    if not isinstance(record_sn, int):
        return head
    try:
        records = await _checkup_records(reader, pet_sn) or []
    except (AppError, BackendError) as exc:
        logger.warning("검사 수치 결과 글: 검진기록 조회 실패: %s", exc)
        records = []
    record = next((r for r in records if r[CHECKUP_SN] == record_sn), None)
    if record is not None:
        head.append(_record_place(record))
    return head


# 이미지 축소 기준 : Anthropic 이미지 5MB 상한·토큰 절약
INTENT_IMAGE_LONG_EDGE = 1024
INTENT_IMAGE_QUALITY = 85


def _intent_jpeg(image: bytes) -> bytes:
    """판단용 긴 변 1024px JPEG"""
    try:
        with Image.open(io.BytesIO(image)) as opened:
            flat = ImageOps.exif_transpose(opened).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as error:
        # 시그니처만 맞고 열 수 없는 파일
        raise AppError(
            "FILE_TYPE_NOT_ALLOWED", 400, "jpg·jpeg·png·webp 이미지만 올릴 수 있습니다."
        ) from error
    flat.thumbnail((INTENT_IMAGE_LONG_EDGE, INTENT_IMAGE_LONG_EDGE), Image.LANCZOS)
    out = io.BytesIO()
    flat.save(out, "JPEG", quality=INTENT_IMAGE_QUALITY)
    return out.getvalue()


async def judge_image_intent(
    judge: ImageIntentJudge, image: bytes, file_name: str, text: str | None
) -> ImageIntentJudgement:
    if is_pdf_name(file_name):
        # 대화창 PDF 첨부 (2026-11-23) : 검사결과지 분석으로, 판단 LLM 미호출(글과 무관)
        # 검사결과지가 아닌 PDF는 lab-results가 422 NOT_LAB_RESULT로 가린다
        validate_pdf(image, file_name)
        return ImageIntentJudgement(kind=ImageIntentKind.CHECKUP_PDF)
    validate_upload(image, file_name)
    jpeg = _intent_jpeg(image)
    text = text.strip() if text and text.strip() else None
    try:
        return await judge.judge(jpeg, text)
    except ImageIntentError:
        # 판단 실패 : 오류 대신 되물음(React 칩)
        return ImageIntentJudgement(kind=ImageIntentKind.ASK)


# 사진 턴 저장 (FN-AIM-013-02, 2026-11-13) : 사진 파일은 저장하지 않고 자리 표시 글만
IMAGE_MARK = "[사진]"
IMAGE_TITLE = "사진 대화"
# PDF 첨부 턴 (2026-11-23) : 결과 요약은 checkup-card가 저장해 여기선 안내 없음
PDF_MARK = "[PDF]"
PDF_TITLE = "PDF 대화"
# 용도별 고정 안내. 동물병원 영수증은 결과 요약을 receipt-result가 저장해 여기선 없음
IMAGE_MESSAGES = {
    ImageIntentKind.ASK: (
        "이 사진으로 무엇을 할까요? 캐릭터 만들기, 영수증 분석, 피부 분석 중에 골라 주세요."
    ),
    ImageIntentKind.CHARACTER: "캐릭터 만들기로 이어 갈게요.",
    ImageIntentKind.EXPENSE_RECEIPT: "가계부 영수증은 본창 가계부에서 등록할 수 있어요.",
    ImageIntentKind.SKIN: "피부 분석으로 이어 갈게요.",
}
# 글이 캐릭터를 원하지만 사진에 반려동물 얼굴·몸이 안 보여 ASK일 때 (2026-11-24)
CHARACTER_PHOTO_UNFIT_MESSAGE = (
    "캐릭터는 반려동물 얼굴이나 몸 전체가 보이는 사진으로 만들 수 있어요. "
    "다른 사진을 올려 주시거나, 이 사진으로 할 일을 골라 주세요."
)


async def save_image_turn(
    repo: ConversationRepository,
    titles: TitleGenerator,
    room_sn: int | None,
    pet_sn: int | None,
    text: str | None,
    kind: ImageIntentKind,
    character_photo_unfit: bool = False,
) -> ImageIntentResult:
    """사진 턴을 대화방에 저장 : 사용자 "[사진] <글>" + 용도별 안내 AI 메시지
    - 방 번호가 없으면 방을 만듦(첫 메시지가 사진 메시지, 글이 없으면 제목 LLM 미호출)"""
    text = text.strip() if text and text.strip() else None
    pdf = kind is ImageIntentKind.CHECKUP_PDF
    mark = PDF_MARK if pdf else IMAGE_MARK
    user_cn = f"{mark} {text}" if text else mark
    saved: list[ConversationMessage] = []
    if room_sn is None:
        empty_title = PDF_TITLE if pdf else IMAGE_TITLE
        title = _cut_title(await titles.generate(text)) if text else empty_title
        room = await repo.create_room(pet_sn, title or DEFAULT_TITLE, user_cn)
        room_sn = room.ai_cnvrs_room_sn
        detail = await repo.get_room(room_sn)
        saved.extend(m for m in detail.messages if m.role_cd == ROLE_USER)
    else:
        saved.append(await repo.add_message(room_sn, ROLE_USER, user_cn))
    guide = IMAGE_MESSAGES.get(kind)
    if kind is ImageIntentKind.ASK and character_photo_unfit:
        guide = CHARACTER_PHOTO_UNFIT_MESSAGE
    if guide is not None:
        saved.append(await repo.add_message(room_sn, ROLE_AI, guide))
    return ImageIntentResult(kind=kind, ai_cnvrs_room_sn=room_sn, messages=saved)


# 대화창 검사결과지 PDF 분석 결과 카드 (SCR-AIM-013, 2026-11-23)
# React가 lab-results 결과를 보내면 요약 글을 저장하고 검사 수치 저장 확인 카드(ACTION)를 준다
INSPECTION_TOOL = "draft_inspection_values"
CHECKUP_LIST_TOOL = "list_checkups"
INSPECTION_ROWS = "values"
CHECKUP_SN = "ckupRcdSn"
CHECKUP_PREFIX = "검사결과지 분석 — "
CHECKUP_MESSAGES = {
    CheckupResult.NOT_LAB_RESULT: "검사결과지로 읽을 수 없는 PDF예요",
    CheckupResult.ERROR: "일시적인 오류로 분석하지 못했어요",
    CheckupResult.CANCELED: "취소했어요",
}
CHECKUP_COUNT = "혈액검사 {count}항목"
CHECKUP_EMPTY = "읽은 혈액검사 항목이 없어요"
CHECKUP_ASK = "{pet}검사 수치를 이렇게 저장할까요?"
CHECKUP_MORE_ROWS = "외 {count}항목"
CHECKUP_SKIPPED = (
    "수치나 단위를 읽지 못한 {count}항목은 빼 두었어요. 검진상세에서 직접 입력해 주세요."
)
CHECKUP_EXCLUDED = "혈액검사가 아닌 항목({names})은 저장하지 않아요."
CHECKUP_NO_TOOL = "검진상세의 [PDF 분석]에서 저장할 수 있어요."
CHECKUP_NO_ROWS = "저장할 수 있는 수치가 없어요. 검진상세에서 직접 입력해 주세요."
# 프론트가 이 글 아래에 [검진기록 등록하기]·[나중에]를 붙인다(noCardReason NO_CHECKUP)
CHECKUP_NO_RECORD = (
    "검진기록이 없어요. 검진기록을 먼저 등록할까요? "
    "등록하면 {pet}검사 수치를 바로 저장할 수 있어요."
)
CHECKUP_ONE_RECORD = "저장할 검진기록: {record}"
CHECKUP_PICK_RECORD = "어느 검진기록에 넣을까요? 날짜나 병원 이름으로 말해 주세요."
CHECKUP_NO_DATE = "날짜 없음"
CHECKUP_SHOW_ROWS = 12
CHECKUP_SHOW_RECORDS = 3
_ROW_FIELDS = (
    "inspArtclCd",
    "inspArtclDrctInptNm",
    "rsltNvl",
    "unitNm",
    "refLlmtNvl",
    "refUplmtNvl",
)


def _inspection_rows(
    entry: "catalog.CatalogEntry", items: list[CheckupLabItem]
) -> tuple[list[dict], int]:
    """분석 항목 -> 카드 values 줄 : 수치·단위가 있고 Java 칸 규칙에 맞는 줄만, 뺀 줄 수"""
    rows: list[dict] = []
    skipped = 0
    for item in items:
        raw = item.model_dump(by_alias=True)
        row = {name: raw[name] for name in _ROW_FIELDS if raw.get(name) is not None}
        # 코드가 있으면 직접입력명은 뺀다(둘 다 보내면 Java 400)
        if row.get("inspArtclCd"):
            row.pop("inspArtclDrctInptNm", None)
        named = row.get("inspArtclCd") or row.get("inspArtclDrctInptNm")
        usable = named and row.get("rsltNvl") is not None and row.get("unitNm")
        if not usable or catalog.invalid_input(entry, {INSPECTION_ROWS: [row]}):
            skipped += 1
            continue
        rows.append(row)
    return rows, skipped


def _row_text(entry: "catalog.CatalogEntry", row: dict) -> str:
    # "WBC 12.3 10^3/uL (참고 6~17)" : 코드는 이름으로
    param = entry.params[INSPECTION_ROWS]
    items = param.items or {}
    name = row.get("inspArtclDrctInptNm") or row.get("inspArtclCd") or ""
    code = items.get("inspArtclCd")
    if row.get("inspArtclCd") and code is not None:
        name = _input_text(code, row["inspArtclCd"])
    text = f"{name} {row['rsltNvl']:g} {row['unitNm']}"
    low, high = row.get("refLlmtNvl"), row.get("refUplmtNvl")
    if low is not None and high is not None:
        text += f" (참고 {low:g}~{high:g})"
    return text


def _record_place(record: dict) -> str:
    # "10-20(화) 메이 동물병원" : 검진일이 없으면 "날짜 없음"
    try:
        day = _md(date.fromisoformat(str(record.get("ckupYmd"))))
    except ValueError:
        day = CHECKUP_NO_DATE
    return f"{day} {record.get('hsptlNm') or ''}".strip()


def _record_text(record: dict) -> str:
    # "10-20(화) 메이 동물병원 · 정기검진" : 검진일이 없으면 "날짜 없음"
    parts = [_record_place(record)]
    if record.get("ckupTypeCdNm"):
        parts.append(str(record["ckupTypeCdNm"]))
    return " · ".join(parts)


async def _checkup_records(reader: ToolReader, pet_sn: int) -> list[dict] | None:
    """그 아이의 검진기록(list_checkups, Java 순서). 도구가 없으면 None"""
    entry = tools.read_entry(CHECKUP_LIST_TOOL)
    if entry is None:
        return None
    request = catalog.read_request(entry, {}, pet_sn)
    if request is None:
        return None
    data = await reader.read(*request)
    rows = data.get("content") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise external_error()
    return [row for row in rows if isinstance(row, dict) and isinstance(row.get(CHECKUP_SN), int)]


async def save_checkup_card(
    repo: ConversationRepository,
    reader: ToolReader,
    contexts: RegisterContextRepository,
    room_sn: int,
    request: CheckupCardRequest,
) -> CheckupCardResult:
    """검사결과지 분석 결과 요약 AI 메시지 + 검사 수치 저장 확인 카드(카드는 미저장)
    - 검진기록 1건이면 카드에 채우고, 여럿이면 빈 칸으로 두고 최근 3건을 글로 보인다
    - Java 읽기가 실패하면 저장 없이 오류(502)"""
    if request.result is not CheckupResult.RECOGNIZED:
        text = CHECKUP_PREFIX + CHECKUP_MESSAGES[request.result]
        return CheckupCardResult(messages=[await repo.add_message(room_sn, ROLE_AI, text)])
    count = len(request.items)
    head = CHECKUP_PREFIX + (CHECKUP_COUNT.format(count=count) if count else CHECKUP_EMPTY)
    excluded = [name.strip() for name in request.excluded_artcl_nms if name.strip()]
    note = [CHECKUP_EXCLUDED.format(names=", ".join(excluded))] if excluded else []
    entry = tools.card_entry(INSPECTION_TOOL)
    card: ActionCard | None = None
    reason: CheckupNoCardReason | None = None
    lines = [head]
    if not count:
        lines += note
    elif entry is None:
        # Java 도구 목록에 저장 도구가 없음(백엔드 @AiTool 병합 전·스냅샷) : 본창으로 안내
        logger.info("검사 수치 저장 도구 없음: 카드 없이 안내")
        lines += [*note, CHECKUP_NO_TOOL]
    else:
        rows, skipped = _inspection_rows(entry, request.items)
        skip_note = [CHECKUP_SKIPPED.format(count=skipped)] if skipped else []
        records = await _checkup_records(reader, request.pet_sn) if rows else []
        if not rows:
            lines += [*note, CHECKUP_NO_ROWS]
        elif records is None:
            lines += [*note, CHECKUP_NO_TOOL]
        elif not records:
            pets = await contexts.get_pets()
            name = next((p.pet_nm for p in pets if p.pet_sn == request.pet_sn), None)
            pet = f"{name}의 " if name else ""
            lines += [*note, CHECKUP_NO_RECORD.format(pet=pet)]
            reason = CheckupNoCardReason.NO_CHECKUP
        else:
            values: dict = {INSPECTION_ROWS: rows}
            if len(records) == 1:
                values[CHECKUP_SN] = records[0][CHECKUP_SN]
            pets = await contexts.get_pets()
            card = action_card(entry, values, pets, [], request.pet_sn, request.pet_sn)
            pet = f"{card.pet_nm}의 " if card.pet_nm else ""
            shown = [f"- {_row_text(entry, row)}" for row in rows[:CHECKUP_SHOW_ROWS]]
            if len(rows) > CHECKUP_SHOW_ROWS:
                shown.append(CHECKUP_MORE_ROWS.format(count=len(rows) - CHECKUP_SHOW_ROWS))
            lines += [CHECKUP_ASK.format(pet=pet), *shown, *skip_note, *note]
            if len(records) == 1:
                lines += [CHECKUP_ONE_RECORD.format(record=_record_text(records[0]))]
                lines += _missing_lines([card]) or [ACTION_ASK_CONFIRM]
            else:
                picks = records[:CHECKUP_SHOW_RECORDS]
                lines.append(CHECKUP_PICK_RECORD)
                lines += [f"{no}. {_record_text(r)}" for no, r in enumerate(picks, start=1)]
            logger.info("검사 수치 확인 카드: %d줄 검진기록 %d건", len(rows), len(records))
    saved = await repo.add_message(room_sn, ROLE_AI, "\n".join(lines))
    return CheckupCardResult(messages=[saved], action=card, no_card_reason=reason)
