import logging
from typing import Annotated, Protocol

from fastapi import Depends

from app.core.backend import external_error
from app.core.config import Settings, get_settings
from app.ocr.schemas import ReceiptOcrResponse

logger = logging.getLogger(__name__)


class OcrApiError(Exception):
    """외부 OCR API 오류 (시간 초과는 서비스에서 별도 구분)"""


class OcrClient(Protocol):
    async def recognize(self, image: bytes) -> ReceiptOcrResponse: ...


def get_ocr_client(settings: Annotated[Settings, Depends(get_settings)]) -> OcrClient:
    # Google Vision 클라이언트 : 서비스 계정 키 수령 후 연결. 그 전에는 502
    logger.error("OCR 호출 불가: Google Vision 클라이언트가 아직 연결되지 않았습니다")
    raise external_error()
