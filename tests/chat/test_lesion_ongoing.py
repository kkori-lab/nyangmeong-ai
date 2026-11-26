"""분석 카드 뒤 이미 관찰 중인 항목에 기록 더하기 (SCR-AIM-013, 2026-11-26 추가 요청)
- lesion-card 글에 관찰 중인 항목(list_observation_items, 관찰중)을 보이고 카드는 그대로
- 돌려받은 관찰 항목 카드 + "○○에 추가해 줘" -> 관찰 기록 카드, 분석 메모·관찰 일시를 옮김"""

from datetime import datetime

import pytest

from app.chat import catalog, rules, tools
from tests.chat.conftest import AJAX
from tests.chat.fakes import FakeToolAgent, fake_catalog, fake_catalog_json
from tests.chat.test_action import send
from tests.chat.test_messages import MessageJava, events
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import CHOCO
from tests.chat.test_tools import room_of, use_agent

URL = "/ai/conversations/{}/lesion-card"
ITEMS_PATH = f"/api/pets/{CHOCO}/observation-items"
ONGOING = "HLTC0055"
ITEM_TOOL = "draft_observation_item"
CYCLE_TOOL = "draft_observation_cycle"
NOW = datetime(2026, 11, 26, 10, 5, 41)
MEMO = "눈 분석 참고: 충혈(높음), 진료 권장"
ITEMS = [
    {
        "obsrvArtclSn": 5,
        "obsrvArtclNm": "흰자 충혈",
        "obsrvRegnCdNm": "얼굴",
        "obsrvRegnDtlNm": "왼쪽 눈",
        "obsrvSttsCd": ONGOING,
        "lastCycle": {"obsrvDt": "2026-11-24T16:54:00"},
    },
    {"obsrvArtclSn": 6, "obsrvArtclNm": "등 혹", "obsrvSttsCd": ONGOING},
]


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def now(monkeypatch):
    monkeypatch.setattr(rules, "now_kst", lambda: NOW)


@pytest.fixture
def without_list():
    raw = fake_catalog_json()
    raw["tools"] = [t for t in raw["tools"] if t["name"] != "list_observation_items"]
    tools.use_catalog(catalog.build(catalog.ToolCatalogResponse.model_validate(raw)))
    yield
    tools.use_catalog(fake_catalog())


def eye(**extra) -> dict:
    return {
        "kind": "EYE",
        "petSn": CHOCO,
        "rslt": "ANALYZED",
        "grade": "VISIT",
        "findings": [{"lesionCd": "redness", "lesionNm": "충혈", "cnfdnc": "HIGH"}],
        "guide": ["눈을 비비지 않게 해 주세요."],
        "notice": "참고용 분석이에요.",
    } | extra


def post(client, room: int, body: dict):
    return client.post(URL.format(room), json=body, headers=AJAX)


def card_text(client, java, reader: FakeToolReader | None) -> tuple[dict, str]:
    if reader is not None:
        use_reader(client, reader)
    room = room_of(client, java, pet_sn=CHOCO)
    res = post(client, room, eye())
    assert res.status_code == 201
    data = res.json()["data"]
    return data, data["messages"][0]["cnvrsCn"]


# lesion-card 글


def test_관찰_중인_항목이_있으면_글에_이름과_안내를_넣고_카드는_그대로다(client, java):
    reader = FakeToolReader(ITEMS)

    data, text = card_text(client, java, reader)

    assert data["action"]["tool"] == ITEM_TOOL
    assert reader.calls == [(ITEMS_PATH, {"obsrvSttsCd": ONGOING})]
    lines = text.splitlines()
    head = lines.index("이미 관찰 중인 항목이 있어요.")
    assert lines[head + 1] == "- 흰자 충혈 (얼굴 왼쪽 눈·11월 24일)"
    assert lines[head + 2] == "- 등 혹"
    assert "'흰자 충혈에 추가해 줘'" in lines[head + 3]


def test_관찰_중인_항목은_세_줄까지만_보인다(client, java):
    many = [{"obsrvArtclNm": f"항목{n}", "obsrvSttsCd": ONGOING} for n in range(5)]

    _, text = card_text(client, java, FakeToolReader(many))

    assert "- 항목2" in text
    assert "- 항목3" not in text


def test_종료된_항목은_보이지_않는다(client, java):
    ended = [{"obsrvArtclNm": "다 나은 상처", "obsrvSttsCd": "HLTC0056"}]

    _, text = card_text(client, java, FakeToolReader(ended))

    assert "이미 관찰 중인 항목" not in text


@pytest.mark.parametrize("reader", [FakeToolReader(fail=True), FakeToolReader([])])
def test_읽기_실패나_0건이면_지금_글_그대로다(client, java, reader):
    _, base = card_text(client, java, FakeToolReader([]))

    data, text = card_text(client, java, reader)

    assert text == base
    assert "이미 관찰 중인 항목" not in text
    assert data["action"]["tool"] == ITEM_TOOL


def test_목록_도구가_없으면_읽지_않고_지금_글_그대로다(client, java, without_list):
    reader = FakeToolReader(ITEMS)

    data, text = card_text(client, java, reader)

    assert reader.calls == []
    assert "이미 관찰 중인 항목" not in text
    assert data["action"]["tool"] == ITEM_TOOL


@pytest.mark.parametrize(
    "body",
    [
        eye(
            grade="OBSERVE",
            findings=[{"lesionCd": "normal", "lesionNm": "이상 없음", "cnfdnc": "HIGH"}],
        ),
        eye(rslt="UNCLEAR", grade=None, findings=[]),
        eye(rslt="ERROR", grade=None, findings=[]),
    ],
)
def test_카드가_없으면_관찰_항목을_읽지_않는다(client, java, body):
    reader = use_reader(client, FakeToolReader(ITEMS))
    room = room_of(client, java, pet_sn=CHOCO)

    res = post(client, room, body)

    assert res.status_code == 201
    assert res.json()["data"]["action"] is None
    assert reader.calls == []


# 대화로 관찰 기록 카드로 바꾸기


def lesion_action(values: dict | None = None) -> dict:
    return {
        "tool": ITEM_TOOL,
        "input": {
            "petSn": CHOCO,
            "obsrvArtclNm": "충혈",
            "obsrvRegnCd": "HLTC0044",
            "obsrvDt": "2026-11-26T10:05:00",
            "memoCn": MEMO,
        }
        | (values or {}),
    }


def add_to_item(client, java, raw: dict, action: dict) -> dict:
    use_reader(client, FakeToolReader(ITEMS))
    use_agent(
        client,
        FakeToolAgent("list_observation_items", {}, follow_tool=CYCLE_TOOL, follow_raw=raw),
    )
    room = room_of(client, java, pet_sn=CHOCO)
    evs = events(send(client, room, "흰자 충혈에 추가해 줘", action))
    return evs[-1][1]["action"]


def test_분석_카드_뒤_관찰_기록_카드로_바뀌면_분석_메모와_관찰_일시를_옮긴다(client, java):
    action = add_to_item(client, java, {"obsrv_artcl_sn": 5}, lesion_action())

    assert action["tool"] == CYCLE_TOOL
    assert action["input"]["obsrvArtclSn"] == 5
    assert action["input"]["memoCn"] == MEMO
    assert action["input"]["obsrvDt"] == "2026-11-26T10:05:00"
    assert action["input"]["petSn"] == CHOCO
    assert "obsrvArtclNm" not in action["input"]
    assert action["missing"] == ["file"]


def test_회원이_메모를_말하면_그_메모를_쓴다(client, java):
    raw = {"obsrv_artcl_sn": 5, "memo_cn": "어제보다 덜 빨개요"}

    action = add_to_item(client, java, raw, lesion_action())

    assert action["input"]["memoCn"] == "어제보다 덜 빨개요"


def test_돌려받은_카드가_다른_도구면_옮기지_않는다(client, java):
    other = {"tool": "draft_schedule", "input": {"petSn": CHOCO, "memoCn": MEMO}}

    action = add_to_item(client, java, {"obsrv_artcl_sn": 5}, other)

    assert action["tool"] == CYCLE_TOOL
    assert "memoCn" not in action["input"]


# 추가-1 (2026-11-26) : 사진 칸만 빈 카드에 확인 말이면 "사진이 없으면…" 문구 없이 실행


def test_사진_칸만_빈_카드에_확인_말이면_사진_안내_문구_없이_실행한다(client, java):
    room = room_of(client, java, pet_sn=CHOCO)

    done = events(send(client, room, "등록해 줘", lesion_action()))[-1][1]

    assert done["execute"] is True
    assert done["message"]["cnvrsCn"] == "사진과 함께 등록할게요."
    assert "사진이 없으면" not in done["message"]["cnvrsCn"]
