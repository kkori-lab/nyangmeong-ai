import copy
import json
import logging

import pytest

from app.chat import rules, service, tools
from app.chat.clients import tool_system
from app.chat.rules import DATA_DIR, MoveType
from app.chat.schemas import RouteItem
from tests.chat.conftest import AJAX, as_member
from tests.chat.test_messages import MessageJava

SNAPSHOT = json.loads((DATA_DIR / "routes.snapshot.json").read_text(encoding="utf-8"))


def item(**fields) -> RouteItem:
    base = {
        "aiRoutMpngSn": 1,
        "trgtScrnNm": "가계부",
        "scrnId": "SCR-MYP-030",
        "scrnParamCn": None,
        "instKwrds": ["가계부"],
        "mvmnMthdCd": "AIMC0032",
        "rprsChipYn": False,
        "prrtSeq": 1,
    }
    return RouteItem.model_validate({**base, **fields})


def send(client, room_sn: int, cn: str):
    return client.post(f"/ai/conversations/{room_sn}/messages", json={"cnvrsCn": cn}, headers=AJAX)


def intent_of(res) -> dict:
    block = res.text.strip().split("\n\n")[0]
    lines = dict(line.split(": ", 1) for line in block.split("\n"))
    assert lines["event"] == "intent"
    return json.loads(lines["data"])


def row_of(routes: list[dict], scr_id: str) -> dict:
    return next(r for r in routes if r["scrnId"] == scr_id)


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(service.route_cache, "clock", lambda: now[0])
    return now


@pytest.fixture
def room(client, java: MessageJava) -> int:
    as_member(client, 1)
    return java.add_room(1, "제목")


# FN-AIM-004-09 Java 응답 -> 매핑표 행


def test_Java_응답_꼴을_그대로_읽는다():
    parsed = item(rprsChipYn=True, instKwrds=[" 가계부 ", "", "지출"])
    assert parsed.ai_rout_mpng_sn == 1
    assert parsed.rprs_chip_yn is True
    assert rules.route_rows([parsed])[0].keywords == ("가계부", "지출")


@pytest.mark.parametrize(
    ("param", "expected"),
    [
        ("cat=hospital", "?cat=hospital"),
        ("?cat=hotel", "?cat=hotel"),
        ("cat=…", None),
        ("", None),
        (None, None),
    ],
)
def test_화면_파라미터는_React에_주는_꼴로_자리표시는_없음으로(param, expected):
    assert rules.route_rows([item(scrnParamCn=param)])[0].param == expected


@pytest.mark.parametrize(
    ("code", "routable", "move_type"),
    [
        ("AIMC0032", True, MoveType.PAGE),
        ("AIMC0033", True, MoveType.MODAL),
        ("AIMC0034", False, MoveType.PAGE),
        ("AIMC0035", False, MoveType.PAGE),
        ("AIMC0036", False, MoveType.PAGE),
        ("AIMC9999", False, MoveType.PAGE),
    ],
)
def test_이동_방식_코드로_이동_여부를_정한다(code, routable, move_type):
    row = rules.route_rows([item(mvmnMthdCd=code)])[0]
    assert (row.routable, row.move_type) == (routable, move_type)


def test_화면_ID가_없는_행은_이동하지_않는다():
    assert not rules.route_rows([item(scrnId=None)])[0].routable


def test_행_번호는_매핑_번호이고_순서는_우선순위():
    rows = rules.route_rows(
        [item(aiRoutMpngSn=7, prrtSeq=2), item(aiRoutMpngSn=9, prrtSeq=1, trgtScrnNm="위")]
    )
    assert [(row.no, row.name) for row in rows] == [(9, "위"), (7, "가계부")]


def test_스냅샷은_Java_응답_꼴이고_읽은_표와_같다():
    assert rules.snapshot_routes() == rules.route_rows(
        [RouteItem.model_validate(r) for r in SNAPSHOT]
    )
    assert rules.routing_table() == rules.snapshot_routes()


# FN-AIM-004-09 관리자 수정 반영


def test_관리자가_더한_지시어로_룰_라우팅한다(client, java, room):
    row_of(java.routes, "SCR-HLT-002")["instKwrds"].append("물그릇")

    intent = intent_of(send(client, room, "물그릇"))

    assert (intent["kind"], intent["scrId"]) == ("ROUTE", "SCR-HLT-002")
    assert len(java.route_requests) == 1
    assert java.route_requests[0].headers["cookie"]


def test_관리자가_더한_지시어가_navigate_화면_목록과_프롬프트에_들어간다(client, java, room):
    target = row_of(java.routes, "SCR-HLT-002")
    target["instKwrds"].append("물그릇")
    send(client, room, "안녕")

    line = f"{target['aiRoutMpngSn']}. {target['trgtScrnNm']}: "
    assert any(s.startswith(line) and "물그릇" in s for s in tools.screen_list().split("\n"))
    assert "물그릇" in tool_system()


def test_사용_안_함인_행은_Java가_주지_않아_이동하지_않는다(client, java, room):
    gone = row_of(java.routes, "SCR-CMU-002")
    java.routes.remove(gone)

    intent = intent_of(send(client, room, "실종센터"))

    assert intent["kind"] != "ROUTE"
    assert all(row.no != gone["aiRoutMpngSn"] for row in rules.routing_table())


def test_이동하지_않는_행은_화면_목록과_navigate_enum에_없다(client, java, room):
    hidden = row_of(java.routes, "SCR-MYP-030")
    hidden["mvmnMthdCd"] = "AIMC0036"
    send(client, room, "안녕")

    navigate = next(d for d in tools.tool_definitions() if d["name"] == tools.NAVIGATE)
    enum = navigate["input_schema"]["properties"]["screen_num"]["enum"]
    assert hidden["aiRoutMpngSn"] not in enum
    assert f"\n{hidden['aiRoutMpngSn']}. " not in f"\n{tools.screen_list()}"


# 10초 캐시


def test_10초_안_두_번째_요청은_Java를_다시_부르지_않는다(client, java, room, clock):
    send(client, room, "안녕")
    clock[0] += 9.9
    send(client, room, "안녕")

    assert len(java.route_requests) == 1


def test_10초가_지나면_다시_받아_수정을_반영한다(client, java, room, clock):
    send(client, room, "안녕")
    row_of(java.routes, "SCR-HLT-002")["instKwrds"].append("물그릇")
    clock[0] += 10
    intent = intent_of(send(client, room, "물그릇"))

    assert len(java.route_requests) == 2
    assert intent["scrId"] == "SCR-HLT-002"


# Java 실패


def test_Java가_처음부터_실패하면_스냅샷으로_이동한다(client, java, room, caplog):
    java.routes_status = 0
    with caplog.at_level(logging.WARNING, logger="app.chat.service"):
        intent = intent_of(send(client, room, "가계부 보여 줘"))

    assert (intent["kind"], intent["scrId"]) == ("ROUTE", "SCR-MYP-030")
    assert rules.routing_table() == rules.snapshot_routes()
    assert "라우팅 매핑표 받기 실패: AppError" in caplog.text


def test_Java가_실패하면_마지막으로_받은_표를_쓴다(client, java, room, clock, caplog):
    row_of(java.routes, "SCR-HLT-002")["instKwrds"].append("물그릇")
    send(client, room, "안녕")
    java.routes_status = 500
    clock[0] += 11
    with caplog.at_level(logging.WARNING, logger="app.chat.service"):
        intent = intent_of(send(client, room, "물그릇"))

    assert intent["scrId"] == "SCR-HLT-002"
    assert "라우팅 매핑표 받기 실패" in caplog.text


def test_Java가_실패하면_10초_동안_다시_부르지_않는다(client, java, room, clock):
    java.routes_status = 0
    send(client, room, "안녕")
    send(client, room, "안녕")

    assert len(java.route_requests) == 1


def test_Java_응답_모양이_다르면_앞의_표를_유지한다(client, java, room):
    java.routes = [{"aiRoutMpngSn": "번호 아님"}]
    intent = intent_of(send(client, room, "가계부 보여 줘"))

    assert intent["scrId"] == "SCR-MYP-030"


def test_이동할_행이_하나도_없으면_앞의_표를_유지한다(client, java, room, caplog):
    java.routes = [{**r, "mvmnMthdCd": "AIMC0035"} for r in copy.deepcopy(SNAPSHOT)]
    with caplog.at_level(logging.WARNING, logger="app.chat.service"):
        send(client, room, "안녕")

    assert rules.routing_table() == rules.snapshot_routes()
    assert "이동할 행 없음" in caplog.text


# FN-AIM-002-04 안내서 바로가기는 화면 ID로


def test_안내서_바로가기는_행_번호가_바뀌어도_화면_ID로_이어진다():
    moved = [
        {**r, "aiRoutMpngSn": 900, "trgtScrnNm": "캐릭터"} if r["scrnId"] == "SCR-MYP-010" else r
        for r in SNAPSHOT
    ]
    rules.use_routes(rules.route_rows([RouteItem.model_validate(r) for r in moved]))

    shortcut = service._guide_shortcut("6-1")

    assert shortcut is not None
    assert (shortcut.scr_id, shortcut.scr_nm) == ("SCR-MYP-010", "캐릭터")


def test_안내서_화면_검색어는_같은_화면_행들의_지시어():
    rows = [r for r in copy.deepcopy(SNAPSHOT)]
    row_of(rows, "SCR-MYP-010")["instKwrds"].append("꾸밈방")
    rules.use_routes(rules.route_rows([RouteItem.model_validate(r) for r in rows]))

    chunk = rules.find_guide("6-1")

    assert chunk is not None and "꾸밈방" in chunk.screen_terms
    assert "6-1" in rules.search_guide("꾸밈방")
