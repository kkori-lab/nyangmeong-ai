"""SCR-AIM-012 2단계 쓰기 ③ : 배열·파일 칸 확인 카드 (지출 등록·관찰 기록 추가)"""

import copy
import logging

import pytest

from app.chat import catalog, rules
from app.chat.service import ACTION_ADD_TARGET_MISSING, ACTION_SHOWN
from tests.chat.fakes import FAKE_CODES, FakeToolAgent, fake_catalog_json
from tests.chat.test_action import action_result, send
from tests.chat.test_messages import MessageJava, deltas, events
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import CHOCO, MUNG, TODAY
from tests.chat.test_tools import room_of, use_agent

FOOD = "MYPC0013"
DIRECT = "MYPC0019"
BIGGER = "HLTC0054"


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


def tool_of(raw: dict, name: str) -> dict:
    return next(tool for tool in raw["tools"] if tool["name"] == name)


def with_nested_codes(raw: dict) -> dict:
    # 가짜 응답(fake_catalog_json)은 요청 칸에만 코드 값을 넣는다 : 배열 항목 칸에도 넣음
    def fill(params: dict) -> None:
        for param in params.values():
            if param["type"] == "code" and "codes" not in param:
                param["codes"] = FAKE_CODES[param["group"]]
            if "items" in param:
                fill(param["items"])

    for tool in raw["tools"]:
        fill(tool["params"])
    return raw


def build(raw: dict, prompts: dict | None = None) -> catalog.Catalog:
    return catalog.build(catalog.ToolCatalogResponse.model_validate(raw), prompts=prompts)


RECEIPT_PROMPT = {
    "label": "영수증 저장",
    "description": "쓸 때: 시험\n말하는 법: 시험",
    "params": {
        "recpt_sn": {"java": "recptSn", "description": "영수증 번호"},
        "hsptl_nm": {"java": "hsptlNm", "description": "병원"},
        "ckup_ymd": {"java": "ckupYmd", "description": "진료일"},
        "pet_sn": {"java": "pets[].petSn", "description": "반려동물"},
        "ckup_type_cd": {"java": "pets[].ckupTypeCd", "description": "진료 유형"},
    },
}


def receipt_entry() -> catalog.CatalogEntry:
    prompts = catalog.tool_prompts() | {
        "draft_receipt_save": catalog.ToolPrompt.model_validate(RECEIPT_PROMPT)
    }
    return build(with_nested_codes(fake_catalog_json()), prompts).entries["draft_receipt_save"]


def entry_of(name: str) -> catalog.CatalogEntry:
    return build(fake_catalog_json()).entries[name]


# 카탈로그 : 배열·파일 칸을 읽는다


def test_배열과_파일_칸이_있는_도구를_버리지_않고_실어야_한다():
    built = build(fake_catalog_json())

    assert {"draft_expense", "draft_observation_cycle"} <= set(built.entries)
    expense = built.entries["draft_expense"]
    assert expense.params["lines"].type == "array"
    assert expense.params["lines"].min_items == 1
    assert expense.params["lines"].items["idmptDmndId"].generated == "uuid"
    cycle = built.entries["draft_observation_cycle"]
    assert cycle.params["file"].type == "file"
    assert cycle.call.content_type == "multipart/form-data"


def test_영수증_저장은_skip이라_싣지_않지만_설명을_주면_중첩_배열까지_읽어야_한다(caplog):
    with caplog.at_level(logging.INFO, logger="app.chat.catalog"):
        built = build(fake_catalog_json())
    assert "draft_receipt_save" not in built.entries
    assert "draft_receipt_save 싣지 않음(" in caplog.text
    assert "draft_receipt_save 설명 없음" not in caplog.text

    entry = receipt_entry()
    drugs = entry.params["pets"].items["drugs"]
    assert drugs.type == "array"
    assert drugs.items["dayMdcnNmtm"].positive is True
    assert entry.to_java_name["ckup_type_cd"] == "pets[].ckupTypeCd"


def test_배열_항목의_코드_칸에_코드_값이_없으면_싣지_않아야_한다(caplog):
    prompts = catalog.tool_prompts() | {
        "draft_receipt_save": catalog.ToolPrompt.model_validate(RECEIPT_PROMPT)
    }
    with caplog.at_level(logging.WARNING, logger="app.chat.catalog"):
        built = build(fake_catalog_json(), prompts)

    assert "draft_receipt_save" not in built.entries
    assert "코드 값 없음 HLTG01" in caplog.text


def test_고정_값이_Java_코드_목록에_없으면_싣지_않아야_한다(caplog):
    raw = fake_catalog_json()
    param = tool_of(raw, "draft_expense")["params"]["expndInptMthCd"]
    param["codes"] = [code for code in param["codes"] if code["cd"] != DIRECT]

    with caplog.at_level(logging.WARNING, logger="app.chat.catalog"):
        built = build(raw)

    assert "draft_expense" not in built.entries
    assert f"고정 값 잘못 expndInptMthCd={DIRECT}" in caplog.text


def test_설명이_없는_배열_항목_칸을_가리키면_싣지_않아야_한다(caplog):
    prompts = copy.deepcopy(catalog.tool_prompts())
    prompts["draft_expense"].params["expnd_amt"].java = "lines[].nope"

    with caplog.at_level(logging.WARNING, logger="app.chat.catalog"):
        built = build(fake_catalog_json(), prompts)

    assert "draft_expense" not in built.entries
    assert "Java에 없는 칸 expnd_amt->lines[].nope" in caplog.text


# 카탈로그 : 배열 검사·빈 칸


def test_배열은_항목_칸마다_Java_규칙으로_검사해야_한다():
    entry = receipt_entry()
    pets = entry.params["pets"]
    good = [
        {
            "petSn": 1,
            "ckupTypeCd": "HLTC0001",
            "drugs": [
                {
                    "mdcnNm": "아조딜",
                    "mdcnBgngYmd": "2026-09-01",
                    "mdcnEndYmd": "2026-09-07",
                    "dayMdcnNmtm": 2,
                    "prscSttsCd": "HLTC0010",
                }
            ],
        }
    ]
    assert catalog._valid(pets, good)
    zero = copy.deepcopy(good)
    zero[0]["drugs"][0]["dayMdcnNmtm"] = 0
    assert not catalog._valid(pets, zero)
    unknown = copy.deepcopy(good)
    unknown[0]["nope"] = 1
    assert not catalog._valid(pets, unknown)
    assert not catalog._valid(pets, {"petSn": 1})


def test_빈_필수_배열과_항목_안_빈_필수_칸은_칸_경로로_세야_한다():
    entry = receipt_entry()
    base = {"recptSn": 9, "hsptlNm": "튼튼병원", "ckupYmd": "2026-09-29"}

    assert catalog.missing(entry, base) == ["pets"]
    rows = {"pets": [{"petSn": 1, "drugs": [{"mdcnNm": "아조딜"}]}]}
    assert catalog.missing(entry, base | rows) == [
        "pets[0].ckupTypeCd",
        "pets[0].drugs[0].mdcnBgngYmd",
        "pets[0].drugs[0].mdcnEndYmd",
        "pets[0].drugs[0].dayMdcnNmtm",
        "pets[0].drugs[0].prscSttsCd",
    ]


def test_generated_칸은_필수로_세지_않고_파일_칸은_카드에서만_세야_한다():
    expense = entry_of("draft_expense")
    values = {
        "expndYmd": "2026-09-29",
        "expndClsfCd": FOOD,
        "expndInptMthCd": DIRECT,
        "lines": [{"expndAmt": 32000}],
    }
    assert catalog.missing(expense, values) == []

    cycle = entry_of("draft_observation_cycle")
    values = {"petSn": CHOCO, "obsrvArtclSn": 5, "obsrvDt": "2026-09-29T09:00:00"}
    assert catalog.missing(cycle, values) == ["file"]
    assert catalog.missing(cycle, values, files=False) == []


def test_카드_input은_파일_칸과_틀린_항목_칸만_버려야_한다():
    expense = entry_of("draft_expense")
    prior = {"lines": [{"petSn": MUNG, "expndAmt": 0, "nope": 1}], "file": "x"}

    values = catalog.card_input(expense, {}, prior=prior)

    assert values["lines"] == [{"petSn": MUNG}]
    assert values["expndInptMthCd"] == DIRECT
    cycle = entry_of("draft_observation_cycle")
    assert "file" not in catalog.card_input(cycle, {}, prior={"file": "photo.png"})


# 지출 등록 카드


def expense_agent(**raw) -> FakeToolAgent:
    args = {"expnd_ymd": "2026-09-28", "expnd_clsf_cd": FOOD, "expnd_amt": 32000} | raw
    return FakeToolAgent("draft_expense", args)


def test_지출_등록_요청은_줄_하나와_입력_방법을_카드에_실어야_한다(client, java):
    use_agent(client, expense_agent(dtl_mttr="사료"))
    room = room_of(client, java)

    evs = events(send(client, room, "어제 사료 3만 2천원 샀어 가계부에 적어 줘"))

    assert evs[0][1]["kind"] == "ACTION"
    action = evs[-1][1]["action"]
    assert (action["tool"], action["domain"], action["label"]) == (
        "draft_expense",
        "expense",
        "지출 등록",
    )
    assert action["call"] == {"method": "POST", "path": "/api/expenses"}
    assert action["input"] == {
        "expndYmd": "2026-09-28",
        "expndClsfCd": FOOD,
        "dtlMttr": "사료",
        "expndInptMthCd": DIRECT,
        "lines": [{"expndAmt": 32000}],
    }
    assert action["missing"] == []
    lines = action["params"]["lines"]
    assert lines["type"] == "array"
    assert lines["minItems"] == 1
    assert lines["items"]["idmptDmndId"]["generated"] == "uuid"
    assert action["petChoices"] == []
    assert len(java.ai_messages(room)) == 1  # 카드 요약 글 (2026-11-13)


def test_지출_등록은_문장_속_반려동물_이름이_하나면_줄의_petSn으로_넣어야_한다(client, java):
    use_agent(client, expense_agent())
    room = room_of(client, java)

    action = events(send(client, room, "초코 사료 3만 2천원 가계부에 적어 줘"))[-1][1]["action"]

    assert action["input"]["lines"] == [{"expndAmt": 32000, "petSn": CHOCO}]


def test_지출_등록_금액이_없거나_0이면_줄의_금액_칸을_물어야_한다(client, java):
    room = room_of(client, java)

    use_agent(client, expense_agent(expnd_amt=None))
    action = events(send(client, room, "어제 사료 샀어 가계부에 적어 줘"))[-1][1]["action"]
    assert action["input"]["lines"] == [{}]
    assert action["missing"] == ["lines[0].expndAmt"]

    use_agent(client, expense_agent(expnd_amt=0, expnd_clsf_cd="MYPC9999"))
    action = events(send(client, room, "어제 사료 0원 적어 줘"))[-1][1]["action"]
    assert "expndClsfCd" not in action["input"]
    assert action["missing"] == ["expndClsfCd", "lines[0].expndAmt"]


def test_돌려받은_지출_카드의_줄에_이_메시지_금액을_덮어써야_한다(client, java):
    use_agent(client, FakeToolAgent("draft_expense", {"expnd_amt": 40000}))
    room = room_of(client, java)
    prior = {
        "tool": "draft_expense",
        "input": {
            "expndYmd": "2026-09-28",
            "expndClsfCd": FOOD,
            "lines": [{"petSn": MUNG, "expndAmt": 32000}],
        },
    }

    action = events(send(client, room, "4만원으로 바꿔 줘", action=prior))[-1][1]["action"]

    assert action["input"]["lines"] == [{"petSn": MUNG, "expndAmt": 40000}]
    assert action["input"]["expndYmd"] == "2026-09-28"


# 관찰 기록 추가 카드


ITEMS = [{"obsrvArtclSn": 5, "obsrvArtclNm": "등 혹", "obsrvSttsCd": "HLTC0050"}]


def observe_after_read(client, raw: dict) -> FakeToolAgent:
    use_reader(client, FakeToolReader(ITEMS))
    return use_agent(
        client,
        FakeToolAgent(
            "list_observation_items", {}, follow_tool="draft_observation_cycle", follow_raw=raw
        ),
    )


def test_관찰_항목을_읽은_뒤_고른_관찰_기록은_목록의_번호와_빈_사진_칸을_카드에_실어야_한다(
    client, java
):
    agent = observe_after_read(
        client,
        {
            "obsrv_artcl_sn": 5,
            "obsrv_ymd": TODAY.isoformat(),
            "obsrv_tm": "09:00",
            "obsrv_sz": 1.2,
            "obsrv_chg_cd": BIGGER,
        },
    )
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "초코 등에 난 혹 오늘 1.2cm야 기록해 줘"))

    assert agent.results[1].startswith(ACTION_SHOWN.split("{summary}")[0])
    action = evs[-1][1]["action"]
    assert action["tool"] == "draft_observation_cycle"
    assert action["call"] == {
        "method": "POST",
        "path": "/api/pets/{petSn}/observation-cycles",
        "contentType": "multipart/form-data",
    }
    assert action["input"] == {
        "petSn": CHOCO,
        "obsrvArtclSn": 5,
        "obsrvDt": f"{TODAY.isoformat()}T09:00:00",
        "obsrvSz": 1.2,
        "obsrvChgCd": BIGGER,
    }
    assert action["missing"] == ["file"]
    assert action["params"]["file"]["type"] == "file"


def test_관찰_항목을_읽었는데_목록에_없는_번호면_카드_없이_다시_물어야_한다(client, java):
    agent = observe_after_read(client, {"obsrv_artcl_sn": 99, "obsrv_sz": 1.2})
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "등에 난 혹 1.2cm야 기록해 줘"))

    assert agent.results[1] == ACTION_ADD_TARGET_MISSING
    assert evs[-1][1]["action"] is None


def test_읽기_없이_바로_고른_관찰_기록은_카드_없이_안내_글을_저장해야_한다(client, java):
    use_agent(
        client, FakeToolAgent("draft_observation_cycle", {"obsrv_artcl_sn": 5, "obsrv_sz": 1.2})
    )
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "등에 난 혹 1.2cm야 기록해 줘"))

    message = "기록할 관찰 항목을 찾지 못했어요. 이름을 넣어 다시 말해 주세요."
    assert evs[0][1]["kind"] == "SEARCH"
    assert evs[-1][1]["action"] is None
    assert deltas(evs) == message
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [message]


# 결과 저장(action-result)


EXPENSE_DONE = {
    "expndYmd": "2026-09-29",
    "expndClsfCd": FOOD,
    "expndInptMthCd": DIRECT,
    "lines": [{"petSn": None, "expndAmt": 32000, "idmptDmndId": "3f1c0a9e-uuid"}],
}


def test_지출_등록_결과는_줄의_금액까지_요약해_저장해야_한다(client, java):
    room = room_of(client, java)

    res = action_result(client, room, "draft_expense", "DONE", EXPENSE_DONE)

    assert res.status_code == 201
    assert res.json()["data"]["cnvrsCn"] == "✔ 지출 등록 — 09-29(화) · 사료 · 32,000"


@pytest.mark.parametrize(
    "lines",
    [
        [{"petSn": CHOCO}],  # 항목 안 필수 칸 빔
        [{"expndAmt": 32000, "nope": 1}],  # 목록 밖 항목 칸
        [],  # minItems 1
    ],
)
def test_지출_등록_결과의_줄이_Java_규칙_밖이면_400이어야_한다(client, java, lines):
    room = room_of(client, java)

    res = action_result(client, room, "draft_expense", "DONE", EXPENSE_DONE | {"lines": lines})

    assert res.status_code == 400
    assert java.ai_messages(room) == []


def test_관찰_기록_결과는_사진_칸_없이도_저장하고_사진_값은_버려야_한다(client, java):
    room = room_of(client, java, pet_sn=CHOCO)
    done = {
        "petSn": CHOCO,
        "obsrvArtclSn": 5,
        "obsrvDt": "2026-09-29T09:00:00",
        "obsrvSz": 1.2,
    }

    res = action_result(client, room, "draft_observation_cycle", "DONE", done)
    again = action_result(
        client, room, "draft_observation_cycle", "DONE", done | {"file": "photo.png"}
    )
    canceled = action_result(client, room, "draft_observation_cycle", "CANCELED", {})

    assert res.status_code == again.status_code == canceled.status_code == 201
    assert res.json()["data"]["cnvrsCn"] == "✔ 관찰 기록 추가 — 09-29(화) 09:00 · 1.2"
    assert canceled.json()["data"]["cnvrsCn"] == "취소됨 — 관찰 기록 추가 · 저장하지 않았어요."
