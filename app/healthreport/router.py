from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core import response
from app.core.auth import require_member, require_requested_with
from app.core.config import Settings, get_settings
from app.healthreport import rules, service
from app.healthreport.clients import ReportGenerator, get_report_generator
from app.healthreport.repository import HealthReportRepository, get_health_report_repository

router = APIRouter(prefix="/ai/pets", dependencies=[Depends(require_requested_with)])


def get_base_ymd() -> date:
    # 기준일 = KST 오늘 (테스트에서 바꿔 끼운다)
    return rules.today_kst()


# 인증 먼저 : 쿠키 없는 요청은 키와 무관하게 401
@router.get("/{pet_sn}/health-report", dependencies=[Depends(require_member)])
async def get_health_report(
    pet_sn: int,
    repo: Annotated[HealthReportRepository, Depends(get_health_report_repository)],
    generator: Annotated[ReportGenerator | None, Depends(get_report_generator)],
    base_ymd: Annotated[date, Depends(get_base_ymd)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    result = await service.get_report(
        repo, generator, pet_sn, base_ymd, settings.health_report_timeout_sec
    )
    return response.success(result.model_dump(mode="json", by_alias=True))


@router.post("/{pet_sn}/health-report/refresh", dependencies=[Depends(require_member)])
async def refresh_health_report(
    pet_sn: int,
    repo: Annotated[HealthReportRepository, Depends(get_health_report_repository)],
    generator: Annotated[ReportGenerator | None, Depends(get_report_generator)],
    base_ymd: Annotated[date, Depends(get_base_ymd)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    result = await service.refresh_report(
        repo, generator, pet_sn, base_ymd, settings.health_report_timeout_sec
    )
    return response.success(result.model_dump(mode="json", by_alias=True))
