from datetime import date
from typing import Annotated, Protocol

from fastapi import Depends

from app.core.config import AiMode, Settings, get_settings
from app.ocr.schemas import Drug, Line, ReceiptOcrResponse, Section


class OcrApiError(Exception):
    """외부 OCR API 오류 (시간 초과는 서비스에서 별도 구분)"""


class OcrClient(Protocol):
    async def recognize(self, image: bytes) -> ReceiptOcrResponse: ...


class MockOcrClient:
    # AI_MODE=mock 전용 고정 응답
    async def recognize(self, image: bytes) -> ReceiptOcrResponse:
        return ReceiptOcrResponse(
            hsptl_nm="냥멍동물병원",
            ckup_ymd=date(2026, 10, 20),
            recpt_amt=45000,
            sections=[
                Section(
                    section_nm="미르",
                    sbttl_amt=45000,
                    items=[Line(item_nm="진료비", item_amt=30000)],
                    drugs=[
                        Drug(mdcn_nm="소염제", mdcn_days=5, mdcn_usage="1일 2회", mdcn_amt=15000)
                    ],
                )
            ],
        )


def get_ocr_client(settings: Annotated[Settings, Depends(get_settings)]) -> OcrClient:
    if settings.ai_mode is AiMode.MOCK:
        return MockOcrClient()
    # Google Vision 클라이언트 : 서비스 계정 키 수령 후 연결
    raise NotImplementedError("OCR real 모드는 아직 연결되지 않았습니다")
