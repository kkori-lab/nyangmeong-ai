import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from pydantic import BaseModel

from app.chat import rules
from app.chat.clients import (
    AnswerError,
    AnswerGenerator,
    Classified,
    ClassifiedKind,
    ClassifyError,
    IntentClassifier,
    TitleGenerator,
)
from app.chat.repository import AiSettings, ConversationRepository
from app.chat.schemas import (
    ROLE_AI,
    ROLE_USER,
    AnswerDone,
    ConversationCreateRequest,
    ConversationDetail,
    ConversationMessage,
    ConversationSummary,
    Intent,
    IntentKind,
    StreamError,
)
from app.core.backend import BackendError
from app.core.response import AppError

logger = logging.getLogger(__name__)

MAX_TITLE_LENGTH = 200
DEFAULT_TITLE = "새 대화"
# FN-AIM-005-02 : 화면설계서 SCR-AIM-005 ② 문구
FALLBACK_MESSAGE = "질문을 이해하지 못했어요. 다시 입력하거나 아래에서 선택해 주세요."
# FN-AIM-002-03 : 화면설계서 SCR-AIM-002 ② 문구. 본문 끝에 붙여 저장한다
DISCLAIMER = "\n\n※ 참고 정보이며 의료 진단이 아닙니다. 이상 징후가 있다면 수의사와 상담하세요."
# FN-AIM-002-07 : 화면설계서 SCR-AIM-002 처리 조건 문구
ANSWER_ERROR_MESSAGE = "일시적으로 답변할 수 없어요"

# SSE 이벤트 하나 : (이름, 내용)
Event = tuple[str, BaseModel | dict]


async def create_conversation(
    repo: ConversationRepository, titles: TitleGenerator, request: ConversationCreateRequest
) -> ConversationSummary:
    # FN-AIM-011-11 : 제목은 첫 메시지로 1회 생성, 200자 제한은 서버에서 적용
    title = (await titles.generate(request.cnvrs_cn)).strip()[:MAX_TITLE_LENGTH] or DEFAULT_TITLE
    # FN-AIM-011-07·14 : 방과 첫 메시지를 함께 저장(Java가 한 트랜잭션으로 묶는다)
    return await repo.create_room(request.pet_sn, title, request.cnvrs_cn)


async def list_conversations(
    repo: ConversationRepository, pet_sn: int | None
) -> list[ConversationSummary]:
    # FN-AIM-011-08·09
    return await repo.list_rooms(pet_sn)


async def get_conversation(repo: ConversationRepository, room_sn: int) -> ConversationDetail:
    # FN-AIM-011-10 : 남의 방은 Java가 없는 방과 같은 404로 답한다
    return await repo.get_room(room_sn)


async def delete_conversation(repo: ConversationRepository, room_sn: int) -> None:
    # FN-AIM-011-13 : 물리 삭제
    await repo.delete_room(room_sn)


@dataclass(frozen=True)
class Judged:
    intent: Intent
    # SEARCH일 때 연관 바로가기(FN-AIM-002-04)
    shortcut: Intent | None = None


async def judge(text: str, has_image: bool, classifier: IntentClassifier) -> Judged:
    # FN-AIM-001-05 : 이미지 첨부면 판정 없이 영수증 분석(SCR-AIM-013)
    if has_image:
        return Judged(Intent(kind=IntentKind.RECEIPT))
    # ① 등록 판정 — FN-AIM-004-13 : 라우팅 키워드가 있어도 등록이 먼저
    if rules.is_register_request(text):
        return Judged(Intent(kind=IntentKind.REGISTER))
    # ② 룰 기반 라우팅. FN-AIM-002-10 : AI 분류보다 앞이라 LLM 장애와 무관하다
    row = rules.match_route(text)
    if row is not None:
        return Judged(row.to_intent())
    # ③ AI 분류(①②가 실패한 입력만, FN-AIM-004-02)
    classified = await classifier.classify(text)
    if classified.kind is ClassifiedKind.SEARCH:
        return Judged(Intent(kind=IntentKind.SEARCH), _shortcut_of(classified))
    if classified.kind is ClassifiedKind.ROUTE and classified.scr_id is not None:
        row = rules.find_route(classified.scr_id, classified.param)
        if row is not None:
            return Judged(row.to_intent())
    # ④ FN-AIM-004-12·005-01 : 어디에도 해당하지 않으면 폴백
    return Judged(Intent(kind=IntentKind.FALLBACK))


def _shortcut_of(classified: Classified) -> Intent | None:
    # FN-AIM-004-08과 같이 매핑표의 라우팅 가능 행만 인정한다
    if classified.related_scr_id is None:
        return None
    row = rules.find_route(classified.related_scr_id, classified.related_param)
    return None if row is None else row.to_intent()


async def judge_intent(text: str, has_image: bool, classifier: IntentClassifier) -> Intent:
    return (await judge(text, has_image, classifier)).intent


def route_message(scr_nm: str) -> str:
    # 받침(ㄹ 제외)이 있으면 '으로', 없으면 '로'
    last = scr_nm.rstrip()[-1:]
    jong = (ord(last) - 0xAC00) % 28 if "가" <= last <= "힣" else 0
    particle = "으로" if jong not in (0, 8) else "로"
    return f"{scr_nm}{particle} 이동할게요"


async def reply_fallback(repo: ConversationRepository, room_sn: int) -> ConversationMessage:
    # FN-AIM-005-02·07 : 실패 사유는 묻지 않고, 부적절 입력도 같은 문구. AI 역할 메시지로 저장
    return await repo.add_message(room_sn, ROLE_AI, FALLBACK_MESSAGE)


@dataclass(frozen=True)
class Turn:
    room_sn: int
    # 답할 사용자 메시지
    question: ConversationMessage
    messages: list[ConversationMessage]


@dataclass(frozen=True)
class AnswerLimits:
    # FN-AIM-002-07 : 첫 글자 제한·전체 제한(초)
    first_token_sec: float
    total_sec: float


async def prepare_turn(repo: ConversationRepository, room_sn: int, cn: str | None) -> Turn:
    # ① 사용자 메시지를 먼저 저장한다. 여기서 실패하면(남의 방·없는 방 포함) LLM을 부르지 않는다
    if cn is not None:
        await repo.add_message(room_sn, ROLE_USER, cn)
    room = await repo.get_room(room_sn)
    question = next((m for m in reversed(room.messages) if m.role_cd == ROLE_USER), None)
    if question is None:
        raise AppError("INVALID_REQUEST", 400, "답할 메시지가 없습니다.")
    return Turn(room_sn, question, room.messages)


def build_context(messages: list[ConversationMessage], question_seq: int, turns: int) -> list[dict]:
    # FN-AIM-002-11·011-15 : 현재 대화의 답할 메시지까지, 미완료 답변 제외, 최근 turns턴(질문+답변)
    usable = [m for m in messages if m.msg_seq <= question_seq and m.cmptn_yn]
    recent = usable[-turns * 2 :]
    # Messages API는 사용자 메시지로 시작해야 한다
    while recent and recent[0].role_cd != ROLE_USER:
        recent = recent[1:]
    return [
        {"role": "user" if m.role_cd == ROLE_USER else "assistant", "content": m.cnvrs_cn}
        for m in recent
    ]


# 브라우저 연결이 끊겨도 답변 생성·저장을 끝까지 하도록 작업을 따로 잡아 둔다(architecture.md)
_running: set[asyncio.Task] = set()


async def answer_turn(
    turn: Turn,
    repo: ConversationRepository,
    classifier: IntentClassifier,
    answers: AnswerGenerator,
    ai: AiSettings,
    limits: AnswerLimits,
) -> AsyncIterator[Event]:
    queue: asyncio.Queue[Event | None] = asyncio.Queue()
    task = asyncio.create_task(
        _run_turn(turn, repo, classifier, answers, ai, limits, queue.put_nowait)
    )
    _running.add(task)
    task.add_done_callback(_running.discard)
    while (event := await queue.get()) is not None:
        yield event


async def _run_turn(
    turn: Turn,
    repo: ConversationRepository,
    classifier: IntentClassifier,
    answers: AnswerGenerator,
    ai: AiSettings,
    limits: AnswerLimits,
    emit: Callable[[Event | None], None],
) -> None:
    try:
        judged = await judge(turn.question.cnvrs_cn, False, classifier)
        emit(("intent", judged.intent))
        kind = judged.intent.kind
        if kind is IntentKind.SEARCH:
            await _search_answer(turn, repo, answers, ai, limits, judged.shortcut, emit)
        elif kind is IntentKind.FALLBACK:
            emit(("done", AnswerDone(message=await reply_fallback(repo, turn.room_sn))))
        elif kind is IntentKind.ROUTE:
            # 이동은 React가 한다. 다시 열어도 답이 남게 이동 안내를 저장한다(2026-10-29 결정)
            text = route_message(judged.intent.scr_nm or "")
            emit(("done", AnswerDone(message=await _save(repo, turn.room_sn, text, True))))
        else:
            # REGISTER·RECEIPT는 SCR-AIM-012·013에서 잇는다
            emit(("done", AnswerDone()))
    except ClassifyError:
        # 분류 LLM 장애는 폴백이 아니라 일시 오류(2026-10-29 결정). 원인 로그는 분류기가 남긴다
        emit(("error", StreamError(code="EXTERNAL_API_ERROR", message=ANSWER_ERROR_MESSAGE)))
    except Exception:
        logger.exception("대화 응답 처리 실패")
        emit(("error", StreamError(code="EXTERNAL_API_ERROR", message=ANSWER_ERROR_MESSAGE)))
    finally:
        emit(None)


async def _search_answer(
    turn: Turn,
    repo: ConversationRepository,
    answers: AnswerGenerator,
    ai: AiSettings,
    limits: AnswerLimits,
    shortcut: Intent | None,
    emit: Callable[[Event | None], None],
) -> None:
    # FN-AIM-002-02·07
    context = build_context(turn.messages, turn.question.msg_seq, ai.context_turns)
    stream = answers.stream(context, ai.max_tokens)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + limits.total_sec
    try:
        # 첫 글자 전 실패 : 저장하지 않고 안내. 사용자 메시지는 남아 [다시 시도]로 다시 부른다
        try:
            async with asyncio.timeout_at(min(deadline, loop.time() + limits.first_token_sec)):
                first = await anext(stream, None)
        except (TimeoutError, AnswerError):
            first = None
        if first is None:
            emit(("error", StreamError(code="EXTERNAL_API_ERROR", message=ANSWER_ERROR_MESSAGE)))
            return
        chunks = [first]
        emit(("delta", {"text": first}))
        complete = False
        try:
            async with asyncio.timeout_at(deadline):
                async for text in stream:
                    chunks.append(text)
                    emit(("delta", {"text": text}))
            complete = True
        except (TimeoutError, AnswerError):
            # 전체 시간 초과·도중 오류 : 부분 답변을 미완료로 저장
            pass
    finally:
        await stream.aclose()
    text = "".join(chunks)
    if complete:
        # FN-AIM-002-03 : 고지는 본문 끝에 포함해 저장한다. 미완료 답변에는 붙이지 않는다
        emit(("delta", {"text": DISCLAIMER}))
        text += DISCLAIMER
    message = await _save(repo, turn.room_sn, text, complete)
    emit(("done", AnswerDone(message=message, shortcut=shortcut)))


async def _save(
    repo: ConversationRepository, room_sn: int, text: str, complete: bool
) -> ConversationMessage | None:
    # 저장이 실패해도 이미 보낸 답변은 그대로 둔다(1,000자 상한은 두지 않음, 2026-10-28 결정)
    try:
        return await repo.add_message(room_sn, ROLE_AI, text, cmptn_yn=complete)
    except (AppError, BackendError) as error:
        logger.warning(
            "AI 답변 저장 실패: %d자 cmptnYn=%s (%s)", len(text), complete, type(error).__name__
        )
        return None
