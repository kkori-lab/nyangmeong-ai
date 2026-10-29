import asyncio
from collections.abc import Awaitable, Callable

from app.core.image import detect_image_type
from app.core.response import AppError
from app.ocr.clients import OcrApiError, OcrClient
from app.ocr.repository import ReceiptRepository, ReceiptStatus
from app.ocr.schemas import ReceiptAnalyzeResponse, ReceiptOcrResponse

# FN-AIM-008-05 : 업로드 제약(REQ-NFR-003)
MAX_IMAGE_BYTES = 10 * 1024 * 1024
EXTENSION_TYPES = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}
# 요청 출처(AIMG07) : 건강 일지, AI 대화창(SCR-AIM-013). 가계부(AIMC0027)는 받지 않는다
SOURCE_CODES = frozenset({"AIMC0026", "AIMC0031"})
# 연결 끊김(취소) 확인 간격(초)
DISCONNECT_POLL_SEC = 0.5

# FN-AIM-008-06 : 분석 중인 회원. 프로세스 메모리라 워커 1개 전제
_in_progress: set[int] = set()


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
        raise _timeout_error() from None
    except OcrApiError:
        raise _api_error() from None


def validate_upload(image: bytes, file_name: str | None) -> None:
    """FN-AIM-008-05 : 확장자와 실제 형식을 함께 검증, 10MB 이하. PDF는 받지 않는다"""
    if len(image) > MAX_IMAGE_BYTES:
        raise AppError("FILE_SIZE_EXCEEDED", 400, "파일 용량은 10MB 이하여야 합니다.")
    _, dot, extension = (file_name or "").rpartition(".")
    expected = EXTENSION_TYPES.get(extension.lower()) if dot else None
    if expected is None or detect_image_type(image) != expected:
        raise AppError("FILE_TYPE_NOT_ALLOWED", 400, "jpg·jpeg·png·webp 이미지만 올릴 수 있습니다.")


def validate_source(src_cd: str) -> None:
    if src_cd not in SOURCE_CODES:
        raise AppError("INVALID_REQUEST", 400, "요청 값이 올바르지 않습니다.")


async def analyze_receipt(
    client: OcrClient,
    repo: ReceiptRepository,
    mbr_sn: int,
    image: bytes,
    file_name: str,
    pet_sn: int,
    src_cd: str,
    timeout_sec: float,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> ReceiptAnalyzeResponse:
    validate_source(src_cd)
    validate_upload(image, file_name)
    # FN-AIM-008-06·013-04 : 같은 회원의 중복 요청 차단
    if mbr_sn in _in_progress:
        raise AppError("OCR_IN_PROGRESS", 409, "이미 분석 중인 영수증이 있습니다.")
    _in_progress.add(mbr_sn)
    try:
        # FN-AIM-008-09·010-06 : 원본을 먼저 저장한다(분석이 실패해도 원본은 남는다)
        recpt_sn = await repo.save_original(image, file_name, pet_sn, src_cd)
        result = await _recognize(client, repo, recpt_sn, image, timeout_sec, is_disconnected)
        # FN-AIM-010-01 : 추출 0건이면 인식 실패(오류가 아닌 빈 응답)
        status = ReceiptStatus.UNRECOGNIZED if _is_empty(result) else ReceiptStatus.RECOGNIZED
        await repo.report_result(recpt_sn, status, result)
        return ReceiptAnalyzeResponse(recpt_sn=recpt_sn, ocr=result)
    finally:
        _in_progress.discard(mbr_sn)


async def _recognize(
    client: OcrClient,
    repo: ReceiptRepository,
    recpt_sn: int,
    image: bytes,
    timeout_sec: float,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> ReceiptOcrResponse:
    # FN-AIM-008-07 : 15초 초과·API 오류는 일시 오류, 연결이 끊기면(React [취소]) 분석을 멈추고 취소
    ocr = asyncio.ensure_future(asyncio.wait_for(client.recognize(image), timeout=timeout_sec))
    watcher = asyncio.ensure_future(_wait_disconnect(is_disconnected))
    try:
        done, _ = await asyncio.wait({ocr, watcher}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        watcher.cancel()
    if ocr not in done:
        ocr.cancel()
        await repo.report_result(recpt_sn, ReceiptStatus.CANCELED, None)
        raise AppError("OCR_CANCELED", 400, "영수증 분석을 취소했습니다.")
    try:
        return ocr.result()
    except TimeoutError:
        await repo.report_result(recpt_sn, ReceiptStatus.TIMEOUT, None)
        raise _timeout_error() from None
    except OcrApiError:
        await repo.report_result(recpt_sn, ReceiptStatus.API_ERROR, None)
        raise _api_error() from None


async def _wait_disconnect(is_disconnected: Callable[[], Awaitable[bool]]) -> None:
    while not await is_disconnected():
        await asyncio.sleep(DISCONNECT_POLL_SEC)


def _is_empty(result: ReceiptOcrResponse) -> bool:
    top = (result.hsptl_nm, result.ckup_ymd, result.recpt_amt, result.btm_dscnt_amt)
    sections = (
        (s.section_nm, s.sbttl_amt, s.dscnt_amt, s.items or None, s.drugs or None)
        for s in result.sections
    )
    return all(v is None for v in top) and all(v is None for s in sections for v in s)


def _timeout_error() -> AppError:
    return AppError("OCR_TIMEOUT", 504, "영수증 분석 시간이 초과되었습니다.")


def _api_error() -> AppError:
    return AppError("OCR_API_ERROR", 502, "영수증 분석 중 오류가 발생했습니다.")
