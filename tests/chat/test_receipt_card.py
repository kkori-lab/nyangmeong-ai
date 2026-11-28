"""대화창 영수증 저장 카드 (SCR-AIM-013 receipt-card, 2026-11-27 추가 요청)
- POST /ai/conversations/{방}/receipt-card : 결과 요약 AI 메시지 + 영수증 저장 확인 카드
- 카드 값은 본창 영수증 확인 모달(FN-AIM-009, 프론트 receiptUtils.js)과 같은 규칙
- 저장 전 확인(Java save-check)은 가짜 checker로"""

import pytest

from app.chat import catalog, repository, rules, tools
from app.chat.repository import PetInfo
from app.chat.schemas import ROLE_AI, ROLE_USER, ReceiptOcr
from app.chat.service import (
    RECEIPT_CHECK_FAILED,
    RECEIPT_NEEDS_FORM,
    RECEIPT_NO_TOOL,
    receipt_rows,
    split_discount,
)
from app.core.response import AppError
from tests.chat.conftest import AJAX
from tests.chat.fakes import (
    RECEIPT_TOOL,
    FakeCardReplyAgent,
    FakeToolAgent,
    fake_catalog,
    fake_catalog_json,
)
from tests.chat.test_action import send
from tests.chat.test_messages import MessageJava, events
from tests.chat.test_register import CHOCO, MUNG, TODAY
from tests.chat.test_tools import room_of, use_agent

URL = "/ai/conversations/{}/receipt-card"
RECPT = 31
# 구역 없는 영수증 : 품목 2개 + 약 2개(하나는 용법을 못 읽음), 하단 할인 1,000원
NO_SECTION = {
    "hsptlNm": "메이 동물병원",
    "ckupYmd": "2026-09-28",
    "recptAmt": 44000,
    "btmDscntAmt": 1000,
    "sections": [
        {
            "sectionNm": None,
            "items": [
                {"itemNm": "진찰료", "itemAmt": 15000},
                {"itemNm": "피부 검사", "itemAmt": 20000},
            ],
            "drugs": [
                {"mdcnNm": "알러지약", "mdcnDays": 7, "mdcnUsage": "1일 2회", "mdcnAmt": 6000},
                {"mdcnNm": "연고", "mdcnDays": 5, "mdcnUsage": "환부에 바름", "mdcnAmt": 4000},
            ],
        }
    ],
}
# 구역 있는 영수증 : 초코·뭉치 구역, 구역 할인은 그 구역에서, 하단 할인 1,001원은 비율로
SECTIONS = {
    "hsptlNm": "튼튼 병원",
    "ckupYmd": "2026-09-20",
    "recptAmt": 60000,
    "btmDscntAmt": 1001,
    "sections": [
        {
            "sectionNm": "초 코",
            "sbttlAmt": 31000,
            "dscntAmt": 1000,
            "items": [{"itemNm": "예방접종", "itemAmt": 31000}],
            "drugs": [{"mdcnNm": "구충제", "mdcnDays": 3, "mdcnUsage": "1일 1회"}],
        },
        {
            "sectionNm": "뭉치",
            "sbttlAmt": 30000,
            "items": [{"itemNm": "진찰료", "itemAmt": 30000}],
            "drugs": [],
        },
    ],
}


class FakeChecker:
    """[가짜 저장 전 확인] data : 돌려줄 data, fail : 502. 받은 영수증 번호·본문 기록"""

    def __init__(self, data: dict | None = None, fail: bool = False) -> None:
        self.data = data or {"duplicateExpenses": [], "nearbySchedules": []}
        self.fail = fail
        self.calls: list[tuple[int, dict]] = []

    async def check(self, recpt_sn: int, body: dict) -> object:
        self.calls.append((recpt_sn, body))
        if self.fail:
            raise AppError("EXTERNAL_API_ERROR", 502, "외부 서비스 호출에 실패했습니다.")
        return self.data


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


@pytest.fixture
def checker(client) -> FakeChecker:
    return use_checker(client, FakeChecker())


@pytest.fixture
def without_tool():
    raw = fake_catalog_json()
    raw["tools"] = [tool for tool in raw["tools"] if tool["name"] != RECEIPT_TOOL]
    tools.use_catalog(catalog.build(catalog.ToolCatalogResponse.model_validate(raw)))
    yield
    tools.use_catalog(fake_catalog())


def use_checker(client, checker: FakeChecker) -> FakeChecker:
    client.app.dependency_overrides[repository.get_receipt_save_checker] = lambda: checker
    return checker


def post(client, room: int, body: dict):
    return client.post(URL.format(room), json=body, headers=AJAX)


def recognized(ocr: dict = NO_SECTION, **extra) -> dict:
    return {"result": "RECOGNIZED", "recptSn": RECPT, "petSn": CHOCO, "ocr": ocr} | extra


def saved(java: MessageJava, room: int) -> list[tuple[str, str]]:
    return [(m["roleCd"], m["cnvrsCn"]) for m in java.rooms[room]["messages"][1:]]


# 카드 값 규칙 (receiptUtils.js와 같음)


def test_하단_할인은_소계_비율로_나누고_남는_금액은_마지막_줄에_붙는다():
    assert split_discount([20000, 10000], 1001) == [19333, 9666]
    assert split_discount([20000, None], 1000) == [19000, None]
    assert split_discount([None], 500) == [None]
    assert split_discount([30000], 0) == [30000]


def test_구역_이름이_회원_반려동물과_안_맞으면_줄_배정이_필요하다():
    pets = [PetInfo(CHOCO, "초코", ()), PetInfo(MUNG, "뭉치", ())]
    ocr = ReceiptOcr.model_validate(
        SECTIONS | {"sections": [SECTIONS["sections"][0] | {"sectionNm": "보리"}]}
    )
    assert receipt_rows(ocr, pets, CHOCO, TODAY) is None
    no_pet = ReceiptOcr.model_validate(NO_SECTION)
    assert receipt_rows(no_pet, pets, None, TODAY) is None


# 구역 없는 영수증


def test_구역_없는_영수증은_한_줄에_전부_싣고_검진_종류만_비운다(client, java, checker):
    room = room_of(client, java, pet_sn=CHOCO)

    res = post(client, room, recognized())

    assert res.status_code == 201
    data = res.json()["data"]
    action = data["action"]
    assert action["tool"] == RECEIPT_TOOL
    assert action["call"] == {"method": "POST", "path": "/api/receipts/{recptSn}/save"}
    assert action["input"] == {
        "recptSn": RECPT,
        "hsptlNm": "메이 동물병원",
        "expndPlcusNm": "메이 동물병원",
        "ckupYmd": "2026-09-28",
        "pets": [
            {
                "petSn": CHOCO,
                "ckupCn": "진찰료, 피부 검사",
                # 품목·약 합 45,000 − 하단 할인 1,000
                "amt": 44000,
                "expenseYn": True,
                "drugs": [
                    {
                        "mdcnNm": "알러지약",
                        "mdcnBgngYmd": "2026-09-28",
                        "mdcnEndYmd": "2026-10-04",
                        "dayMdcnNmtm": 2,
                        "prscSttsCd": "HLTC0010",
                    }
                ],
            }
        ],
    }
    assert action["missing"] == ["pets[0].ckupTypeCd"]
    assert data["noCardReason"] is None
    text = data["messages"][0]["cnvrsCn"]
    assert text.startswith("영수증 분석 — 메이 동물병원, 9월 28일, 44,000원\n이렇게 저장할까요?")
    assert "- 초코 · 44,000원 · 약 1건" in text
    assert "처방약 1건은 건강 일지에서 직접 입력해 주세요." in text
    assert "검진 종류" in text
    assert "등록" not in text
    assert checker.calls == [
        (
            RECPT,
            {"ckupYmd": "2026-09-28", "pets": [{"petSn": CHOCO, "amt": 44000, "expenseYn": True}]},
        )
    ]
    assert saved(java, room) == [(ROLE_AI, text)]


def test_함께_보낸_글은_사용자_메시지로_먼저_저장한다(client, java, checker):
    room = room_of(client, java, pet_sn=CHOCO)

    res = post(client, room, recognized(cnvrsCn="이거 저장해 줘"))

    messages = res.json()["data"]["messages"]
    assert [(m["roleCd"], m["cnvrsCn"]) for m in messages][0] == (ROLE_USER, "이거 저장해 줘")
    assert [role for role, _ in saved(java, room)] == [ROLE_USER, ROLE_AI]


def test_종료일이_오늘보다_앞인_약은_종료로_싣는다(client, java, checker):
    room = room_of(client, java, pet_sn=CHOCO)
    ocr = NO_SECTION | {"ckupYmd": "2026-09-01"}

    action = post(client, room, recognized(ocr)).json()["data"]["action"]

    drug = action["input"]["pets"][0]["drugs"][0]
    assert (drug["mdcnEndYmd"], drug["prscSttsCd"]) == ("2026-09-07", "HLTC0011")


def test_검진일이_없으면_약은_싣지_않고_저장_전_확인도_부르지_않는다(client, java, checker):
    room = room_of(client, java, pet_sn=CHOCO)
    ocr = NO_SECTION | {"ckupYmd": None}

    data = post(client, room, recognized(ocr)).json()["data"]

    action = data["action"]
    assert "ckupYmd" not in action["input"]
    assert "drugs" not in action["input"]["pets"][0]
    assert "ckupYmd" in action["missing"]
    assert "처방약 2건은" in data["messages"][0]["cnvrsCn"]
    assert checker.calls == []


# 구역 있는 영수증


def test_구역마다_이름이_같은_반려동물_줄로_싣고_할인을_나눈다(client, java, checker):
    room = room_of(client, java, pet_sn=CHOCO)

    data = post(client, room, recognized(SECTIONS, petSn=None)).json()["data"]

    pets = data["action"]["input"]["pets"]
    assert [(p["petSn"], p["ckupCn"], p["amt"]) for p in pets] == [
        # 소계 30,000(31,000 − 구역 할인 1,000), 30,000 : 하단 1,001을 500·501로
        (CHOCO, "예방접종", 29500),
        (MUNG, "진찰료", 29499),
    ]
    assert pets[0]["drugs"][0]["mdcnEndYmd"] == "2026-09-22"
    assert "drugs" not in pets[1]
    assert data["action"]["missing"] == ["pets[0].ckupTypeCd", "pets[1].ckupTypeCd"]
    text = data["messages"][0]["cnvrsCn"]
    assert "- 초코 · 29,500원 · 약 1건" in text
    assert "- 뭉치 · 29,499원" in text


def test_같은_아이의_구역이_여럿이면_한_줄로_합친다(client, java, checker):
    room = room_of(client, java, pet_sn=CHOCO)
    second = {"sectionNm": "초코", "sbttlAmt": 10000, "items": [{"itemNm": "주사"}], "drugs": []}
    ocr = SECTIONS | {"btmDscntAmt": 0, "sections": [SECTIONS["sections"][0], second]}

    pets = post(client, room, recognized(ocr)).json()["data"]["action"]["input"]["pets"]

    assert len(pets) == 1
    assert (pets[0]["petSn"], pets[0]["ckupCn"], pets[0]["amt"]) == (CHOCO, "예방접종, 주사", 40000)


def test_구역_이름이_안_맞으면_카드_없이_모달로_보낸다(client, java, checker):
    room = room_of(client, java, pet_sn=CHOCO)
    ocr = SECTIONS | {"sections": [SECTIONS["sections"][0] | {"sectionNm": "보리"}]}

    data = post(client, room, recognized(ocr)).json()["data"]

    assert data["action"] is None
    assert data["noCardReason"] == "NEEDS_FORM"
    assert (
        data["messages"][0]["cnvrsCn"]
        == f"영수증 분석 — 튼튼 병원, 9월 20일, 60,000원\n{RECEIPT_NEEDS_FORM}"
    )
    assert checker.calls == []


def test_구역_없는_영수증에_반려동물이_없으면_모달로_보낸다(client, java, checker):
    room = room_of(client, java)

    data = post(client, room, recognized(petSn=None)).json()["data"]

    assert (data["action"], data["noCardReason"]) == (None, "NEEDS_FORM")


# 저장 전 확인 (Java save-check)


def test_겹치는_지출은_가계부_기록을_끄고_가까운_일정은_연결한다(client, java):
    checker = use_checker(
        client,
        FakeChecker(
            {
                "duplicateExpenses": [{"petSn": MUNG, "expndSn": 3}],
                "nearbySchedules": [
                    {
                        "petSn": CHOCO,
                        "schdlSn": 55,
                        "schdlDt": "2026-09-21T10:00:00",
                        "hsptlNm": "튼튼 병원",
                    }
                ],
            }
        ),
    )
    room = room_of(client, java, pet_sn=CHOCO)

    data = post(client, room, recognized(SECTIONS)).json()["data"]

    pets = data["action"]["input"]["pets"]
    assert (pets[0]["expenseYn"], pets[0]["schdlSn"]) == (True, 55)
    assert (pets[1]["expenseYn"], pets[1].get("schdlSn")) == (False, None)
    assert pets[1]["amt"] == 29499
    text = data["messages"][0]["cnvrsCn"]
    assert "뭉치: 가계부에 같은 지출이 있어 가계부 기록은 빼 두었어요." in text
    assert "초코: 9월 21일 튼튼 병원 병원 일정에 연결해요." in text
    assert checker.calls[0][1]["pets"] == [
        {"petSn": CHOCO, "amt": 29500, "expenseYn": True},
        {"petSn": MUNG, "amt": 29499, "expenseYn": True},
    ]


def test_저장_전_확인이_실패하면_카드는_그대로_주고_한_줄_안내한다(client, java):
    use_checker(client, FakeChecker(fail=True))
    room = room_of(client, java, pet_sn=CHOCO)

    res = post(client, room, recognized())

    assert res.status_code == 201
    data = res.json()["data"]
    assert data["action"]["input"]["pets"][0]["expenseYn"] is True
    assert RECEIPT_CHECK_FAILED in data["messages"][0]["cnvrsCn"]


# 카드 없음


@pytest.mark.parametrize(
    ("result", "text"),
    [
        ("FAILED", "영수증 분석 — 영수증을 읽지 못했어요"),
        ("ERROR", "영수증 분석 — 일시적인 오류로 분석하지 못했어요"),
        ("CANCELED", "영수증 분석 — 취소했어요"),
    ],
)
def test_인식이_아니면_요약만_저장한다(client, java, checker, result, text):
    room = room_of(client, java, pet_sn=CHOCO)

    data = post(client, room, {"result": result}).json()["data"]

    assert data["action"] is None
    assert data["noCardReason"] is None
    assert saved(java, room) == [(ROLE_AI, text)]
    assert checker.calls == []


def test_도구_목록에_저장_도구가_없으면_카드_없이_안내한다(client, java, checker, without_tool):
    room = room_of(client, java, pet_sn=CHOCO)

    data = post(client, room, recognized()).json()["data"]

    assert (data["action"], data["noCardReason"]) == (None, "NO_TOOL")
    assert data["messages"][0]["cnvrsCn"].endswith(RECEIPT_NO_TOOL)


@pytest.mark.parametrize(
    "body",
    [
        {"result": "RECOGNIZED", "ocr": NO_SECTION},
        {"result": "RECOGNIZED", "recptSn": RECPT},
        {"result": "MAYBE"},
        {"result": "FAILED", "cnvrsCn": "   "},
    ],
)
def test_잘못된_요청은_400이고_저장하지_않는다(client, java, checker, body):
    room = room_of(client, java, pet_sn=CHOCO)

    res = post(client, room, body)

    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"
    assert saved(java, room) == []


def test_남의_대화방이면_404다(client, java, checker):
    room = java.add_room(2, "남의 방", cn="안녕")
    room_of(client, java)

    res = post(client, room, recognized())

    assert res.status_code == 404


# 이어 말하기 : 돌려받은 카드 고치기·확인 말


def test_검진_종류를_말하면_같은_카드에_그_칸만_채운다(client, java, checker):
    room = room_of(client, java, pet_sn=CHOCO)
    card = post(client, room, recognized()).json()["data"]["action"]
    use_agent(client, FakeToolAgent(RECEIPT_TOOL, {"ckup_type_cd": "HLTC0003"}))

    evs = events(send(client, room, "질병진료로 해 줘", card))

    action = evs[-1][1]["action"]
    assert action["tool"] == RECEIPT_TOOL
    assert action["input"]["recptSn"] == RECPT
    assert action["input"]["pets"][0]["ckupTypeCd"] == "HLTC0003"
    assert action["input"]["pets"][0]["amt"] == 44000
    assert action["input"]["pets"][0]["drugs"] == card["input"]["pets"][0]["drugs"]
    assert action["missing"] == []


def test_검진_종류를_고른_카드에_확인_말이면_실행_지시한다(client, java, checker):
    room = room_of(client, java, pet_sn=CHOCO)
    card = post(client, room, recognized()).json()["data"]["action"]
    card["input"]["pets"][0]["ckupTypeCd"] = "HLTC0001"
    card["missing"] = []
    agent = use_agent(client, FakeCardReplyAgent())

    evs = events(send(client, room, "등록해 줘", card))

    done = evs[-1][1]
    assert done["execute"] is True
    assert done["action"]["input"]["recptSn"] == RECPT
    assert done["message"]["cnvrsCn"] == "저장할게요."
    assert len(agent.decides) == 1


# 돌려받은 카드의 빈 칸만 채운 실행 명령은 바로 실행 (2026-11-27 사람 결정 A)


def test_빈_칸만_채우고_저장해_달라고_하면_바로_실행_지시한다(client, java, checker):
    room = room_of(client, java, pet_sn=CHOCO)
    card = post(client, room, recognized()).json()["data"]["action"]
    use_agent(client, FakeToolAgent(RECEIPT_TOOL, {"ckup_type_cd": "HLTC0005"}))

    evs = events(send(client, room, "일반진료로 저장해 줘", card))

    done = evs[-1][1]
    assert done["execute"] is True
    assert done["action"]["input"]["pets"][0]["ckupTypeCd"] == "HLTC0005"
    assert done["action"]["input"]["pets"][0]["amt"] == 44000
    assert done["action"]["missing"] == []


def test_있던_값을_바꾸는_말은_실행하지_않고_확인을_기다린다(client, java, checker):
    room = room_of(client, java, pet_sn=CHOCO)
    card = post(client, room, recognized()).json()["data"]["action"]
    use_agent(
        client,
        FakeToolAgent(RECEIPT_TOOL, {"ckup_type_cd": "HLTC0005", "hsptl_nm": "튼튼 병원"}),
    )

    evs = events(send(client, room, "병원은 튼튼 병원이고 일반진료로 저장해 줘", card))

    done = evs[-1][1]
    assert done["execute"] is False
    assert done["action"]["input"]["hsptlNm"] == "튼튼 병원"


def test_빈_칸이_남으면_실행_명령이어도_되묻는다(client, java, checker):
    room = room_of(client, java, pet_sn=CHOCO)
    card = post(client, room, recognized(SECTIONS)).json()["data"]["action"]
    use_agent(client, FakeToolAgent(RECEIPT_TOOL, {"ckup_type_cd": "HLTC0005"}))

    evs = events(send(client, room, "일반진료로 저장해 줘", card))

    done = evs[-1][1]
    assert done["execute"] is False
    assert done["action"]["missing"] == ["pets[1].ckupTypeCd"]
