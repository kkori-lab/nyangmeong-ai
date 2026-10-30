import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.chat import rules, service
from app.chat.clients import (
    AnswerGenerator,
    IntentClassifier,
    RegisterExtractor,
    TitleGenerator,
    get_answer_generator,
    get_intent_classifier,
    get_register_extractor,
    get_title_generator,
)
from app.chat.repository import (
    AiSettings,
    ConversationRepository,
    RegisterContextRepository,
    get_ai_settings,
    get_conversation_repository,
    get_register_context_repository,
)
from app.chat.schemas import (
    ConversationCreateRequest,
    MessageSendRequest,
    ReceiptResultRequest,
    RegisterResultRequest,
)
from app.core import response
from app.core.auth import require_member, require_requested_with
from app.core.config import Settings, get_settings

# 대화 API의 회원 판정은 Java 대화 내부 API(Cookie) : 별도 인증 확인 호출 없음
router = APIRouter(prefix="/ai/conversations", dependencies=[Depends(require_requested_with)])
me_router = APIRouter(prefix="/ai", dependencies=[Depends(require_requested_with)])

Member = Annotated[int, Depends(require_member)]
Repo = Annotated[ConversationRepository, Depends(get_conversation_repository)]


@me_router.get("/me")
async def me(mbr_sn: Member) -> JSONResponse:
    # FN-AIM-011-03 : 인증 확인용. Java /internal/auth/check 결과만 반환
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
    contexts: Annotated[RegisterContextRepository, Depends(get_register_context_repository)],
    extractor: Annotated[RegisterExtractor, Depends(get_register_extractor)],
    room_sn: Annotated[int, Path(alias="aiCnvrsRoomSn")],
) -> StreamingResponse:
    # 스트림 시작 전 오류(400·401·403·404·502)는 다른 API와 같은 JSON 응답
    turn = await service.prepare_turn(repo, room_sn, body.cnvrs_cn, body.draft)
    limits = service.AnswerLimits(settings.answer_first_token_sec, settings.answer_total_sec)
    register = service.RegisterDeps(contexts, extractor, rules.today_kst())
    events = service.answer_turn(turn, repo, classifier, answers, ai, limits, register)
    return StreamingResponse(_sse(events), media_type="text/event-stream")


@router.post("/{aiCnvrsRoomSn}/register-result")
async def save_register_result(
    body: RegisterResultRequest,
    repo: Repo,
    room_sn: Annotated[int, Path(alias="aiCnvrsRoomSn")],
) -> JSONResponse:
    # FN-AIM-012-11·16 : 등록 카드의 결과(등록됨·취소됨) 텍스트 요약 저장
    result = await service.save_register_result(repo, room_sn, body)
    return response.success(result.model_dump(by_alias=True), http_code=201)


# 저장 전에 인증 확인 : 로그인하지 않은 요청은 사용자 메시지부터 401
@router.post("/{aiCnvrsRoomSn}/receipt-result", dependencies=[Depends(require_member)])
async def save_receipt_result(
    body: ReceiptResultRequest,
    repo: Repo,
    room_sn: Annotated[int, Path(alias="aiCnvrsRoomSn")],
) -> JSONResponse:
    # FN-AIM-013-02·09 : 영수증 분석 후 함께 보낸 텍스트·결과 요약 저장
    saved = await service.save_receipt_result(repo, room_sn, body)
    return response.success([m.model_dump(by_alias=True) for m in saved], http_code=201)


async def _sse(events: AsyncIterator[service.Event]) -> AsyncIterator[str]:
    # 이 API만 ApiResponse 대신 SSE 이벤트 응답
    async for name, data in events:
        payload = data.model_dump(by_alias=True) if isinstance(data, BaseModel) else data
        text = json.dumps(jsonable_encoder(payload), ensure_ascii=False)
        yield f"event: {name}\ndata: {text}\n\n"
