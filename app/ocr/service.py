import asyncio

from app.core.image import detect_image_type
from app.core.response import AppError
from app.ocr.clients import OcrApiError, OcrClient
from app.ocr.schemas import ReceiptOcrResponse


async def recognize_receipt(
    client: OcrClient, image: bytes, timeout_sec: float
) -> ReceiptOcrResponse:
    # FN-AIM-008-06 : 형식·용량 검증은 Java 담당, 여기서는 이미지 판독 여부만 확인
    if detect_image_type(image) is None:
        raise AppError("FILE_TYPE_NOT_ALLOWED", 400, "이미지 파일로 읽을 수 없습니다.")
    # FN-AIM-010-01 : 시간 초과·API 오류 구분, 추출 0건은 오류가 아닌 빈 응답
    try:
        return await asyncio.wait_for(client.recognize(image), timeout=timeout_sec)
    except TimeoutError:
        raise AppError("OCR_TIMEOUT", 504, "영수증 분석 시간이 초과되었습니다.") from None
    except OcrApiError:
        raise AppError("OCR_API_ERROR", 502, "영수증 분석 중 오류가 발생했습니다.") from None
