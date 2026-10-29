import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.ocr.schemas import ReceiptOcrResponse

logger = logging.getLogger(__name__)


class ReceiptStatus(StrEnum):
    # 영수증 상태(AIMG01). Java 내부 API가 생기면 공통코드 값으로 맞춘다
    RECOGNIZED = "RECOGNIZED"  # 인식완료
    UNRECOGNIZED = "UNRECOGNIZED"  # 인식실패(추출 0건)
    TIMEOUT = "TIMEOUT"  # 일시오류(분석 시간 초과)
    API_ERROR = "API_ERROR"  # 일시오류(외부 API 오류)
    CANCELED = "CANCELED"  # 취소


class ReceiptRepository(Protocol):
    async def save_original(
        self, image: bytes, file_name: str, pet_sn: int, src_cd: str
    ) -> int: ...

    async def report_result(
        self, recpt_sn: int, status: ReceiptStatus, result: ReceiptOcrResponse | None
    ) -> None: ...


@dataclass
class SavedReceipt:
    recpt_sn: int
    image: bytes
    file_name: str
    pet_sn: int
    src_cd: str
    status: ReceiptStatus | None = None
    result: ReceiptOcrResponse | None = None


class FakeReceiptRepository:
    """Java 영수증 원본·상태 저장 내부 API가 생기기 전의 가짜. 메모리에 기록만 한다

    연결은 LJS 백엔드 영수증 흐름 재설계 뒤(docs/api/internal.md "Python → Java" 미정 행)
    """

    def __init__(self) -> None:
        self.receipts: dict[int, SavedReceipt] = {}
        self._next = 1

    async def save_original(self, image: bytes, file_name: str, pet_sn: int, src_cd: str) -> int:
        recpt_sn = self._next
        self._next += 1
        self.receipts[recpt_sn] = SavedReceipt(recpt_sn, image, file_name, pet_sn, src_cd)
        logger.info("가짜 Java 영수증 원본 저장: recptSn=%d, %d바이트", recpt_sn, len(image))
        return recpt_sn

    async def report_result(
        self, recpt_sn: int, status: ReceiptStatus, result: ReceiptOcrResponse | None
    ) -> None:
        saved = self.receipts[recpt_sn]
        saved.status = status
        saved.result = result
        logger.info("가짜 Java 영수증 상태 보고: recptSn=%d, %s", recpt_sn, status)


_fake = FakeReceiptRepository()


def get_receipt_repository() -> ReceiptRepository:
    return _fake
