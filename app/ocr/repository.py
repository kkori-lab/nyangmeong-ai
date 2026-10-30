from enum import StrEnum
from typing import Annotated, Protocol

import httpx2
from fastapi import Depends, Request
from pydantic import BaseModel, Field, ValidationError

from app.core.auth import REQUESTED_WITH
from app.core.backend import call_backend, external_error, get_backend_client
from app.core.config import Settings, get_settings
from app.core.image import detect_image_type
from app.ocr.schemas import ReceiptOcrResponse

# Java 영수증 내부 API (정본은 백엔드 docs/api/receipt.md, 백엔드 PR #64)
RECEIPTS_PATH = "/internal/ai/receipts"
REQUESTED_WITH_HEADER = "X-Requested-With"


class ReceiptStatus(StrEnum):
    # 영수증 상태 보고값(ReceiptReportRequest.ocrRslt) : Java가 AIMG01 공통코드로 변환
    RECOGNIZED = "RECOGNIZED"  # 인식완료
    UNRECOGNIZED = "UNRECOGNIZED"  # 인식실패(추출 0건)
    TIMEOUT = "TIMEOUT"  # 일시오류(분석 시간 초과)
    API_ERROR = "API_ERROR"  # 일시오류(외부 API 오류)
    CANCELED = "CANCELED"  # 취소


# 인식 결과(ocr) 동봉 상태 : 일시 오류·취소는 Java가 ocr 무시
_WITH_RESULT = frozenset({ReceiptStatus.RECOGNIZED, ReceiptStatus.UNRECOGNIZED})


class ReceiptRepository(Protocol):
    async def save_original(
        self, image: bytes, file_name: str, pet_sn: int, src_cd: str
    ) -> int: ...

    async def report_result(
        self, recpt_sn: int, status: ReceiptStatus, result: ReceiptOcrResponse | None
    ) -> None: ...


class _OriginalResponse(BaseModel):
    recpt_sn: int = Field(alias="recptSn")


class JavaReceiptRepository:
    # 회원 판정은 Java(브라우저 Cookie) : 4xx(PET_ACCESS_DENIED·FILE_TOO_LARGE 등) 그대로 전달,
    # 연결 실패·5xx·응답 모양 불일치는 502
    def __init__(self, client: httpx2.AsyncClient, settings: Settings, cookie: str | None) -> None:
        self._client = client
        self._settings = settings
        # Java RequestedWithFilter가 /internal/**의 POST에도 적용
        self._headers = {REQUESTED_WITH_HEADER: REQUESTED_WITH}
        if cookie:
            self._headers["Cookie"] = cookie

    async def save_original(self, image: bytes, file_name: str, pet_sn: int, src_cd: str) -> int:
        # FN-AIM-008-09·010-06·013-08 : Java가 원본 파일과 RECPT(분석중) 생성
        content_type = f"image/{detect_image_type(image)}"
        data = await call_backend(
            self._client,
            self._settings,
            "POST",
            RECEIPTS_PATH,
            headers=self._headers,
            files={"file": (file_name, image, content_type)},
            # Python 요청의 ocrRqstSrcCd -> Java 이름 ocrDmndSrcCd
            data={"petSn": str(pet_sn), "ocrDmndSrcCd": src_cd},
        )
        try:
            return _OriginalResponse.model_validate(data).recpt_sn
        except ValidationError:
            raise external_error() from None

    async def report_result(
        self, recpt_sn: int, status: ReceiptStatus, result: ReceiptOcrResponse | None
    ) -> None:
        # FN-AIM-008-07·010-01·013-04 : 인식·0건·일시 오류·취소 모두 보고
        ocr = None
        if status in _WITH_RESULT and result is not None:
            ocr = result.model_dump(mode="json", by_alias=True)
        await call_backend(
            self._client,
            self._settings,
            "POST",
            f"{RECEIPTS_PATH}/{recpt_sn}/result",
            headers=self._headers,
            json={"ocrRslt": status.value, "ocr": ocr},
        )


def get_receipt_repository(
    request: Request,
    client: Annotated[httpx2.AsyncClient, Depends(get_backend_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReceiptRepository:
    return JavaReceiptRepository(client, settings, request.headers.get("cookie"))
