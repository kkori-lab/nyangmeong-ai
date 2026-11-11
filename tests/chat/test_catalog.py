import asyncio
import copy
import logging

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.chat import catalog, rules, tools
from app.core.config import Settings, get_settings
from app.main import create_app
from tests.chat.fakes import (
    FAKE_CODES,
    FakeToolAgent,
    FakeToolCatalogClient,
    fake_catalog_json,
)
from tests.chat.test_messages import MessageJava, events, send
from tests.chat.test_register import CHOCO, Extractor, use_extractor
from tests.chat.test_tools import room_of, use_agent

BUILTIN = {"navigate", "search_guide", "decline"}
REGISTER = {"draft_schedule", "draft_care_item"}
# 2단계 쓰기 확인 카드(ACTION)
ACTION = {
    "draft_care_completion",
    "draft_daily_health_record",
    "draft_expense_limit",
    # 수정 4개(2단계 ②) : 모두 코드 칸이 있어 스냅샷만이면 안 실림
    "draft_schedule_update",
    "draft_care_item_update",
    "draft_expense_update",
    "draft_pet_update",
    # 배열·파일 칸(2단계 ③) : 코드 칸이 있어 스냅샷만이면 안 실림
    "draft_expense",
    "draft_observation_cycle",
}
# 스냅샷(코드 값 없음)으로도 싣는 ACTION : 코드 칸 없음
ACTION_WITHOUT_CODES = {"draft_care_completion", "draft_expense_limit"}
READ = {
    "get_checkup",
    "get_health_indicators",
    "list_care_completions",
    "list_care_items",
    "list_my_care_schedules",
    "list_checkups",
    "list_daily_health_records",
    "list_etc_inspections",
    "list_inspection_values",
    "list_observation_cycles",
    "list_observation_items",
    "list_prescriptions",
    "list_repeat_preventions",
    # 가계부
    "get_expense_statistics",
    "get_expense_total",
    "get_receipt",
    "list_expense_months",
    "list_expense_pets",
    "list_expenses",
    # 반려동물·캐릭터(2026-11-11)
    "get_pet",
    "get_pixel_character",
    "get_points",
    "list_caregivers",
    "list_daily_missions",
    "list_pets",
    "list_pixel_characters",
    "list_point_ledgers",
    "list_sent_caregiver_invitations",
    "list_shop_items",
    # 커뮤니티·플레이스(2026-11-11)
    "get_popular_photo",
    "get_post",
    "list_care_recruitments",
    "list_comments",
    "list_health_tips",
    "list_lost_reports",
    "list_news",
    "list_place_bookmarks",
    "list_posts",
}
# 일부러 싣지 않는 Java 도구(tool_prompts.yaml skip)
SKIP = {"list_care_schedules", "draft_receipt_save", "list_places", "list_faqs"}
# 스냅샷(코드 값 없음)으로도 싣는 READ : 코드 칸 없음
READ_WITHOUT_CODES = {
    "get_checkup",
    "get_health_indicators",
    "list_care_completions",
    "list_care_items",
    "list_etc_inspections",
    "list_observation_cycles",
    "list_repeat_preventions",
    "get_expense_statistics",
    "get_receipt",
    "list_expense_months",
    "list_expense_pets",
    "get_pet",
    "get_pixel_character",
    "get_points",
    "list_caregivers",
    "list_daily_missions",
    "list_pets",
    "list_pixel_characters",
    "list_point_ledgers",
    "list_sent_caregiver_invitations",
    "get_popular_photo",
    "get_post",
    "list_comments",
    "list_health_tips",
}


def build(raw: dict) -> catalog.Catalog:
    return catalog.build(catalog.ToolCatalogResponse.model_validate(raw))


def entry(name: str) -> catalog.CatalogEntry:
    return build(fake_catalog_json()).entries[name]


def tool_of(raw: dict, name: str) -> dict:
    return next(tool for tool in raw["tools"] if tool["name"] == name)


# 설계 7절 테스트 ①~⑤


def test_스냅샷의_CARD_도구마다_설명이_있고_설명의_Java_도구는_스냅샷에_있어야_한다():
    # ① READ without a fillable required id has no prompt (design 8-4)
    prompts = catalog.tool_prompts()
    snapshot = catalog.read_snapshot().tools
    cards = {tool.name for tool in snapshot if tool.kind == "CARD"}
    java_prompts = {
        name for name, prompt in prompts.items() if not prompt.builtin and prompt.skip is None
    }
    assert {name for name, prompt in prompts.items() if prompt.skip is not None} == SKIP
    assert {tool.name for tool in snapshot} >= SKIP

    assert cards >= REGISTER
    assert java_prompts == REGISTER | READ | ACTION
    assert java_prompts <= {tool.name for tool in snapshot}
    assert {name for name, prompt in prompts.items() if prompt.builtin} == BUILTIN


def test_설명의_hook_이름과_역할은_Python에_있어야_한다():
    # ②
    for prompt in catalog.tool_prompts().values():
        assert set(prompt.hooks) <= set(catalog.HOOKS)
        for param in prompt.params.values():
            if param.hook is not None:
                hook, _, role = param.hook.partition(":")
                assert hook in prompt.hooks
                assert role in catalog.HOOKS[hook].roles


def test_navigate만_쓰는_API는_스냅샷에_없어야_한다():
    # ③ 설계 2-3절 : 반려동물 등록·모든 삭제·회원정보·공동양육·관리자·인증·내부 API
    navigate_only = (
        ("POST", "/api/pets"),
        ("PUT", "/api/members/me"),
        ("PATCH", "/api/members/me"),
    )
    for tool in catalog.read_snapshot().tools:
        call = tool.call
        assert call.method != "DELETE"
        assert (call.method, call.path) not in navigate_only
        assert not call.path.startswith(("/api/admin", "/api/auth", "/internal"))
        # 공동양육자·보낸 초대 목록 읽기는 2-1절 READ 후보, 초대·수락·해제(쓰기)만 navigate
        assert call.method == "GET" or "caregiver" not in call.path
        assert "chat-rooms" not in call.path


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"schdl_knd_cd": "HLTC0057", "schdl_ymd": "2026-10-06"}, ["ckupTypeCd", "hsptlNm"]),
        ({"schdl_knd_cd": "HLTC0058", "schdl_ymd": "2026-10-06"}, ["schdlNm"]),
        ({"schdl_knd_cd": "HLTC0060"}, ["schdlDt", "hrInptYn", "schdlNm"]),
        ({}, ["schdlKndCd", "schdlDt", "hrInptYn"]),
    ],
)
def test_일정_도구는_Java_필수와_requiredIf로_빈_칸을_찾아야_한다(values, expected):
    # ④
    schedule = entry("draft_schedule")

    java = catalog.to_java(schedule, values) | {"petSn": 1}

    assert catalog.missing(schedule, java) == expected


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"care_artcl_nm": "산책", "care_zone_cd": "HLTC0036"}, []),
        ({"care_artcl_nm": "발톱", "care_zone_cd": "HLTC0037"}, ["careCycleCd"]),
        (
            {"care_artcl_nm": "약", "care_zone_cd": "HLTC0037", "care_cycle_cd": "HLTC0042"},
            ["cycleDrctInptDayCnt"],
        ),
        ({"care_zone_cd": "HLTC0036"}, ["careArtclNm"]),
    ],
)
def test_케어_항목_도구는_Java_필수와_requiredIf로_빈_칸을_찾아야_한다(values, expected):
    # ④
    care = entry("draft_care_item")

    java = catalog.to_java(care, values) | {"petSn": 1}

    assert catalog.missing(care, java) == expected


def test_LLM_도구_스키마에는_required가_없어야_한다():
    # ⑤ 필수라고 하면 LLM이 값을 지어낸다
    for name in REGISTER:
        assert "required" not in entry(name).definition["input_schema"]


# 칸 대응·hook


def test_date_hook은_날짜와_시간을_schdlDt와_hrInptYn으로_합쳐야_한다():
    schedule = entry("draft_schedule")

    with_time = catalog.to_java(schedule, {"schdl_ymd": "2026-10-06", "schdl_tm": "15:00"})
    date_only = catalog.to_java(schedule, {"schdl_ymd": "2026-10-06"})

    assert with_time == {"schdlDt": "2026-10-06T15:00:00", "hrInptYn": True}
    assert date_only == {"schdlDt": "2026-10-06T00:00:00", "hrInptYn": False}


def test_LLM_칸은_Java_DTO_칸_이름으로_바뀌어야_한다():
    care = entry("draft_care_item")

    java = catalog.to_java(
        care, {"care_artcl_nm": "약", "cycle_days": 10, "last_cmptn_ymd": "2026-10-01"}
    )

    assert java == {"careArtclNm": "약", "cycleDrctInptDayCnt": 10, "lastCmptnYmd": "2026-10-01"}


def test_LLM에_보이는_칸은_설명이_있는_칸뿐이어야_한다():
    # 반려동물(petSn)은 서버가 정하고, 메모·색상 등 설명 없는 Java 칸은 LLM에 보이지 않는다
    props = entry("draft_schedule").definition["input_schema"]["properties"]

    assert set(props) == {
        "schdl_knd_cd",
        "schdl_ymd",
        "schdl_tm",
        "ckup_type_cd",
        "hsptl_nm",
        "schdl_nm",
    }


def test_코드_칸은_Java_코드_값을_enum과_설명에_실어야_한다():
    prop = entry("draft_schedule").definition["input_schema"]["properties"]["schdl_knd_cd"]

    assert prop["anyOf"][0]["enum"] == ["HLTC0057", "HLTC0058", "HLTC0059", "HLTC0060"]
    assert "HLTC0058 미용·목욕" in prop["description"]


def test_Java_목록에_없는_코드는_도구_인자에서_비워야_한다():
    raw = fake_catalog_json()
    param = tool_of(raw, "draft_schedule")["params"]["schdlKndCd"]
    param["codes"] = [code for code in param["codes"] if code["cd"] != "HLTC0060"]
    tools.use_catalog(build(raw))

    call = tools.parse("draft_schedule", {"schdl_knd_cd": "HLTC0060", "schdl_nm": "산책"})

    assert call.args is not None
    assert call.args.model_dump(exclude_none=True) == {"schdl_nm": "산책"}


def test_숫자_칸은_Java_min_max를_input_schema_범위로_실어야_한다():
    prop = entry("draft_care_item").definition["input_schema"]["properties"]["cycle_days"]

    value = next(item for item in prop["anyOf"] if item.get("type") != "null")
    assert (value["minimum"], value["maximum"]) == (1, 9999)


@pytest.mark.parametrize("days", [0, 10000])
def test_주기가_Java_min_max_밖이면_도구_인자에서_비워야_한다(days):
    tools.use_catalog(build(fake_catalog_json()))

    call = tools.parse(
        "draft_care_item",
        {"care_artcl_nm": "발톱 깎기", "care_cycle_cd": "HLTC0042", "cycle_days": days},
    )

    assert call.args is not None
    assert call.args.model_dump(exclude_none=True) == {
        "care_artcl_nm": "발톱 깎기",
        "care_cycle_cd": "HLTC0042",
    }


def test_주기가_Java_min_max_안이면_도구_인자에_남아야_한다():
    tools.use_catalog(build(fake_catalog_json()))

    call = tools.parse(
        "draft_care_item",
        {"care_artcl_nm": "발톱 깎기", "care_cycle_cd": "HLTC0042", "cycle_days": 9999},
    )

    assert call.args is not None
    assert call.args.cycle_days == 9999


def test_가짜_공통코드는_룰_흐름의_코드와_같아야_한다():
    # 두 출처가 어긋나면 도구 흐름과 룰 흐름의 등록 결과가 달라진다
    codes = {group: {code["cd"] for code in items} for group, items in FAKE_CODES.items()}

    assert codes["HLTG19"] == rules.schedule_codes()
    assert codes["HLTG01"] == rules.checkup_codes()
    assert codes["HLTG13"] == {rules.ZONE_DAILY, rules.ZONE_PERIODIC}
    assert codes["HLTG15"] == rules.CYCLE_CODES


# 합치기(설계 4-2절 3번)


def test_설명이_없는_Java_도구는_싣지_않고_경고해야_한다(caplog):
    raw = fake_catalog_json()
    extra = copy.deepcopy(tool_of(raw, "draft_care_item")) | {"name": "draft_unknown"}
    raw["tools"].append(extra)

    with caplog.at_level(logging.WARNING, logger="app.chat.catalog"):
        built = build(raw)

    assert set(built.entries) == REGISTER | READ | ACTION
    assert "draft_unknown 설명 없음" in caplog.text


def test_Java_목록에_없는_설명_도구는_싣지_않고_경고해야_한다(caplog):
    raw = fake_catalog_json()
    raw["tools"] = [tool_of(raw, "draft_schedule")]

    with caplog.at_level(logging.WARNING, logger="app.chat.catalog"):
        built = build(raw)

    assert set(built.entries) == {"draft_schedule"}
    assert "draft_care_item Java 목록에 없음" in caplog.text


def test_설명에_없는_Java_필수_칸이_있으면_싣지_않아야_한다(caplog):
    raw = fake_catalog_json()
    tool_of(raw, "draft_schedule")["params"]["memoCn"]["required"] = True

    with caplog.at_level(logging.WARNING, logger="app.chat.catalog"):
        built = build(raw)

    assert "draft_schedule" not in built.entries
    assert "채울 수 없는 필수 칸 ['memoCn']" in caplog.text


def test_지원하지_않는_칸_타입이면_싣지_않아야_한다(caplog):
    raw = fake_catalog_json()
    tool_of(raw, "draft_care_item")["params"]["rprsIconId"]["type"] = "list"

    with caplog.at_level(logging.WARNING, logger="app.chat.catalog"):
        built = build(raw)

    assert "draft_care_item" not in built.entries
    assert "지원하지 않는 칸 타입 list" in caplog.text


# 기동(설계 4-2절 1·2번)


def test_Java_목록을_받으면_등록_도구를_실어야_한다():
    installed = asyncio.run(catalog.install(FakeToolCatalogClient()))
    assert installed is not None

    assert installed.source == "java"
    assert set(installed.entries) == REGISTER | READ | ACTION


def test_Java가_실패하면_스냅샷으로_뜨고_코드_칸_도구는_빼야_한다(caplog):
    with caplog.at_level(logging.WARNING, logger="app.chat.catalog"):
        installed = asyncio.run(catalog.install(FakeToolCatalogClient(fail=True)))
    assert installed is not None
    tools.use_catalog(installed)

    assert installed.source == "snapshot"
    assert set(installed.entries) == READ_WITHOUT_CODES | ACTION_WITHOUT_CODES
    assert {d["name"] for d in tools.tool_definitions()} == (
        BUILTIN | READ_WITHOUT_CODES | ACTION_WITHOUT_CODES
    )
    assert "Java 받기 실패" in caplog.text
    assert "공통코드 값 없음" in caplog.text


def test_Java_응답_모양이_다르면_스냅샷으로_떠야_한다():
    installed = asyncio.run(catalog.install(FakeToolCatalogClient(response={"tools": 1})))
    assert installed is not None

    assert installed.source == "snapshot"


def test_structureVersion이_스냅샷과_다르면_경고하고_Java_응답을_써야_한다(caplog):
    client = FakeToolCatalogClient(response=fake_catalog_json(structure_version="changed"))

    with caplog.at_level(logging.WARNING, logger="app.chat.catalog"):
        installed = asyncio.run(catalog.install(client))

    assert installed is not None
    assert installed.source == "java"
    assert set(installed.entries) == REGISTER | READ | ACTION
    assert "structureVersion 다름" in caplog.text


def test_Java_클라이언트는_내부_API_응답의_data를_읽어야_한다():
    requests: list[httpx2.Request] = []
    raw = fake_catalog_json()

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={"status": "success", "data": raw})

    backend = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    settings = Settings(_env_file=None, backend_base_url="http://backend.test")

    response = asyncio.run(catalog.JavaToolCatalogClient(backend, settings).fetch())

    assert str(requests[0].url) == "http://backend.test/internal/ai/tools"
    assert "cookie" not in requests[0].headers
    assert {tool.name for tool in response.tools} == {tool["name"] for tool in raw["tools"]}


def test_기동_때_켜져_있고_Java가_없으면_builtin_도구만_실어야_한다(monkeypatch):
    monkeypatch.setenv("BACKEND_BASE_URL", "")
    get_settings.cache_clear()
    tools.use_catalog(None)

    with TestClient(create_app()):
        names = {d["name"] for d in tools.tool_definitions()}

    get_settings.cache_clear()
    active = tools.active_catalog()
    assert names == BUILTIN | READ_WITHOUT_CODES | ACTION_WITHOUT_CODES
    assert active is not None and active.source == "snapshot"


# 한 턴(설계 4-3절) : 도구 흐름의 빈 칸은 Java 필수·requiredIf로


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


def register_card(client, java, tool: str, raw: dict, text: str) -> tuple[dict, dict]:
    use_agent(client, FakeToolAgent(tool, raw))
    use_extractor(client, Extractor({}))
    room = room_of(client, java, pet_sn=CHOCO)
    evs = events(send(client, room, text))
    return evs[0][1], evs[-1][1]


def test_케어_항목_도구에_반복_유형이_없으면_카드_빈_칸에_반복_유형이_있어야_한다(client, java):
    # SCR-AIM-012 2단계 ④ : 빈 칸은 카드 missing으로, 되물음 글은 저장하지 않음
    intent, done = register_card(
        client, java, "draft_care_item", {"care_artcl_nm": "발톱 깎기"}, "발톱 깎기 넣어줘"
    )

    assert intent["kind"] == "ACTION"
    assert done["action"]["input"]["careArtclNm"] == "발톱 깎기"
    assert done["action"]["missing"] == ["careZoneCd"]
    assert done["message"] is None


def test_병원_일정의_빈_칸은_Java_requiredIf로_정해야_한다(client, java):
    raw = {"schdl_knd_cd": "HLTC0057", "schdl_ymd": "2026-10-06"}

    _, done = register_card(client, java, "draft_schedule", raw, "6일에 병원 잡아줘")

    assert done["action"]["missing"] == ["ckupTypeCd", "hsptlNm"]


def test_Java_규칙이_바뀌면_되묻는_칸도_따라_바뀌어야_한다(client, java):
    # 빈 칸 판정의 출처가 Java 목록 : 병원명 requiredIf를 빼면 병원명을 묻지 않는다
    raw_catalog = fake_catalog_json()
    schedule = tool_of(raw_catalog, "draft_schedule")
    schedule["rules"] = [r for r in schedule["rules"] if r["requiredIf"]["field"] != "hsptlNm"]
    tools.use_catalog(build(raw_catalog))
    raw = {"schdl_knd_cd": "HLTC0057", "schdl_ymd": "2026-10-06"}

    _, done = register_card(client, java, "draft_schedule", raw, "6일에 병원 잡아줘")

    assert done["action"]["missing"] == ["ckupTypeCd"]


def test_빈_칸_LLM_이름은_Java_칸을_LLM_칸으로_되돌려야_한다():
    schedule = entry("draft_schedule")

    names = catalog.missing_llm(schedule, {})

    assert names == ["schdl_knd_cd", "schdl_ymd"]


def test_Java_주소_꼴이_틀려도_예외_없이_스냅샷으로_떠야_한다(caplog):
    settings = Settings(_env_file=None, backend_base_url="http://localhost:abc")
    client = catalog.JavaToolCatalogClient(httpx2.AsyncClient(), settings)

    with caplog.at_level(logging.WARNING, logger="app.chat.catalog"):
        loaded = asyncio.run(catalog.load(client))

    assert loaded.source == "snapshot"
    assert "주소 꼴 틀림 InvalidURL" in caplog.text


def test_skip_도구는_싣지_않고_경고_없이_info_로그만_남겨야_한다(caplog):
    with caplog.at_level(logging.INFO, logger="app.chat.catalog"):
        built = build(fake_catalog_json())

    assert not SKIP & set(built.entries)
    assert "설명 없음" not in caplog.text
    for name in SKIP:
        record = next(r for r in caplog.records if f"{name} 싣지 않음(" in r.getMessage())
        assert record.levelno == logging.INFO


def test_skip_항목에_다른_칸이_있으면_경고하고_싣지_않아야_한다(caplog):
    prompts = catalog.tool_prompts() | {
        "list_places": catalog.ToolPrompt.model_validate(
            {"skip": "좌표 칸", "description": "장소를 찾는다"}
        )
    }
    with caplog.at_level(logging.INFO, logger="app.chat.catalog"):
        built = catalog.build(
            catalog.ToolCatalogResponse.model_validate(fake_catalog_json()), prompts=prompts
        )

    assert "list_places" not in built.entries
    assert "list_places skip 항목에 다른 칸 description" in caplog.text


def test_설명도_skip도_없는_설명_항목은_만들_수_없어야_한다():
    with pytest.raises(ValueError):
        catalog.ToolPrompt.model_validate({"hooks": ["pet"]})
