from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Form, UploadFile
from fastapi.responses import JSONResponse

from app.character import service
from app.character.clients import CharacterClient, get_character_client
from app.character.repository import CharacterJobRepository, get_character_job_repository
from app.character.schemas import CharacterCreateResponse
from app.core import response
from app.core.auth import require_member, require_requested_with
from app.core.image import MAX_IMAGE_BYTES

router = APIRouter(prefix="/ai/characters", dependencies=[Depends(require_requested_with)])


# 인증 먼저 : 쿠키 없는 요청은 생성기와 무관하게 401
# 생성기 없으면 업로드 검증 뒤, Java 작업 생성 전에 502
@router.post("", dependencies=[Depends(require_member)])
async def create_character(
    background_tasks: BackgroundTasks,
    photo: UploadFile,
    pet_sn: Annotated[int, Form(alias="petSn")],
    client: Annotated[CharacterClient | None, Depends(get_character_client)],
    repo: Annotated[CharacterJobRepository, Depends(get_character_job_repository)],
) -> JSONResponse:
    # 10MB + 1바이트까지만 읽기 : 초과 판정용
    image = await photo.read(MAX_IMAGE_BYTES + 1)
    job = await service.create_job(client, repo, image, photo.filename or "", pet_sn)
    # FN-MYP-010-09 : 응답 뒤 생성 (상태 조회는 React가 Java에서)
    background_tasks.add_task(service.generate_and_report, client, repo, job, image)
    return response.success(CharacterCreateResponse(chrc_job_sn=job.chrc_job_sn), 202)
