from datetime import date

import pytest

from app.chat import clients, repository, rules
from app.chat.repository import PetInfo
from app.chat.schemas import ROLE_AI
from app.chat.service import CANCELED_MESSAGE
from tests.chat.conftest import AJAX, as_member
from tests.chat.test_messages import Answers, MessageJava, events, names

# 화면설계서 SCR-AIM-012 예시의 기준일 : 2026-09-29(화)
TODAY = date(2026, 9, 29)
HOSPITAL_TEXT = "다음 주 화요일 오후 3시에 메이 동물병원 예방접종 잡아줘"
CARE_TEXT = "뭉치 2주마다 발톱 깎기 넣어줘, 지난주 토요일에 했어"
CHOCO, MUNG = 1, 2


class Extractor:
    """가짜 AI 보조 추출기. 받은 인자는 기록, result 반환(fail이면 예외)"""

    def __init__(self, result: dict | None = None, fail: bool = False) -> None:
        self.result = result or {}
        self.fail = fail
        self.calls: list[tuple] = []

    async def extract(self, *args, **kwargs) -> dict:
        self.calls.append((args, kwargs))
        if self.fail:
            raise RuntimeError("api_error")
        return self.result


class Pets:
    def __init__(self, pets: list[PetInfo]) -> None:
        self.pets = pets

    async def get_pets(self) -> list[PetInfo]:
        return self.pets


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


@pytest.fixture
def extractor(client) -> Extractor:
    return use_extractor(client, Extractor())


@pytest.fixture
def answers(client) -> Answers:
    fake = Answers()
    client.app.dependency_overrides[clients.get_answer_generator] = lambda: fake
    return fake


def use_extractor(client, fake: Extractor) -> Extractor:
    client.app.dependency_overrides[clients.get_register_extractor] = lambda: fake
    return fake


def use_pets(client, *pets: PetInfo) -> None:
    fake = Pets(list(pets))
    client.app.dependency_overrides[repository.get_register_context_repository] = lambda: fake


def send(client, room_sn: int, cn: str, draft: dict | None = None):
    body = {"cnvrsCn": cn}
    if draft is not None:
        body["draft"] = draft
    return events(client.post(f"/ai/conversations/{room_sn}/messages", json=body, headers=AJAX))


def done(evs) -> dict:
    assert names(evs)[-1] == "done"
    return evs[-1][1]


def register_result(client, room_sn: int, result: str, card: dict):
    return client.post(
        f"/ai/conversations/{room_sn}/register-result",
        json={"result": result, "card": card},
        headers=AJAX,
    )


# 미리보기 카드(FN-AIM-012-02·06·07)


def test_필수_칸이_찬_요청은_AI_없이_일정_카드를_주고_저장하지_않는다(client, java, extractor):
    as_member(client, 1)
    room = java.add_room(1, "제목", pet_sn=CHOCO)
    evs = send(client, room, HOSPITAL_TEXT)

    assert names(evs) == ["intent", "done"]
    assert evs[0][1]["kind"] == "REGISTER"
    card = done(evs)["card"]
    assert card["cardType"] == "SCHEDULE"
    assert (card["petSn"], card["petNm"]) == (CHOCO, "초코")
    assert card["schdlKndCd"] == "HLTC0057"
    assert card["ckupTypeCd"] == "HLTC0002"
    assert card["hsptlNm"] == "메이 동물병원"
    assert (card["schdlYmd"], card["schdlTm"]) == ("2026-10-06", "15:00")
    assert card["missing"] == []
    # FN-AIM-012-02 : 규칙으로 다 찼으면 AI 미호출
    assert extractor.calls == []
    # FN-AIM-012-11 : 카드 미저장(무응답이면 아무것도 남지 않음)
    assert done(evs)["message"] is None
    assert java.ai_messages(room) == []


def test_주기_요청은_케어_항목_카드와_다음_예정일(client, java, extractor):
    # FN-AIM-012-07·14 : 주기가 있으면 일정이 아니라 케어 항목
    as_member(client, 1)
    room = java.add_room(1, "제목")
    card = done(send(client, room, "초코 매주 목욕 넣어줘"))["card"]

    assert card["cardType"] == "CARE_ITEM"
    assert card["petNm"] == "초코"
    assert card["careArtclNm"] == "목욕"
    assert (card["careZoneCd"], card["careCycleCd"]) == ("HLTC0037", "HLTC0038")
    # 마지막으로 한 날이 없으면 오늘 기준
    assert card["lastCmptnYmd"] is None
    assert card["nxtmPrnmntYmd"] == "2026-10-06"
    assert card["duplicateName"] is False
    # 일정 칸 제외
    assert card["schdlKndCd"] is None


def test_같은_이름_케어_항목이_있으면_안내한다(client, java, extractor):
    # FN-AIM-012-08 : 가짜 register-context에서 뭉치는 '발톱 깎기' 보유
    as_member(client, 1)
    room = java.add_room(1, "제목")
    card = done(send(client, room, CARE_TEXT))["card"]

    assert card["cardType"] == "CARE_ITEM"
    assert card["petNm"] == "뭉치"
    assert card["lastCmptnYmd"] == "2026-09-26"
    assert card["nxtmPrnmntYmd"] == "2026-10-10"
    assert card["duplicateName"] is True
    assert card["notice"] == "뭉치에게 '발톱 깎기' 항목이 이미 있어요. 그래도 새로 등록할까요?"


def test_다른_반려동물의_같은_이름은_안내하지_않는다(client, java, extractor):
    as_member(client, 1)
    room = java.add_room(1, "제목")
    card = done(send(client, room, "초코 2주마다 발톱 깎기 넣어줘"))["card"]

    assert card["duplicateName"] is False
    assert card["notice"] is None


# 되물음(FN-AIM-012-05)


def test_내일_3시_병원_일정은_병원명과_검진유형을_되묻고_저장한다(client, java, extractor):
    # 마일스톤 완료 조건 : 빈 칸이 있으면 되물음
    as_member(client, 1)
    room = java.add_room(1, "제목", pet_sn=CHOCO)
    body = done(send(client, room, "내일 3시 병원 일정 잡아줘"))
    card = body["card"]

    assert card["cardType"] == "ASK"
    assert card["missing"] == ["ckupTypeCd", "hsptlNm"]
    assert (card["schdlYmd"], card["schdlTm"]) == ("2026-09-30", "15:00")
    expected = "어느 병원인가요? 검진 종류도 알려 주세요. (예: 정기검진, 예방접종)"
    assert body["message"]["cnvrsCn"] == expected
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [expected]
    # 빈 칸이 있어 AI 보조 해석 1회 호출
    assert len(extractor.calls) == 1


def test_되물음에_답하면_초안을_채워_일정_카드(client, java, extractor):
    as_member(client, 1)
    room = java.add_room(1, "제목", pet_sn=CHOCO)
    ask = done(send(client, room, "금요일에 병원 예약 잡아줘"))["card"]
    assert ask["cardType"] == "ASK"

    card = done(send(client, room, "메이 동물병원 예방접종", draft=ask))["card"]

    assert card["cardType"] == "SCHEDULE"
    assert card["schdlYmd"] == "2026-10-02"
    assert card["hsptlNm"] == "메이 동물병원"
    assert card["ckupTypeCd"] == "HLTC0002"


def test_항목명을_되물으면_답_전체를_항목명으로(client, java, extractor):
    as_member(client, 1)
    room = java.add_room(1, "제목", pet_sn=CHOCO)
    draft = {"petSn": CHOCO, "careZoneCd": "HLTC0036"}

    card = done(send(client, room, "산책", draft=draft))["card"]

    assert card["cardType"] == "CARE_ITEM"
    assert card["careArtclNm"] == "산책"


# 반려동물 결정(FN-AIM-012-04)


def test_문장_속_이름이_펫_태그보다_먼저다(client, java, extractor):
    as_member(client, 1)
    room = java.add_room(1, "제목", pet_sn=CHOCO)
    card = done(send(client, room, "뭉치 " + HOSPITAL_TEXT))["card"]

    assert (card["petSn"], card["petNm"]) == (MUNG, "뭉치")


def test_이름이_없으면_대화의_펫_태그(client, java, extractor):
    as_member(client, 1)
    room = java.add_room(1, "제목", pet_sn=MUNG)
    card = done(send(client, room, HOSPITAL_TEXT))["card"]

    assert card["petNm"] == "뭉치"
    assert card["petChoices"] == []


@pytest.mark.parametrize("text", [HOSPITAL_TEXT, "초코 뭉치 " + HOSPITAL_TEXT])
def test_전체_태그나_이름이_여럿이면_이름_칩으로_되묻는다(client, java, extractor, text):
    as_member(client, 1)
    room = java.add_room(1, "제목", pet_sn=None)
    body = done(send(client, room, text))
    card = body["card"]

    assert card["cardType"] == "ASK"
    assert card["missing"] == ["petSn"]
    assert card["petSn"] is None
    assert card["petChoices"] == [
        {"petSn": CHOCO, "petNm": "초코"},
        {"petSn": MUNG, "petNm": "뭉치"},
    ]
    assert body["message"]["cnvrsCn"] == "어느 아이의 일정인가요? 아래에서 골라 주세요."


def test_이름_칩을_고르면_그_반려동물로_카드(client, java, extractor):
    as_member(client, 1)
    room = java.add_room(1, "제목")
    ask = done(send(client, room, HOSPITAL_TEXT))["card"]

    card = done(send(client, room, "뭉치", draft=ask))["card"]

    assert card["cardType"] == "SCHEDULE"
    assert card["petNm"] == "뭉치"
    assert card["hsptlNm"] == "메이 동물병원"


def test_반려동물이_1마리면_자동_선택(client, java, extractor):
    use_pets(client, PetInfo(7, "보리"))
    as_member(client, 1)
    room = java.add_room(1, "제목", pet_sn=None)
    card = done(send(client, room, HOSPITAL_TEXT))["card"]

    assert card["cardType"] == "SCHEDULE"
    assert (card["petSn"], card["petNm"]) == (7, "보리")


# 카드 수정(FN-AIM-012-10)


def test_초안과_4시로_바꿔줘는_시간만_바꾼_새_카드(client, java, extractor):
    as_member(client, 1)
    room = java.add_room(1, "제목", pet_sn=CHOCO)
    first = done(send(client, room, HOSPITAL_TEXT))["card"]

    evs = send(client, room, "4시로 바꿔줘", draft=first)
    card = done(evs)["card"]

    assert evs[0][1]["kind"] == "REGISTER"
    assert card["cardType"] == "SCHEDULE"
    assert card["schdlTm"] == "16:00"
    assert card["schdlYmd"] == first["schdlYmd"]
    assert card["hsptlNm"] == first["hsptlNm"]


def test_초안이_있어도_뽑힌_칸이_없으면_일반_판정(client, java, extractor, answers):
    as_member(client, 1)
    room = java.add_room(1, "제목", pet_sn=CHOCO)
    first = done(send(client, room, HOSPITAL_TEXT))["card"]

    evs = send(client, room, "강아지 포도 먹어도 돼?", draft=first)

    assert evs[0][1]["kind"] == "SEARCH"
    assert done(evs)["card"] is None


# AI 보조 해석(FN-AIM-012-03)


def test_AI에는_요청_문장과_오늘_날짜만_보낸다(client, java, extractor):
    as_member(client, 1)
    room = java.add_room(1, "제목", pet_sn=CHOCO)
    send(client, room, "금요일에 병원 예약 잡아줘")

    args, kwargs = extractor.calls[0]
    assert args == ("금요일에 병원 예약 잡아줘", TODAY)
    assert kwargs == {}
    assert "초코" not in repr(extractor.calls) and "뭉치" not in repr(extractor.calls)


def test_AI가_채운_빈_칸으로_카드를_만든다(client, java):
    use_extractor(client, Extractor({"hsptl_nm": "메이 동물병원", "ckup_type_cd": "HLTC0001"}))
    as_member(client, 1)
    room = java.add_room(1, "제목", pet_sn=CHOCO)
    card = done(send(client, room, "금요일에 병원 예약 잡아줘"))["card"]

    assert card["cardType"] == "SCHEDULE"
    assert (card["hsptlNm"], card["ckupTypeCd"]) == ("메이 동물병원", "HLTC0001")


def test_AI가_준_잘못된_날짜는_빈_칸이라_되묻는다(client, java):
    # 규칙으로 날짜를 못 찾은 문장에 AI가 없는 날짜를 준 경우
    use_extractor(client, Extractor({"schdl_ymd": "2026-02-30"}))
    as_member(client, 1)
    room = java.add_room(1, "제목", pet_sn=CHOCO)
    card = done(send(client, room, "3시에 메이 동물병원 예방접종 잡아줘"))["card"]

    assert card["cardType"] == "ASK"
    assert card["schdlYmd"] is None
    assert card["missing"] == ["schdlYmd"]


def test_AI가_규칙으로_찬_칸을_덮어쓰지_않는다(client, java):
    use_extractor(client, Extractor({"schdl_ymd": "2026-12-25", "hsptl_nm": "다른 병원"}))
    as_member(client, 1)
    room = java.add_room(1, "제목", pet_sn=CHOCO)
    card = done(send(client, room, "금요일에 메이 동물병원 잡아줘"))["card"]

    assert card["schdlYmd"] == "2026-10-02"
    assert card["hsptlNm"] == "메이 동물병원"


def test_AI_보조_해석이_실패해도_오류가_아니라_되묻는다(client, java):
    use_extractor(client, Extractor(fail=True))
    as_member(client, 1)
    room = java.add_room(1, "제목", pet_sn=CHOCO)
    evs = send(client, room, "금요일에 병원 예약 잡아줘")

    assert names(evs) == ["intent", "done"]
    assert done(evs)["card"]["cardType"] == "ASK"


# 결과 이력 저장(FN-AIM-012-11·16)


def test_등록됨은_일정_요약을_AI_메시지로_저장(client, java, extractor):
    as_member(client, 1)
    room = java.add_room(1, "제목", pet_sn=CHOCO)
    card = done(send(client, room, HOSPITAL_TEXT))["card"]

    res = register_result(client, room, "REGISTERED", card)

    assert res.status_code == 201
    assert res.json()["data"]["cnvrsCn"] == "✔ 등록됨 — 초코 예방접종 · 10-06(화) 15:00"
    assert res.json()["data"]["roleCd"] == ROLE_AI
    # 다시 열면 버튼 없이 결과 글만 유지
    detail = client.get(f"/ai/conversations/{room}", headers=AJAX).json()["data"]
    assert detail["messages"][-1]["cnvrsCn"] == "✔ 등록됨 — 초코 예방접종 · 10-06(화) 15:00"


def test_시간이_없으면_요약에_날짜만(client, java, extractor):
    as_member(client, 1)
    room = java.add_room(1, "제목", pet_sn=CHOCO)
    card = done(send(client, room, "모레 목욕 예약해줘"))["card"]

    res = register_result(client, room, "REGISTERED", card)

    assert res.json()["data"]["cnvrsCn"] == "✔ 등록됨 — 초코 목욕 · 10-01(목)"


def test_등록됨은_케어_항목_요약을_저장(client, java, extractor):
    as_member(client, 1)
    room = java.add_room(1, "제목")
    card = done(send(client, room, CARE_TEXT))["card"]

    res = register_result(client, room, "REGISTERED", card)

    expected = "✔ 등록됨 — 뭉치 발톱 깎기 · 2주마다 · 다음 예정일 10-10(토)"
    assert res.json()["data"]["cnvrsCn"] == expected


def test_취소됨은_취소_문구를_저장(client, java, extractor):
    as_member(client, 1)
    room = java.add_room(1, "제목", pet_sn=CHOCO)
    card = done(send(client, room, HOSPITAL_TEXT))["card"]

    res = register_result(client, room, "CANCELED", card)

    assert res.status_code == 201
    assert res.json()["data"]["cnvrsCn"] == CANCELED_MESSAGE == "취소됨 — 등록하지 않았어요."
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [CANCELED_MESSAGE]


@pytest.mark.parametrize(
    "card",
    [
        # 병원 일정인데 병원명이 없음
        {
            "cardType": "SCHEDULE",
            "petSn": 1,
            "petNm": "초코",
            "schdlKndCd": "HLTC0057",
            "schdlYmd": "2026-10-06",
            "ckupTypeCd": "HLTC0002",
        },
        # 되물음 카드는 결과 없음
        {"cardType": "ASK", "petSn": 1, "petNm": "초코"},
        # 반려동물 없음
        {"cardType": "CARE_ITEM", "careArtclNm": "산책", "careZoneCd": "HLTC0036"},
    ],
)
def test_카드_칸이_비면_400(client, java, card):
    as_member(client, 1)
    room = java.add_room(1, "제목")

    res = register_result(client, room, "REGISTERED", card)

    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"
    assert java.ai_messages(room) == []


def test_결과값이_허용값_밖이면_400(client, java):
    as_member(client, 1)
    room = java.add_room(1, "제목")
    card = {"cardType": "CARE_ITEM", "petNm": "초코", "careArtclNm": "산책"}

    res = register_result(client, room, "DONE", card | {"careZoneCd": "HLTC0036"})

    assert res.status_code == 400


def test_남의_대화에_결과를_저장하면_404(client, java, extractor):
    as_member(client, 1)
    mine = java.add_room(1, "제목", pet_sn=CHOCO)
    card = done(send(client, mine, HOSPITAL_TEXT))["card"]
    others = java.add_room(2, "남의 방")

    res = register_result(client, others, "REGISTERED", card)

    assert res.status_code == 404
    assert java.ai_messages(others) == []


# Java 등록 맥락 내부 API(GET /internal/ai/register-context, 백엔드 #54)


def test_반려동물_목록은_Java에_쿠키와_X_Requested_With로_요청한다(client, java, extractor):
    as_member(client, 7)
    room = java.add_room(7, "제목")
    send(client, room, "초코 " + HOSPITAL_TEXT)

    sent = [r for r in java.requests if r.url.path == "/internal/ai/register-context"]
    assert len(sent) == 1
    assert sent[0].method == "GET"
    assert "access_token=member-7" in sent[0].headers["cookie"]
    assert sent[0].headers["x-requested-with"] == "XMLHttpRequest"


def test_Java가_준_반려동물로_카드의_반려동물을_정한다(client, java, extractor):
    # FN-AIM-012-04 : 1마리 회원이면 그 반려동물
    java.pets = [{"petSn": 9, "petNm": "보리", "careArtclNms": []}]
    as_member(client, 1)
    room = java.add_room(1, "제목")
    card = done(send(client, room, HOSPITAL_TEXT))["card"]

    assert (card["petSn"], card["petNm"]) == (9, "보리")


@pytest.mark.parametrize("status", [401, 500, 0])
def test_Java_등록_맥락이_실패하면_SSE_error(client, java, extractor, status):
    # 스트림 시작 뒤라 Java 본문 전달 불가(0은 연결 실패)
    java.context_status = status
    as_member(client, 1)
    room = java.add_room(1, "제목")
    evs = send(client, room, HOSPITAL_TEXT)

    assert names(evs) == ["intent", "error"]
    assert evs[-1][1]["code"] == "EXTERNAL_API_ERROR"
    assert java.ai_messages(room) == []
