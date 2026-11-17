import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Path, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.chat import rules, service
from app.chat.clients import (
    ImageIntentJudge,
    RegisterExtractor,
    TitleGenerator,
    ToolAgent,
    get_image_intent_judge,
    get_register_extractor,
    get_title_generator,
    get_tool_agent,
)
from app.chat.repository import (
    AiSettings,
    ConversationRepository,
    RegisterContextRepository,
    RouteRepository,
    ToolReader,
    get_ai_settings,
    get_conversation_repository,
    get_register_context_repository,
    get_route_repository,
    get_tool_reader,
)
from app.chat.schemas import (
    MAX_MESSAGE_LENGTH,
    ActionResultRequest,
    ConversationCreateRequest,
    MessageSendRequest,
    ReceiptResultRequest,
    RegisterResultRequest,
)
from app.core import response
from app.core.auth import require_member, require_requested_with
from app.core.config import Settings, get_settings
from app.core.image import MAX_IMAGE_BYTES

# 대화 API의 회원 판정은 Java 대화 내부 API(Cookie) : 별도 인증 확인 호출 없음
router = APIRouter(prefix="/ai/conversations", dependencies=[Depends(require_requested_with)])
me_router = APIRouter(prefix="/ai", dependencies=[Depends(require_requested_with)])

Member = Annotated[int, Depends(require_member)]
Repo = Annotated[ConversationRepository, Depends(get_conversation_repository)]


@me_router.get("/me")
async def me(mbr_sn: Member) -> JSONResponse:
    # FN-AIM-011-03 : 인증 확인용. Java /internal/auth/check 결과만 반환
    return response.success({"mbrSn": mbr_sn})


# 인증 먼저 : 쿠키 없는 요청은 LLM 미호출
@me_router.post("/image-intent", dependencies=[Depends(require_member)])
async def judge_image_intent(
    file: UploadFile,
    judge: Annotated[ImageIntentJudge, Depends(get_image_intent_judge)],
    repo: Repo,
    titles: Annotated[TitleGenerator, Depends(get_title_generator)],
    cnvrs_cn: Annotated[str | None, Form(alias="cnvrsCn", max_length=MAX_MESSAGE_LENGTH)] = None,
    # 판단 미사용 : 새 방의 펫 태그, React가 다음 요청(영수증·캐릭터)에 사용
    pet_sn: Annotated[int | None, Form(alias="petSn", ge=1)] = None,
    # 사진 턴을 저장할 방 : 없으면 방을 만듦 (2026-11-13)
    room_sn: Annotated[int | None, Form(alias="aiCnvrsRoomSn", ge=1)] = None,
) -> JSONResponse:
    # 10MB + 1바이트까지만 읽기 : 초과 판정용
    image = await file.read(MAX_IMAGE_BYTES + 1)
    # 형식·크기 400은 판단 전에 끝남 : 저장 없음
    kind = await service.judge_image_intent(judge, image, file.filename or "", cnvrs_cn)
    result = await service.save_image_turn(repo, titles, room_sn, pet_sn, cnvrs_cn, kind)
    return response.success(result.model_dump(by_alias=True, mode="json"))


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


# LLM(도구 고르기·답변) 전에 인증 확인 : 로그인하지 않은 요청이 LLM을 부르지 않게
@router.post("/{aiCnvrsRoomSn}/messages", dependencies=[Depends(require_member)])
async def send_message(
    body: MessageSendRequest,
    repo: Repo,
    ai: Annotated[AiSettings, Depends(get_ai_settings)],
    settings: Annotated[Settings, Depends(get_settings)],
    contexts: Annotated[RegisterContextRepository, Depends(get_register_context_repository)],
    extractor: Annotated[RegisterExtractor, Depends(get_register_extractor)],
    titles: Annotated[TitleGenerator, Depends(get_title_generator)],
    agent: Annotated[ToolAgent, Depends(get_tool_agent)],
    reader: Annotated[ToolReader, Depends(get_tool_reader)],
    routes: Annotated[RouteRepository, Depends(get_route_repository)],
    room_sn: Annotated[int, Path(alias="aiCnvrsRoomSn")],
) -> StreamingResponse:
    # 스트림 시작 전 오류(400·401·403·404·502)는 다른 API와 같은 JSON 응답
    turn = await service.prepare_turn(repo, room_sn, body.cnvrs_cn, body.draft, body.action)
    # FN-AIM-004-09 : 판정 전에 매핑표 갱신, 실패해도 대화는 이어 감
    await service.route_cache.refresh(routes)
    limits = service.AnswerLimits(settings.answer_first_token_sec, settings.answer_total_sec)
    register = service.RegisterDeps(contexts, extractor, rules.today_kst())
    events = service.answer_turn(turn, repo, agent, ai, limits, register, titles, reader)
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


@router.post("/{aiCnvrsRoomSn}/action-result")
async def save_action_result(
    body: ActionResultRequest,
    repo: Repo,
    room_sn: Annotated[int, Path(alias="aiCnvrsRoomSn")],
) -> JSONResponse:
    # 2단계 쓰기 : 확인 카드의 결과(완료·취소·실패) 텍스트 요약 저장
    result = await service.save_action_result(repo, room_sn, body)
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
