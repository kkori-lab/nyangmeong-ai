from datetime import date

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _Camel(BaseModel):
    # JSON = 백엔드 DTO와 같은 camelCase, Python 속성 = snake_case
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Line(_Camel):
    item_nm: str | None = None
    item_amt: int | None = None


class Drug(_Camel):
    mdcn_nm: str | None = None
    mdcn_days: int | None = None
    mdcn_usage: str | None = None
    mdcn_amt: int | None = None


class Section(_Camel):
    section_nm: str | None = None
    sbttl_amt: int | None = None
    dscnt_amt: int | None = None
    items: list[Line] = []
    drugs: list[Drug] = []


class ReceiptOcrResponse(_Camel):
    hsptl_nm: str | None = None
    # FN-MYP-031-03 : 사용처(영수증의 상호), 카테고리 추정(MYPG05). 모든 출처에서 채움
    expnd_plcus_nm: str | None = None
    expnd_clsf_cd: str | None = None
    # 건강 일지는 진료일, 가계부는 결제일
    ckup_ymd: date | None = None
    recpt_amt: int | None = None
    btm_dscnt_amt: int | None = None
    sections: list[Section] = []


class ReceiptAnalyzeResponse(_Camel):
    recpt_sn: int
    ocr: ReceiptOcrResponse
