from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _Camel(BaseModel):
    # JSON = 백엔드 DTO와 같은 camelCase, Python 속성 = snake_case
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class LabResultItem(_Camel):
    # 백엔드 InspectionAnalysisItem(INSP_NVL 컬럼)과 같은 이름 (registered는 Java·React 결정)
    insp_artcl_cd: str | None = None
    insp_artcl_drct_inpt_nm: str | None = None
    rslt_nvl: float | None = None
    unit_nm: str | None = None
    ref_llmt_nvl: float | None = None
    ref_uplmt_nvl: float | None = None


class LabResultAnalyzeResponse(_Camel):
    items: list[LabResultItem] = []
    excluded_artcl_nms: list[str] = []
