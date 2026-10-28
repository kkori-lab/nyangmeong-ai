from app.chat import rules
from app.chat.clients import ClassifiedKind, IntentClassifier, TitleGenerator
from app.chat.repository import ConversationRepository
from app.chat.schemas import (
    ROLE_AI,
    ConversationCreateRequest,
    ConversationDetail,
    ConversationMessage,
    ConversationSummary,
    Intent,
    IntentKind,
)

MAX_TITLE_LENGTH = 200
DEFAULT_TITLE = "새 대화"
# FN-AIM-005-02 : 화면설계서 SCR-AIM-005 ② 문구
FALLBACK_MESSAGE = "질문을 이해하지 못했어요. 다시 입력하거나 아래에서 선택해 주세요."


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


async def judge_intent(text: str, has_image: bool, classifier: IntentClassifier) -> Intent:
    # FN-AIM-001-05 : 이미지 첨부면 판정 없이 영수증 분석(SCR-AIM-013)
    if has_image:
        return Intent(kind=IntentKind.RECEIPT)
    # ① 등록 판정 — FN-AIM-004-13 : 라우팅 키워드가 있어도 등록이 먼저
    if rules.is_register_request(text):
        return Intent(kind=IntentKind.REGISTER)
    # ② 룰 기반 라우팅
    row = rules.match_route(text)
    if row is not None:
        return row.to_intent()
    # ③ AI 분류(①②가 실패한 입력만, FN-AIM-004-02)
    classified = await classifier.classify(text)
    if classified.kind is ClassifiedKind.SEARCH:
        return Intent(kind=IntentKind.SEARCH)
    if classified.kind is ClassifiedKind.ROUTE and classified.scr_id is not None:
        row = rules.find_route(classified.scr_id, classified.param)
        if row is not None:
            return row.to_intent()
    # ④ FN-AIM-004-12·005-01 : 어디에도 해당하지 않으면 폴백
    return Intent(kind=IntentKind.FALLBACK)


async def reply_fallback(repo: ConversationRepository, room_sn: int) -> ConversationMessage:
    # FN-AIM-005-02·07 : 실패 사유는 묻지 않고, 부적절 입력도 같은 문구. AI 역할 메시지로 저장
    return await repo.add_message(room_sn, ROLE_AI, FALLBACK_MESSAGE)
