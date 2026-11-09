import pytest

from app.chat import rules
from app.chat.service import ACTION_SHOWN, DISCLAIMER
from tests.chat.conftest import AJAX
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_messages import MessageJava, deltas, events, names
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import CHOCO, MUNG, TODAY
from tests.chat.test_tools import room_of, use_agent

WEIGHT = "HLTC0014"
STOOL = "HLTC0017"


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


def send(client, room_sn: int, cn: str, action: dict | None = None):
    body: dict = {"cnvrsCn": cn}
    if action is not None:
        body["action"] = action
    return client.post(f"/ai/conversations/{room_sn}/messages", json=body, headers=AJAX)


def action_result(client, room_sn: int, tool: str, status: str, values: dict):
    return client.post(
        f"/ai/conversations/{room_sn}/action-result",
        json={"tool": tool, "status": status, "input": values},
        headers=AJAX,
    )


def weight_agent(**raw) -> FakeToolAgent:
    args = {"daily_rcd_idct_cd": WEIGHT, "rcd_ymd": TODAY.isoformat(), "rcd_nvl": 4.2} | raw
    return FakeToolAgent("draft_daily_health_record", args)


# 확인 카드(intent ACTION)


def test_건강_일지_요청은_ACTION_카드에_Java_칸과_검증한_값을_실어야_한다(client, java):
    agent = use_agent(client, weight_agent(rcd_tm="08:30"))
    room = room_of(client, java)

    evs = events(send(client, room, "초코 오늘 아침 8시 반 체중 4.2kg 기록해줘"))

    assert names(evs) == ["intent", "done"]
    assert evs[0][1]["kind"] == "ACTION"
    action = evs[1][1]["action"]
    assert (action["tool"], action["domain"], action["label"]) == (
        "draft_daily_health_record",
        "health",
        "건강 일지 기록",
    )
    assert action["call"] == {"method": "POST", "path": "/api/pets/{petSn}/daily-health-records"}
    assert action["input"] == {
        "petSn": CHOCO,
        "dailyRcdIdctCd": WEIGHT,
        "rcdDt": "2026-09-29T08:30:00",
        "rcdNvl": 4.2,
    }
    assert action["missing"] == []
    assert (action["petNm"], action["petChoices"]) == ("초코", [])
    kind = action["params"]["dailyRcdIdctCd"]
    assert (kind["in"], kind["type"], kind["group"], kind["required"]) == (
        "body",
        "code",
        "HLTG09",
        True,
    )
    assert {"cd": WEIGHT, "nm": "체중"} in kind["codes"]
    assert action["params"]["petSn"]["in"] == "path"
    assert {"field": "rcdNvl", "when": "dailyRcdIdctCd", "equals": WEIGHT} in action["rules"]
    assert evs[1][1]["card"] is None and evs[1][1]["message"] is None
    assert java.ai_messages(room) == []
    assert agent.decides[0][2] == rules.match_route("초코 오늘 아침 8시 반 체중 4.2kg 기록해줘")


def test_월_지출_한도_요청은_반려동물_없이_ACTION_카드여야_한다(client, java):
    use_agent(client, FakeToolAgent("draft_expense_limit", {"mm_expnd_lim_amt": 300000}))
    room = room_of(client, java)

    evs = events(send(client, room, "이번 달 지출 한도 30만원으로 해줘"))

    assert evs[0][1]["kind"] == "ACTION"
    action = evs[1][1]["action"]
    assert action["tool"] == "draft_expense_limit"
    assert action["call"] == {"method": "PUT", "path": "/api/members/me/expense-limit"}
    assert action["input"] == {"mmExpndLimAmt": 300000}
    assert (action["missing"], action["petChoices"], action["petNm"]) == ([], [], None)
    assert action["params"]["mmExpndLimAmt"]["min"] == 1


def test_날짜만_오고_오늘이면_지금_시각을_붙여야_한다(client, java):
    use_agent(client, weight_agent())
    room = room_of(client, java)

    action = events(send(client, room, "초코 오늘 체중 4.2kg 기록해줘"))[-1][1]["action"]

    assert action["input"]["rcdDt"].startswith("2026-09-29T")
    assert action["missing"] == []


def test_날짜만_오고_다른_날이면_기록_시각을_빈_칸으로_되물어야_한다(client, java):
    use_agent(client, weight_agent(rcd_ymd="2026-09-27"))
    room = room_of(client, java)

    action = events(send(client, room, "초코 그저께 체중 4.2kg 기록해줘"))[-1][1]["action"]

    assert "rcdDt" not in action["input"]
    assert action["missing"] == ["rcdDt"]


@pytest.mark.parametrize(
    ("raw", "missing"),
    [
        # 체중은 수치 필수(requiredIf)
        ({"rcd_nvl": None}, ["rcdNvl"]),
        # 배변상태는 상태 필수(requiredIf), 수치는 아님
        ({"daily_rcd_idct_cd": STOOL, "rcd_nvl": None}, ["crsdSttsCd"]),
        # Java 목록에 없는 코드 값은 비우고 되물음
        ({"daily_rcd_idct_cd": "HLTC9999"}, ["dailyRcdIdctCd"]),
    ],
)
def test_필수_칸이_비면_missing에_Java_칸_이름으로_담아야_한다(client, java, raw, missing):
    use_agent(client, weight_agent(**raw))
    room = room_of(client, java)

    action = events(send(client, room, "초코 오늘 기록해줘"))[-1][1]["action"]

    assert action["missing"] == missing


def test_반려동물을_정하지_못하면_petChoices로_되물어야_한다(client, java):
    use_agent(client, weight_agent())
    room = room_of(client, java)

    action = events(send(client, room, "오늘 체중 4.2kg 기록해줘"))[-1][1]["action"]

    assert "petSn" not in action["input"]
    assert action["missing"] == ["petSn"]
    assert action["petNm"] is None
    assert action["petChoices"] == [
        {"petSn": CHOCO, "petNm": "초코"},
        {"petSn": MUNG, "petNm": "뭉치"},
    ]


def test_돌려받은_카드와_같은_도구면_그_값에_이_메시지_칸을_덮어써야_한다(client, java):
    use_agent(client, FakeToolAgent("draft_daily_health_record", {"rcd_nvl": 4.5}))
    room = room_of(client, java)
    prior = {
        "tool": "draft_daily_health_record",
        "input": {"petSn": MUNG, "dailyRcdIdctCd": WEIGHT, "rcdDt": "2026-09-29T08:00:00"},
    }

    evs = events(send(client, room, "아 4.5kg이었어", action=prior))

    action = evs[-1][1]["action"]
    assert evs[0][1]["kind"] == "ACTION"
    assert action["input"] == {
        "petSn": MUNG,
        "dailyRcdIdctCd": WEIGHT,
        "rcdDt": "2026-09-29T08:00:00",
        "rcdNvl": 4.5,
    }
    assert action["missing"] == []


def test_돌려받은_카드의_틀린_값은_비워야_한다(client, java):
    use_agent(client, FakeToolAgent("draft_expense_limit", {}))
    room = room_of(client, java)
    prior = {"tool": "draft_expense_limit", "input": {"mmExpndLimAmt": 0, "unknown": 1}}

    action = events(send(client, room, "한도 바꿔 줘", action=prior))[-1][1]["action"]

    assert action["input"] == {}
    assert action["missing"] == ["mmExpndLimAmt"]


def test_돌려받은_카드와_다른_도구면_그_값을_쓰지_않아야_한다(client, java):
    use_agent(client, FakeToolAgent("draft_expense_limit", {}))
    room = room_of(client, java)
    prior = {"tool": "draft_daily_health_record", "input": {"rcdNvl": 4.5}}

    action = events(send(client, room, "한도 바꿔 줘", action=prior))[-1][1]["action"]

    assert action["input"] == {}


def test_처음_고른_완료_체크_카드의_케어_항목_번호는_빈_칸이어야_한다(client, java):
    use_agent(client, FakeToolAgent("draft_care_completion", {"care_artcl_sn": 7}))
    room = room_of(client, java, pet_sn=CHOCO)

    action = events(send(client, room, "산책 완료 체크해줘"))[-1][1]["action"]

    assert action["input"] == {"petSn": CHOCO}
    assert action["missing"] == ["careArtclSn"]


# READ 다음 쓰기 도구(목록 -> 완료 체크)


@pytest.mark.parametrize(("picked", "expected"), [(7, {"careArtclSn": 7}), (99, {})])
def test_케어_목록을_읽은_뒤_고른_완료_체크는_목록에_나온_번호만_카드에_실어야_한다(
    client, java, picked, expected
):
    agent = use_agent(
        client,
        FakeToolAgent(
            "list_care_items",
            {},
            follow_tool="draft_care_completion",
            follow_raw={"care_artcl_sn": picked},
        ),
    )
    reader = use_reader(client, FakeToolReader([{"careArtclSn": 7, "careArtclNm": "산책"}]))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "오늘 산책 완료 체크해줘"))

    assert evs[0][1]["kind"] == "SEARCH"
    assert len(reader.calls) == 1
    assert agent.results[1] == ACTION_SHOWN
    action = evs[-1][1]["action"]
    assert action["tool"] == "draft_care_completion"
    assert action["input"] == {"petSn": CHOCO} | expected
    assert action["missing"] == ([] if expected else ["careArtclSn"])
    assert deltas(evs) == "안내서대로 답할게요." + DISCLAIMER


def test_읽기만_한_답변에는_확인_카드가_없어야_한다(client, java):
    use_agent(client, FakeToolAgent("list_care_items", {}))
    use_reader(client, FakeToolReader([{"careArtclSn": 7}]))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "케어 항목 뭐 있어?"))

    assert evs[-1][1]["action"] is None


# 기존 등록 카드


@pytest.mark.parametrize("tool", ["draft_schedule", "draft_care_item"])
def test_기존_등록_도구도_ACTION_카드여야_한다(client, java, tool):
    # SCR-AIM-012 2단계 ④ : 등록 카드 2개도 확인 카드로
    use_agent(client, FakeToolAgent(tool, {}))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "등록해 줘"))

    assert evs[0][1]["kind"] == "ACTION"
    assert evs[-1][1]["card"] is None
    assert evs[-1][1]["action"]["tool"] == tool


# 추가-1 : 키워드에 걸린 문장도 도구 고르기


def test_키워드에_걸린_질문꼴_아닌_문장도_힌트와_함께_도구_고르기를_불러야_한다(client, java):
    agent = use_agent(client, FakeToolAgent("draft_expense_limit", {"mm_expnd_lim_amt": 300000}))
    room = room_of(client, java)

    evs = events(send(client, room, "이번 달 지출 한도 30만원으로 해줘"))

    assert evs[0][1]["kind"] == "ACTION"
    assert agent.decides[0][2] == rules.match_route("이번 달 지출 한도 30만원으로 해줘")


def test_키워드에_걸린_문장은_도구_고르기가_실패하면_그_행으로_이동해야_한다(client, java):
    use_agent(client, FakeToolAgent(fail=True))
    room = room_of(client, java)

    evs = events(send(client, room, "초코 오늘 체중 4.2kg 기록해줘"))

    row = rules.match_route("초코 오늘 체중 4.2kg 기록해줘")
    assert (evs[0][1]["kind"], evs[0][1]["scrId"]) == ("ROUTE", row.scr_id)


# 결과 저장(action-result)


@pytest.mark.parametrize(
    ("tool", "values", "message"),
    [
        (
            "draft_daily_health_record",
            {
                "petSn": CHOCO,
                "dailyRcdIdctCd": WEIGHT,
                "rcdDt": "2026-09-29T08:30:00",
                "rcdNvl": 4.2,
            },
            "✔ 건강 일지 기록 — 체중 · 09-29(화) 08:30 · 4.2",
        ),
        ("draft_expense_limit", {"mmExpndLimAmt": 300000}, "✔ 월 지출 한도 설정 — 300,000"),
        ("draft_care_completion", {"petSn": CHOCO, "careArtclSn": 7}, "✔ 케어 완료 체크"),
    ],
)
def test_완료_결과는_도구_이름과_값으로_요약해_저장해야_한다(client, java, tool, values, message):
    room = room_of(client, java)

    res = action_result(client, room, tool, "DONE", values)

    assert res.status_code == 201
    assert res.json()["data"]["cnvrsCn"] == message
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [message]


@pytest.mark.parametrize(
    ("status", "message"),
    [
        ("CANCELED", "취소됨 — 월 지출 한도 설정 · 저장하지 않았어요."),
        ("FAILED", "실패 — 월 지출 한도 설정 · 저장하지 못했어요."),
    ],
)
def test_취소와_실패는_빈_칸이어도_정해진_글로_저장해야_한다(client, java, status, message):
    room = room_of(client, java)

    res = action_result(client, room, "draft_expense_limit", status, {})

    assert res.status_code == 201
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [message]


@pytest.mark.parametrize(
    ("tool", "status", "values"),
    [
        # 목록 밖 도구, 등록 카드 도구인데 필수 칸 빔
        ("delete_pet", "DONE", {}),
        ("draft_schedule", "DONE", {}),
        # 허용값 밖
        ("draft_expense_limit", "DONE", {"mmExpndLimAmt": 0}),
        ("draft_daily_health_record", "CANCELED", {"dailyRcdIdctCd": "HLTC9999"}),
        ("draft_expense_limit", "DONE", {"unknown": 1}),
        ("draft_expense_limit", "SAVED", {"mmExpndLimAmt": 1}),
        # 완료인데 필수 칸 빔
        ("draft_care_completion", "DONE", {"petSn": CHOCO}),
    ],
)
def test_목록_밖_도구나_허용값_밖이면_400(client, java, tool, status, values):
    room = room_of(client, java)

    res = action_result(client, room, tool, status, values)

    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"
    assert java.ai_messages(room) == []


def test_남의_대화에_결과를_저장하면_404(client, java):
    room_of(client, java)
    others = java.add_room(2, "남의 방")

    res = action_result(client, others, "draft_expense_limit", "DONE", {"mmExpndLimAmt": 1})

    assert res.status_code == 404
    assert java.ai_messages(others) == []
