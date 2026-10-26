from typing import Annotated

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import JSONResponse

from app.core import response
from app.core.config import Settings, get_settings
from app.ocr import service
from app.ocr.clients import OcrClient, get_ocr_client

router = APIRouter(prefix="/internal/v1/ocr")


@router.post("/receipt")
async def recognize_receipt(
    file: UploadFile,
    client: Annotated[OcrClient, Depends(get_ocr_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    result = await service.recognize_receipt(client, await file.read(), settings.ocr_timeout_sec)
    return response.success(result)
