from typing import Annotated

from fastapi import APIRouter, Depends, Path
from fastapi.responses import JSONResponse

from app.chat import service
from app.chat.repository import ConversationRepository, get_conversation_repository
from app.core import response
from app.core.internal_auth import require_internal_key

router = APIRouter(prefix="/internal/v1/members", dependencies=[Depends(require_internal_key)])


@router.delete("/{mbrSn}/conversations")
async def purge_member_conversations(
    mbr_sn: Annotated[int, Path(alias="mbrSn")],
    repo: Annotated[ConversationRepository, Depends(get_conversation_repository)],
) -> JSONResponse:
    await service.purge_member(repo, mbr_sn)
    return response.success()
