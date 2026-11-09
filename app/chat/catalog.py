"""AI 매니저 도구 목록(docs/design/tool-catalog.md 4절)

- Java 도구 목록(GET /internal/ai/tools) = 경로·칸·필수·조건부 규칙·공통코드 값
- data/tool_prompts.yaml = LLM 설명·예문·hook
- 둘을 도구 이름으로 합쳐 검증 모델과 Anthropic 도구 정의를 만든다
- Java 실패면 data/tools.snapshot.json(코드 값 없음)으로 뜨고, 코드 칸이 있는 도구는 싣지 않는다
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path
from typing import Literal, Protocol

import httpx2
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from app.core.backend import BackendError, call_backend
from app.core.config import Settings
from app.core.response import AppError

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CATALOG_PATH = "/internal/ai/tools"
PET_SN = "petSn"
HR_INPUT = "hrInptYn"
YEAR_MONTH = "yearMonth"
_YEAR_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


# Java 응답(설계 3-2절). 외부 입력이라 모양을 검증한다


class CatalogCode(BaseModel):
    cd: str
    nm: str


ParamType = Literal[
    "string", "long", "int", "decimal", "boolean", "date", "time", "datetime", "code"
]


class CatalogParam(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    loc: Literal["path", "query", "body"] = Field(alias="in")
    type: str
    required: bool = False
    group: str | None = None
    codes: list[CatalogCode] | None = None
    max_length: int | None = Field(None, alias="maxLength")
    # @Min·@Max (숫자 칸)
    min_value: int | None = Field(None, alias="min")
    max_value: int | None = Field(None, alias="max")
    # @Positive (숫자 칸), @Pattern (글자 칸)
    positive: bool | None = None
    pattern: str | None = None


class RequiredIf(BaseModel):
    field: str
    when: str
    equals: str


class CatalogRule(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    required_if: RequiredIf | None = Field(None, alias="requiredIf")


class CatalogCall(BaseModel):
    method: str
    path: str


class CatalogTool(BaseModel):
    name: str
    domain: str
    kind: Literal["READ", "CARD"]
    call: CatalogCall
    params: dict[str, CatalogParam]
    rules: list[CatalogRule] = []


class ToolCatalogResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: str
    structure_version: str = Field(alias="structureVersion")
    tools: list[CatalogTool]


# Python 설명(data/tool_prompts.yaml)


class PromptParam(BaseModel):
    description: str
    java: str | None = None
    hook: str | None = None


class ToolPrompt(BaseModel):
    builtin: bool = False
    # 도구 표시 이름 : 확인 카드 제목·결과 요약 글
    label: str | None = None
    # 수정 도구 : 바꿀 대상을 찾지 못했을 때 안내 글의 대상 이름
    target: str | None = None
    description: str
    hooks: list[str] = []
    params: dict[str, PromptParam] = {}


# hook(설계 4-4절) : 이름 -> 만드는 Java 칸. 반려동물·같은 이름 경고는 지금 service.py 흐름이 처리


@dataclass(frozen=True)
class Hook:
    makes: frozenset[str] = frozenset()
    roles: frozenset[str] = frozenset()


HOOKS: dict[str, Hook] = {
    "pet": Hook(makes=frozenset({"petSn"})),
    # 도구의 datetime 칸(schdlDt·rcdDt)을 만듦. hrInptYn이 있는 도구만 시간 입력 여부도
    "date": Hook(makes=frozenset({"schdlDt", HR_INPUT, "rcdDt"}), roles=frozenset({"ymd", "tm"})),
    "same_name_warning": Hook(),
    # 가계부 READ : 문장 속 이름이 하나면 petSn 조건, 아니면 전체(공용 지출 포함)
    "pet_filter": Hook(),
}

# LLM 칸 타입 : 날짜·시간은 글자로 받아 다시 검증
_PY_TYPES: dict[str, type] = {
    "string": str,
    "code": str,
    "date": str,
    "time": str,
    "datetime": str,
    "long": int,
    "int": int,
    "decimal": float,
    "boolean": bool,
}


@dataclass(frozen=True)
class CatalogEntry:
    """합친 도구 하나 : Java 사실 + LLM 설명 + 검증 모델"""

    name: str
    kind: str
    domain: str
    label: str | None
    call: CatalogCall
    params: dict[str, CatalogParam]
    rules: tuple[RequiredIf, ...]
    hooks: tuple[str, ...]
    model: type[BaseModel]
    definition: dict
    # LLM 칸 -> Java 칸, LLM 칸 -> hook 역할("date:ymd")
    to_java_name: dict[str, str]
    hook_roles: dict[str, str]
    # LLM 칸 -> 허용 코드, LLM 칸 -> (min, max)
    codes: dict[str, frozenset[str]]
    bounds: dict[str, tuple[int | None, int | None]] = field(default_factory=dict)
    target: str | None = None


@dataclass(frozen=True)
class Catalog:
    version: str
    structure_version: str
    source: Literal["java", "snapshot"]
    entries: dict[str, CatalogEntry] = field(default_factory=dict)


@lru_cache
def tool_prompts() -> dict[str, ToolPrompt]:
    raw = yaml.safe_load((DATA_DIR / "tool_prompts.yaml").read_text(encoding="utf-8"))
    return {name: ToolPrompt.model_validate(value) for name, value in raw.items()}


def read_snapshot() -> ToolCatalogResponse:
    raw = json.loads((DATA_DIR / "tools.snapshot.json").read_text(encoding="utf-8"))
    return ToolCatalogResponse.model_validate(raw)


def build(
    response: ToolCatalogResponse,
    source: Literal["java", "snapshot"] = "java",
    prompts: dict[str, ToolPrompt] | None = None,
) -> Catalog:
    # 4-2절 3·4번 : 이름으로 합치고 한쪽에만 있으면 싣지 않는다
    prompts = tool_prompts() if prompts is None else prompts
    entries: dict[str, CatalogEntry] = {}
    java_names = {tool.name for tool in response.tools}
    for tool in response.tools:
        prompt = prompts.get(tool.name)
        if prompt is None or prompt.builtin:
            logger.warning("도구 목록: %s 설명 없음, 싣지 않음", tool.name)
            continue
        problem = _problem(tool, prompt, source)
        if problem:
            logger.warning("도구 목록: %s %s, 싣지 않음", tool.name, problem)
            continue
        entries[tool.name] = _entry(tool, prompt)
    for name, prompt in prompts.items():
        if not prompt.builtin and name not in java_names:
            logger.warning("도구 목록: %s Java 목록에 없음, 싣지 않음", name)
    return Catalog(response.version, response.structure_version, source, entries)


def _problem(tool: CatalogTool, prompt: ToolPrompt, source: str) -> str | None:
    unknown = [name for name in prompt.hooks if name not in HOOKS]
    if unknown:
        return f"모르는 hook {unknown}"
    for param in tool.params.values():
        if param.type not in _PY_TYPES:
            return f"지원하지 않는 칸 타입 {param.type}"
        if param.type == "code" and not param.codes:
            # 4-2절 1번 : 스냅샷(코드 값 없음)이면 코드 칸 도구는 싣지 않는다
            return "공통코드 값 없음" if source == "snapshot" else f"코드 값 없음 {param.group}"
    made: set[str] = set()
    for name, param in prompt.params.items():
        if param.java is not None and param.java not in tool.params:
            return f"Java에 없는 칸 {name}->{param.java}"
        if param.hook is not None:
            hook_name, _, role = param.hook.partition(":")
            if hook_name not in prompt.hooks or role not in HOOKS[hook_name].roles:
                return f"hook 역할 잘못 {name}->{param.hook}"
            made |= HOOKS[hook_name].makes
    for hook_name in prompt.hooks:
        made |= HOOKS[hook_name].makes
    mapped = {param.java for param in prompt.params.values() if param.java} | made
    uncovered = [
        name for name, param in tool.params.items() if param.required and name not in mapped
    ]
    if uncovered:
        return f"채울 수 없는 필수 칸 {uncovered}"
    return None


def _entry(tool: CatalogTool, prompt: ToolPrompt) -> CatalogEntry:
    fields: dict = {}
    to_java_name: dict[str, str] = {}
    hook_roles: dict[str, str] = {}
    codes: dict[str, frozenset[str]] = {}
    code_names: dict[str, str] = {}
    bounds: dict[str, tuple[int | None, int | None]] = {}
    for name, param in prompt.params.items():
        java = tool.params.get(param.java) if param.java else None
        py_type = _PY_TYPES[java.type] if java else str
        # 4-2절 4번 : 필수 판단은 Python이 Java 규칙으로, LLM에는 required를 주지 않는다
        fields[name] = (py_type | None, Field(None, description=param.description))
        if param.java:
            to_java_name[name] = param.java
        if param.hook:
            hook_roles[name] = param.hook
        if java is not None and java.codes:
            codes[name] = frozenset(code.cd for code in java.codes)
            code_names[name] = ", ".join(f"{code.cd} {code.nm}" for code in java.codes)
        if java is not None and (java.min_value is not None or java.max_value is not None):
            bounds[name] = (java.min_value, java.max_value)
    model = create_model(_model_name(tool.name), **fields)
    definition = {
        "name": tool.name,
        "description": _description(prompt),
        "input_schema": _schema(model, codes, code_names, bounds),
    }
    rules = tuple(rule.required_if for rule in tool.rules if rule.required_if is not None)
    return CatalogEntry(
        name=tool.name,
        kind=tool.kind,
        domain=tool.domain,
        label=prompt.label,
        call=tool.call,
        params=tool.params,
        rules=rules,
        hooks=tuple(prompt.hooks),
        model=model,
        definition=definition,
        to_java_name=to_java_name,
        hook_roles=hook_roles,
        codes=codes,
        bounds=bounds,
        target=prompt.target,
    )


def _model_name(name: str) -> str:
    return "".join(part.title() for part in name.split("_"))


def _description(prompt: ToolPrompt) -> str:
    return "\n".join(line.strip() for line in prompt.description.strip().splitlines())


def _schema(
    model: type[BaseModel],
    codes: dict[str, frozenset[str]],
    code_names: dict[str, str],
    bounds: dict[str, tuple[int | None, int | None]],
) -> dict:
    # 설명은 description 칸에만 : 스키마 안 제목·기본값 제거
    # 코드 칸은 enum + 코드 이름, 숫자 칸은 minimum·maximum
    schema = model.model_json_schema()
    schema.pop("title", None)
    schema.pop("description", None)
    schema.pop("required", None)
    for name, prop in schema.get("properties", {}).items():
        prop.pop("title", None)
        prop.pop("default", None)
        if name in codes:
            value = next(item for item in prop["anyOf"] if item.get("type") != "null")
            value["enum"] = sorted(codes[name])
            prop["description"] = f"{prop['description']}: {code_names[name]}"
        if name in bounds:
            value = next(item for item in prop["anyOf"] if item.get("type") != "null")
            low, high = bounds[name]
            if low is not None:
                value["minimum"] = low
            if high is not None:
                value["maximum"] = high
    return schema


def builtin_description(name: str) -> str:
    return _description(tool_prompts()[name])


def builtin_param_description(name: str, param: str) -> str:
    return tool_prompts()[name].params[param].description


# 한 턴(설계 4-3절)


def clean_codes(entry: CatalogEntry, args: BaseModel) -> BaseModel:
    # Java 목록에 없는 코드 값과 min·max 밖 숫자는 비운다(틀린 칸만 비움 -> 되물음)
    wrong = {
        name: None
        for name, allowed in entry.codes.items()
        if getattr(args, name) is not None and getattr(args, name) not in allowed
    }
    for name, (low, high) in entry.bounds.items():
        value = getattr(args, name)
        if value is None:
            continue
        if (low is not None and value < low) or (high is not None and value > high):
            wrong[name] = None
    return args.model_copy(update=wrong) if wrong else args


def to_java(entry: CatalogEntry, values: dict, now: datetime | None = None) -> dict:
    """LLM 칸 값 -> Java 요청 칸 값 (date hook이 날짜·시간을 도구의 datetime 칸으로 합침)"""
    names, hooks = entry.to_java_name, entry.hook_roles
    java = {names[name]: value for name, value in values.items() if name in names}
    roles = {hooks[name]: value for name, value in values.items() if name in hooks}
    if "date" in entry.hooks:
        java |= _compose_datetime(entry, roles.get("date:ymd"), roles.get("date:tm"), now)
    return {name: value for name, value in java.items() if value is not None}


def _compose_datetime(entry: CatalogEntry, ymd, tm, now: datetime | None) -> dict:
    target = next((name for name, p in entry.params.items() if p.type == "datetime"), None)
    if ymd is None or target is None:
        return {}
    day = ymd if isinstance(ymd, date) else date.fromisoformat(str(ymd))
    clock = tm if isinstance(tm, time) else time.fromisoformat(str(tm)) if tm else None
    if HR_INPUT in entry.params:
        # 일정 : 시간이 없으면 0시 + 시간 미입력
        moment = datetime.combine(day, clock or time(0, 0))
        return {target: moment.isoformat(), HR_INPUT: clock is not None}
    if clock is None:
        # 2026-11-06 결정 : 날짜만이면 오늘은 지금 시각(KST), 다른 날은 빈 칸(되물음)
        if now is None or day != now.date():
            return {}
        clock = now.time().replace(second=0, microsecond=0)
    return {target: datetime.combine(day, clock).isoformat()}


def is_id(name: str) -> bool:
    # 번호 칸(…Sn). petSn은 서버 규칙(pet hook·문장 속 이름)으로 정한다
    return name.endswith("Sn") and name != PET_SN


def seen_ids(data: object, seen: dict[str, set[int]] | None = None) -> dict[str, set[int]]:
    """READ 결과에 나온 번호 칸 값 (칸 이름 -> 값들, 중첩까지)"""
    seen = {} if seen is None else seen
    if isinstance(data, dict):
        for key, value in data.items():
            if is_id(key) and isinstance(value, int) and not isinstance(value, bool):
                seen.setdefault(key, set()).add(value)
            else:
                seen_ids(value, seen)
    elif isinstance(data, list):
        for value in data:
            seen_ids(value, seen)
    return seen


Rows = dict[tuple[str, int], dict]


def seen_rows(data: object, rows: Rows | None = None) -> Rows:
    """READ 결과의 번호 칸이 있는 행 : (칸 이름, 값) -> 그 행. 수정 카드가 원래 값을 쓰려고"""
    rows = {} if rows is None else rows
    if isinstance(data, dict):
        for key, value in data.items():
            if is_id(key) and isinstance(value, int) and not isinstance(value, bool):
                rows.setdefault((key, value), data)
            else:
                seen_rows(value, rows)
    elif isinstance(data, list):
        for value in data:
            seen_rows(value, rows)
    return rows


def read_request(
    entry: CatalogEntry,
    values: dict,
    pet_sn: int | None,
    seen: dict[str, set[int]] | None = None,
) -> tuple[str, dict] | None:
    """READ 도구 인자 -> Java 경로·query (필수 칸이 비면 None)
    - 번호 칸은 같은 턴 앞 READ 결과(seen)에 나온 값만 : LLM이 지어낸 번호면 그 칸을 비움"""
    java = to_java(entry, values)
    if pet_sn is not None and PET_SN in entry.params:
        java[PET_SN] = pet_sn
    seen = seen or {}
    for name, value in list(java.items()):
        param = entry.params.get(name)
        if param is None:
            continue
        if is_id(name):
            if value not in seen.get(name, set()):
                del java[name]
        elif param.type == "date":
            # LLM 날짜 글자 재검증 : 틀리면 그 조건만 비움
            try:
                java[name] = date.fromisoformat(str(value)).isoformat()
            except ValueError:
                del java[name]
        elif name == YEAR_MONTH and not _YEAR_MONTH.fullmatch(str(value)):
            # Java YearMonth.parse 형식(YYYY-MM)
            del java[name]
    if any(param.required and java.get(name) is None for name, param in entry.params.items()):
        return None
    path = entry.call.path
    for name, param in entry.params.items():
        if param.loc == "path":
            path = path.replace(f"{{{name}}}", str(java[name]))
    query = {
        name: str(value).lower() if isinstance(value, bool) else value
        for name, value in java.items()
        if name in entry.params and entry.params[name].loc == "query"
    }
    return path, query


def missing(entry: CatalogEntry, java_values: dict) -> list[str]:
    """Java 필수·requiredIf로 빈 Java 칸 (설계 4-3절 CARD)"""
    names = [name for name, param in entry.params.items() if param.required]
    for rule in entry.rules:
        if java_values.get(rule.when) == rule.equals and rule.field not in names:
            names.append(rule.field)
    return [name for name in names if java_values.get(name) in (None, "")]


def missing_llm(entry: CatalogEntry, values: dict) -> list[str]:
    """빈 칸을 LLM 칸 이름으로 (되물음 카드용). 반려동물(petSn)은 service.py가 따로 정한다"""
    java = to_java(entry, values)
    by_java = {java_name: name for name, java_name in entry.to_java_name.items()}
    date_ymd = next((name for name, role in entry.hook_roles.items() if role == "date:ymd"), None)
    names: list[str] = []
    for java_name in missing(entry, java):
        if java_name in HOOKS["pet"].makes:
            continue
        name = date_ymd if java_name in HOOKS["date"].makes else by_java.get(java_name)
        if name is not None and name not in names:
            names.append(name)
    return names


# 확인 카드(2단계 쓰기, CARD)


def _valid(param: CatalogParam, value: object) -> bool:
    # Java 칸 규칙(타입·코드 값·min·max·maxLength)에 맞는 값인지
    kind = param.type
    if value is None:
        return False
    if kind in ("date", "datetime", "time"):
        parse = {"date": date, "datetime": datetime, "time": time}[kind].fromisoformat
        try:
            parse(str(value))
        except ValueError:
            return False
        return True
    if kind == "code":
        return bool(param.codes) and value in {code.cd for code in param.codes}
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "string":
        if not isinstance(value, str) or not value.strip():
            return False
        if param.pattern is not None and re.fullmatch(param.pattern, value) is None:
            return False
        return param.max_length is None or len(value) <= param.max_length
    numeric = (int,) if kind in ("long", "int") else (int, float)
    if isinstance(value, bool) or not isinstance(value, numeric):
        return False
    if param.positive and value <= 0:
        return False
    low, high = param.min_value, param.max_value
    return (low is None or value >= low) and (high is None or value <= high)


def _valid_role(role: str, value: object) -> bool:
    parse = date.fromisoformat if role == "date:ymd" else time.fromisoformat
    try:
        parse(str(value))
    except ValueError:
        return False
    return True


def card_input(
    entry: CatalogEntry,
    values: dict,
    now: datetime | None = None,
    seen: dict[str, set[int]] | None = None,
    prior: dict | None = None,
    rows: Rows | None = None,
) -> dict:
    """CARD 도구 인자 -> 확인 카드 input(Java 칸). 틀린 칸은 비움(되물음)
    - 번호 칸은 같은 턴 앞 READ 결과(seen)에 나온 값만, petSn은 service.py가 pet hook으로
    - prior : 돌려받은 카드 input(같은 도구), 이 메시지 값이 덮어씀
    - rows : 같은 턴 READ 결과 행. 수정 카드에서 날짜만 바꾸면 원래 시간을 씀(_keep_time)"""
    params = entry.params
    base = {
        name: value
        for name, value in (prior or {}).items()
        if name in params and name != PET_SN and _valid(params[name], value)
    }
    roles = entry.hook_roles
    usable = {
        name: value
        for name, value in values.items()
        if name not in roles or _valid_role(roles[name], value)
    }
    seen = seen or {}
    new = {
        name: value
        for name, value in to_java(entry, usable, now).items()
        if name in params
        and name != PET_SN
        and _valid(params[name], value)
        and (not is_id(name) or value in seen.get(name, set()))
    }
    given = {roles[name] for name in usable if name in roles}
    return _keep_time(entry, base | new, given, new, rows or {}, prior or {})


def _keep_time(
    entry: CatalogEntry, merged: dict, given: set[str], new: dict, rows: Rows, prior: dict
) -> dict:
    # 수정 카드(경로 번호 칸·date hook·hrInptYn) : 날짜만 오면 0시·미입력 대신 원래 시간
    # 원래 값은 같은 턴 READ 결과의 그 번호 행, 없으면 돌려받은 카드 input. 새 등록 카드는 그대로
    ids = [n for n, p in entry.params.items() if p.loc == "path" and is_id(n)]
    target = next((n for n, p in entry.params.items() if p.type == "datetime"), None)
    if not ids or target is None or HR_INPUT not in entry.params or "date" not in entry.hooks:
        return merged
    if "date:ymd" not in given or "date:tm" in given or target not in new:
        return merged
    sn = merged.get(ids[0])
    source = rows.get((ids[0], sn)) if sn is not None else None
    if source is None and sn is not None and prior.get(ids[0]) == sn:
        source = prior
    if source is None:
        return merged
    try:
        original = datetime.fromisoformat(str(source.get(target)))
    except ValueError:
        return merged
    entered = source.get(HR_INPUT)
    if entered is False or (entered is None and original.time() == time(0, 0)):
        # 원래 시간 미입력 : 0시·미입력 그대로
        return merged
    day = datetime.fromisoformat(str(merged[target])).date()
    moment = datetime.combine(day, original.time().replace(second=0, microsecond=0))
    return merged | {target: moment.isoformat(), HR_INPUT: True}


def missing_path_ids(entry: CatalogEntry, values: dict) -> list[str]:
    """경로의 번호 칸(…Sn, petSn 제외) 중 빈 칸. 회원이 카드에서 고를 수 없어 카드를 안 띄움"""
    return [
        name
        for name, param in entry.params.items()
        if param.loc == "path" and is_id(name) and values.get(name) is None
    ]


def invalid_input(entry: CatalogEntry, values: dict) -> list[str]:
    """목록에 없는 칸·Java 규칙 밖 값 (결과 저장 요청 검사)"""
    return [
        name
        for name, value in values.items()
        if name not in entry.params or (value is not None and not _valid(entry.params[name], value))
    ]


def card_params(entry: CatalogEntry) -> dict[str, dict]:
    return {
        name: param.model_dump(by_alias=True, exclude_none=True)
        for name, param in entry.params.items()
    }


def card_rules(entry: CatalogEntry) -> list[dict]:
    return [rule.model_dump() for rule in entry.rules]


# Java 호출


class ToolCatalogClient(Protocol):
    async def fetch(self) -> ToolCatalogResponse: ...


class JavaToolCatalogClient:
    """GET /internal/ai/tools (백엔드 PR #174·#177). 회원과 관계없는 목록이라 쿠키 없이"""

    def __init__(self, client: httpx2.AsyncClient, settings: Settings):
        self.client = client
        self.settings = settings

    async def fetch(self) -> ToolCatalogResponse:
        data = await call_backend(self.client, self.settings, "GET", CATALOG_PATH)
        return ToolCatalogResponse.model_validate(data)


async def load(client: ToolCatalogClient) -> Catalog:
    # 4-2절 1·2번 : Java 실패면 스냅샷, 구조가 다르면 경고 후 Java 응답
    snapshot = read_snapshot()
    try:
        response = await client.fetch()
    except (AppError, BackendError, ValidationError) as error:
        logger.warning("도구 목록: Java 받기 실패(%s), 스냅샷으로", type(error).__name__)
        return build(snapshot, "snapshot")
    if response.structure_version != snapshot.structure_version:
        logger.warning(
            "도구 목록: structureVersion 다름(Java %s, 스냅샷 %s)",
            response.structure_version,
            snapshot.structure_version,
        )
    return build(response, "java")


async def install(client: ToolCatalogClient) -> Catalog:
    # 다시 받기는 기동 때 1회(9절 결정 남음)
    catalog = await load(client)
    logger.info(
        "도구 목록: %s %s, %d개 %s",
        catalog.source,
        catalog.version,
        len(catalog.entries),
        ",".join(catalog.entries),
    )
    return catalog
