from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

MAX_MESSAGE_LENGTH = 1000
# 대화 역할 코드(공통코드 AIMG06)
ROLE_USER = "AIMC0024"
ROLE_AI = "AIMC0025"


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


class CardType(StrEnum):
    SCHEDULE = "SCHEDULE"  # 일정 미리보기 카드(FN-AIM-012-06)
    CARE_ITEM = "CARE_ITEM"  # 케어 항목 미리보기 카드(FN-AIM-012-07)
    ASK = "ASK"  # 필수 칸 되물음(FN-AIM-012-05)


class RegisterDraft(_Camel):
    # 등록 카드의 칸. 이름은 SCHDL·CARE_ARTCL 컬럼, 코드는 공통코드 그대로.
    # Python은 초안을 저장하지 않는다 : React가 가장 최근 카드를 다음 메시지에 돌려보낸다
    pet_sn: int | None = Field(default=None, ge=1)
    schdl_knd_cd: str | None = Field(default=None, max_length=8)  # HLTG19
    schdl_ymd: date | None = None
    # HH:MM. 없으면 시간 미입력(HR_INPT_YN N)
    schdl_tm: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    ckup_type_cd: str | None = Field(default=None, max_length=8)  # HLTG01
    hsptl_nm: str | None = Field(default=None, max_length=80)
    schdl_nm: str | None = Field(default=None, max_length=40)
    memo_cn: str | None = Field(default=None, max_length=500)
    care_artcl_nm: str | None = Field(default=None, max_length=40)
    care_zone_cd: str | None = Field(default=None, max_length=8)  # HLTG13
    care_cycle_cd: str | None = Field(default=None, max_length=8)  # HLTG15
    # 케어주기가 직접입력(HLTC0042)일 때 n일마다
    cycle_days: int | None = Field(default=None, ge=1, le=3650)
    last_cmptn_ymd: date | None = None


class PetChoice(_Camel):
    pet_sn: int
    pet_nm: str


class RegisterCard(RegisterDraft):
    card_type: CardType
    pet_nm: str | None = None
    # ASK에서 반려동물을 정하지 못했을 때 이름 칩(FN-AIM-012-04)
    pet_choices: list[PetChoice] = []
    # ASK일 때 빈 필수 칸(필드 이름)
    missing: list[str] = []
    # CARE_ITEM : 마지막으로 한 날(없으면 오늘) + 주기
    nxtm_prnmnt_ymd: date | None = None
    # FN-AIM-012-08 : 같은 반려동물에 같은 이름의 케어 항목이 있음. notice가 안내 문구
    duplicate_name: bool = False
    notice: str | None = None


class MessageSendRequest(_Camel):
    # 없으면 저장 없이 방의 마지막 사용자 메시지에 답한다(첫 메시지 직후·다시 시도·다시 생성)
    cnvrs_cn: str | None = Field(default=None, min_length=1, max_length=MAX_MESSAGE_LENGTH)
    # FN-AIM-012-05·10 : 가장 최근 카드(되물음 포함). 있으면 이 메시지로 칸을 채우거나 고친다
    draft: RegisterDraft | None = None

    @field_validator("cnvrs_cn")
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
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
    # FN-AIM-002-07 : false면 미완료 답변(AI 컨텍스트에서 뺀다)
    cmptn_yn: bool = True


class ConversationDetail(ConversationSummary):
    messages: list[ConversationMessage]


class IntentKind(StrEnum):
    # FN-AIM-001-05 : 의도 분기 결과. 괄호는 이어지는 화면
    REGISTER = "REGISTER"  # 일정 생성 확인(SCR-AIM-012)
    ROUTE = "ROUTE"  # 페이지 라우팅(SCR-AIM-004)
    SEARCH = "SEARCH"  # 검색 질문/응답(SCR-AIM-002)
    FALLBACK = "FALLBACK"  # 매칭 실패 폴백(SCR-AIM-005)
    RECEIPT = "RECEIPT"  # 영수증 분석(SCR-AIM-013)


class MoveType(StrEnum):
    PAGE = "PAGE"  # 본창 이동
    MODAL = "MODAL"  # 본창에서 모달 열기(SCR-COM-009)


class Intent(_Camel):
    kind: IntentKind
    # ROUTE일 때만. 화면 ID → 프론트 경로 변환은 프론트가 한다
    scr_id: str | None = None
    scr_nm: str | None = None
    param: str | None = None
    move_type: MoveType | None = None


class AnswerDone(_Camel):
    # SSE done 이벤트. message는 저장된 AI 메시지(없거나 저장 실패면 null)
    message: ConversationMessage | None = None
    # FN-AIM-002-04 : 연관 바로가기(ROUTE 모양). 저장하지 않는다
    shortcut: Intent | None = None
    # REGISTER : 미리보기 카드나 되물음(FN-AIM-012-05~08). 카드는 저장하지 않는다
    card: RegisterCard | None = None


class StreamError(_Camel):
    # SSE error 이벤트 : 첫 글자 전 실패(FN-AIM-002-07)
    code: str
    message: str


class RegisterResult(StrEnum):
    REGISTERED = "REGISTERED"
    CANCELED = "CANCELED"


class RegisterResultRequest(_Camel):
    # FN-AIM-012-11·16 : 카드 결과를 텍스트 요약으로 저장한다
    result: RegisterResult
    card: RegisterCard
