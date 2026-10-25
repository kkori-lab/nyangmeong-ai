from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

MAX_MESSAGE_LENGTH = 1000


class _Camel(BaseModel):
    # JSON = 백엔드 DTO와 같은 camelCase, Python 속성 = snake_case
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ConversationCreateRequest(_Camel):
    # 펫 태그. 소유권은 Java가 검사하므로 여기서는 구분값으로만 저장
    pet_sn: int | None = Field(default=None, ge=1)
    cnvrs_cn: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)

    @field_validator("cnvrs_cn")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("공백만 입력할 수 없습니다.")
        return value


class ConversationSummary(_Camel):
    ai_cnvrs_room_sn: int
    pet_sn: int | None = None
    cnvrs_ttl: str
    reg_dt: datetime


class ConversationMessage(_Camel):
    ai_cnvrs_msg_sn: int
    role_cd: str
    cnvrs_cn: str
    msg_seq: int
    reg_dt: datetime


class ConversationDetail(ConversationSummary):
    messages: list[ConversationMessage]
