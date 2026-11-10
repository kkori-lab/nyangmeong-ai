"""AI 매니저 도구 목록(docs/design/tool-catalog.md 4절)

- Java 도구 목록(GET /internal/ai/tools) = 경로·칸·필수·조건부 규칙·공통코드 값
- data/tool_prompts.yaml = LLM 설명·예문·hook
- 둘을 도구 이름으로 합쳐 검증 모델과 Anthropic 도구 정의를 만든다
- Java 실패면 data/tools.snapshot.json(코드 값 없음)으로 뜨고, 코드 칸이 있는 도구는 싣지 않는다
"""

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path
from typing import Literal, Protocol

import httpx2
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from app.core.backend import BackendError, call_backend, failure_reason
from app.core.config import Settings
from app.core.response import AppError

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CATALOG_PATH = "/internal/ai/tools"
# 도구 목록만 Java 공통 3초보다 길게 : 재시작 직후 첫 호출 17.7초(2026-11-09 배포 서버)
CATALOG_TIMEOUT_SEC = 20.0
# 기동 때 실패하면 뒤에서 다시 받기 : 30초 간격 10번(약 5분)
RETRY_INTERVAL_SEC = 30.0
RETRY_ATTEMPTS = 10
PET_SN = "petSn"
HR_INPUT = "hrInptYn"
YEAR_MONTH = "yearMonth"
_YEAR_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


# Java 응답(설계 3-2절). 외부 입력이라 모양을 검증한다


class CatalogCode(BaseModel):
    cd: str
    nm: str


ParamType = Literal[
    "string",
    "long",
    "int",
    "decimal",
    "boolean",
    "date",
    "time",
    "datetime",
    "code",
    "array",
    "file",
]
ARRAY = "array"
FILE = "file"


class CatalogItemParam(BaseModel):
    """칸 규칙 : 배열 항목 칸(in 없음)과 요청 칸(CatalogParam)이 같이 쓴다"""

    model_config = ConfigDict(populate_by_name=True)

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
    # 배열 칸 : 항목 칸 규칙(중첩 배열 포함)·최소 항목 수
    items: dict[str, "CatalogItemParam"] | None = None
    min_items: int | None = Field(None, alias="minItems")
    # "uuid" : React가 [확인] 때 카드 하나에 한 번 만든다(Python은 채우지 않고 필수로 세지 않음)
    generated: str | None = None


class CatalogParam(CatalogItemParam):
    loc: Literal["path", "query", "body"] = Field(alias="in")


class RequiredIf(BaseModel):
    field: str
    when: str
    equals: str


class CatalogRule(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    required_if: RequiredIf | None = Field(None, alias="requiredIf")


class CatalogCall(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    method: str
    path: str
    # 파일 칸이 있는 도구 : multipart/form-data
    content_type: str | None = Field(None, alias="contentType")


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
    # Java 칸 -> 늘 넣는 값(지출 등록의 입력 방법 등). 불러올 때 Java 규칙으로 검사
    fixed: dict[str, str | int | bool] = {}


# hook(설계 4-4절) : 이름 -> 만드는 Java 칸. 반려동물·같은 이름 경고는 지금 service.py 흐름이 처리


@dataclass(frozen=True)
class Hook:
    makes: frozenset[str] = frozenset()
    roles: frozenset[str] = frozenset()


HOOKS: dict[str, Hook] = {
    "pet": Hook(makes=frozenset({"petSn"})),
    # 도구의 datetime 칸(schdlDt·rcdDt)을 만듦. hrInptYn이 있는 도구만 시간 입력 여부도
    "date": Hook(
        makes=frozenset({"schdlDt", HR_INPUT, "rcdDt", "obsrvDt"}), roles=frozenset({"ymd", "tm"})
    ),
    "same_name_warning": Hook(),
    # 가계부 READ : 문장 속 이름이 하나면 petSn 조건, 아니면 전체(공용 지출 포함)
    "pet_filter": Hook(),
    # 배열 줄의 petSn(지출 등록 lines[0].petSn) : 문장 속 이름이 하나면 그 번호, 아니면 비움(공용)
    "line_pet": Hook(),
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
    fixed: dict[str, object] = field(default_factory=dict)


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


ITEM_MARK = "[]."


def _java_param(params: dict[str, CatalogParam], java: str) -> CatalogItemParam | None:
    """설명의 java 칸 -> Java 칸 규칙. "lines[].expndAmt"는 배열 lines 항목의 expndAmt"""
    array, mark, item = java.partition(ITEM_MARK)
    if not mark:
        return params.get(java)
    param = params.get(array)
    if param is None or param.type != ARRAY or not param.items:
        return None
    return param.items.get(item)


def _all_params(params: dict) -> list[CatalogItemParam]:
    # 칸 규칙 전부(배열 항목 칸까지 중첩)
    found: list[CatalogItemParam] = []
    for param in params.values():
        found.append(param)
        if param.items:
            found += _all_params(param.items)
    return found


def _problem(tool: CatalogTool, prompt: ToolPrompt, source: str) -> str | None:
    unknown = [name for name in prompt.hooks if name not in HOOKS]
    if unknown:
        return f"모르는 hook {unknown}"
    for param in _all_params(tool.params):
        if param.type not in _PY_TYPES and param.type not in (ARRAY, FILE):
            return f"지원하지 않는 칸 타입 {param.type}"
        if param.type == "code" and not param.codes:
            # 4-2절 1번 : 스냅샷(코드 값 없음)이면 코드 칸 도구는 싣지 않는다
            return "공통코드 값 없음" if source == "snapshot" else f"코드 값 없음 {param.group}"
    for name, value in prompt.fixed.items():
        param = tool.params.get(name)
        if param is None or not _valid(param, value):
            return f"고정 값 잘못 {name}={value}"
    made: set[str] = set(prompt.fixed)
    for name, param in prompt.params.items():
        if param.java is not None:
            java = _java_param(tool.params, param.java)
            if java is None or java.type in (ARRAY, FILE):
                return f"Java에 없는 칸 {name}->{param.java}"
            made.add(param.java.partition(ITEM_MARK)[0])
        if param.hook is not None:
            hook_name, _, role = param.hook.partition(":")
            if hook_name not in prompt.hooks or role not in HOOKS[hook_name].roles:
                return f"hook 역할 잘못 {name}->{param.hook}"
            made |= HOOKS[hook_name].makes
    for hook_name in prompt.hooks:
        made |= HOOKS[hook_name].makes
    # 파일 칸은 React 카드에서 첨부, generated 칸은 React가 만든다
    uncovered = [
        name
        for name, param in tool.params.items()
        if param.required and name not in made and param.type != FILE and not param.generated
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
        java = _java_param(tool.params, param.java) if param.java else None
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
        fixed=dict(prompt.fixed),
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
    java: dict = {}
    for name, value in values.items():
        if name not in names:
            continue
        array, mark, item = names[name].partition(ITEM_MARK)
        if not mark:
            java[array] = value
        elif value is not None:
            # 배열 항목 칸 : 첫 줄 하나에 모은다(지출 등록 lines[0])
            java.setdefault(array, [{}])[0][item] = value
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


def missing(entry: CatalogEntry, java_values: dict, files: bool = True) -> list[str]:
    """Java 필수·requiredIf로 빈 Java 칸 (설계 4-3절 CARD)
    - 배열 : 빈 필수 배열은 "lines", 항목 안 빈 필수 칸은 "lines[0].expndAmt"
    - files : 파일 필수 칸을 셈(카드는 늘 셈, action-result는 React가 파일을 보낸 뒤라 안 셈)"""
    found = _missing_in(entry.params, java_values, "", files)
    for rule in entry.rules:
        empty = java_values.get(rule.field) in (None, "")
        if java_values.get(rule.when) == rule.equals and empty and rule.field not in found:
            found.append(rule.field)
    return found


def _missing_in(params: dict, values: dict, prefix: str, files: bool) -> list[str]:
    found: list[str] = []
    for name, param in params.items():
        value = values.get(name)
        if param.generated or (param.type == FILE and not files):
            continue
        if param.type == ARRAY:
            rows = value if isinstance(value, list) else []
            least = max(param.min_items or 0, 1 if param.required else 0)
            if len(rows) < least:
                found.append(prefix + name)
            for index, row in enumerate(rows):
                if isinstance(row, dict):
                    inner = f"{prefix}{name}[{index}]."
                    found += _missing_in(param.items or {}, row, inner, files)
        elif param.required and value in (None, ""):
            found.append(prefix + name)
    return found


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


def _valid(param: CatalogItemParam, value: object) -> bool:
    # Java 칸 규칙(타입·코드 값·min·max·maxLength)에 맞는 값인지
    # 배열은 모양과 들어 있는 값만(빈 필수 항목 칸은 missing이 센다), 파일은 Python이 받지 않음
    kind = param.type
    if value is None or kind == FILE:
        return False
    if kind == ARRAY:
        return _clean_array(param, value) == value
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


def _clean_array(
    param: CatalogItemParam, value: object, seen: dict[str, set[int]] | None = None
) -> list[dict] | None:
    """배열 칸 값에서 항목 칸 규칙 밖 값·모르는 칸을 뺀다(틀린 칸만 비움). 배열 모양이 아니면 None
    - seen : 주면 번호 칸(…Sn)은 같은 턴 READ 결과 값만(LLM 값). None 값은 그대로 둔다"""
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        return None
    items = param.items or {}
    cleaned: list[dict] = []
    for row in value:
        kept: dict = {}
        for name, item_value in row.items():
            rule = items.get(name)
            if rule is None:
                continue
            if item_value is None:
                kept[name] = None
            elif rule.type == ARRAY:
                inner = _clean_array(rule, item_value, seen)
                if inner is not None:
                    kept[name] = inner
            elif _valid(rule, item_value) and (
                seen is None or not is_id(name) or item_value in seen.get(name, set())
            ):
                kept[name] = item_value
        cleaned.append(kept)
    return cleaned


def _usable(
    param: CatalogParam, value: object, seen: dict[str, set[int]] | None = None
) -> object | None:
    # 카드 input에 쓸 값(배열은 틀린 항목 칸만 뺌). 쓸 수 없으면 None
    if param.type == ARRAY:
        return _clean_array(param, value, seen)
    return value if _valid(param, value) else None


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
        name: _usable(params[name], value)
        for name, value in (prior or {}).items()
        if name in params and name != PET_SN and _usable(params[name], value) is not None
    }
    roles = entry.hook_roles
    usable = {
        name: value
        for name, value in values.items()
        if name not in roles or _valid_role(roles[name], value)
    }
    seen = seen or {}
    new = {
        name: _usable(params[name], value, seen)
        for name, value in to_java(entry, usable, now).items()
        if name in params
        and name != PET_SN
        and _usable(params[name], value, seen) is not None
        and (not is_id(name) or value in seen.get(name, set()))
    }
    merged = base | new
    for name in mapped_arrays(entry):
        # 배열 첫 줄 : 돌려받은 카드의 줄에 이 메시지 값을 덮어씀, 줄이 없으면 빈 줄 하나(되물음)
        old, fresh = base.get(name) or [], new.get(name) or []
        first = (old[0] if old else {}) | (fresh[0] if fresh else {})
        merged[name] = [first, *old[1:]]
    merged |= entry.fixed
    given = {roles[name] for name in usable if name in roles}
    return _keep_time(entry, merged, given, new, rows or {}, prior or {})


def mapped_arrays(entry: CatalogEntry) -> list[str]:
    """LLM 칸이 항목 칸으로 이어진 배열("lines[].expndAmt"의 lines)"""
    found = [
        java.partition(ITEM_MARK)[0] for java in entry.to_java_name.values() if ITEM_MARK in java
    ]
    return list(dict.fromkeys(found))


def keep_prior_dates(
    entry: CatalogEntry, values: dict, prior: dict, date_said: bool, today: date
) -> dict:
    """돌려받은 카드(prior, 같은 도구)가 있는데 이 메시지에 날짜 말이 없고 LLM 날짜가 오늘이면
    그 날짜(date hook·date 칸)를 버려 카드 값을 유지한다
    (설명의 "말하지 않았으면 오늘"이 회원이 카드에서 고친 날짜를 덮지 않게, 추가-1)
    - 오늘이 아닌 날짜는 LLM이 계산한 것("하루 더 미뤄줘")이라 그대로 쓴다
    - 카드에 그 칸 값이 없으면 LLM 값을 그대로 쓴다
    - 시간이 오면 카드의 날짜에 그 시간"""
    if date_said:
        return values
    roles = entry.hook_roles
    today_iso = today.isoformat()
    target = next((n for n, p in entry.params.items() if p.type == "datetime"), None)
    original = None
    if "date" in entry.hooks and target is not None and prior.get(target) is not None:
        try:
            original = datetime.fromisoformat(str(prior[target]))
        except ValueError:
            original = None
    kept: dict = {}
    dropped = False
    for name, value in values.items():
        if original is not None and roles.get(name) == "date:ymd" and str(value) == today_iso:
            dropped = True
            continue
        java = entry.to_java_name.get(name)
        param = _java_param(entry.params, java) if java else None
        if (
            param is not None
            and param.type == "date"
            and ITEM_MARK not in java
            and prior.get(java) is not None
            and str(value) == today_iso
        ):
            continue
        kept[name] = value
    ymd = next((n for n, r in roles.items() if r == "date:ymd"), None)
    tm = next((n for n, r in roles.items() if r == "date:tm"), None)
    if dropped and ymd is not None and tm in kept:
        kept[ymd] = original.date().isoformat()
    return kept


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


def missing_target_ids(entry: CatalogEntry, values: dict) -> list[str]:
    """경로의 번호 칸과, 찾을 대상(target)이 있는 도구의 본문 필수 번호 칸(…Sn, petSn 빼고)의 빈 칸
    회원이 카드에서 고를 수 없어 카드를 안 띄움(수정 대상·관찰 기록의 관찰 항목)
    - target이 없는 도구(케어 완료 체크)는 본문 번호 칸이 비어도 카드를 띄운다(지금 동작)"""
    return [
        name
        for name, param in entry.params.items()
        if (param.loc == "path" or (param.required and entry.target is not None))
        and is_id(name)
        and values.get(name) is None
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
        data = await call_backend(
            self.client, self.settings, "GET", CATALOG_PATH, timeout=CATALOG_TIMEOUT_SEC
        )
        return ToolCatalogResponse.model_validate(data)


def _reason(error: Exception) -> str:
    if isinstance(error, ValidationError):
        first = error.errors()[0] if error.errors() else {}
        where = ".".join(str(part) for part in first.get("loc", ())) or "-"
        return f"응답 모양 다름 {where}"
    reason = failure_reason(error)
    if reason.startswith("제한 시간 초과"):
        return f"{reason}, {CATALOG_TIMEOUT_SEC:g}초"
    return reason


async def _fetch(client: ToolCatalogClient) -> tuple[ToolCatalogResponse | None, str]:
    try:
        return await client.fetch(), ""
    except (AppError, BackendError, ValidationError) as error:
        return None, _reason(error)


def _from_java(response: ToolCatalogResponse, snapshot: ToolCatalogResponse) -> Catalog:
    if response.structure_version != snapshot.structure_version:
        logger.warning(
            "도구 목록: structureVersion 다름(Java %s, 스냅샷 %s)",
            response.structure_version,
            snapshot.structure_version,
        )
    return build(response, "java")


async def load(client: ToolCatalogClient) -> Catalog:
    # 4-2절 1·2번 : Java 실패면 스냅샷, 구조가 다르면 경고 후 Java 응답
    snapshot = read_snapshot()
    response, reason = await _fetch(client)
    if response is None:
        logger.warning("도구 목록: Java 받기 실패(%s), 스냅샷으로", reason)
        return build(snapshot, "snapshot")
    return _from_java(response, snapshot)


def _log_installed(catalog: Catalog) -> None:
    logger.info(
        "도구 목록: %s %s, %d개 %s",
        catalog.source,
        catalog.version,
        len(catalog.entries),
        ",".join(catalog.entries),
    )


async def install(client: ToolCatalogClient) -> Catalog:
    # 기동 때 1회. 실패해 스냅샷이면 retry로 뒤에서 다시 받는다(4-2절 5번)
    catalog = await load(client)
    _log_installed(catalog)
    return catalog


async def retry(
    client: ToolCatalogClient,
    use: Callable[[Catalog], None],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    attempts: int = RETRY_ATTEMPTS,
    interval_sec: float = RETRY_INTERVAL_SEC,
) -> Catalog | None:
    """스냅샷으로 뜬 뒤 Java 목록 다시 받기 : 성공하면 바꾸고 멈춤, 다 실패하면 스냅샷 유지"""
    for attempt in range(1, attempts + 1):
        await sleep(interval_sec)
        response, reason = await _fetch(client)
        if response is None:
            logger.warning("도구 목록: 다시 받기 %d/%d 실패(%s)", attempt, attempts, reason)
            continue
        catalog = _from_java(response, read_snapshot())
        use(catalog)
        _log_installed(catalog)
        return catalog
    logger.warning("도구 목록: 다시 받기 %d번 모두 실패, 스냅샷 유지", attempts)
    return None
