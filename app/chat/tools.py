"""AI 매니저 도구(tool calling 1단계 실험, docs/design/tool-calling.md 3-1·3-5절)

- 도구 설명 정본 : 모델 docstring -> 도구 description, Field description -> 인자 설명
- LLM은 도구와 인자만 고름 -> 인자는 여기서 다시 검증(매핑표·안내서·공통코드)
"""

from dataclasses import dataclass
from functools import lru_cache

from pydantic import BaseModel, Field, ValidationError

from app.chat import rules

NAVIGATE = "navigate"
SEARCH_GUIDE = "search_guide"
DRAFT_SCHEDULE = "draft_schedule"
DRAFT_CARE_ITEM = "draft_care_item"
DECLINE = "decline"
REGISTER_TOOLS = frozenset({DRAFT_SCHEDULE, DRAFT_CARE_ITEM})


class Navigate(BaseModel):
    """본창을 앱의 한 화면으로 옮긴다. 대화창에서는 아무것도 저장하지 않는다.

    쓸 때: 화면을 보거나 그 화면으로 가고 싶다는 말, 그 화면에 있는 내 기록을 확인하려는 말.
      예) "가계부 보여 줘", "실종센터 가자", "이번 달 병원비 얼마 나왔어?"
    쓰지 않을 때: 기능의 위치·사용 방법을 묻는 말("캐릭터 어디서 만들어?", "알림 어떻게 꺼?")은
      search_guide. 날짜·주기가 있는 일정·케어 항목 등록 요청은 draft_schedule·draft_care_item.
    인자: screen_num은 시스템의 화면 목록 번호 그대로. 목록에 없는 화면은 고르지 않는다.
    말하는 법: 글을 쓰지 않는다. 이동 안내 문구는 서버가 붙인다.
    """

    screen_num: int = Field(description="화면 목록의 번호")


class SearchGuide(BaseModel):
    """이 앱 사용법 안내서에서 기능의 위치와 사용 순서를 꺼내 와 답한다. 아무것도 저장하지 않는다.

    쓸 때: 앱 기능이 어디 있는지, 어떻게 쓰는지 묻는 말.
      예) "캐릭터 어디서 만들어?", "가족 초대 어떻게 해?", "알림 어디서 꺼?"
    쓰지 않을 때: 화면으로 가자는 말("가계부 열어 줘")은 navigate. 반려동물 건강·생활 지식 질문은
      도구 없이 바로 답한다. 이 앱·반려동물과 관계없는 질문은 decline.
    인자: chunk_id는 안내서 목차에서 가장 맞는 번호 하나. 맞는 것이 없으면 비운다(지어내지 않는다).
    말하는 법: 안내서 내용만 근거로, 메뉴·버튼 이름은 [ ] 안의 글자 그대로 쓴다.
    """

    chunk_id: str | None = Field(None, description="안내서 목차의 번호. 맞는 것이 없으면 비운다")


class DraftSchedule(BaseModel):
    """날짜가 정해진 한 번짜리 일정(병원 예약·미용·투약 등)의 등록 카드를 대화창에 띄운다.
    회원이 카드에서 [등록]을 누르기 전에는 아무것도 저장하지 않는다.

    쓸 때: 날짜·시간이 있는 한 번짜리 일을 등록·예약·잡아 달라는 말.
      예) "다음 주 화요일 3시 병원 예약 등록해 줘", "토요일에 미용 잡아줘"
    쓰지 않을 때: 매일·매주·한 달마다처럼 주기가 있는 반복 일은 draft_care_item.
      일정을 어디서 등록하는지 묻는 말("일정 어디서 등록해?")은 search_guide.
    인자: 회원이 말하지 않은 칸은 비운다(지어내지 않는다).
      날짜는 시스템의 오늘 날짜 기준으로 계산한다.
      반려동물은 고르지 않는다(서버가 문장과 대화의 반려동물로 정한다).
    말하는 법: 글을 쓰지 않는다. 카드와 되물음 문구는 서버가 만든다.
    """

    schdl_knd_cd: str | None = Field(
        None,
        description="일정 종류: HLTC0057 병원, HLTC0058 미용·목욕, HLTC0059 케어·투약, "
        "HLTC0060 기타",
    )
    schdl_ymd: str | None = Field(None, description="일정 날짜 YYYY-MM-DD")
    schdl_tm: str | None = Field(None, description="일정 시간 24시간 HH:MM. 말하지 않았으면 비운다")
    ckup_type_cd: str | None = Field(
        None,
        description="병원일 때 검진유형: HLTC0001 정기검진, HLTC0002 예방접종, HLTC0003 질병진료, "
        "HLTC0004 검사, HLTC0005 기타 진료",
    )
    hsptl_nm: str | None = Field(None, description="병원 이름. 말하지 않았으면 비운다")
    schdl_nm: str | None = Field(None, description="병원이 아닌 일정의 이름(40자 이내)")


class DraftCareItem(BaseModel):
    """매일 또는 주기마다 반복하는 케어 항목(산책·발톱 깎기·예방약 등)의 등록 카드를
    대화창에 띄운다.
    회원이 카드에서 [등록]을 누르기 전에는 아무것도 저장하지 않는다.

    쓸 때: 매일·매주·2주마다·한 달마다·n일마다처럼 반복하는 일을 넣어 달라는 말.
      예) "2주마다 발톱 깎기 넣어줘", "매일 산책 추가해 줘", "한 달마다 심장사상충약 등록해 줘"
    쓰지 않을 때: 주기 없이 날짜가 정해진 한 번짜리 일은 draft_schedule.
    인자: 회원이 말하지 않은 칸은 비운다. 마지막으로 한 날은 오늘 날짜 기준으로 계산한다.
    말하는 법: 글을 쓰지 않는다. 카드와 되물음 문구는 서버가 만든다.
    """

    care_artcl_nm: str | None = Field(None, description="케어 항목 이름(40자 이내)")
    care_zone_cd: str = Field(description="HLTC0036 매일 / HLTC0037 주기")
    care_cycle_cd: str | None = Field(
        None,
        description="주기일 때: HLTC0038 1주, HLTC0039 2주, HLTC0040 한달, HLTC0041 1년, "
        "HLTC0042 직접입력(cycle_days에 n일)",
    )
    cycle_days: int | None = Field(None, description="직접입력 주기의 날 수")
    last_cmptn_ymd: str | None = Field(None, description="마지막으로 한 날 YYYY-MM-DD")


class Decline(BaseModel):
    """도와줄 수 없는 입력에 정해진 안내 문구를 보낸다. 문구는 서버가 붙인다.

    쓸 때: 반려동물·이 앱과 관계없는 질문(요리·주식·코딩·집 가계부 쓰는 법 등)은 unclear false.
      뜻 없는 글자, 욕설, 무엇을 원하는지 알 수 없는 입력은 unclear true.
    쓰지 않을 때: 반려동물 건강·생활 질문과 이 앱의 화면·기능 질문은 범위 안이다.
    말하는 법: 글을 쓰지 않는다.
    """

    unclear: bool = Field(
        False, description="뜻을 알 수 없는 입력이면 true, 범위 밖 질문이면 false"
    )


TOOL_MODELS: dict[str, type[BaseModel]] = {
    NAVIGATE: Navigate,
    SEARCH_GUIDE: SearchGuide,
    DRAFT_SCHEDULE: DraftSchedule,
    DRAFT_CARE_ITEM: DraftCareItem,
    DECLINE: Decline,
}


def _schema(model: type[BaseModel]) -> dict:
    # 설명은 description 칸에만 : 스키마 안 제목·설명 중복 제거
    schema = model.model_json_schema()
    schema.pop("title", None)
    schema.pop("description", None)
    for prop in schema.get("properties", {}).values():
        prop.pop("title", None)
        prop.pop("default", None)
    return schema


def _description(model: type[BaseModel]) -> str:
    lines = (model.__doc__ or "").strip().splitlines()
    return "\n".join(line.strip() for line in lines)


@lru_cache
def tool_definitions() -> tuple[dict, ...]:
    # 고정 내용 : 매 요청 같은 정의라 system과 함께 캐시
    defs = []
    for name, model in TOOL_MODELS.items():
        schema = _schema(model)
        props = schema.get("properties", {})
        if name == NAVIGATE:
            props["screen_num"]["enum"] = [row.no for row in _routable_rows()]
        if name == SEARCH_GUIDE:
            props["chunk_id"]["anyOf"] = [
                {"type": "string", "enum": [chunk.id for chunk in rules.guide_chunks()]},
                {"type": "null"},
            ]
        defs.append({"name": name, "description": _description(model), "input_schema": schema})
    return tuple(defs)


def _routable_rows() -> list[rules.RouteRow]:
    return [row for row in rules.routing_table() if row.routable]


def screen_list() -> str:
    # 시스템 프롬프트의 화면 목록 : 번호. 화면명: 키워드
    return "\n".join(f"{row.no}. {row.name}: {', '.join(row.keywords)}" for row in _routable_rows())


def route_row(call: "ToolCall") -> rules.RouteRow | None:
    # FN-AIM-004-08 : 매핑표의 라우팅 가능 행만 인정
    if not isinstance(call.args, Navigate):
        return None
    return next((row for row in _routable_rows() if row.no == call.args.screen_num), None)


@dataclass(frozen=True)
class ToolCall:
    """LLM이 고른 도구와 검증한 인자. 검증 실패면 args None"""

    name: str
    args: BaseModel | None
    # Anthropic tool_use 블록 id·원 인자 : 서버 도구의 tool_result 응답용
    use_id: str = ""
    raw: dict | None = None


def parse(name: str, raw: dict, use_id: str = "") -> ToolCall:
    model = TOOL_MODELS.get(name)
    if model is None:
        return ToolCall(name, None, use_id, raw)
    try:
        args = model.model_validate(raw)
    except ValidationError:
        return ToolCall(name, None, use_id, raw)
    call = ToolCall(name, args, use_id, raw)
    if name == NAVIGATE and route_row(call) is None:
        return ToolCall(name, None, use_id, raw)
    return call


def register_values(call: ToolCall) -> dict:
    # FN-AIM-012-03 : 도구 인자도 AI 출력이라 같은 재검증, 틀린 칸은 비움
    if call.name not in REGISTER_TOOLS or call.args is None:
        return {}
    return rules.clean_ai_fields(call.args.model_dump(exclude_none=True)).values()


def guide_ids(call: ToolCall, text: str) -> list[str]:
    # FN-AIM-002-02 : LLM이 고른 목차 청크를 앞에, M1 키워드 색인 결과를 뒤에(최대 3개)
    picked = rules.find_guide(call.args.chunk_id) if isinstance(call.args, SearchGuide) else None
    ids = [picked.id] if picked else []
    ids += [chunk_id for chunk_id in rules.search_guide(text) if chunk_id not in ids]
    return ids[: rules.GUIDE_TOP_K]
