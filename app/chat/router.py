from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import JSONResponse

from app.chat import service
from app.chat.clients import TitleGenerator, get_title_generator
from app.chat.repository import ConversationRepository, get_conversation_repository
from app.chat.schemas import ConversationCreateRequest
from app.core import response
from app.core.auth import require_member, require_requested_with
from app.core.crypto import FieldCrypto, get_crypto

router = APIRouter(prefix="/ai/conversations", dependencies=[Depends(require_requested_with)])

Member = Annotated[int, Depends(require_member)]
Repo = Annotated[ConversationRepository, Depends(get_conversation_repository)]
Crypto = Annotated[FieldCrypto, Depends(get_crypto)]


@router.post("")
async def create_conversation(
    body: ConversationCreateRequest,
    mbr_sn: Member,
    repo: Repo,
    crypto: Crypto,
    titles: Annotated[TitleGenerator, Depends(get_title_generator)],
) -> JSONResponse:
    result = await service.create_conversation(repo, crypto, titles, mbr_sn, body)
    return response.success(result.model_dump(by_alias=True), http_code=201)


@router.get("")
async def list_conversations(
    mbr_sn: Member,
    repo: Repo,
    crypto: Crypto,
    pet_sn: Annotated[int | None, Query(alias="petSn", ge=1)] = None,
) -> JSONResponse:
    result = await service.list_conversations(repo, crypto, mbr_sn, pet_sn)
    return response.success([r.model_dump(by_alias=True) for r in result])


@router.get("/{aiCnvrsRoomSn}")
async def get_conversation(
    mbr_sn: Member,
    repo: Repo,
    crypto: Crypto,
    room_sn: Annotated[int, Path(alias="aiCnvrsRoomSn")],
) -> JSONResponse:
    result = await service.get_conversation(repo, crypto, mbr_sn, room_sn)
    return response.success(result.model_dump(by_alias=True))


@router.delete("/{aiCnvrsRoomSn}")
async def delete_conversation(
    mbr_sn: Member,
    repo: Repo,
    room_sn: Annotated[int, Path(alias="aiCnvrsRoomSn")],
) -> JSONResponse:
    await service.delete_conversation(repo, mbr_sn, room_sn)
    return response.success()
