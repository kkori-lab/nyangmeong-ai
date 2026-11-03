from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# PETG01 공통코드 : 강아지·고양이 (백엔드 db/..._insert_com_cd 와 같은 값)
PetSeCd = Literal["PETC0001", "PETC0002"]

# FN-MYP-010-17 : 백엔드 CharacterSpec 과 같은 규격
CANVAS_SIZE = 512
FACE_X, FACE_Y, FACE_W, FACE_H = 128, 64, 256, 256


class CharacterCreateResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    char_crt_job_sn: int


class CharacterPreviewRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    # FN-MYP-011-01 : 안 산 아이템도 입혀 봄 -> 보유 번호가 아닌 ITEM_SN
    item_sns: list[int]


# FN-ADM-070-02 : 관리자 아이템 등록 보조
ITEM_NM_MAX = 50
BAKE_HINT_INPUT_MAX = 300


class ItemBakeHintResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    bake_hint: str


class ItemTrialRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    pixel_char_sn: int
    regn_cd: str
    bake_hint: str = Field(min_length=1, max_length=BAKE_HINT_INPUT_MAX)


class ItemBakeResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    item_sn: int
    target_cnt: int
