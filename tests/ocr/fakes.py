from dataclasses import dataclass

from app.ocr.repository import ReceiptStatus
from app.ocr.schemas import ReceiptOcrResponse


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
    """Java 영수증 내부 API 대신 메모리에 기록만 하는 가짜"""

    def __init__(self) -> None:
        self.receipts: dict[int, SavedReceipt] = {}
        self._next = 1

    async def save_original(self, image: bytes, file_name: str, pet_sn: int, src_cd: str) -> int:
        recpt_sn = self._next
        self._next += 1
        self.receipts[recpt_sn] = SavedReceipt(recpt_sn, image, file_name, pet_sn, src_cd)
        return recpt_sn

    async def report_result(
        self, recpt_sn: int, status: ReceiptStatus, result: ReceiptOcrResponse | None
    ) -> None:
        saved = self.receipts[recpt_sn]
        saved.status = status
        saved.result = result
