"""2026-11-27 새 도구 싣기 ③ : 백엔드 #326 도구 10개·값 목록 칸 (SCR-AIM-004·011·012 공통)
- 값 목록 칸(values) : LLM 스키마 enum, 카드 params에 values, 목록 밖 값은 버림
- 저장 전 확인 READ(POST) : 본문 칸을 JSON 본문으로
- 알림 설정 카드 : 말하지 않은 칸은 지금 설정값
- 지출 여러 건·조건 삭제, 반려동물 삭제 대상 글, 칸 없는 카드"""

import asyncio

import pytest

from app.chat import catalog, rules, service
from app.chat.repository import PetInfo
from tests.chat.fakes import FakeToolAgent, fake_catalog
from tests.chat.test_messages import MessageJava, events, send
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import CHOCO, TODAY
from tests.chat.test_tools import room_of, use_agent

SETTINGS = "draft_notification_settings"
LEAD_TIMES = ["TODAY", "D1", "D3", "D7"]
NOW_SETTINGS = {
    "maskedAcntEml": "a***@test.com",
    "emlNotiRcptnYn": True,
    "inappNotiRcptnYn": True,
    "careSchdlNotiRcptnYn": True,
    "leadTimes": ["D1"],
    "mtchDlngNotiRcptnYn": True,
    "cmntNotiRcptnYn": True,
    "lostExpryNotiRcptnYn": False,
    "expndLimNotiRcptnYn": True,
    "expndLimSetYn": False,
}


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


def entry(name: str) -> catalog.CatalogEntry:
    return fake_catalog().entries[name]


# 값 목록 칸


def test_값_목록_칸은_LLM_스키마에_그_값만_고르게_한다():
    schema = entry(SETTINGS).definition["input_schema"]["properties"]["lead_times"]
    value = next(item for item in schema["anyOf"] if item.get("type") == "array")

    assert value["items"]["enum"] == LEAD_TIMES


def test_값_목록_칸은_카드_params에_values를_싣는다():
    params = catalog.card_params(entry(SETTINGS))

    assert params["leadTimes"]["values"] == LEAD_TIMES
    assert params["leadTimes"]["itemType"] == "string"


def test_값_목록의_목록_밖_값은_버리고_선언_순서로_싣는다():
    card = catalog.card_input(entry(SETTINGS), {"lead_times": ["D7", "D30", "TODAY", "D7"]})

    assert card["leadTimes"] == ["TODAY", "D7"]


def test_값_목록이_모두_틀리면_칸을_비워_되묻는다():
    found = entry(SETTINGS)
    card = catalog.card_input(found, {"lead_times": ["D30"]})

    assert "leadTimes" not in card
    assert "leadTimes" in catalog.missing(found, card)


def test_값_목록_빈_목록은_사전_알림_없음이라_그대로_싣는다():
    found = entry(SETTINGS)
    card = catalog.card_input(found, {"lead_times": []})

    assert card["leadTimes"] == []
    assert "leadTimes" not in catalog.missing(found, card)


def test_값_목록_칸_규칙은_결과_저장_검사도_한다():
    found = entry(SETTINGS)

    assert catalog.invalid_input(found, {"leadTimes": ["D3"]}) == []
    assert catalog.invalid_input(found, {"leadTimes": ["D30"]}) == ["leadTimes"]


# 저장 전 확인 READ(POST)


def test_지출_중복_확인은_본문_칸과_고정_값을_POST_본문으로_보낸다():
    found = entry("check_expense_duplicates")
    values = {"expnd_ymd": "2026-09-28", "expnd_clsf_cd": "MYPC0012", "expnd_amt": 50000}

    request = catalog.read_request(found, values, None)

    assert request is not None and len(request) == 3
    path, query, body = request
    assert path == "/api/expenses/duplicate-check"
    assert query == {}
    assert body["expndYmd"] == "2026-09-28"
    assert body["lines"] == [{"expndAmt": 50000}]
    assert body["expndInptMthCd"] == "MYPC0019"


def test_영수증_저장_전_확인은_이_턴_READ의_영수증_번호만_쓴다():
    found = entry("check_receipt_save")
    values = {"recpt_sn": 8, "ckup_ymd": "2026-09-20", "pet_sn": CHOCO}

    assert catalog.read_request(found, values, None, {"recptSn": {9}}) is None
    path, _, body = catalog.read_request(found, values, None, {"recptSn": {8}})
    assert path == "/api/receipts/8/save-check"
    assert body == {"ckupYmd": "2026-09-20", "pets": [{"petSn": CHOCO}]}


def test_GET_READ는_본문_없이_경로와_query만():
    request = catalog.read_request(entry("get_notification_settings"), {}, None)

    assert request == ("/api/members/me/notification-settings", {})


def test_POST_READ는_Java_읽기에_본문을_넘긴다():
    from tests.chat.fakes import FakeEvalReader

    reader = FakeEvalReader()
    found = entry("check_expense_duplicates")
    values = {"expnd_ymd": "2026-09-28", "expnd_clsf_cd": "MYPC0012", "expnd_amt": 50000}

    asyncio.run(reader.read(*catalog.read_request(found, values, None)))

    assert reader.bodies[0][0] == "/api/expenses/duplicate-check"
    assert reader.bodies[0][1]["lines"] == [{"expndAmt": 50000}]


# 알림 설정 카드 : 말하지 않은 칸은 지금 설정값


def test_알림_설정_카드는_말하지_않은_칸을_지금_설정값으로_채운다(client, java):
    use_agent(client, FakeToolAgent(SETTINGS, {"cmnt_noti_rcptn_yn": False}))
    reader = use_reader(client, FakeToolReader(NOW_SETTINGS))
    room = room_of(client, java, pet_sn=CHOCO)

    action = events(send(client, room, "댓글 알림 꺼 줘"))[-1][1]["action"]

    assert action["input"]["cmntNotiRcptnYn"] is False
    assert action["input"]["leadTimes"] == ["D1"]
    assert action["input"]["lostExpryNotiRcptnYn"] is False
    assert "maskedAcntEml" not in action["input"]
    assert action["missing"] == []
    assert action["params"]["leadTimes"]["values"] == LEAD_TIMES
    assert ("/api/members/me/notification-settings", {}) in reader.calls


def test_알림_설정_지금_값_읽기에_실패하면_빈_칸은_되묻는다(client, java):
    use_agent(client, FakeToolAgent(SETTINGS, {"cmnt_noti_rcptn_yn": False}))
    use_reader(client, FakeToolReader(fail=True))
    room = room_of(client, java, pet_sn=CHOCO)

    action = events(send(client, room, "댓글 알림 꺼 줘"))[-1][1]["action"]

    assert action["input"] == {"cmntNotiRcptnYn": False}
    assert "leadTimes" in action["missing"]


def test_알림_설정이_아닌_카드는_지금_값을_읽지_않는다():
    reader = FakeToolReader(NOW_SETTINGS)
    card = service.action_card(entry("draft_expense_limit"), {}, [], [], None, None)

    filled = asyncio.run(service.fill_current_values(card, reader))

    assert filled == card
    assert reader.calls == []


# 삭제 카드


def test_지출_여러_건_삭제는_번호마다_이_턴_READ_결과만_쓴다():
    found = entry("delete_expenses")
    seen = {"expndSn": {10, 11}}

    assert catalog.card_input(found, {"expnd_sns": [10, 11]}, seen=seen)["expndSn"] == [10, 11]
    assert "expndSn" not in catalog.card_input(found, {"expnd_sns": [10, 99]}, seen=seen)


def test_지출_여러_건_삭제_대상_글은_번호마다_READ_행():
    found = entry("delete_expenses")
    rows = {
        ("expndSn", 10): {"expndSn": 10, "expndYmd": "2026-09-28", "expndAmt": 32000},
        ("expndSn", 11): {"expndSn": 11, "expndYmd": "2026-09-29", "expndAmt": 5000},
    }

    text = service.delete_target_text(found, {"expndSn": [10, 11]}, rows)

    assert text == "09-28(월) · 32,000원 / 09-29(화) · 5,000원"


def test_지출_조건_삭제는_POST지만_삭제_카드로_본다():
    found = entry("delete_expenses_by_condition")

    assert found.call.method == "POST"
    assert service.is_delete(found)
    assert service.entry_verb(found) == "삭제"


def test_지출_조건_삭제_대상_글은_조건과_지울_건수():
    found = entry("delete_expenses_by_condition")
    values = {"startYmd": "2026-09-01", "endYmd": "2026-09-30", "common": True, "expectedCnt": 3}

    text = service.delete_target_text(found, values, {})

    assert text == "09-01(화) · 09-30(수) · 공용 지출 · 3건"


def test_지출_조건_삭제는_문장_속_이름이_하나면_그_아이_없으면_모든_아이():
    found = entry("delete_expenses_by_condition")
    choco = PetInfo(CHOCO, "초코")
    values = {"expectedCnt": 2}

    named = service.action_card(found, values, [choco], [choco], None, None)
    everyone = service.action_card(found, values, [choco], [], None, None)

    assert named.values["petSn"] == CHOCO
    assert "petSn" not in everyone.values
    assert everyone.pet_choices == []


def test_반려동물_삭제_대상_글은_고른_아이_이름_종_품종():
    found = entry("delete_pet")
    choco = PetInfo(CHOCO, "초코", pet_se_nm="강아지", vrty_nm="말티즈")

    card = service.action_card(found, {}, [choco], [choco], None, None)

    assert card.values == {"petSn": CHOCO}
    assert card.target_text == "초코 · 강아지 · 말티즈"


def test_공동양육_해제는_이_턴_READ의_관계_번호만():
    found = entry("unlink_caregiver")

    card = catalog.card_input(found, {"brup_rel_sn": 7}, seen={"brupRelSn": {7}})
    made = catalog.card_input(found, {"brup_rel_sn": 8}, seen={"brupRelSn": {7}})

    assert card["brupRelSn"] == 7
    assert catalog.missing_target_ids(found, made) == ["brupRelSn"]


def test_튜토리얼_그만_보기는_칸_없는_카드():
    found = entry("mark_service_tutorial_viewed")

    card = service.action_card(found, {}, [], [], None, None)

    assert card.values == {}
    assert card.missing == []
    assert service.entry_verb(found) == "저장"


def test_영수증_검진기록_등록은_이_턴_READ의_영수증_번호가_없으면_카드를_띄우지_않는다():
    found = entry("draft_receipt_checkup")

    card = catalog.card_input(found, {"recpt_sn": 8, "hsptl_nm": "메이"}, seen={})

    assert catalog.missing_target_ids(found, card) == ["recptSn"]
