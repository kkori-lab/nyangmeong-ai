from app.chat.clients import TitleGenerator
from app.chat.repository import ConversationRepository, RoomRow
from app.chat.schemas import (
    ConversationCreateRequest,
    ConversationDetail,
    ConversationMessage,
    ConversationSummary,
)
from app.core.crypto import CryptoError, FieldCrypto
from app.core.response import AppError

MAX_TITLE_LENGTH = 200
DEFAULT_TITLE = "새 대화"


async def create_conversation(
    repo: ConversationRepository,
    crypto: FieldCrypto,
    titles: TitleGenerator,
    mbr_sn: int,
    request: ConversationCreateRequest,
) -> ConversationSummary:
    # FN-AIM-011-11 : 제목은 첫 메시지로 1회 생성, 200자 제한은 서버에서 적용
    title = (await titles.generate(request.cnvrs_cn)).strip()[:MAX_TITLE_LENGTH] or DEFAULT_TITLE
    # FN-AIM-011-07·14 : 방과 첫 메시지를 함께 저장(저장소가 한 트랜잭션으로 묶는다)
    room = await repo.create_room(
        mbr_sn, request.pet_sn, crypto.encrypt(title), crypto.encrypt(request.cnvrs_cn)
    )
    return _summary(crypto, room)


async def list_conversations(
    repo: ConversationRepository, crypto: FieldCrypto, mbr_sn: int, pet_sn: int | None
) -> list[ConversationSummary]:
    # FN-AIM-011-08·09
    return [_summary(crypto, r) for r in await repo.list_rooms(mbr_sn, pet_sn)]


async def get_conversation(
    repo: ConversationRepository, crypto: FieldCrypto, mbr_sn: int, room_sn: int
) -> ConversationDetail:
    # FN-AIM-011-10 : 남의 방은 없는 방과 같은 404
    room = await repo.get_room(mbr_sn, room_sn)
    if room is None:
        raise _not_found()
    messages = [
        ConversationMessage(
            ai_cnvrs_msg_sn=m.msg_sn,
            role_cd=m.role_cd,
            cnvrs_cn=_decrypt(crypto, m.cn_enc),
            msg_seq=m.msg_seq,
            reg_dt=m.reg_dt,
        )
        for m in await repo.list_messages(room.room_sn)
    ]
    return ConversationDetail(**_summary(crypto, room).model_dump(), messages=messages)


async def delete_conversation(repo: ConversationRepository, mbr_sn: int, room_sn: int) -> None:
    # FN-AIM-011-13 : 물리 삭제
    if not await repo.delete_room(mbr_sn, room_sn):
        raise _not_found()


async def purge_member(repo: ConversationRepository, mbr_sn: int) -> None:
    # FN-AIM-011-19 : 탈퇴 회원 대화 파기. 보관일수 판단은 Java, 대화가 없어도 정상
    await repo.delete_member(mbr_sn)


def _summary(crypto: FieldCrypto, room: RoomRow) -> ConversationSummary:
    return ConversationSummary(
        ai_cnvrs_room_sn=room.room_sn,
        pet_sn=room.pet_sn,
        cnvrs_ttl=_decrypt(crypto, room.ttl_enc),
        reg_dt=room.reg_dt,
    )


def _decrypt(crypto: FieldCrypto, envelope: str) -> str:
    try:
        return crypto.decrypt(envelope)
    except CryptoError:
        raise AppError("INTERNAL_SERVER_ERROR", 500, "대화를 읽을 수 없습니다.") from None


def _not_found() -> AppError:
    return AppError("NOT_FOUND", 404, "요청한 정보를 찾을 수 없습니다.")
