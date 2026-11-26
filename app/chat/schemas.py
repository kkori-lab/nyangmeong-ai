from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)
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
    # 등록 카드의 칸. 이름은 SCHDL·CARE_ARTCL 컬럼, 코드는 공통코드 그대로
    # Python은 초안 미저장 : React가 가장 최근 카드를 다음 메시지에 반환
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
    # 같은 이름 반려동물을 칩에서 구별해 보여 줄 때(FN-AIM-012-04), 모르면 칸 없음
    pet_se_nm: str | None = Field(default=None, exclude_if=lambda value: value is None)
    vrty_nm: str | None = Field(default=None, exclude_if=lambda value: value is None)


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


class ActionDraft(_Camel):
    # 2단계 쓰기 : React가 돌려보낸 가장 최근 확인 카드의 도구와 input(Java 칸 이름)
    tool: str = Field(min_length=1, max_length=64)
    values: dict[str, Any] = Field(default_factory=dict, alias="input")
    # 삭제 카드의 대상 글(ActionCard.targetText 그대로, 2026-11-25)
    target_text: str | None = Field(default=None, max_length=200)


class MessageSendRequest(_Camel):
    # 없으면 저장 없이 방의 마지막 사용자 메시지에 답변 (첫 메시지 직후·다시 시도·다시 생성)
    cnvrs_cn: str | None = Field(default=None, min_length=1, max_length=MAX_MESSAGE_LENGTH)
    # FN-AIM-012-05·10 : 가장 최근 카드(되물음 포함). 있으면 이 메시지로 칸 채움·수정
    draft: RegisterDraft | None = None
    # 가장 최근 확인 카드(ACTION). 같은 도구를 다시 고르면 이 input을 바탕으로 칸 채움·수정
    action: ActionDraft | None = None
    # 한 메시지 여러 명령 ② : 가장 최근 확인 카드 목록(최대 3). 있으면 action 대신 씀
    actions: list[ActionDraft] | None = Field(default=None, max_length=3)

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
    # FN-AIM-002-07 : false면 미완료 답변 (AI 컨텍스트에서 제외)
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
    ACTION = "ACTION"  # 쓰기 확인 카드(SCR-AIM-012 2단계)


class MoveType(StrEnum):
    PAGE = "PAGE"  # 본창 이동
    MODAL = "MODAL"  # 본창에서 모달 열기(SCR-COM-009)


class RouteItem(BaseModel):
    # Java GET /internal/ai/routes 응답 원소(AiRouteResponse, 백엔드 c0bf1f2)
    ai_rout_mpng_sn: int = Field(alias="aiRoutMpngSn")
    trgt_scrn_nm: str = Field(alias="trgtScrnNm")
    scrn_id: str | None = Field(default=None, alias="scrnId")
    scrn_param_cn: str | None = Field(default=None, alias="scrnParamCn")
    inst_kwrds: list[str] = Field(default_factory=list, alias="instKwrds")
    mvmn_mthd_cd: str = Field(alias="mvmnMthdCd")
    rprs_chip_yn: bool = Field(default=False, alias="rprsChipYn")
    prrt_seq: int = Field(alias="prrtSeq")


class Intent(_Camel):
    kind: IntentKind
    # ROUTE일 때만. 화면 ID → 프론트 경로 변환은 프론트 담당
    scr_id: str | None = None
    scr_nm: str | None = None
    param: str | None = None
    move_type: MoveType | None = None


class ActionCode(_Camel):
    cd: str
    nm: str


class ActionItemParam(_Camel):
    """확인 카드 칸 규칙 : 배열 항목 칸(in 없음). 요청 칸은 ActionParam"""

    type: str
    required: bool = False
    group: str | None = None
    codes: list[ActionCode] | None = None
    max_length: int | None = None
    min_value: int | None = Field(default=None, alias="min")
    max_value: int | None = Field(default=None, alias="max")
    positive: bool | None = None
    pattern: str | None = None
    # 배열 칸(type array) : 항목 칸 규칙·최소 항목 수
    items: dict[str, "ActionItemParam"] | None = None
    min_items: int | None = None
    # "uuid" : React가 [확인] 때 카드 하나에 한 번 만든다
    generated: str | None = None


class ActionParam(ActionItemParam):
    """확인 카드 칸 : Java 도구 목록(GET /internal/ai/tools)의 칸 그대로"""

    loc: str = Field(alias="in")


class ActionRule(_Camel):
    # requiredIf : when 칸이 equals면 field 칸 필수
    field: str
    when: str
    equals: str


class ActionCall(_Camel):
    method: str
    path: str
    # 파일 칸이 있는 도구(관찰 기록 추가) : multipart/form-data. 없으면 키를 내지 않는다
    content_type: str | None = None

    @model_serializer(mode="wrap")
    def _drop_empty_type(self, handler):
        data = handler(self)
        if self.content_type is None:
            data.pop("contentType", None)
            data.pop("content_type", None)
        return data


class ActionCard(_Camel):
    """[확인 카드(2단계 쓰기)]
    - React가 params로 폼을 그리고 [확인] 때 call로 Java 공개 API 실행
    - Python은 카드·실행 결과 미저장 : 결과 요약만 action-result로 저장"""

    tool: str
    domain: str
    # 도구 표시 이름(data/tool_prompts.yaml label)
    label: str | None = None
    call: ActionCall
    params: dict[str, ActionParam]
    rules: list[ActionRule] = []
    # Python이 검증한 값(Java 칸 이름). 경로 칸(petSn 등)도 여기
    values: dict[str, Any] = Field(default_factory=dict, alias="input")
    # 빈 필수·조건부 필수 칸(Java 칸 이름)
    missing: list[str] = []
    # 반려동물을 정하지 못했을 때 이름 칩(FN-AIM-012-04 규칙)
    pet_choices: list[PetChoice] = []
    pet_nm: str | None = None
    # FN-AIM-012-08 : 같은 이름 케어 항목 안내 문구(케어 항목 등록), 없으면 null
    notice: str | None = None
    # 삭제 카드(call.method DELETE)의 대상 글 : 이 턴 READ 결과 행으로 Python이 만듦 (2026-11-25)
    # React는 보여 주고 다음 메시지·action-result에 그대로 돌려보낸다. 없으면 null
    target_text: str | None = None


class StepEvent(_Camel):
    # SSE step 이벤트(에이전트 루프 진행, 저장 안 함). kind : READ(읽기 직전)·CARD(카드 만들 때)
    tool: str
    label: str
    kind: Literal["READ", "CARD"]


class AgentPending(_Camel):
    # done.pending (에이전트 ③, 2026-11-26) : 카드 실행 뒤 agent-continue로 이어 갈 서명 토큰
    agent_token: str
    # 이 멈춤의 카드 수
    cards: int


class AnswerDone(_Camel):
    # SSE done 이벤트. message는 저장된 AI 메시지(없거나 저장 실패면 null)
    message: ConversationMessage | None = None
    # FN-AIM-002-04 : 연관 바로가기(ROUTE 모양), 미저장
    shortcut: Intent | None = None
    # REGISTER : 미리보기 카드나 되물음(FN-AIM-012-05~08), 카드 미저장
    card: RegisterCard | None = None
    # ACTION : 확인 카드. READ 결과를 본 뒤 고른 쓰기 도구면 SEARCH 답변에도 붙음
    action: ActionCard | None = None
    # 한 메시지 여러 명령 ② : 확인 카드 목록(최대 3). action은 첫 카드(프론트 전환 뒤 삭제)
    actions: list[ActionCard] | None = None
    # 돌려받은 카드 + 확인 말("등록해 줘") : React가 action의 call을 바로 실행 (2026-11-13)
    execute: bool = False
    # 에이전트 ③ : 실행 결과를 보고 이어 갈 수 있을 때만(없으면 null, 지금 흐름)
    pending: AgentPending | None = None


class StreamError(_Camel):
    # SSE error 이벤트 : 첫 글자 전 실패(FN-AIM-002-07)
    code: str
    message: str


class RegisterResult(StrEnum):
    REGISTERED = "REGISTERED"
    CANCELED = "CANCELED"


class RegisterResultRequest(_Camel):
    # FN-AIM-012-11·16 : 카드 결과 텍스트 요약 저장
    result: RegisterResult
    card: RegisterCard


class ActionStatus(StrEnum):
    DONE = "DONE"  # [확인] 뒤 Java 실행 성공
    CANCELED = "CANCELED"  # [취소]
    FAILED = "FAILED"  # Java 실행 실패


class ActionFieldError(_Camel):
    # Java 400 data의 한 줄 {field, message} : Python은 field만 쓴다(message는 Java 문구라 안 보임)
    field: str = Field(min_length=1, max_length=200)
    message: str | None = Field(default=None, max_length=1000)


class ActionResultRequest(_Camel):
    # 확인 카드 결과 텍스트 요약 저장 : 요약 글은 Python이 도구 표시 이름과 input으로 만듦
    tool: str = Field(min_length=1, max_length=64)
    status: ActionStatus
    values: dict[str, Any] = Field(default_factory=dict, alias="input")
    # FAILED 때 Java 400 칸 오류(선택, 2026-11-25) : 저장 글에 칸 표시 이름으로 "다시 확인"
    errors: list[ActionFieldError] = Field(default_factory=list, max_length=50)
    # 삭제 카드의 대상 글(ActionCard.targetText 그대로, 2026-11-25) : 결과 요약에 씀
    target_text: str | None = Field(default=None, max_length=200)


# agent-continue results 최대 수 : 지금 카드 최대 3장(ACTION_MAX_CARDS), 8장은 프론트 합의 뒤
AGENT_RESULTS_MAX = 3
# agentToken 길이 상한 : 서명 토큰 48KB(agentstate.MAX_BYTES)
AGENT_TOKEN_MAX = 48 * 1024


class AgentResult(_Camel):
    # 이 멈춤의 카드 하나의 실행 결과 (docs/design/agent.md 5절)
    tool: str = Field(min_length=1, max_length=64)
    status: ActionStatus
    # FAILED 때 Java 400 data [{field, message}] (ActionResultRequest errors와 같음)
    errors: list[ActionFieldError] = Field(default_factory=list, max_length=50)
    # DONE 때 Java 성공 응답 data(선택) : 새 번호(…Sn 정수 칸)만 이 턴 번호 칸 값으로 씀
    data: dict[str, Any] | None = None


class AgentContinueRequest(_Camel):
    # POST /ai/conversations/{방}/agent-continue (에이전트 ③, 2026-11-26)
    agent_token: str = Field(min_length=1, max_length=AGENT_TOKEN_MAX)
    results: list[AgentResult] = Field(min_length=1, max_length=AGENT_RESULTS_MAX)


class ReceiptResult(StrEnum):
    RECOGNIZED = "RECOGNIZED"  # 인식·부분 인식(결과 카드)
    FAILED = "FAILED"  # 인식 실패(추출 0건)
    ERROR = "ERROR"  # 일시 오류(API 오류·15초 초과)
    CANCELED = "CANCELED"  # 분석 중 [취소]


class ReceiptResultRequest(_Camel):
    # FN-AIM-013-02·09 : 영수증 분석(/ai/receipts) 후 함께 보낸 텍스트·결과 요약 저장
    result: ReceiptResult
    cnvrs_cn: str | None = Field(default=None, min_length=1, max_length=MAX_MESSAGE_LENGTH)
    # ReceiptOcrResponse와 같은 이름. RECOGNIZED일 때만 쓴다
    hsptl_nm: str | None = None
    ckup_ymd: date | None = None
    recpt_amt: int | None = None

    @field_validator("cnvrs_cn")
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("공백만 입력할 수 없습니다.")
        return value


class ImageIntentKind(StrEnum):
    """첨부 사진 용도 (SCR-AIM-013, 메인 검색창 공용)"""

    CHARACTER = "CHARACTER"  # 반려동물 사진 -> 캐릭터 만들기
    MEDICAL_RECEIPT = "MEDICAL_RECEIPT"  # 동물병원 영수증 -> 영수증 분석
    EXPENSE_RECEIPT = "EXPENSE_RECEIPT"  # 그 밖의 영수증 -> 가계부
    SKIN = "SKIN"  # 반려동물 피부·털 문제 사진 -> 피부 병변 분석 (2026-11-24)
    EYE = "EYE"  # 반려동물 눈 문제 사진 -> 안구 질환 분석 (2026-11-24)
    CHECKUP_PDF = "CHECKUP_PDF"  # PDF -> 검사결과지 분석 (판단 LLM 미호출, 2026-11-23)
    ASK = "ASK"  # 모름 -> React가 칩으로 되물음


class ImageIntentJudgement(BaseModel):
    """사진 용도 판단 결과 (내부용) : ASK 안내 문구를 이유별로 고르기 위함 (2026-11-24)
    - character_photo_unfit : 글이 캐릭터를 원하지만 사진에 반려동물 얼굴·몸이 안 보여 ASK"""

    kind: ImageIntentKind
    character_photo_unfit: bool = False


class ImageIntentResult(_Camel):
    """POST /ai/image-intent 응답 : 판단 + 사진 턴을 저장한 방·메시지 (2026-11-13)
    - 방 번호를 안 주면 Python이 방을 만듦(메인 첫 사진). messages는 저장 순서"""

    kind: ImageIntentKind
    ai_cnvrs_room_sn: int
    messages: list[ConversationMessage]


class CheckupResult(StrEnum):
    RECOGNIZED = "RECOGNIZED"  # 분석 성공(인식 0건 포함)
    NOT_LAB_RESULT = "NOT_LAB_RESULT"  # 검사결과지가 아님(lab-results 422)
    ERROR = "ERROR"  # 일시 오류(시간 초과·API 오류)
    CANCELED = "CANCELED"  # 분석 중 [취소]


class CheckupLabItem(_Camel):
    # POST /ai/checkups/lab-results LabResultItem 그대로(Java InspectionValueItemRequest 칸 이름)
    insp_artcl_cd: str | None = None
    insp_artcl_drct_inpt_nm: str | None = None
    rslt_nvl: float | None = None
    unit_nm: str | None = None
    ref_llmt_nvl: float | None = None
    ref_uplmt_nvl: float | None = None


class CheckupCardRequest(_Camel):
    """대화창 검사결과지 PDF 분석 뒤 결과 요약 저장 + 검사 수치 저장 확인 카드 (2026-11-23)
    - React가 lab-results 응답을 그대로 보낸다. RECOGNIZED일 때만 items를 쓴다"""

    result: CheckupResult
    # 대상 반려동물 : 영수증처럼 React가 정함(FN-AIM-013-03)
    pet_sn: int = Field(ge=1)
    items: list[CheckupLabItem] = Field(default_factory=list, max_length=100)
    excluded_artcl_nms: list[str] = Field(default_factory=list, max_length=100)


class CheckupNoCardReason(StrEnum):
    # 카드가 없는 이유 중 프론트가 다음 흐름을 여는 것 (2026-11-24)
    NO_CHECKUP = "NO_CHECKUP"  # 그 아이 검진기록 0건 : 프론트가 검진기록 추가로 잇는다


class LesionKind(StrEnum):
    SKIN = "SKIN"  # POST /ai/skin-analyses
    EYE = "EYE"  # POST /ai/eye-analyses


class LesionResult(StrEnum):
    ANALYZED = "ANALYZED"
    NOT_PET_SKIN = "NOT_PET_SKIN"
    NOT_PET_EYE = "NOT_PET_EYE"
    UNCLEAR = "UNCLEAR"
    ERROR = "ERROR"  # 일시 오류(시간 초과·API 오류) : React가 남김
    CANCELED = "CANCELED"  # 분석 중 [취소] : React가 남김


class LesionGrade(StrEnum):
    OBSERVE = "OBSERVE"
    VISIT = "VISIT"
    URGENT = "URGENT"


class LesionConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"


class LesionFinding(_Camel):
    # skin-analyses·eye-analyses findings 그대로
    lesion_cd: str = Field(min_length=1, max_length=40)
    lesion_nm: str = Field(min_length=1, max_length=40)
    cnfdnc: LesionConfidence


class LesionCardRequest(_Camel):
    """대화창 피부·눈 분석 뒤 결과 요약 저장 + 지속 관찰 항목 확인 카드 (2026-11-24)
    - React가 분석 응답을 그대로 보낸다 + kind·petSn"""

    kind: LesionKind
    pet_sn: int = Field(ge=1)
    rslt: LesionResult
    grade: LesionGrade | None = None
    findings: list[LesionFinding] = Field(default_factory=list, max_length=3)
    guide: list[str] = Field(default_factory=list, max_length=10)
    notice: str | None = Field(None, max_length=500)
    rule_version: str | None = Field(None, max_length=40)

    @model_validator(mode="after")
    def _graded(self) -> "LesionCardRequest":
        # 판정 결과에는 등급 필수(분석 응답 규칙)
        if self.rslt is LesionResult.ANALYZED and self.grade is None:
            raise ValueError("ANALYZED에는 grade가 필요합니다.")
        return self


class LesionCardResult(_Camel):
    # 저장한 AI 메시지와 확인 카드(없으면 null). 카드는 done.action과 같은 모양, 저장 안 함
    messages: list[ConversationMessage]
    action: ActionCard | None = None


class CheckupCardResult(_Camel):
    # 저장한 AI 메시지와 확인 카드(없으면 null). 카드는 done.action과 같은 모양, 저장 안 함
    messages: list[ConversationMessage]
    action: ActionCard | None = None
    # 카드가 없는 이유. 검진기록 0건일 때만 NO_CHECKUP, 그 밖은 null
    no_card_reason: CheckupNoCardReason | None = None
