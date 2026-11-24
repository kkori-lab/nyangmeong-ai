"""대화창 피부·눈 분석 결과 카드 (SCR-AIM-013, 2026-11-24 추가 요청)
- POST /ai/conversations/{방}/lesion-card : 결과 요약 AI 메시지 + 지속 관찰 항목 확인 카드
- 카드 도구 draft_observation_item(백엔드 PR #295), 사진은 React가 카드에 첨부"""

from datetime import datetime

import pytest

from app.chat import catalog, rules, tools
from app.chat.schemas import ROLE_AI
from app.chat.service import ACTION_ASK_CONFIRM, LESION_NO_TOOL
from tests.chat.conftest import AJAX
from tests.chat.fakes import fake_catalog, fake_catalog_json
from tests.chat.test_messages import MessageJava
from tests.chat.test_register import CHOCO
from tests.chat.test_tools import room_of

URL = "/ai/conversations/{}/lesion-card"
TOOL = "draft_observation_item"
FACE = "HLTC0044"
NOTICE = "참고용 분석이에요. 정확한 진단은 수의사와 상담해 주세요."
NOW = datetime(2026, 11, 24, 13, 50, 37)


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def now(monkeypatch):
    monkeypatch.setattr(rules, "now_kst", lambda: NOW)


@pytest.fixture
def without_tool():
    raw = fake_catalog_json()
    raw["tools"] = [tool for tool in raw["tools"] if tool["name"] != TOOL]
    tools.use_catalog(catalog.build(catalog.ToolCatalogResponse.model_validate(raw)))
    yield
    tools.use_catalog(fake_catalog())


def post(client, room: int, body: dict):
    return client.post(URL.format(room), json=body, headers=AJAX)


def analyzed(kind: str = "SKIN", **extra) -> dict:
    return {
        "kind": kind,
        "petSn": CHOCO,
        "rslt": "ANALYZED",
        "grade": "VISIT",
        "findings": [
            {"lesionCd": "hair_loss", "lesionNm": "탈모", "cnfdnc": "HIGH"},
            {"lesionCd": "dandruff", "lesionNm": "비듬", "cnfdnc": "MEDIUM"},
        ],
        "guide": ["털이 빠진 곳을 사진으로 남겨 두세요."],
        "notice": NOTICE,
        "ruleVersion": "2026-11-24-draft",
    } | extra


def saved(java: MessageJava, room: int) -> list[tuple[str, str]]:
    return [(m["roleCd"], m["cnvrsCn"]) for m in java.rooms[room]["messages"][1:]]


def test_피부_판정이면_요약을_저장하고_부위를_비운_관찰_항목_카드를_준다(client, java):
    room = room_of(client, java, pet_sn=CHOCO)

    res = post(client, room, analyzed())

    assert res.status_code == 201
    data = res.json()["data"]
    action = data["action"]
    assert action["tool"] == TOOL
    assert action["call"] == {
        "method": "POST",
        "path": "/api/pets/{petSn}/observation-items",
        "contentType": "multipart/form-data",
    }
    assert action["input"]["petSn"] == CHOCO
    assert action["input"]["obsrvArtclNm"] == "탈모"
    assert action["input"]["obsrvDt"] == "2026-11-24T13:50:00"
    assert action["input"]["memoCn"] == (
        "피부 분석 참고: 탈모(높음)·비듬(보통), 진료 권장, 규칙 2026-11-24-draft"
    )
    assert "obsrvRegnCd" not in action["input"]
    assert action["missing"] == ["obsrvRegnCd", "file"]
    assert "file" in action["params"]
    text = data["messages"][0]["cnvrsCn"]
    assert text.startswith("피부 분석 — 진료 권장\n- 탈모 (확신도 높음)\n- 비듬 (확신도 보통)\n")
    assert "털이 빠진 곳을 사진으로 남겨 두세요." in text
    assert NOTICE in text
    assert "초코의 지속 관찰 항목으로 남길까요?" in text
    assert "file" not in text
    assert "부위" in text.splitlines()[-1]
    assert saved(java, room) == [(ROLE_AI, text)]


def test_눈_판정이면_부위를_얼굴로_채운다(client, java):
    room = room_of(client, java, pet_sn=CHOCO)
    findings = [{"lesionCd": "discharge", "lesionNm": "눈곱", "cnfdnc": "HIGH"}]

    data = post(client, room, analyzed("EYE", grade="OBSERVE", findings=findings)).json()["data"]

    action = data["action"]
    assert action["input"]["obsrvRegnCd"] == FACE
    assert action["input"]["obsrvArtclNm"] == "눈곱"
    assert action["missing"] == ["file"]
    text = data["messages"][0]["cnvrsCn"]
    assert text.startswith("눈 분석 — 지켜보기\n- 눈곱 (확신도 높음)")
    assert "부위는 얼굴로 골라 두었어요." in text
    assert text.endswith(ACTION_ASK_CONFIRM)


def test_긴_이름과_메모는_Java_길이로_자른다(client, java):
    room = room_of(client, java, pet_sn=CHOCO)
    findings = [{"lesionCd": "lump", "lesionNm": "가" * 40, "cnfdnc": "HIGH"}] * 3

    data = post(client, room, analyzed(findings=findings, ruleVersion="v" * 40)).json()["data"]

    values = data["action"]["input"]
    assert len(values["obsrvArtclNm"]) <= 40
    assert len(values["memoCn"]) <= 200


def test_이상_없음만이면_카드_없이_요약만_저장한다(client, java):
    room = room_of(client, java, pet_sn=CHOCO)
    findings = [{"lesionCd": "normal", "lesionNm": "이상 없음", "cnfdnc": "HIGH"}]

    data = post(client, room, analyzed(grade="OBSERVE", findings=findings)).json()["data"]

    assert data["action"] is None
    text = data["messages"][0]["cnvrsCn"]
    assert text.startswith("피부 분석 — 지켜보기\n- 이상 없음 (확신도 높음)")
    assert "지속 관찰" not in text


@pytest.mark.parametrize(
    ("kind", "rslt", "head"),
    [
        ("SKIN", "NOT_PET_SKIN", "피부 분석 — 반려동물 피부 사진이 아니에요"),
        ("EYE", "NOT_PET_EYE", "눈 분석 — 반려동물 눈 사진이 아니에요"),
        ("SKIN", "UNCLEAR", "피부 분석 — 사진으로 판단하기 어려워요"),
    ],
)
def test_판정하지_못하면_안내와_고지만_저장한다(client, java, kind, rslt, head):
    room = room_of(client, java, pet_sn=CHOCO)
    body = {"kind": kind, "petSn": CHOCO, "rslt": rslt, "guide": ["다시 찍어 주세요."]}

    data = post(client, room, body | {"notice": NOTICE}).json()["data"]

    assert data == {"messages": [data["messages"][0]], "action": None}
    assert saved(java, room) == [(ROLE_AI, f"{head}\n다시 찍어 주세요.\n{NOTICE}")]


@pytest.mark.parametrize(
    ("rslt", "text"),
    [
        ("ERROR", "눈 분석 — 일시적인 오류로 분석하지 못했어요"),
        ("CANCELED", "눈 분석 — 취소했어요"),
    ],
)
def test_분석_실패와_취소는_한_줄만_저장한다(client, java, rslt, text):
    room = room_of(client, java, pet_sn=CHOCO)

    res = post(client, room, {"kind": "EYE", "petSn": CHOCO, "rslt": rslt})

    assert res.status_code == 201
    assert res.json()["data"]["action"] is None
    assert saved(java, room) == [(ROLE_AI, text)]


def test_관찰_도구가_도구_목록에_없으면_직접_남기라고_안내한다(client, java, without_tool):
    room = room_of(client, java, pet_sn=CHOCO)

    data = post(client, room, analyzed()).json()["data"]

    assert data["action"] is None
    assert data["messages"][0]["cnvrsCn"].endswith(LESION_NO_TOOL)
    assert LESION_NO_TOOL == "건강기록의 지속 관찰에서 직접 남길 수 있어요."


def test_남의_방이면_Java_404를_그대로_준다(client, java):
    room_of(client, java)
    other = java.add_room(2, "남의 방", cn="안녕")

    res = post(client, other, analyzed())

    assert res.status_code == 404
    assert len(java.rooms[other]["messages"]) == 1


@pytest.mark.parametrize(
    "body",
    [
        analyzed(kind="BODY"),
        analyzed(rslt="FAILED"),
        analyzed(petSn=0),
        {"kind": "SKIN", "rslt": "ERROR"},
        analyzed(grade=None),
        analyzed(findings=[{"lesionCd": "lump", "lesionNm": "혹", "cnfdnc": "HIGH"}] * 4),
        analyzed(findings=[{"lesionCd": "lump", "lesionNm": "혹", "cnfdnc": "LOW"}]),
    ],
)
def test_허용값_밖이면_400(client, java, body):
    room = room_of(client, java, pet_sn=CHOCO)

    res = post(client, room, body)

    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"
    assert saved(java, room) == []
