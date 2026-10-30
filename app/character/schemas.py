from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

# PETG01 공통코드 : 강아지·고양이 (백엔드 db/..._insert_com_cd 와 같은 값)
PetSeCd = Literal["PETC0001", "PETC0002"]

# FN-MYP-010-17 : 백엔드 CharacterSpec 과 같은 규격
CANVAS_SIZE = 512
FACE_X, FACE_Y, FACE_W, FACE_H = 128, 64, 256, 256


class CharacterCreateResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    # 이름 : Java 작업 테이블 확정 시 맞춤
    chrc_job_sn: int
