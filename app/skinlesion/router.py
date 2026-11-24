from typing import Annotated

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import JSONResponse

from app.core import response
from app.core.auth import require_member, require_requested_with
from app.core.config import Settings, get_settings
from app.core.image import MAX_IMAGE_BYTES
from app.skinlesion import service
from app.skinlesion.clients import SkinJudge, get_skin_judge

router = APIRouter(prefix="/ai/skin-analyses", dependencies=[Depends(require_requested_with)])


# 인증 먼저 : 쿠키 없는 요청은 키와 무관하게 401
@router.post("", dependencies=[Depends(require_member)])
async def analyze_skin(
    file: UploadFile,
    judge: Annotated[SkinJudge | None, Depends(get_skin_judge)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    # 10MB + 1바이트까지만 읽기 : 초과 판정용
    image = await file.read(MAX_IMAGE_BYTES + 1)
    result = await service.analyze_skin(
        judge, image, file.filename or "", settings.skin_analyze_timeout_sec
    )
    return response.success(result)
