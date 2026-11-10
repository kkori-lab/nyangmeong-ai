import asyncio
import logging
from datetime import date, datetime

from app.core.backend import BackendError, external_error
from app.core.response import AppError
from app.healthreport import rules
from app.healthreport.clients import HealthReportApiError, ReportGenerator
from app.healthreport.repository import HealthReportRepository
from app.healthreport.schemas import (
    HealthReportResponse,
    HealthReportSaveRequest,
    HealthReportSource,
    SavedReport,
)

logger = logging.getLogger(__name__)


async def get_report(
    repo: HealthReportRepository,
    generator: ReportGenerator | None,
    pet_sn: int,
    base_ymd: date,
    timeout_sec: float,
) -> HealthReportResponse:
    """FN-MAN-006 : 입력 해시가 같으면 저장본, 다르면 다시 생성 (자정 갱신도 baseYmd로 같은 규칙)"""
    source = await repo.get_source(pet_sn, base_ymd)
    if not rules.has_data(source.input):
        return _data_lack(pet_sn, base_ymd)
    current_hash = rules.input_hash(base_ymd, source.input)
    saved = source.report
    if saved is not None and saved.input_hash == current_hash:
        return _from_saved(pet_sn, base_ymd, saved, source.rfrsh_psbl_yn, stale=False)
    # 자동 재생성 하루 상한(Java가 셈) 초과 : LLM 없이 저장본을 stale로
    if saved is not None and not source.auto_rgnr_psbl_yn:
        return _from_saved(pet_sn, base_ymd, saved, source.rfrsh_psbl_yn, stale=True)
    return await _generate_and_save(
        repo, generator, pet_sn, base_ymd, source, current_hash, False, timeout_sec
    )


async def refresh_report(
    repo: HealthReportRepository,
    generator: ReportGenerator | None,
    pet_sn: int,
    base_ymd: date,
    timeout_sec: float,
) -> HealthReportResponse:
    """FN-MAN-006 : 새로고침 1일 1회 (입력이 같아도 다시 생성, 횟수 판정은 Java)"""
    source = await repo.get_source(pet_sn, base_ymd)
    if not source.rfrsh_psbl_yn:
        raise AppError(
            "HEALTH_REPORT_REFRESH_LIMIT", 409, "리포트 새로고침은 하루에 한 번만 할 수 있습니다."
        )
    if not rules.has_data(source.input):
        return _data_lack(pet_sn, base_ymd)
    current_hash = rules.input_hash(base_ymd, source.input)
    return await _generate_and_save(
        repo, generator, pet_sn, base_ymd, source, current_hash, True, timeout_sec
    )


async def _generate_and_save(
    repo: HealthReportRepository,
    generator: ReportGenerator | None,
    pet_sn: int,
    base_ymd: date,
    source: HealthReportSource,
    current_hash: str,
    refresh: bool,
    timeout_sec: float,
) -> HealthReportResponse:
    if generator is None:
        raise external_error()
    try:
        output = await asyncio.wait_for(generator.generate(source.input), timeout=timeout_sec)
    except TimeoutError:
        raise AppError(
            "HEALTH_REPORT_TIMEOUT", 504, "건강분석 리포트 생성 시간이 초과되었습니다."
        ) from None
    except HealthReportApiError:
        raise AppError(
            "HEALTH_REPORT_API_ERROR", 502, "건강분석 리포트 생성 중 오류가 발생했습니다."
        ) from None
    title = rules.clip_title(output.title)
    tips = rules.clip_tips(output.tips)
    request = HealthReportSaveRequest(
        base_ymd=base_ymd, rpt_ttl=title, tips=tips, input_hash=current_hash, rfrsh_yn=refresh
    )
    try:
        await repo.save(pet_sn, request)
    except (AppError, BackendError):
        # 저장 실패해도 리포트는 돌려준다 : 다음 조회에서 다시 생성
        logger.warning("건강분석 리포트 저장 실패: petSn=%d", pet_sn)
    return HealthReportResponse(
        pet_sn=pet_sn,
        base_ymd=base_ymd,
        rpt_ttl=title,
        tips=tips,
        notice=rules.NOTICE,
        data_lack_yn=False,
        stale_yn=False,
        rfrsh_psbl_yn=False if refresh else source.rfrsh_psbl_yn,
        crt_dt=datetime.now(rules.KST),
    )


def _from_saved(
    pet_sn: int, base_ymd: date, saved: SavedReport, rfrsh_psbl_yn: bool, stale: bool
) -> HealthReportResponse:
    return HealthReportResponse(
        pet_sn=pet_sn,
        base_ymd=base_ymd,
        rpt_ttl=saved.rpt_ttl,
        tips=saved.tips,
        notice=rules.NOTICE,
        data_lack_yn=False,
        stale_yn=stale,
        rfrsh_psbl_yn=rfrsh_psbl_yn,
        crt_dt=_with_kst(saved.crt_dt),
    )


def _with_kst(value: datetime | None) -> datetime | None:
    # Java crtDt는 LocalDateTime(시간대 없음, KST) : 새로 생성한 응답과 같은 +09:00 꼴로
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=rules.KST)


def _data_lack(pet_sn: int, base_ymd: date) -> HealthReportResponse:
    return HealthReportResponse(
        pet_sn=pet_sn,
        base_ymd=base_ymd,
        rpt_ttl=rules.DATA_LACK_TITLE,
        tips=list(rules.DATA_LACK_TIPS),
        notice=rules.NOTICE,
        data_lack_yn=True,
        stale_yn=False,
        rfrsh_psbl_yn=False,
    )
