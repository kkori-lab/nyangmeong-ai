"""대화창 검사결과지 PDF 분석 결과 카드 (SCR-AIM-013, 2026-11-23 추가 요청)
- POST /ai/conversations/{방}/checkup-card : 결과 요약 AI 메시지 + 검사 수치 저장 확인 카드
- 검진기록 1건이면 카드에 채우고, 여럿이면 빈 칸 + 최근 3건 글, 0건이면 카드 없음
- 저장 도구(draft_inspection_values)는 백엔드 요청한 칸 규칙으로 스냅샷에 먼저 넣음"""

from datetime import date

import pytest

from app.chat import catalog, rules, tools
from app.chat.schemas import ROLE_AI
from app.chat.service import (
    CHECKUP_NO_ROWS,
    CHECKUP_NO_TOOL,
    CHECKUP_PICK_RECORD,
    _md,
)
from tests.chat.conftest import AJAX
from tests.chat.fakes import (
    INSPECTION_TOOL,
    FakeCardReplyAgent,
    fake_catalog,
    fake_catalog_json,
)
from tests.chat.test_action import action_result, send
from tests.chat.test_action_update_follow import ChainAgent
from tests.chat.test_messages import MessageJava, events
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import CHOCO, TODAY
from tests.chat.test_tools import room_of, use_agent

URL = "/ai/conversations/{}/checkup-card"
CHECKUPS = f"/api/pets/{CHOCO}/checkups"
WBC = "HLTC0024"
RECORD = {
    "ckupRcdSn": 7,
    "ckupYmd": "2026-10-20",
    "hsptlNm": "메이 동물병원",
    "ckupTypeCdNm": "정기검진",
}
ITEMS = [
    {
        "inspArtclCd": WBC,
        "inspArtclDrctInptNm": None,
        "rsltNvl": 12.3,
        "unitNm": "10^3/uL",
        "refLlmtNvl": 6,
        "refUplmtNvl": 17,
    },
    {"inspArtclCd": None, "inspArtclDrctInptNm": "SDMA", "rsltNvl": 14, "unitNm": "ug/dL"},
    # 단위를 못 읽은 줄 : 카드에서 뺀다(Java 필수)
    {"inspArtclCd": None, "inspArtclDrctInptNm": "T4", "rsltNvl": 2.1, "unitNm": None},
]


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


@pytest.fixture
def without_tool():
    # 저장 도구가 없는 도구 목록 (백엔드 병합 전·Java가 이 도구를 빼고 줄 때)
    raw = fake_catalog_json()
    raw["tools"] = [tool for tool in raw["tools"] if tool["name"] != INSPECTION_TOOL]
    tools.use_catalog(catalog.build(catalog.ToolCatalogResponse.model_validate(raw)))
    yield
    tools.use_catalog(fake_catalog())


def post(client, room: int, body: dict):
    return client.post(URL.format(room), json=body, headers=AJAX)


def recognized(**extra) -> dict:
    return {"result": "RECOGNIZED", "petSn": CHOCO, "items": ITEMS} | extra


def saved(java: MessageJava, room: int) -> list[tuple[str, str]]:
    return [(m["roleCd"], m["cnvrsCn"]) for m in java.rooms[room]["messages"][1:]]


def test_검진기록이_1건이면_카드에_채우고_요약_글을_저장한다(client, java):
    reader = use_reader(client, FakeToolReader(by_path={CHECKUPS: {"content": [RECORD]}}))
    room = room_of(client, java, pet_sn=CHOCO)

    res = post(client, room, recognized(excludedArtclNms=["요검사 pH"]))

    assert res.status_code == 201
    data = res.json()["data"]
    action = data["action"]
    assert action["tool"] == "draft_inspection_values"
    assert action["call"] == {"method": "POST", "path": "/api/pets/{petSn}/inspection-values"}
    assert action["input"]["petSn"] == CHOCO
    assert action["input"]["ckupRcdSn"] == 7
    assert action["input"]["values"] == [
        {
            "inspArtclCd": WBC,
            "rsltNvl": 12.3,
            "unitNm": "10^3/uL",
            "refLlmtNvl": 6,
            "refUplmtNvl": 17,
        },
        {"inspArtclDrctInptNm": "SDMA", "rsltNvl": 14, "unitNm": "ug/dL"},
    ]
    assert action["missing"] == []
    assert data["noCardReason"] is None
    assert reader.calls == [(CHECKUPS, {})]
    text = data["messages"][0]["cnvrsCn"]
    assert text.startswith(
        "검사결과지 분석 — 혈액검사 3항목\n초코의 검사 수치를 이렇게 저장할까요?"
    )
    assert "- WBC 12.3 10^3/uL (참고 6~17)" in text
    assert "- SDMA 14 ug/dL" in text
    assert "T4" not in text
    assert "수치나 단위를 읽지 못한 1항목은 빼 두었어요. 검진상세에서 직접 입력해 주세요." in text
    assert "본창" not in text
    assert "혈액검사가 아닌 항목(요검사 pH)은 저장하지 않아요." in text
    assert f"저장할 검진기록: {_md(date(2026, 10, 20))} 메이 동물병원 · 정기검진" in text
    assert "등록해 줘" in text
    assert saved(java, room) == [(ROLE_AI, text)]


def test_검진기록이_여럿이면_빈_칸으로_두고_최근_3건을_보인다(client, java):
    records = [
        RECORD,
        {"ckupRcdSn": 8, "ckupYmd": None, "hsptlNm": "튼튼 병원", "ckupTypeCdNm": "검사"},
        {"ckupRcdSn": 9, "ckupYmd": "2026-08-01", "hsptlNm": "메이 동물병원"},
        {"ckupRcdSn": 10, "ckupYmd": "2026-07-01", "hsptlNm": "네 번째 병원"},
    ]
    use_reader(client, FakeToolReader(by_path={CHECKUPS: {"content": records}}))
    room = room_of(client, java, pet_sn=CHOCO)

    data = post(client, room, recognized()).json()["data"]

    assert data["action"]["missing"] == ["ckupRcdSn"]
    assert data["noCardReason"] is None
    assert "ckupRcdSn" not in data["action"]["input"]
    text = data["messages"][0]["cnvrsCn"]
    assert CHECKUP_PICK_RECORD in text
    assert f"1. {_md(date(2026, 10, 20))} 메이 동물병원 · 정기검진" in text
    assert "2. 날짜 없음 튼튼 병원 · 검사" in text
    assert f"3. {_md(date(2026, 8, 1))} 메이 동물병원" in text
    assert "네 번째 병원" not in text


def test_검진기록이_없으면_카드_없이_먼저_등록하라고_안내한다(client, java):
    use_reader(client, FakeToolReader(by_path={CHECKUPS: {"content": []}}))
    room = room_of(client, java, pet_sn=CHOCO)

    data = post(client, room, recognized()).json()["data"]

    assert data["action"] is None
    assert data["noCardReason"] == "NO_CHECKUP"
    text = data["messages"][0]["cnvrsCn"]
    assert text.endswith(
        "검진기록이 없어요. 검진기록을 먼저 등록할까요? "
        "등록하면 초코의 검사 수치를 바로 저장할 수 있어요."
    )
    assert "본창" not in text


def test_검진기록이_없고_반려동물_이름을_모르면_이름_없이_묻는다(client, java):
    use_reader(client, FakeToolReader(by_path={CHECKUPS: {"content": []}}))
    room = room_of(client, java, pet_sn=CHOCO)

    data = post(client, room, recognized(petSn=9999)).json()["data"]

    assert data["noCardReason"] == "NO_CHECKUP"
    assert data["messages"][0]["cnvrsCn"].endswith(
        "검진기록이 없어요. 검진기록을 먼저 등록할까요? 등록하면 검사 수치를 바로 저장할 수 있어요."
    )


def test_수치를_하나도_못_쓰면_검진기록을_읽지_않고_직접_입력을_안내한다(client, java):
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java, pet_sn=CHOCO)
    items = [{"inspArtclDrctInptNm": "T4", "rsltNvl": None, "unitNm": "ug/dL"}]

    data = post(client, room, recognized(items=items)).json()["data"]

    assert data["action"] is None
    assert data["noCardReason"] is None
    assert data["messages"][0]["cnvrsCn"] == f"검사결과지 분석 — 혈액검사 1항목\n{CHECKUP_NO_ROWS}"
    assert CHECKUP_NO_ROWS == "저장할 수 있는 수치가 없어요. 검진상세에서 직접 입력해 주세요."
    assert reader.calls == []


def test_인식_항목이_0건이면_요약만_저장한다(client, java):
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java, pet_sn=CHOCO)

    data = post(client, room, recognized(items=[])).json()["data"]

    assert data["action"] is None
    assert data["messages"][0]["cnvrsCn"] == "검사결과지 분석 — 읽은 혈액검사 항목이 없어요"
    assert reader.calls == []


@pytest.mark.parametrize(
    ("result", "text"),
    [
        ("NOT_LAB_RESULT", "검사결과지 분석 — 검사결과지로 읽을 수 없는 PDF예요"),
        ("ERROR", "검사결과지 분석 — 일시적인 오류로 분석하지 못했어요"),
        ("CANCELED", "검사결과지 분석 — 취소했어요"),
    ],
)
def test_분석_실패는_카드_없이_요약만_저장한다(client, java, result, text):
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java, pet_sn=CHOCO)

    res = post(client, room, {"result": result, "petSn": CHOCO, "items": ITEMS})

    assert res.status_code == 201
    data = res.json()["data"]
    assert data == {"messages": [data["messages"][0]], "action": None, "noCardReason": None}
    assert saved(java, room) == [(ROLE_AI, text)]
    assert reader.calls == []


def test_저장_도구가_도구_목록에_없으면_검진상세_PDF_분석으로_안내한다(client, java, without_tool):
    # 백엔드 @AiTool 병합 전(Java 목록에 없음)
    reader = use_reader(client, FakeToolReader(by_path={CHECKUPS: {"content": [RECORD]}}))
    room = room_of(client, java, pet_sn=CHOCO)

    data = post(client, room, recognized()).json()["data"]

    assert data["action"] is None
    assert data["noCardReason"] is None
    assert data["messages"][0]["cnvrsCn"] == f"검사결과지 분석 — 혈액검사 3항목\n{CHECKUP_NO_TOOL}"
    assert CHECKUP_NO_TOOL == "검진상세의 [PDF 분석]에서 저장할 수 있어요."
    assert reader.calls == []


def test_코드와_직접입력명이_같이_오면_카드_줄에는_코드만_남긴다(client, java):
    # 둘 다 보내면 Java 400 : React가 보낸 items를 그대로 믿지 않는다
    use_reader(client, FakeToolReader(by_path={CHECKUPS: {"content": [RECORD]}}))
    room = room_of(client, java, pet_sn=CHOCO)
    items = [
        {"inspArtclCd": WBC, "inspArtclDrctInptNm": "백혈구", "rsltNvl": 12.3, "unitNm": "10^3/uL"}
    ]

    data = post(client, room, recognized(items=items)).json()["data"]

    assert data["action"]["input"]["values"] == [
        {"inspArtclCd": WBC, "rsltNvl": 12.3, "unitNm": "10^3/uL"}
    ]
    text = data["messages"][0]["cnvrsCn"]
    assert "- WBC 12.3 10^3/uL" in text
    assert "백혈구" not in text


def test_검진기록_읽기가_실패하면_저장하지_않고_502(client, java):
    use_reader(client, FakeToolReader(fail_paths=(CHECKUPS,)))
    room = room_of(client, java, pet_sn=CHOCO)

    res = post(client, room, recognized())

    assert res.status_code == 502
    assert res.json()["code"] == "EXTERNAL_API_ERROR"
    assert saved(java, room) == []


def test_남의_방이면_Java_404를_그대로_준다(client, java):
    use_reader(client, FakeToolReader(by_path={CHECKUPS: {"content": [RECORD]}}))
    room_of(client, java)
    other = java.add_room(2, "남의 방", cn="안녕")

    res = post(client, other, recognized())

    assert res.status_code == 404
    assert len(java.rooms[other]["messages"]) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"result": "FAILED", "petSn": CHOCO},
        {"result": "RECOGNIZED"},
        {"result": "RECOGNIZED", "petSn": 0},
    ],
)
def test_허용값_밖이면_400(client, java, body):
    room = room_of(client, java, pet_sn=CHOCO)

    res = post(client, room, body)

    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"
    assert saved(java, room) == []


# 이어 말하기 : 검진기록 고르기·확인 말


def picked_card(client, java, room: int) -> dict:
    records = [RECORD, {"ckupRcdSn": 8, "ckupYmd": "2026-09-01", "hsptlNm": "튼튼 병원"}]
    use_reader(client, FakeToolReader(by_path={CHECKUPS: {"content": records}}))
    return post(client, room, recognized()).json()["data"]["action"]


def test_검진기록을_말하면_READ_뒤_같은_카드에_번호만_채운다(client, java):
    room = room_of(client, java, pet_sn=CHOCO)
    card = picked_card(client, java, room)
    use_agent(
        client,
        ChainAgent(
            "list_checkups",
            [("draft_inspection_values", {"ckup_rcd_sn": 8})],
            ("카드를 확인해 주세요.",),
        ),
    )

    evs = events(send(client, room, "9월 1일 튼튼 병원 검진에 넣어줘", card))

    action = evs[-1][1]["action"]
    assert action["tool"] == "draft_inspection_values"
    assert action["input"]["ckupRcdSn"] == 8
    assert action["input"]["values"] == card["input"]["values"]
    assert action["missing"] == []


def test_검진기록이_채워진_카드에_확인_말이면_실행_지시한다(client, java):
    use_reader(client, FakeToolReader(by_path={CHECKUPS: {"content": [RECORD]}}))
    room = room_of(client, java, pet_sn=CHOCO)
    card = post(client, room, recognized()).json()["data"]["action"]
    agent = use_agent(client, FakeCardReplyAgent())

    evs = events(send(client, room, "등록해 줘", card))

    done = evs[-1][1]
    assert done["execute"] is True
    assert done["action"]["input"]["ckupRcdSn"] == 7
    assert len(agent.decides) == 1


# 검사 수치 저장 결과(action-result, 2026-11-24) : 배열은 펼치지 않고 반려동물·검진기록·항목 수


def inspection_done(count: int) -> dict:
    row = {"inspArtclDrctInptNm": "SDMA", "rsltNvl": 14, "unitNm": "ug/dL"}
    return {"petSn": CHOCO, "ckupRcdSn": 7, "values": [row] * count}


def test_검사_수치_저장_결과는_반려동물_검진기록_항목_수로_요약한다(client, java):
    reader = use_reader(client, FakeToolReader(by_path={CHECKUPS: {"content": [RECORD]}}))
    room = room_of(client, java, pet_sn=CHOCO)

    res = action_result(client, room, INSPECTION_TOOL, "DONE", inspection_done(52))

    day = _md(date(2026, 10, 20))
    assert res.status_code == 201
    assert res.json()["data"]["cnvrsCn"] == (
        f"✔ 검사 수치 저장 — 초코 · {day} 메이 동물병원 · 혈액검사 52항목"
    )
    assert reader.calls == [(CHECKUPS, {})]


@pytest.mark.parametrize(
    ("status", "end"),
    [
        ("CANCELED", "취소됨 — {} · 저장하지 않았어요."),
        ("FAILED", "실패 — {} · 저장하지 못했어요."),
    ],
)
def test_검사_수치_취소와_실패도_같은_요약을_넣는다(client, java, status, end):
    use_reader(client, FakeToolReader(by_path={CHECKUPS: {"content": [RECORD]}}))
    room = room_of(client, java, pet_sn=CHOCO)

    res = action_result(client, room, INSPECTION_TOOL, status, inspection_done(2))

    day = _md(date(2026, 10, 20))
    summary = f"검사 수치 저장 · 초코 · {day} 메이 동물병원 · 혈액검사 2항목"
    assert res.json()["data"]["cnvrsCn"] == end.format(summary)


def test_검사_수치_결과는_검진기록_읽기가_실패해도_그_부분만_빼고_저장한다(client, java):
    use_reader(client, FakeToolReader(fail_paths=(CHECKUPS,)))
    room = room_of(client, java, pet_sn=CHOCO)

    res = action_result(client, room, INSPECTION_TOOL, "DONE", inspection_done(1))

    assert res.status_code == 201
    message = "✔ 검사 수치 저장 — 초코 · 혈액검사 1항목"
    assert res.json()["data"]["cnvrsCn"] == message
    assert saved(java, room) == [(ROLE_AI, message)]


def test_검사_수치_결과는_검진기록이_목록에_없으면_빼고_저장한다(client, java):
    other = RECORD | {"ckupRcdSn": 8}
    use_reader(client, FakeToolReader(by_path={CHECKUPS: {"content": [other]}}))
    room = room_of(client, java, pet_sn=CHOCO)

    res = action_result(client, room, INSPECTION_TOOL, "DONE", inspection_done(3))

    assert res.json()["data"]["cnvrsCn"] == "✔ 검사 수치 저장 — 초코 · 혈액검사 3항목"


def test_검사_수치_결과는_반려동물_조회가_실패해도_이름만_빼고_저장한다(client, java):
    use_reader(client, FakeToolReader(by_path={CHECKUPS: {"content": [RECORD]}}))
    room = room_of(client, java, pet_sn=CHOCO)
    java.context_status = 500

    res = action_result(client, room, INSPECTION_TOOL, "DONE", inspection_done(3))

    day = _md(date(2026, 10, 20))
    assert res.status_code == 201
    assert (
        res.json()["data"]["cnvrsCn"] == f"✔ 검사 수치 저장 — {day} 메이 동물병원 · 혈액검사 3항목"
    )
