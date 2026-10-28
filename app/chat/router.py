import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.chat import service
from app.chat.clients import (
    AnswerGenerator,
    IntentClassifier,
    TitleGenerator,
    get_answer_generator,
    get_intent_classifier,
    get_title_generator,
)
from app.chat.repository import (
    AiSettings,
    ConversationRepository,
    get_ai_settings,
    get_conversation_repository,
)
from app.chat.schemas import ConversationCreateRequest, MessageSendRequest
from app.core import response
from app.core.auth import require_member, require_requested_with
from app.core.config import Settings, get_settings

# 대화 API는 Java 대화 내부 API가 Cookie로 회원을 판정한다 : 여기서 따로 인증 확인을 부르지 않는다
router = APIRouter(prefix="/ai/conversations", dependencies=[Depends(require_requested_with)])
me_router = APIRouter(prefix="/ai", dependencies=[Depends(require_requested_with)])

Member = Annotated[int, Depends(require_member)]
Repo = Annotated[ConversationRepository, Depends(get_conversation_repository)]


@me_router.get("/me")
async def me(mbr_sn: Member) -> JSONResponse:
    # FN-AIM-011-03 : 인증 확인용. Java /internal/auth/check 결과만 돌려준다
    return response.success({"mbrSn": mbr_sn})


# 생성만 제목 생성(LLM) 전에 인증 확인 : 로그인하지 않은 요청이 LLM을 부르지 않게
@router.post("", dependencies=[Depends(require_member)])
async def create_conversation(
    body: ConversationCreateRequest,
    repo: Repo,
    titles: Annotated[TitleGenerator, Depends(get_title_generator)],
) -> JSONResponse:
    result = await service.create_conversation(repo, titles, body)
    return response.success(result.model_dump(by_alias=True), http_code=201)


@router.get("")
async def list_conversations(
    repo: Repo,
    pet_sn: Annotated[int | None, Query(alias="petSn", ge=1)] = None,
) -> JSONResponse:
    result = await service.list_conversations(repo, pet_sn)
    return response.success([r.model_dump(by_alias=True) for r in result])


@router.get("/{aiCnvrsRoomSn}")
async def get_conversation(
    repo: Repo,
    room_sn: Annotated[int, Path(alias="aiCnvrsRoomSn")],
) -> JSONResponse:
    result = await service.get_conversation(repo, room_sn)
    return response.success(result.model_dump(by_alias=True))


@router.delete("/{aiCnvrsRoomSn}")
async def delete_conversation(
    repo: Repo,
    room_sn: Annotated[int, Path(alias="aiCnvrsRoomSn")],
) -> JSONResponse:
    await service.delete_conversation(repo, room_sn)
    return response.success()


# LLM(분류·답변) 전에 인증 확인 : 로그인하지 않은 요청이 LLM을 부르지 않게
@router.post("/{aiCnvrsRoomSn}/messages", dependencies=[Depends(require_member)])
async def send_message(
    body: MessageSendRequest,
    repo: Repo,
    classifier: Annotated[IntentClassifier, Depends(get_intent_classifier)],
    answers: Annotated[AnswerGenerator, Depends(get_answer_generator)],
    ai: Annotated[AiSettings, Depends(get_ai_settings)],
    settings: Annotated[Settings, Depends(get_settings)],
    room_sn: Annotated[int, Path(alias="aiCnvrsRoomSn")],
) -> StreamingResponse:
    # 스트림 시작 전 오류(400·401·403·404·502)는 다른 API와 같은 JSON 응답
    turn = await service.prepare_turn(repo, room_sn, body.cnvrs_cn)
    limits = service.AnswerLimits(settings.answer_first_token_sec, settings.answer_total_sec)
    events = service.answer_turn(turn, repo, classifier, answers, ai, limits)
    return StreamingResponse(_sse(events), media_type="text/event-stream")


async def _sse(events: AsyncIterator[service.Event]) -> AsyncIterator[str]:
    # 이 API만 ApiResponse 껍데기 대신 SSE 이벤트로 준다
    async for name, data in events:
        payload = data.model_dump(by_alias=True) if isinstance(data, BaseModel) else data
        text = json.dumps(jsonable_encoder(payload), ensure_ascii=False)
        yield f"event: {name}\ndata: {text}\n\n"
