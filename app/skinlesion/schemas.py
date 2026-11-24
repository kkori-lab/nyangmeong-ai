from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _Camel(BaseModel):
    # JSON = camelCase, Python 속성 = snake_case
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SkinFinding(_Camel):
    lesion_cd: str
    lesion_nm: str
    cnfdnc: str


class SkinAnalysisResponse(_Camel):
    # docs/api/skinlesion.md SkinAnalysisResponse
    rslt: str
    grade: str | None = None
    findings: list[SkinFinding] = []
    guide: list[str] = []
    notice: str
    rule_version: str
