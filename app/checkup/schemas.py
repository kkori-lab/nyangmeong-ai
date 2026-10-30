from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _Camel(BaseModel):
    # JSON = 백엔드 DTO와 같은 camelCase, Python 속성 = snake_case
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class LabResultItem(_Camel):
    # 필드 이름은 초안 : 건강기록 백엔드의 검사 수치 저장 DTO와 맞춘다
    insp_artcl_nm: str
    rslt_vl: str | None = None
    unit_nm: str | None = None
    ref_min_vl: str | None = None
    ref_max_vl: str | None = None
    blood_yn: str = "Y"


class LabResultAnalyzeResponse(_Camel):
    items: list[LabResultItem] = []
