import asyncio
from datetime import date

from app.core.backend import external_error
from app.healthreport.clients import HealthReportApiError, ReportOutput
from app.healthreport.schemas import (
    DailyValue,
    HealthReportInput,
    HealthReportSaveRequest,
    HealthReportSource,
    InspectionOutOfRange,
    StoolValue,
)

BASE_YMD = date(2026, 11, 4)


def sample_input(weight: float = 5.2) -> HealthReportInput:
    return HealthReportInput(
        pet_nm="나비",
        pet_se_cd="CAT",
        vrty_nm="코리안숏헤어",
        age_mm=38,
        nutr_yn=True,
        goal_bdwg=5.0,
        weights=[
            DailyValue(ymd=date(2026, 10, 28), rcd_nvl=5.3),
            DailyValue(ymd=date(2026, 11, 3), rcd_nvl=weight),
        ],
        meals=[DailyValue(ymd=date(2026, 11, 3), rcd_nvl=80)],
        waters=[DailyValue(ymd=date(2026, 11, 3), rcd_nvl=200)],
        walks=[],
        stools=[StoolValue(ymd=date(2026, 11, 3), crsd_stts_cd_nm="정상")],
        latest_ckup_ymd=date(2026, 10, 1),
        insp_out_of_range=[
            InspectionOutOfRange(
                insp_artcl_nm="ALT", rslt_nvl=120, unit_nm="U/L", ref_llmt_nvl=10, ref_uplmt_nvl=100
            )
        ],
    )


class FakeRepository:
    """Java 리포트 내부 API 흉내. source를 돌려주고 save 요청을 saves에 기록"""

    def __init__(self, source: HealthReportSource, save_fails: bool = False) -> None:
        self.source = source
        self.save_fails = save_fails
        self.gets: list[tuple[int, date]] = []
        self.saves: list[tuple[int, HealthReportSaveRequest]] = []

    async def get_source(self, pet_sn: int, base_ymd: date) -> HealthReportSource:
        self.gets.append((pet_sn, base_ymd))
        return self.source

    async def save(self, pet_sn: int, request: HealthReportSaveRequest) -> None:
        self.saves.append((pet_sn, request))
        if self.save_fails:
            raise external_error()


class FakeGenerator:
    """behavior: ok·error·slow. 받은 입력은 calls에 기록"""

    def __init__(self, behavior: str = "ok") -> None:
        self.behavior = behavior
        self.calls: list[HealthReportInput] = []

    async def generate(self, data: HealthReportInput) -> ReportOutput:
        self.calls.append(data)
        if self.behavior == "slow":
            await asyncio.sleep(1)
        if self.behavior == "error":
            raise HealthReportApiError("boom")
        return ReportOutput(
            title="물을 조금 더 마시면 좋아요",
            tips=["음수량이 평소보다 적어요", "ALT 수치는 수의사와 상담해 보세요"],
        )
