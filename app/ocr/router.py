from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from app.core import response
from app.core.auth import require_member, require_requested_with
from app.core.config import Settings, get_settings
from app.core.image import MAX_IMAGE_BYTES
from app.ocr import service
from app.ocr.clients import OcrClient, get_ocr_client
from app.ocr.repository import ReceiptRepository, get_receipt_repository

router = APIRouter(prefix="/internal/v1/ocr")
ai_router = APIRouter(prefix="/ai/receipts", dependencies=[Depends(require_requested_with)])


@router.post("/receipt")
async def recognize_receipt(
    file: UploadFile,
    client: Annotated[OcrClient, Depends(get_ocr_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    result = await service.recognize_receipt(client, await file.read(), settings.ocr_timeout_sec)
    return response.success(result)


# 인증을 OCR 클라이언트보다 먼저 : 쿠키 없는 요청은 키와 관계없이 401
@ai_router.post("", dependencies=[Depends(require_member)])
async def analyze_receipt(
    request: Request,
    mbr_sn: Annotated[int, Depends(require_member)],
    file: UploadFile,
    pet_sn: Annotated[int, Form(alias="petSn")],
    src_cd: Annotated[str, Form(alias="ocrRqstSrcCd")],
    client: Annotated[OcrClient, Depends(get_ocr_client)],
    repo: Annotated[ReceiptRepository, Depends(get_receipt_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    # 10MB를 넘는 부분은 읽지 않는다(1바이트만 더 읽어 초과 판정)
    image = await file.read(MAX_IMAGE_BYTES + 1)
    result = await service.analyze_receipt(
        client,
        repo,
        mbr_sn,
        image,
        file.filename or "",
        pet_sn,
        src_cd,
        settings.ocr_timeout_sec,
        request.is_disconnected,
    )
    return response.success(result)
