from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from app.character import service
from app.character.clients import CharacterClient, get_character_client
from app.character.repository import CharacterJobRepository, get_character_job_repository
from app.character.schemas import (
    ITEM_NM_MAX,
    CharacterCreateResponse,
    CharacterPreviewRequest,
    ItemBakeHintResponse,
    ItemBakeResponse,
    ItemTrialRequest,
)
from app.character.service import BakeQueue, get_bake_queue
from app.core import response
from app.core.auth import require_admin, require_member, require_requested_with
from app.core.config import Settings, get_settings
from app.core.image import MAX_IMAGE_BYTES

# 캐릭터(/ai/characters)와 관리자 아이템(/ai/items) : 굽기 코드를 같이 써서 한 라우터
router = APIRouter(prefix="/ai", dependencies=[Depends(require_requested_with)])


# 인증 먼저 : 쿠키 없는 요청은 생성기와 무관하게 401
# 생성기 없으면 업로드 검증 뒤, Java 작업 생성 전에 502
@router.post("/characters", dependencies=[Depends(require_member)])
async def create_character(
    background_tasks: BackgroundTasks,
    photo: UploadFile,
    pet_sn: Annotated[int, Form(alias="petSn")],
    client: Annotated[CharacterClient | None, Depends(get_character_client)],
    repo: Annotated[CharacterJobRepository, Depends(get_character_job_repository)],
    queue: Annotated[BakeQueue, Depends(get_bake_queue)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    # 10MB + 1바이트까지만 읽기 : 초과 판정용
    image = await photo.read(MAX_IMAGE_BYTES + 1)
    job = await service.create_job(client, repo, image, photo.filename or "", pet_sn)
    # FN-MYP-010-09 : 응답 뒤 생성 (상태 조회는 React가 Java에서)
    background_tasks.add_task(
        service.generate_and_report,
        client,
        repo,
        queue,
        job,
        image,
        settings.character_bake_enabled,
    )
    return response.success(CharacterCreateResponse(char_crt_job_sn=job.char_crt_job_sn), 202)


@router.post("/characters/{pixel_char_sn}/preview", dependencies=[Depends(require_member)])
async def preview_character(
    request: Request,
    background_tasks: BackgroundTasks,
    pixel_char_sn: int,
    body: CharacterPreviewRequest,
    client: Annotated[CharacterClient | None, Depends(get_character_client)],
    repo: Annotated[CharacterJobRepository, Depends(get_character_job_repository)],
    queue: Annotated[BakeQueue, Depends(get_bake_queue)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    enabled = settings.character_bake_enabled
    image = await service.preview(client, repo, queue, pixel_char_sn, body.item_sns, enabled)
    if image is not None:
        return Response(image, media_type="image/png")
    # 예외로 끝내면 백그라운드 작업이 버려짐 : 응답으로 반환
    background_tasks.add_task(queue.drain)
    message = "아이템을 준비하고 있습니다. 잠시 후 다시 시도해 주세요."
    return response.error("ITEM_BAKING", 409, message, request.url.path)


# 착용 확정은 Java PUT /pixel-characters/{pixelCharSn}/equipped-items가 먼저, React가 성공 뒤 호출
@router.post("/characters/{pixel_char_sn}/equipped-image", dependencies=[Depends(require_member)])
async def save_equipped_image(
    request: Request,
    background_tasks: BackgroundTasks,
    pixel_char_sn: int,
    body: CharacterPreviewRequest,
    client: Annotated[CharacterClient | None, Depends(get_character_client)],
    repo: Annotated[CharacterJobRepository, Depends(get_character_job_repository)],
    queue: Annotated[BakeQueue, Depends(get_bake_queue)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    enabled = settings.character_bake_enabled
    saved = await service.save_equipped_image(
        client, repo, queue, pixel_char_sn, body.item_sns, enabled
    )
    if saved:
        return response.success(None)
    background_tasks.add_task(queue.drain)
    message = "아이템을 준비하고 있습니다. 잠시 후 다시 시도해 주세요."
    return response.error("ITEM_BAKING", 409, message, request.url.path)


@router.post("/items/bake-hints", dependencies=[Depends(require_admin)])
async def create_bake_hint(
    image: UploadFile,
    regn_cd: Annotated[str, Form(alias="regnCd")],
    item_nm: Annotated[str, Form(alias="itemNm", min_length=1, max_length=ITEM_NM_MAX)],
    client: Annotated[CharacterClient | None, Depends(get_character_client)],
) -> JSONResponse:
    # 10MB + 1바이트까지만 읽기 : 초과 판정용
    raw = await image.read(MAX_IMAGE_BYTES + 1)
    hint = await service.describe_item(client, raw, image.filename or "", regn_cd, item_nm)
    return response.success(ItemBakeHintResponse(bake_hint=hint))


# 상점 이미지용 : 관리자 프론트가 확인한 뒤 Java 아이템 등록에 이 그림을 올림
@router.post("/items/pixel-image", dependencies=[Depends(require_admin)])
async def create_pixel_image(
    image: UploadFile,
    regn_cd: Annotated[str, Form(alias="regnCd")],
    item_nm: Annotated[str, Form(alias="itemNm", min_length=1, max_length=ITEM_NM_MAX)],
    client: Annotated[CharacterClient | None, Depends(get_character_client)],
) -> Response:
    # 10MB + 1바이트까지만 읽기 : 초과 판정용
    raw = await image.read(MAX_IMAGE_BYTES + 1)
    png = await service.draw_item(client, raw, image.filename or "", regn_cd, item_nm)
    return Response(png, media_type="image/png")


@router.post("/items/trial-preview", dependencies=[Depends(require_admin)])
async def trial_preview(
    body: ItemTrialRequest,
    client: Annotated[CharacterClient | None, Depends(get_character_client)],
    repo: Annotated[CharacterJobRepository, Depends(get_character_job_repository)],
) -> Response:
    image = await service.trial_preview(
        client, repo, body.pixel_char_sn, body.regn_cd, body.bake_hint
    )
    return Response(image, media_type="image/png")


# 한 묶음을 다 굽고 답함 : 관리자 프론트가 lastYn까지 다시 부름 (쿠키 30분 만료 대책)
@router.post("/items/{item_sn}/bake", dependencies=[Depends(require_admin)])
async def bake_item(
    item_sn: int,
    client: Annotated[CharacterClient | None, Depends(get_character_client)],
    repo: Annotated[CharacterJobRepository, Depends(get_character_job_repository)],
    queue: Annotated[BakeQueue, Depends(get_bake_queue)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    enabled = settings.character_bake_enabled
    result = await service.bake_item_batch(client, repo, queue, item_sn, enabled)
    return response.success(
        ItemBakeResponse(
            item_sn=item_sn,
            baked_cnt=result.baked_cnt,
            failed_cnt=result.failed_cnt,
            last_yn=result.last,
        )
    )
