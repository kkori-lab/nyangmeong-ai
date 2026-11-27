"""대화창 가계부 영수증 지출 등록 카드 (SCR-AIM-013 expense-card, 2026-11-27 추가 요청)
- image-intent EXPENSE_RECEIPT -> /ai/receipts(가계부 AIMC0027) -> POST …/{방}/expense-card
- 결과 요약 AI 메시지 + 지출 등록 확인 카드(draft_expense), 카드는 저장하지 않음"""

import pytest

from app.chat import catalog, rules, tools
from app.chat.schemas import ROLE_AI, ROLE_USER
from app.chat.service import EXPENSE_NO_TOOL, EXPENSE_TOOL
from tests.chat.conftest import AJAX
from tests.chat.fakes import FakeToolAgent, fake_catalog, fake_catalog_json
from tests.chat.test_action import send
from tests.chat.test_messages import MessageJava, events
from tests.chat.test_register import CHOCO, TODAY
from tests.chat.test_tools import room_of, use_agent

URL = "/ai/conversations/{}/expense-card"
RECPT = 41
OCR = {
    "hsptlNm": None,
    "expndPlcusNm": "사료왕",
    "expndClsfCd": "MYPC0013",
    "ckupYmd": "2026-11-26",
    "recptAmt": 33000,
    "btmDscntAmt": 1000,
    "sections": [
        {
            "sectionNm": None,
            "items": [
                {"itemNm": "연어 사료 2kg", "itemAmt": 28000},
                {"itemNm": " 닭가슴살 간식 ", "itemAmt": 5000},
            ],
            "drugs": [],
        }
    ],
}


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


@pytest.fixture
def without_tool():
    raw = fake_catalog_json()
    raw["tools"] = [tool for tool in raw["tools"] if tool["name"] != EXPENSE_TOOL]
    tools.use_catalog(catalog.build(catalog.ToolCatalogResponse.model_validate(raw)))
    yield
    tools.use_catalog(fake_catalog())


def post(client, room: int, body: dict):
    return client.post(URL.format(room), json=body, headers=AJAX)


def recognized(ocr: dict = OCR, **extra) -> dict:
    return {"result": "RECOGNIZED", "recptSn": RECPT, "ocr": ocr} | extra


def saved(java: MessageJava, room: int) -> list[tuple[str, str]]:
    return [(m["roleCd"], m["cnvrsCn"]) for m in java.rooms[room]["messages"][1:]]


def test_인식_결과로_지출_등록_카드를_준다(client, java):
    room = room_of(client, java)

    res = post(client, room, recognized(petSn=CHOCO))

    assert res.status_code == 201
    data = res.json()["data"]
    action = data["action"]
    assert action["tool"] == EXPENSE_TOOL
    assert action["call"] == {"method": "POST", "path": "/api/expenses"}
    values = action["input"]
    assert values["recptSn"] == RECPT
    assert values["expndYmd"] == "2026-11-26"
    assert values["expndPlcusNm"] == "사료왕"
    assert values["expndClsfCd"] == "MYPC0013"
    assert values["dtlMttr"] == "연어 사료 2kg, 닭가슴살 간식"
    # recptAmt는 이미 할인 뒤 결제 금액
    assert values["lines"][0]["expndAmt"] == 33000
    assert values["lines"][0]["petSn"] == CHOCO
    # 입력 방법은 코드 목록의 "OCR" (추가-2)
    assert values["expndInptMthCd"] == "MYPC0020"
    assert action["missing"] == []
    assert data["noCardReason"] is None
    text = data["messages"][0]["cnvrsCn"]
    assert text.startswith(
        "가계부 영수증 분석 — 사료왕, 11월 26일, 33,000원\n가계부에 이렇게 적을까요?"
    )
    assert saved(java, room) == [(ROLE_AI, text)]


def test_회원_반려동물이_아니거나_없으면_공용_지출(client, java):
    room = room_of(client, java)

    for body in (recognized(), recognized(petSn=999)):
        values = post(client, room, body).json()["data"]["action"]["input"]
        assert "petSn" not in values["lines"][0]


def test_못_읽은_칸은_카드에서_비워_되묻는다(client, java):
    room = room_of(client, java)
    ocr = OCR | {"ckupYmd": None, "expndClsfCd": "XXXX9999", "recptAmt": None, "sections": []}

    data = post(client, room, recognized(ocr)).json()["data"]

    values = data["action"]["input"]
    assert "expndYmd" not in values
    assert "expndClsfCd" not in values
    assert "dtlMttr" not in values
    assert "expndAmt" not in values["lines"][0]
    assert {"expndYmd", "expndClsfCd"} <= set(data["action"]["missing"])
    assert data["messages"][0]["cnvrsCn"].startswith("가계부 영수증 분석 — 사료왕\n")


def test_사용처가_없으면_상호_자리에_병원_이름(client, java):
    room = room_of(client, java)
    ocr = OCR | {"expndPlcusNm": None, "hsptlNm": "메이 동물병원"}

    values = post(client, room, recognized(ocr)).json()["data"]["action"]["input"]

    assert values["expndPlcusNm"] == "메이 동물병원"


@pytest.mark.parametrize(
    ("result", "summary"),
    [
        ("FAILED", "가계부 영수증 분석 — 영수증을 읽지 못했어요"),
        ("ERROR", "가계부 영수증 분석 — 일시적인 오류로 분석하지 못했어요"),
        ("CANCELED", "가계부 영수증 분석 — 취소했어요"),
    ],
)
def test_인식이_아니면_요약만(client, java, result, summary):
    room = room_of(client, java)

    data = post(client, room, {"result": result, "cnvrsCn": "가계부에 넣어줘"}).json()["data"]

    assert data["action"] is None
    assert data["noCardReason"] is None
    assert saved(java, room) == [(ROLE_USER, "가계부에 넣어줘"), (ROLE_AI, summary)]


def test_도구가_없으면_카드_없이_안내(client, java, without_tool):
    room = room_of(client, java)

    data = post(client, room, recognized()).json()["data"]

    assert data["action"] is None
    assert data["noCardReason"] == "NO_TOOL"
    assert data["messages"][0]["cnvrsCn"].endswith(EXPENSE_NO_TOOL)


@pytest.mark.parametrize(
    "body",
    [
        {"result": "MAYBE"},
        {"result": "RECOGNIZED", "ocr": OCR},
        {"result": "RECOGNIZED", "recptSn": RECPT},
        {"result": "FAILED", "cnvrsCn": "   "},
    ],
)
def test_요청_형식_오류는_400(client, java, body):
    room = room_of(client, java)

    res = post(client, room, body)

    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"


def test_남의_대화는_404(client, java):
    room_of(client, java)

    res = post(client, 9999, recognized())

    assert res.status_code == 404


# 입력 방법 (추가-2) : OCR 코드, 대화로 고쳐도 유지


@pytest.fixture
def without_ocr_code():
    raw = fake_catalog_json()
    for tool in raw["tools"]:
        param = tool["params"].get("expndInptMthCd")
        if param and param.get("codes"):
            param["codes"] = [code for code in param["codes"] if code["nm"] != "OCR"]
    tools.use_catalog(catalog.build(catalog.ToolCatalogResponse.model_validate(raw)))
    yield
    tools.use_catalog(fake_catalog())


def test_코드_목록에_OCR이_없으면_도구의_고정_값(client, java, without_ocr_code):
    room = room_of(client, java)

    values = post(client, room, recognized()).json()["data"]["action"]["input"]

    assert values["expndInptMthCd"] == "MYPC0019"


def test_영수증_지출_카드를_대화로_고쳐도_OCR_입력_방법을_유지한다(client, java):
    use_agent(client, FakeToolAgent(EXPENSE_TOOL, {"expnd_amt": 30000}))
    room = room_of(client, java)
    card = post(client, room, recognized()).json()["data"]["action"]
    prior = {"tool": EXPENSE_TOOL, "input": card["input"]}

    action = events(send(client, room, "3만원으로 바꿔 줘", action=prior))[-1][1]["action"]

    assert action["input"]["expndInptMthCd"] == "MYPC0020"
    assert action["input"]["lines"][0]["expndAmt"] == 30000


def test_돌려받은_카드의_입력_방법이_목록_밖이면_고정_값(client, java):
    use_agent(client, FakeToolAgent(EXPENSE_TOOL, {"expnd_amt": 30000}))
    room = room_of(client, java)
    card = post(client, room, recognized()).json()["data"]["action"]
    prior = {"tool": EXPENSE_TOOL, "input": card["input"] | {"expndInptMthCd": "XXXX0000"}}

    action = events(send(client, room, "3만원으로 바꿔 줘", action=prior))[-1][1]["action"]

    assert action["input"]["expndInptMthCd"] == "MYPC0019"
