from datetime import date, datetime

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _Camel(BaseModel):
    # JSON = 백엔드 DTO와 같은 camelCase, Python 속성 = snake_case
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class DailyValue(_Camel):
    # DAILY_HLTH_RCD 한 건 : 체중·식사량·음수량·산책(분)
    ymd: date
    rcd_nvl: float | None = None


class StoolValue(_Camel):
    # DAILY_HLTH_RCD 배변상태(HLTC0017) 한 건
    ymd: date
    crsd_stts_cd_nm: str | None = None


class InspectionOutOfRange(_Camel):
    # INSP_NVL : 가장 최근 검진의 참고 범위 밖 항목
    insp_artcl_nm: str | None = None
    rslt_nvl: float | None = None
    unit_nm: str | None = None
    ref_llmt_nvl: float | None = None
    ref_uplmt_nvl: float | None = None


class HealthReportInput(_Camel):
    # FN-MAN-006 : 분석 입력 (최근 14일, Java가 모아 준다)
    pet_nm: str | None = None
    pet_se_cd: str | None = None
    vrty_nm: str | None = None
    age_mm: int | None = None
    nutr_yn: bool | None = None
    goal_bdwg: float | None = None
    weights: list[DailyValue] = []
    meals: list[DailyValue] = []
    waters: list[DailyValue] = []
    walks: list[DailyValue] = []
    stools: list[StoolValue] = []
    latest_ckup_ymd: date | None = None
    insp_out_of_range: list[InspectionOutOfRange] = []


class SavedReport(_Camel):
    # Java에 저장된 최근 리포트
    rpt_ttl: str
    tips: list[str] = []
    input_hash: str
    crt_dt: datetime | None = None


class HealthReportSource(_Camel):
    # Java GET /internal/ai/pets/{petSn}/health-report-input 응답 data
    input: HealthReportInput
    report: SavedReport | None = None
    rfrsh_psbl_yn: bool = False
    auto_rgnr_psbl_yn: bool = True


class HealthReportSaveRequest(_Camel):
    # Java PUT /internal/ai/pets/{petSn}/health-report 요청
    base_ymd: date
    rpt_ttl: str
    tips: list[str]
    input_hash: str
    rfrsh_yn: bool


class HealthReportResponse(_Camel):
    # React GET /ai/pets/{petSn}/health-report 응답 data
    pet_sn: int
    base_ymd: date
    rpt_ttl: str
    tips: list[str]
    notice: str
    data_lack_yn: bool
    stale_yn: bool
    rfrsh_psbl_yn: bool
    crt_dt: datetime | None = None
