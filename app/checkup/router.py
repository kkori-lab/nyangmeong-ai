from typing import Annotated

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import JSONResponse

from app.checkup import service
from app.checkup.clients import LabResultClient, get_lab_result_client
from app.checkup.rules import MAX_PDF_BYTES
from app.core import response
from app.core.auth import require_member, require_requested_with
from app.core.config import Settings, get_settings

router = APIRouter(prefix="/ai/checkups", dependencies=[Depends(require_requested_with)])


# 인증 먼저 : 쿠키 없는 요청은 키와 무관하게 401
@router.post("/lab-results", dependencies=[Depends(require_member)])
async def analyze_lab_result(
    file: UploadFile,
    client: Annotated[LabResultClient | None, Depends(get_lab_result_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    # 10MB + 1바이트까지만 읽기 : 초과 판정용
    pdf = await file.read(MAX_PDF_BYTES + 1)
    result = await service.analyze_lab_result(
        client, pdf, file.filename or "", settings.pdf_analyze_timeout_sec
    )
    return response.success(result)
