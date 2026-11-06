"""AI 매니저 도구(docs/design/tool-catalog.md 4절, tool calling 1단계)

- 도구 설명 정본 : data/tool_prompts.yaml
- 등록 도구(draft_*)의 칸·필수·코드 값 : Java 도구 목록(catalog)
- navigate·search_guide·decline : Java API가 아닌 Python 도구(builtin)
- LLM은 도구와 인자만 고름 -> 인자는 여기서 다시 검증(매핑표·안내서·공통코드)
"""

from dataclasses import dataclass
from functools import lru_cache

from pydantic import BaseModel, ValidationError

from app.chat import catalog, rules

NAVIGATE = "navigate"
SEARCH_GUIDE = "search_guide"
DRAFT_SCHEDULE = "draft_schedule"
DRAFT_CARE_ITEM = "draft_care_item"
DECLINE = "decline"
REGISTER_TOOLS = frozenset({DRAFT_SCHEDULE, DRAFT_CARE_ITEM})


class Navigate(BaseModel):
    screen_num: int


class SearchGuide(BaseModel):
    chunk_id: str | None = None


class Decline(BaseModel):
    unclear: bool = False


BUILTIN_MODELS: dict[str, type[BaseModel]] = {
    NAVIGATE: Navigate,
    SEARCH_GUIDE: SearchGuide,
    DECLINE: Decline,
}

# 기동 때 받은 도구 목록(app/main.py lifespan). 없으면 builtin 도구만
_catalog: catalog.Catalog | None = None


def use_catalog(value: catalog.Catalog | None) -> None:
    global _catalog
    _catalog = value


def active_catalog() -> catalog.Catalog | None:
    return _catalog


def _schema(name: str, model: type[BaseModel]) -> dict:
    # 설명은 description 칸에만 : 스키마 안 제목·설명 중복 제거
    schema = model.model_json_schema()
    schema.pop("title", None)
    schema.pop("description", None)
    for param, prop in schema.get("properties", {}).items():
        prop.pop("title", None)
        prop.pop("default", None)
        prop["description"] = catalog.builtin_param_description(name, param)
    return schema


@lru_cache
def _builtin_definition(name: str) -> dict:
    # 고정 내용 : 매 요청 같은 정의라 system과 함께 캐시
    schema = _schema(name, BUILTIN_MODELS[name])
    props = schema.get("properties", {})
    if name == NAVIGATE:
        props["screen_num"]["enum"] = [row.no for row in _routable_rows()]
    if name == SEARCH_GUIDE:
        props["chunk_id"]["anyOf"] = [
            {"type": "string", "enum": [chunk.id for chunk in rules.guide_chunks()]},
            {"type": "null"},
        ]
    return {"name": name, "description": catalog.builtin_description(name), "input_schema": schema}


def tool_definitions() -> tuple[dict, ...]:
    # 순서 고정(캐시 앞부분) : navigate, search_guide, Java 목록 도구, decline
    entries = _catalog.entries.values() if _catalog is not None else ()
    return (
        _builtin_definition(NAVIGATE),
        _builtin_definition(SEARCH_GUIDE),
        *(entry.definition for entry in entries),
        _builtin_definition(DECLINE),
    )


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
    entry = _catalog.entries.get(name) if _catalog is not None else None
    model = BUILTIN_MODELS.get(name) or (entry.model if entry is not None else None)
    if model is None:
        return ToolCall(name, None, use_id, raw)
    try:
        args = model.model_validate(raw)
    except ValidationError:
        return ToolCall(name, None, use_id, raw)
    if entry is not None:
        # 도구 흐름의 코드 값은 Java 목록 코드로 검사 : 틀린 칸만 비움
        args = catalog.clean_codes(entry, args)
    call = ToolCall(name, args, use_id, raw)
    if name == NAVIGATE and route_row(call) is None:
        return ToolCall(name, None, use_id, raw)
    return call


def register_values(call: ToolCall) -> dict:
    # FN-AIM-012-03 : 도구 인자도 AI 출력이라 같은 재검증, 틀린 칸은 비움
    if call.name not in REGISTER_TOOLS or call.args is None:
        return {}
    return rules.clean_ai_fields(call.args.model_dump(exclude_none=True)).values()


def register_missing(name: str | None, values: dict) -> list[str] | None:
    # FN-AIM-012-05 : 도구 흐름의 빈 칸은 Java 필수·requiredIf로. 목록에 없으면 None(손 규칙)
    entry = _catalog.entries.get(name) if _catalog is not None and name else None
    return catalog.missing_llm(entry, values) if entry is not None else None


def read_entry(name: str) -> catalog.CatalogEntry | None:
    entry = _catalog.entries.get(name) if _catalog is not None else None
    return entry if entry is not None and entry.kind == "READ" else None


def guide_ids(call: ToolCall, text: str) -> list[str]:
    # FN-AIM-002-02 : LLM이 고른 목차 청크를 앞에, M1 키워드 색인 결과를 뒤에(최대 3개)
    picked_id = call.args.chunk_id if isinstance(call.args, SearchGuide) else None
    return rules.merge_guide(picked_id, text)
