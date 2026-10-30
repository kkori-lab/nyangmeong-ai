import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.core.backend import BackendError
from app.core.image import detect_image_type, validate_upload
from app.core.response import AppError
from app.ocr.clients import OcrApiError, OcrClient
from app.ocr.repository import ReceiptRepository, ReceiptStatus
from app.ocr.schemas import ReceiptAnalyzeResponse, ReceiptOcrResponse

# 요청 출처(AIMG07) : 건강 일지, AI 대화창(SCR-AIM-013), 가계부(AIMC0027) 제외
SOURCE_CODES = frozenset({"AIMC0026", "AIMC0031"})
# 연결 끊김(취소) 확인 간격(초)
DISCONNECT_POLL_SEC = 0.5

logger = logging.getLogger(__name__)

# FN-AIM-008-06 : 분석 중인 회원. 프로세스 메모리라 워커 1개 전제
_in_progress: set[int] = set()


async def recognize_receipt(
    client: OcrClient, image: bytes, timeout_sec: float
) -> ReceiptOcrResponse:
    # FN-AIM-008-06 : 형식·용량 검증은 Java, 여기서는 이미지 판독 가능 여부만
    if detect_image_type(image) is None:
        raise AppError("FILE_TYPE_NOT_ALLOWED", 400, "이미지 파일로 읽을 수 없습니다.")
    # FN-AIM-010-01 : 시간 초과·API 오류 구분, 추출 0건은 오류가 아닌 빈 응답
    try:
        return await asyncio.wait_for(client.recognize(image), timeout=timeout_sec)
    except TimeoutError:
        raise _timeout_error() from None
    except OcrApiError:
        raise _api_error() from None


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
        # FN-AIM-008-09·010-06 : 원본 선저장 (분석 실패에도 원본 유지)
        recpt_sn = await repo.save_original(image, file_name, pet_sn, src_cd)
        result = await _recognize(client, repo, recpt_sn, image, timeout_sec, is_disconnected)
        # FN-AIM-010-01 : 추출 0건은 인식 실패 (오류 아닌 빈 응답)
        status = ReceiptStatus.UNRECOGNIZED if _is_empty(result) else ReceiptStatus.RECOGNIZED
        # 보고 실패 시 결과 미반환 : RECPT가 분석중으로 남아 이후 저장 깨짐 방지
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
    # FN-AIM-008-07 : 15초 초과·API 오류는 일시 오류, 연결 끊김(React [취소])은 분석 중단 후 취소
    ocr = asyncio.ensure_future(asyncio.wait_for(client.recognize(image), timeout=timeout_sec))
    watcher = asyncio.ensure_future(_wait_disconnect(is_disconnected))
    try:
        done, _ = await asyncio.wait({ocr, watcher}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        watcher.cancel()
    if ocr not in done:
        ocr.cancel()
        await _report_failure(repo, recpt_sn, ReceiptStatus.CANCELED)
        raise AppError("OCR_CANCELED", 400, "영수증 분석을 취소했습니다.")
    try:
        return ocr.result()
    except TimeoutError:
        await _report_failure(repo, recpt_sn, ReceiptStatus.TIMEOUT)
        raise _timeout_error() from None
    except OcrApiError:
        await _report_failure(repo, recpt_sn, ReceiptStatus.API_ERROR)
        raise _api_error() from None


async def _report_failure(repo: ReceiptRepository, recpt_sn: int, status: ReceiptStatus) -> None:
    # 실패·취소 보고 실패에도 원래 오류(시간 초과·API 오류·취소) 유지
    try:
        await repo.report_result(recpt_sn, status, None)
    except (AppError, BackendError):
        logger.warning("Java 영수증 상태 보고 실패: recptSn=%d, %s", recpt_sn, status)


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
