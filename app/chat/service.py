import asyncio
import logging
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel
from pydantic.alias_generators import to_camel

from app.chat import rules
from app.chat.clients import (
    AnswerError,
    AnswerGenerator,
    Classified,
    ClassifiedKind,
    ClassifyError,
    IntentClassifier,
    RegisterExtractor,
    TitleGenerator,
)
from app.chat.repository import (
    AiSettings,
    ConversationRepository,
    PetInfo,
    RegisterContextRepository,
)
from app.chat.schemas import (
    ROLE_AI,
    ROLE_USER,
    AnswerDone,
    CardType,
    ConversationCreateRequest,
    ConversationDetail,
    ConversationMessage,
    ConversationSummary,
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
from app.core.backend import BackendError
from app.core.response import AppError

logger = logging.getLogger(__name__)

MAX_TITLE_LENGTH = 200
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

# SSE 이벤트 하나 : (이름, 내용)
Event = tuple[str, BaseModel | dict]


async def create_conversation(
    repo: ConversationRepository, titles: TitleGenerator, request: ConversationCreateRequest
) -> ConversationSummary:
    # FN-AIM-011-11 : 제목은 첫 메시지로 1회 생성, 200자 제한은 서버에서 적용
    title = (await titles.generate(request.cnvrs_cn)).strip()[:MAX_TITLE_LENGTH] or DEFAULT_TITLE
    # FN-AIM-011-07·14 : 방과 첫 메시지 함께 저장 (Java 단일 트랜잭션)
    return await repo.create_room(request.pet_sn, title, request.cnvrs_cn)


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


async def judge(text: str, has_image: bool, classifier: IntentClassifier) -> Judged:
    # FN-AIM-001-05 : 이미지 첨부면 판정 없이 영수증 분석(SCR-AIM-013)
    if has_image:
        return Judged(Intent(kind=IntentKind.RECEIPT))
    # ① 등록 판정 — FN-AIM-004-13 : 라우팅 키워드가 있어도 등록이 먼저
    if rules.is_register_request(text):
        return Judged(Intent(kind=IntentKind.REGISTER))
    # FN-AIM-002-10 : ② 룰 기반 라우팅, AI 분류보다 앞이라 LLM 장애와 무관
    row = rules.match_route(text)
    if row is None:
        # ③ AI 분류(①②가 실패한 입력만, FN-AIM-004-02)
        classified = await classifier.classify(text)
    elif not rules.is_question(text):
        return Judged(row.to_intent())
    else:
        # 범위 밖 질문 차단(2026-10-30) : 키워드에 걸린 질문꼴은 AI로 서비스 범위 확인
        try:
            classified = await classifier.classify(text, hint=row)
        except ClassifyError:
            # 룰 라우팅은 LLM 장애와 무관 (FN-AIM-002-10), 원인 로그는 분류기에서 기록
            return Judged(row.to_intent())
    if classified.kind is ClassifiedKind.SEARCH:
        return Judged(Intent(kind=IntentKind.SEARCH), _shortcut_of(classified))
    if classified.kind is ClassifiedKind.ROUTE and classified.scr_id is not None:
        row = rules.find_route(classified.scr_id, classified.param)
        if row is not None:
            return Judged(row.to_intent())
    # ④ FN-AIM-004-12·005-01 : 어디에도 해당하지 않으면 폴백
    out_of_scope = classified.kind is ClassifiedKind.OUT_OF_SCOPE
    return Judged(Intent(kind=IntentKind.FALLBACK), out_of_scope=out_of_scope)


def _shortcut_of(classified: Classified) -> Intent | None:
    # FN-AIM-004-08과 같이 매핑표의 라우팅 가능 행만 인정
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
) -> Turn:
    # ① 사용자 메시지 선저장 : 실패 시(남의 방·없는 방 포함) LLM 미호출
    if cn is not None:
        await repo.add_message(room_sn, ROLE_USER, cn)
    room = await repo.get_room(room_sn)
    question = next((m for m in reversed(room.messages) if m.role_cd == ROLE_USER), None)
    if question is None:
        raise AppError("INVALID_REQUEST", 400, "답할 메시지가 없습니다.")
    return Turn(room_sn, question, room.messages, room.pet_sn, draft)


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
    classifier: IntentClassifier,
    answers: AnswerGenerator,
    ai: AiSettings,
    limits: AnswerLimits,
    register: "RegisterDeps | None" = None,
    titles: TitleGenerator | None = None,
) -> AsyncIterator[Event]:
    queue: asyncio.Queue[Event | None] = asyncio.Queue()
    task = asyncio.create_task(
        _run_turn(turn, repo, classifier, answers, ai, limits, queue.put_nowait, register, titles)
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
    register: "RegisterDeps | None" = None,
    titles: TitleGenerator | None = None,
) -> None:
    try:
        text = turn.question.cnvrs_cn
        card = None
        if register is not None and turn.draft is not None:
            # FN-AIM-012-05·10 : 초안이 있으면 이 메시지로 칸 채움·수정
            # 뽑힌 칸이 없으면 일반 판정
            card = await build_card(text, turn.pet_sn, turn.draft, register)
        if card is not None:
            judged = Judged(Intent(kind=IntentKind.REGISTER))
        else:
            judged = await judge(text, False, classifier)
        emit(("intent", judged.intent))
        kind = judged.intent.kind
        if kind is IntentKind.SEARCH:
            answer = await _search_answer(turn, repo, answers, ai, limits, judged.shortcut, emit)
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
            card = card or await build_card(text, turn.pet_sn, None, register)
            await _register_reply(repo, turn.room_sn, card, emit)
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
    answers: AnswerGenerator,
    ai: AiSettings,
    limits: AnswerLimits,
    shortcut: Intent | None,
    emit: Callable[[Event | None], None],
) -> str | None:
    # FN-AIM-002-02·07 : 완료면 고지 전 본문 반환(제목 요약용), 실패·미완료면 None
    context = build_context(turn.messages, turn.question.msg_seq, ai.context_turns)
    stream = answers.stream(context, ai.max_tokens)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + limits.total_sec
    try:
        # 첫 글자 전 실패 : 미저장·안내, 사용자 메시지는 남아 [다시 시도]로 재호출
        try:
            async with asyncio.timeout_at(min(deadline, loop.time() + limits.first_token_sec)):
                first = await anext(stream, None)
        except (TimeoutError, AnswerError):
            first = None
        if first is None:
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
        except (TimeoutError, AnswerError):
            # 전체 시간 초과·도중 오류 : 부분 답변을 미완료로 저장
            pass
    finally:
        await stream.aclose()
    body = "".join(chunks)
    text = body
    if complete:
        # FN-AIM-002-03 : 고지는 본문 끝에 포함해 저장, 미완료 답변 제외
        emit(("delta", {"text": DISCLAIMER}))
        text += DISCLAIMER
    message = await _save(repo, turn.room_sn, text, complete)
    emit(("done", AnswerDone(message=message, shortcut=shortcut)))
    return body if complete else None


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
        title = summary.strip()[:MAX_TITLE_LENGTH]
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


def _pick_pet(
    pets: list[PetInfo], named: list[PetInfo], draft_pet: int | None, room_pet: int | None
) -> PetInfo | None:
    # FN-AIM-012-04 : 반려동물은 항상 서버 규칙으로 결정, None이면 이름 칩으로 되물음
    if len(named) == 1:
        return named[0]
    if named:
        return None
    by_sn = {pet.pet_sn: pet for pet in pets}
    if draft_pet in by_sn:
        return by_sn[draft_pet]
    if len(pets) == 1:
        return pets[0]
    return by_sn.get(room_pet)


async def build_card(
    text: str, room_pet: int | None, draft: RegisterDraft | None, deps: RegisterDeps
) -> RegisterCard | None:
    # FN-AIM-012-02~08·10. 초안이 있는데 이 메시지에서 뽑힌 칸이 없으면 None(일반 판정으로)
    pets = await deps.contexts.get_pets()
    names = [pet.pet_nm for pet in pets]
    compact = re.sub(r"\s+", "", text)
    named = [pet for pet in pets if pet.pet_nm in compact]
    parsed = rules.parse_register(text, deps.today, names).values()
    if draft is None:
        values = parsed
    else:
        found = parsed or _answer_fill(text, draft, names)
        if not found and not named:
            return None
        values = _draft_values(draft) | found
    if _missing(values):
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
    care = bool(values.get("care_zone_cd"))
    keep = _CARE_FIELDS if care else _SCHEDULE_FIELDS
    values = {name: value for name, value in values.items() if name in keep}
    pet = _pick_pet(pets, named, draft.pet_sn if draft else None, room_pet)
    missing = (["pet_sn"] if pet is None else []) + _missing(values)
    card = RegisterCard(
        card_type=CardType.ASK if missing else CardType.CARE_ITEM if care else CardType.SCHEDULE,
        pet_sn=pet.pet_sn if pet else None,
        pet_nm=pet.pet_nm if pet else None,
        pet_choices=[] if pet else [PetChoice(pet_sn=p.pet_sn, pet_nm=p.pet_nm) for p in pets],
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
