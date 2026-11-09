import asyncio
import io
import logging
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import date, datetime

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel
from pydantic.alias_generators import to_camel

from app.chat import catalog, rules, tools
from app.chat.clients import (
    AnswerError,
    AnswerGenerator,
    Classified,
    ClassifiedKind,
    ClassifyError,
    ImageIntentError,
    ImageIntentJudge,
    IntentClassifier,
    ReadMore,
    RegisterExtractor,
    TitleGenerator,
    ToolAgent,
    ToolDecision,
)
from app.chat.repository import (
    AiSettings,
    ConversationRepository,
    PetInfo,
    RegisterContextRepository,
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
    ConversationCreateRequest,
    ConversationDetail,
    ConversationMessage,
    ConversationSummary,
    ImageIntentKind,
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
from app.core.image import validate_upload
from app.core.response import AppError

logger = logging.getLogger(__name__)

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
# READ 결과를 본 LLM이 쓰기 도구를 고른 경우의 tool_result : 카드는 done.action으로
ACTION_SHOWN = (
    "확인 카드를 띄움. 회원이 카드에서 [확인]을 누르기 전에는 저장되지 않음. "
    "카드 내용을 확인하고 [확인]을 눌러 달라고 한두 문장으로 안내한다."
)
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
READ_EMPTY_CARD_MESSAGE = "카드 내용을 확인하고 [확인]을 눌러 주세요."
READ_EMPTY_MESSAGE = "요청을 처리하지 못했어요. 이름이나 날짜를 넣어 다시 말해 주세요."


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
    # SEARCH(READ) : 결과를 본 뒤 고른 쓰기 도구의 확인 카드, 답변 스트림이 채움
    cards: list[ActionCard] | None = None
    # FN-AIM-002-03 : 의료 고지 여부. 사용법 답변은 False
    notice: bool = True
    # SEARCH(READ) : 성공한 READ 도메인, 답변 스트림이 채움. health가 있을 때만 고지
    read_domains: set[str] | None = None


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
    if classified.kind is ClassifiedKind.GUIDE:
        guided = _guide_judged(text, classified)
        if guided is not None:
            return guided
        # 설계 초안 0절 : M1·목차 선택 모두 못 찾으면 범위 안내
        return Judged(Intent(kind=IntentKind.FALLBACK), out_of_scope=True)
    if classified.kind is ClassifiedKind.ROUTE and classified.scr_id is not None:
        row = rules.find_route(classified.scr_id, classified.param)
        if row is not None:
            return Judged(row.to_intent())
    # ④ FN-AIM-004-12·005-01 : 어디에도 해당하지 않으면 폴백
    out_of_scope = classified.kind is ClassifiedKind.OUT_OF_SCOPE
    return Judged(Intent(kind=IntentKind.FALLBACK), out_of_scope=out_of_scope)


def _guide_judged(text: str, classified: Classified) -> Judged | None:
    # FN-AIM-002-02 : 분류 LLM의 목차 선택을 앞에, M1 키워드 색인 결과를 뒤에
    ids = rules.merge_guide(classified.guide_id, text)
    picked = bool(ids) and ids[0] == classified.guide_id
    stage = ("목차+M1" if len(ids) > 1 else "목차") if picked else "M1"
    if not ids:
        logger.info("사용법 안내: 안내서 청크 없음")
        return None
    logger.info("사용법 안내: %s %d개 %s", stage, len(ids), ",".join(ids))
    return Judged(
        Intent(kind=IntentKind.SEARCH), _guide_shortcut(ids[0], classified), guide_ids=tuple(ids)
    )


def _guide_shortcut(chunk_id: str, classified: Classified) -> Intent | None:
    # FN-AIM-002-04 : 첫 청크 화면이 라우팅 대상이면 그 화면, 아니면 분류의 연관 화면
    chunk = rules.find_guide(chunk_id)
    num = chunk.num if chunk else None
    row = next((r for r in rules.routing_table() if r.no == num and r.routable), None)
    return row.to_intent() if row is not None else _shortcut_of(classified)


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
) -> Judged:
    """도구 흐름 판정(docs/design/tool-calling.md 4절)"""
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
    except (ClassifyError, TimeoutError):
        if row is not None:
            return Judged(row.to_intent())
        raise ClassifyError("tool_decide") from None
    return _tool_judged(text, context, agent, decision, max_tokens, today, read, prior, now)


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
) -> Judged:
    # 도구 -> intent 값 (설계 6절). CARD 도구는 ACTION(등록 카드 2개도 ④부터)
    call = decision.call
    if call is None:
        if decision.text is not None:
            # FN-AIM-002-03 : 인사·잡담에 대한 바로 답은 고지 없음(추가 요청 2026-11-09)
            notice = not rules.is_small_talk(text)
            return Judged(Intent(kind=IntentKind.SEARCH), stream=decision.text, notice=notice)
        return Judged(Intent(kind=IntentKind.FALLBACK))
    if call.args is None:
        logger.info("도구 인자 거부: %s", call.name)
        return Judged(Intent(kind=IntentKind.FALLBACK))
    if call.name == tools.NAVIGATE:
        return Judged(tools.route_row(call).to_intent())
    if call.name == tools.DECLINE:
        return Judged(Intent(kind=IntentKind.FALLBACK), out_of_scope=not call.args.unclear)
    card = tools.card_entry(call.name)
    if card is not None:
        # 돌려받은 카드와 같은 도구면 그 input을 바탕으로 이 메시지 칸을 덮어씀
        base = prior.values if prior is not None and prior.tool == call.name else None
        args = call.args.model_dump(exclude_none=True)
        if base:
            # 추가-1 : 날짜를 말하지 않았으면 돌려받은 카드의 날짜를 유지
            date_said = rules.mentions_date(text)
            args = catalog.keep_prior_dates(card, args, base, date_said, today)
        values = catalog.card_input(card, args, now, {}, base)
        if catalog.missing_target_ids(card, values):
            # 경로·본문 필수 번호 칸은 카드에서 고를 수 없음 : 안내 글(SEARCH), 고지 없음
            logger.info("쓰기 도구 대상 번호 없음: %s", call.name)
            stream = _fixed(_target_missing(card))
            return Judged(Intent(kind=IntentKind.SEARCH), stream=stream, notice=False)
        return Judged(Intent(kind=IntentKind.ACTION), tool=call.name, action=values)
    entry = tools.read_entry(call.name)
    if entry is not None:
        if read is None:
            logger.info("READ 도구 실행 불가: %s", call.name)
            return Judged(Intent(kind=IntentKind.FALLBACK))
        # Java 호출은 답변 스트림 안 : 첫 글자 제한이 Java 호출까지 덮음
        cards: list[ActionCard] = []
        domains: set[str] = set()
        stream = _read_answer(
            text, context, agent, decision, entry, max_tokens, today, read, cards, domains
        )
        return Judged(
            Intent(kind=IntentKind.SEARCH), stream=stream, cards=cards, read_domains=domains
        )
    ids = tuple(tools.guide_ids(call, text))
    if not ids:
        logger.info("사용법 안내: 안내서 청크 없음")
        return Judged(Intent(kind=IntentKind.FALLBACK), out_of_scope=True)
    logger.info("사용법 안내: 도구 %d개 %s", len(ids), ",".join(ids))
    stream = agent.answer(context, decision, guide_text(ids) or "", max_tokens, today)
    shortcut = _guide_shortcut(ids[0], Classified(ClassifiedKind.GUIDE))
    # FN-AIM-002-03 : 사용법 안내는 건강 관련 응답이 아님
    return Judged(
        Intent(kind=IntentKind.SEARCH), shortcut, guide_ids=ids, stream=stream, notice=False
    )


@dataclass(frozen=True)
class ReadDeps:
    reader: ToolReader
    contexts: RegisterContextRepository
    # 대화의 펫 태그. null이면 "전체"
    room_pet: int | None = None
    # 쓰기 도구 datetime 칸 : 날짜만 오면 오늘은 이 시각
    now: datetime | None = None


class _ReadPets:
    """한 턴 READ의 반려동물 : 목록은 처음 필요할 때 한 번만 받는다"""

    def __init__(self, text: str, read: ReadDeps) -> None:
        self.compact = re.sub(r"\s+", "", text)
        self.read = read
        self._pets: list[PetInfo] | None = None

    async def pets(self) -> list[PetInfo]:
        if self._pets is None:
            try:
                self._pets = await self.read.contexts.get_pets()
            except (AppError, BackendError):
                raise AnswerError("read_pets") from None
        return self._pets

    def named(self, pets: list[PetInfo]) -> list[PetInfo]:
        return [p for p in pets if p.pet_nm in self.compact]


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
    domains: set[str] | None = None,
    rows: "catalog.Rows | None" = None,
) -> _ReadOutcome:
    pet_sn = None
    if "pet" in entry.hooks:
        # FN-AIM-012-04 규칙 : 못 정하면 Java 미호출·이름 되물음
        found = await pets.pets()
        pet = _pick_pet(found, pets.named(found), None, pets.read.room_pet)
        if pet is None:
            names = ", ".join(p.pet_nm for p in found)
            return _ReadOutcome(ask=READ_PET_ASK.format(names=names) if found else READ_NO_PET)
        pet_sn = pet.pet_sn
    elif "pet_filter" in entry.hooks:
        # 가계부 : 문장 속 이름이 하나면 그 반려동물, 아니면 전체(공용 지출 포함, 2026-11-06 결정)
        named = pets.named(await pets.pets())
        pet_sn = named[0].pet_sn if len(named) == 1 else None
    args = call.args if call is not None else None
    values = args.model_dump(exclude_none=True) if args is not None else {}
    request = catalog.read_request(entry, values, pet_sn, seen)
    if request is None:
        logger.info("READ 도구 필수 칸 없음: %s", entry.name)
        return _ReadOutcome(result=rules.READ_FAILED)
    try:
        data = await pets.read.reader.read(*request)
    except (AppError, BackendError) as error:
        logger.info("READ 도구 Java 실패: %s %s", entry.name, type(error).__name__)
        return _ReadOutcome(result=rules.READ_FAILED)
    catalog.seen_ids(data, seen)
    if rows is not None:
        catalog.seen_rows(data, rows)
    if domains is not None:
        domains.add(entry.domain)
    return _ReadOutcome(result=rules.read_result_text(data))


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
    domains: set[str] | None = None,
) -> AsyncIterator[str]:
    pets = _ReadPets(text, read)
    # 번호 칸은 이 턴 READ 결과에 나온 값만 (catalog.read_request)
    seen: dict[str, set[int]] = {}
    # 번호별 원래 행 : 수정 카드가 날짜만 바꿀 때 원래 시간을 씀(추가-3)
    rows: catalog.Rows = {}
    # 되물음·실패만이면 domains가 비어 고지 없음(FN-AIM-002-03)
    first = await _read_once(entry, decision.call, pets, seen, domains, rows)
    if first.ask is not None:
        yield first.ask
        return

    reads = 1

    async def follow(call: tools.ToolCall) -> str | None:
        nonlocal reads
        # 결과를 보고 고른 쓰기 도구 : 번호 칸은 이 턴 READ 결과 값만, 카드로 끝냄(목록→완료 체크)
        card = tools.card_entry(call.name)
        if card is not None and call.args is not None and cards is not None:
            if cards:
                logger.info("쓰기 도구 두 번째 실행 안 함: %s", call.name)
                return None
            found = await pets.pets() if _uses_pets(card) else []
            values = call.args.model_dump(exclude_none=True)
            values = catalog.card_input(card, values, read.now, seen, rows=rows)
            if catalog.missing_target_ids(card, values):
                logger.info("쓰기 도구 대상 번호 없음: %s", call.name)
                return _target_missing_note(card)
            cards.append(action_card(card, values, found, pets.named(found), None, read.room_pet))
            return ACTION_SHOWN
        # 한 턴 READ 최대 2번 : 두 번째는 읽기 도구만, 반려동물을 못 정하면 불러오지 못함
        second = tools.read_entry(call.name)
        if second is None or call.args is None or reads >= 2:
            logger.info("두 번째 도구 실행 안 함: %s", call.name)
            return None
        reads += 1
        outcome = await _read_once(second, call, pets, seen, domains, rows)
        if outcome.ask is not None:
            return rules.READ_FAILED
        # READ 2번 뒤에도 쓰기 카드는 한 번 고를 수 있게 (2단계 ②, 목록 두 번 → 수정 카드)
        return ReadMore(outcome.result)

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
        yield READ_EMPTY_CARD_MESSAGE if cards else READ_EMPTY_MESSAGE


def guide_text(ids: tuple[str, ...]) -> str | None:
    chunks = [chunk for chunk in map(rules.find_guide, ids) if chunk is not None]
    return "\n\n".join(chunk.text for chunk in chunks) or None


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
    # 2단계 쓰기 : React가 돌려보낸 가장 최근 확인 카드
    action: ActionDraft | None = None


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
) -> Turn:
    # ① 사용자 메시지 선저장 : 실패 시(남의 방·없는 방 포함) LLM 미호출
    if cn is not None:
        await repo.add_message(room_sn, ROLE_USER, cn)
    room = await repo.get_room(room_sn)
    question = next((m for m in reversed(room.messages) if m.role_cd == ROLE_USER), None)
    if question is None:
        raise AppError("INVALID_REQUEST", 400, "답할 메시지가 없습니다.")
    return Turn(room_sn, question, room.messages, room.pet_sn, draft, action)


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
    agent: ToolAgent | None = None,
    reader: ToolReader | None = None,
) -> AsyncIterator[Event]:
    queue: asyncio.Queue[Event | None] = asyncio.Queue()
    task = asyncio.create_task(
        _run_turn(
            turn,
            repo,
            classifier,
            answers,
            ai,
            limits,
            queue.put_nowait,
            register,
            titles,
            agent,
            reader,
        )
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
    agent: ToolAgent | None = None,
    reader: ToolReader | None = None,
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
        elif agent is not None:
            # 앱은 항상 이 흐름(2026-11-09) : 분류·목차 선택·등록 칸 추출을 도구 고르기 한 번으로
            # agent None(기존 흐름)은 테스트 가짜 미주입 때만
            context = build_context(turn.messages, turn.question.msg_seq, ai.context_turns)
            today = register.today if register is not None else rules.today_kst()
            now = datetime.combine(today, datetime.now(rules.KST).time())
            read = (
                ReadDeps(reader, register.contexts, turn.pet_sn, now)
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
            )
        else:
            judged = await judge(text, False, classifier)
        emit(("intent", judged.intent))
        kind = judged.intent.kind
        if kind is IntentKind.SEARCH:
            answer = await _search_answer(
                turn,
                repo,
                answers,
                ai,
                limits,
                judged.shortcut,
                emit,
                guide_text(judged.guide_ids),
                judged.stream,
                judged.cards,
                _notice(judged),
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
            emit(("done", AnswerDone(action=await _action_reply(text, turn, judged, register))))
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
    guide: str | None = None,
    started: AsyncIterator[str] | None = None,
    cards: list[ActionCard] | None = None,
    notice: Callable[[], bool] = lambda: True,
) -> str | None:
    # FN-AIM-002-02·07 : 완료면 고지 전 본문 반환(제목 요약용), 실패·미완료면 None
    context = build_context(turn.messages, turn.question.msg_seq, ai.context_turns)
    # started : 도구 흐름이 이미 시작한 답변 스트림
    # 안내서가 없으면 guide 인자 없이 : 안내서를 모르는 답변기 구현과도 호환
    if started is not None:
        stream = started
    elif guide is None:
        stream = answers.stream(context, ai.max_tokens)
    else:
        stream = answers.stream(context, ai.max_tokens, guide=guide)
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
    if complete and notice():
        # FN-AIM-002-03 : 건강 관련 응답만 고지를 본문 끝에 포함해 저장, 미완료 답변 제외
        emit(("delta", {"text": DISCLAIMER}))
        text += DISCLAIMER
    message = await _save(repo, turn.room_sn, text, complete)
    action = cards[0] if cards else None
    emit(("done", AnswerDone(message=message, shortcut=shortcut, action=action)))
    return body if complete else None


HEALTH_DOMAIN = "health"


def _notice(judged: Judged) -> Callable[[], bool]:
    # FN-AIM-002-03 : READ 답변은 스트림이 끝난 뒤 health READ가 하나라도 성공했는지로 정함
    def decide() -> bool:
        if not judged.notice:
            return False
        return judged.read_domains is None or HEALTH_DOMAIN in judged.read_domains

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


def action_card(
    entry: "catalog.CatalogEntry",
    values: dict,
    pets: list[PetInfo],
    named: list[PetInfo],
    draft_pet: int | None,
    room_pet: int | None,
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
            choices = [PetChoice(pet_sn=p.pet_sn, pet_nm=p.pet_nm) for p in pets]
    notice = None
    name = values.get("careArtclNm")
    warn = "same_name_warning" in entry.hooks and pet is not None and isinstance(name, str)
    # FN-AIM-012-08 : 같은 반려동물에 같은 이름의 케어 항목이 있으면 안내
    if warn and _same_name(name, pet.care_artcl_nms):
        notice = DUPLICATE_NOTICE.format(pet=pet.pet_nm, name=name)
    return ActionCard.model_validate(
        {
            "tool": entry.name,
            "domain": entry.domain,
            "label": entry.label,
            "call": entry.call.model_dump(exclude_none=True),
            "params": catalog.card_params(entry),
            "rules": catalog.card_rules(entry),
            "input": values,
            "missing": catalog.missing(entry, values),
            "petChoices": choices,
            "petNm": pet.pet_nm if pet else None,
            "notice": notice,
        }
    )


async def _action_reply(
    text: str, turn: Turn, judged: Judged, register: RegisterDeps
) -> ActionCard:
    # 카드는 미저장 : 결과만 action-result로 텍스트 요약 저장
    entry = tools.card_entry(judged.tool)
    if entry is None:
        raise AppError("INVALID_REQUEST", 400, "모르는 도구입니다.")
    pets = await register.contexts.get_pets() if _uses_pets(entry) else []
    compact = re.sub(r"\s+", "", text)
    named = [pet for pet in pets if pet.pet_nm in compact]
    prior = turn.action
    same = prior is not None and prior.tool == entry.name
    draft_pet = prior.values.get(catalog.PET_SN) if same else None
    return action_card(entry, judged.action or {}, pets, named, draft_pet, turn.pet_sn)


def _uses_pets(entry: "catalog.CatalogEntry") -> bool:
    # 반려동물 목록이 필요한 카드 : 카드의 petSn(pet) 또는 배열 줄의 petSn(line_pet)
    return "pet" in entry.hooks or "line_pet" in entry.hooks


ACTION_FAILED_MESSAGE = "실패 — {label} · 저장하지 못했어요."
ACTION_CANCELED_MESSAGE = "취소됨 — {label} · 저장하지 않았어요."


def _input_text(param: "catalog.CatalogItemParam", value: object, clock: bool = True) -> str:
    if param.type == catalog.ARRAY:
        # 배열 : 항목마다 값(번호·uuid·petSn·참거짓 칸 빼고)을 " / "로, 항목끼리는 ", "로
        rows = []
        for row in value if isinstance(value, list) else []:
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


def action_result_message(request: ActionResultRequest) -> str:
    # 확인 카드 결과 요약 : 도구 표시 이름 + input(번호 칸·참거짓 제외). 저장 글은 서버가 정함
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
    label = entry.label or entry.name
    if request.status is ActionStatus.CANCELED:
        return ACTION_CANCELED_MESSAGE.format(label=label)
    if request.status is ActionStatus.FAILED:
        return ACTION_FAILED_MESSAGE.format(label=label)
    if catalog.missing(entry, values, files=False):
        raise AppError("INVALID_REQUEST", 400, "확인 카드의 필수 칸이 비어 있습니다.")
    clock = values.get(catalog.HR_INPUT) is not False
    texts = (
        _input_text(param, values[name], clock)
        for name, param in entry.params.items()
        if name in values and name not in entry.fixed and _summarized(name, param)
    )
    parts = [text for text in texts if text]
    return f"✔ {label}" + (f" — {' · '.join(parts)}" if parts else "")


def _summarized(name: str, param: "catalog.CatalogItemParam") -> bool:
    # 요약 글에 넣는 칸 : 번호·petSn·참거짓·파일·generated(uuid) 칸은 뺀다
    return (
        not catalog.is_id(name)
        and name != catalog.PET_SN
        and param.type not in ("boolean", catalog.FILE)
        and not param.generated
    )


async def save_action_result(
    repo: ConversationRepository, room_sn: int, request: ActionResultRequest
) -> ConversationMessage:
    # 실행(React -> Java 공개 API)·취소·실패의 결과를 AI 메시지로 저장
    return await repo.add_message(room_sn, ROLE_AI, action_result_message(request))


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
) -> ImageIntentKind:
    validate_upload(image, file_name)
    jpeg = _intent_jpeg(image)
    text = text.strip() if text and text.strip() else None
    try:
        return await judge.judge(jpeg, text)
    except ImageIntentError:
        # 판단 실패 : 오류 대신 되물음(React 칩)
        return ImageIntentKind.ASK
