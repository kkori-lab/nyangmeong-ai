"""SCR-AIM-012 수정·삭제 도구 (2026-11-25 추가 요청)
- 삭제 카드 : READ 결과 행으로 대상 글(targetText), 확인 말은 삭제 동사가 든 말만
- 수정 카드 : 말한 칸만 input에 (PATCH는 보낸 값만 수정)"""

import pytest

from app.chat import catalog, rules, tools
from app.chat.schemas import ActionCard
from app.chat.service import (
    ACTION_ASK_DELETE,
    ACTION_DELETE_CONFIRM,
    ACTION_DELETE_TARGET_MISSING,
    action_ask_message,
    delete_target_text,
)
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_action import send
from tests.chat.test_action_update_follow import ChainAgent
from tests.chat.test_messages import AJAX, MessageJava, events
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import CHOCO, TODAY
from tests.chat.test_tools import room_of, use_agent

DELETE_RECORD = "delete_daily_health_record"
WEIGHT = "HLTC0014"
RECORDS = [
    {
        "dailyHlthRcdSn": 51,
        "dailyRcdIdctCd": WEIGHT,
        "rcdNvl": 4.2,
        "rcdDt": "2026-09-28T08:30:00",
    }
]
TARGET = "09-28(월) 08:30 · 체중 · 4.2kg"
DRAFT = {
    "tool": DELETE_RECORD,
    "input": {"petSn": CHOCO, "dailyHlthRcdSn": 51},
    "targetText": TARGET,
}


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


def done_of(response) -> dict:
    evs = events(response)
    assert evs[-1][0] == "done"
    return evs[-1][1]


def send_actions(client, room: int, cn: str, actions: list[dict]):
    body = {"cnvrsCn": cn, "actions": actions}
    return client.post(f"/ai/conversations/{room}/messages", json=body, headers=AJAX)


def result(client, room: int, body: dict):
    return client.post(f"/ai/conversations/{room}/action-result", json=body, headers=AJAX)


# 확인 말


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("삭제해 줘", rules.ACTION_CONFIRM),
        ("지워줘", rules.ACTION_CONFIRM),
        ("응 삭제해", rules.ACTION_CONFIRM),
        ("없애 줘!", rules.ACTION_CONFIRM),
        ("삭제하지 마", rules.ACTION_CANCEL),
        ("지우지 마", rules.ACTION_CANCEL),
    ],
)
def test_삭제_확인_취소_말을_가린다(text, kind):
    assert rules.action_reply_kind(text) == kind


def test_READ_결과로_삭제_카드와_대상_글을_만든다(client, java):
    agent = use_agent(
        client,
        ChainAgent(
            "list_daily_health_records",
            [(DELETE_RECORD, {"daily_hlth_rcd_sn": 51})],
            ("카드를 확인해 주세요.",),
        ),
    )
    use_reader(client, FakeToolReader(RECORDS))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "초코 어제 체중 기록 지워 줘"))

    action = done["action"]
    assert action["tool"] == DELETE_RECORD
    assert action["call"]["method"] == "DELETE"
    assert action["input"] == {"petSn": CHOCO, "dailyHlthRcdSn": 51}
    assert action["targetText"] == TARGET
    # READ 뒤 카드의 답변 글은 LLM이 씀 : 카드 요약(대상 글)과 '삭제해 줘' 안내를 tool_result로
    assert f"초코 건강 일지 삭제 — {TARGET}" in agent.results[1]
    assert "'삭제해 줘'" in agent.results[1]
    # 카드 턴 저장 글(돌려받은 카드를 다시 띄울 때) : 고칠 칸이 없어 확인 말 안내만
    assert action_ask_message(ActionCard.model_validate(action)) == (
        f"이렇게 할까요?\n초코 건강 일지 삭제 — {TARGET}\n{ACTION_ASK_DELETE}"
    )


def test_READ_없이_고른_삭제_도구는_카드_없이_안내한다(client, java):
    use_agent(client, FakeToolAgent(DELETE_RECORD, {}))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "체중 기록 지워 줘"))

    assert done.get("action") is None
    assert done["message"]["cnvrsCn"] == (
        "지울 건강 일지 기록을 찾지 못했어요. 이름이나 날짜를 넣어 다시 말해 주세요."
    )


def test_READ_뒤_삭제_번호를_못_정하면_LLM에_삭제_안내를_준다(client, java):
    agent = use_agent(
        client,
        ChainAgent("list_daily_health_records", [(DELETE_RECORD, {"daily_hlth_rcd_sn": 99})]),
    )
    use_reader(client, FakeToolReader(RECORDS))
    room = room_of(client, java, pet_sn=CHOCO)

    events(send(client, room, "체중 기록 지워 줘"))

    assert agent.results[1] == ACTION_DELETE_TARGET_MISSING


# 확인 턴


def test_삭제_카드에_응만_말하면_실행하지_않고_다시_안내한다(client, java):
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "응", DRAFT))

    assert done["execute"] is False
    assert done["message"]["cnvrsCn"] == ACTION_DELETE_CONFIRM
    assert done["action"]["targetText"] == TARGET


def test_삭제_카드에_삭제해_줘면_실행_지시한다(client, java):
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "삭제해 줘", DRAFT))

    assert done["execute"] is True
    assert done["message"]["cnvrsCn"] == "삭제할게요."
    assert done["action"]["call"]["method"] == "DELETE"
    assert done["action"]["targetText"] == TARGET


def test_삭제_카드_취소_말은_삭제하지_않았어요(client, java):
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "아니", DRAFT))

    assert done["message"]["cnvrsCn"] == "삭제하지 않았어요."
    assert done.get("action") is None


def test_등록_카드에_삭제해_줘는_실행하지_않는다(client, java):
    use_agent(client, FakeToolAgent("decline", {"unclear": True}))
    room = room_of(client, java, pet_sn=CHOCO)
    add = {
        "tool": "draft_daily_health_record",
        "input": {
            "petSn": CHOCO,
            "dailyRcdIdctCd": WEIGHT,
            "rcdDt": "2026-09-29T08:30:00",
            "rcdNvl": 4.2,
        },
    }

    done = done_of(send(client, room, "삭제해 줘", add))

    assert not done.get("execute")


def test_등록과_삭제가_섞이면_진행해_줘로_실행하고_응은_다시_안내한다(client, java):
    room = room_of(client, java, pet_sn=CHOCO)
    add = {"tool": "draft_care_completion", "input": {"petSn": CHOCO, "careArtclSn": 7}}

    again = done_of(send_actions(client, room, "응", [add, DRAFT]))
    run = done_of(send_actions(client, room, "진행해 줘", [add, DRAFT]))

    assert again["execute"] is False
    assert again["message"]["cnvrsCn"] == ACTION_DELETE_CONFIRM
    assert run["execute"] is True
    assert run["message"]["cnvrsCn"] == "진행할게요."


# 결과 저장


@pytest.mark.parametrize(
    ("status", "message"),
    [
        ("DONE", f"✔ 건강 일지 삭제 — {TARGET}"),
        ("CANCELED", f"취소됨 — 건강 일지 삭제 · {TARGET} · 삭제하지 않았어요."),
        ("FAILED", "실패 — 건강 일지 삭제 · 삭제하지 못했어요."),
    ],
)
def test_삭제_결과는_대상_글로_요약한다(client, java, status, message):
    room = room_of(client, java, pet_sn=CHOCO)

    response = result(client, room, DRAFT | {"status": status})

    assert response.status_code == 201
    assert java.ai_messages(room)[-1]["cnvrsCn"] == message


def test_대상_글이_없는_삭제_결과는_label만(client, java):
    room = room_of(client, java)
    body = {"tool": "delete_expense", "status": "DONE", "input": {"expndSn": 3}}

    assert result(client, room, body).status_code == 201
    assert java.ai_messages(room)[-1]["cnvrsCn"] == "✔ 지출 삭제"


# 수정 : 말한 칸만


def test_건강_일지_수정은_말한_칸만_보낸다(client, java):
    agent = use_agent(
        client,
        ChainAgent(
            "list_daily_health_records",
            [("draft_daily_health_record_update", {"daily_hlth_rcd_sn": 51, "rcd_nvl": 4.57})],
            ("카드를 확인해 주세요.",),
        ),
    )
    use_reader(client, FakeToolReader(RECORDS))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "어제 체중 4.57로 바꿔줘"))

    action = done["action"]
    assert action["tool"] == "draft_daily_health_record_update"
    assert action["call"]["method"] == "PATCH"
    assert action["input"] == {"petSn": CHOCO, "dailyHlthRcdSn": 51, "rcdNvl": 4.57}
    assert action["targetText"] is None
    assert "'수정해 줘'" in agent.results[1]


# 대상 글 : target_fields 칸 (코드 이름·단위·다른 READ 행·시간 미입력)


def target_of(tool: str, values: dict, data: object) -> str | None:
    return delete_target_text(tools.card_entry(tool), values, catalog.seen_rows(data))


def test_지출_대상_글은_분류_이름과_원_단위():
    data = [{"expndSn": 3, "expndYmd": "2026-09-28", "expndClsfCd": "MYPC0013", "expndAmt": 32000}]

    assert target_of("delete_expense", {"expndSn": 3}, data) == "09-28(월) · 사료 · 32,000원"


def test_시간을_넣지_않은_일정은_날짜만():
    data = [
        {
            "schdlSn": 31,
            "schdlDt": "2026-10-01T00:00:00",
            "hrInptYn": False,
            "schdlKndCd": "HLTC0058",
            "schdlKndCdNm": "미용·목욕",
            "schdlNm": "미용",
        }
    ]

    assert target_of("delete_schedule", {"petSn": CHOCO, "schdlSn": 31}, data) == (
        "10-01(목) · 미용·목욕 · 미용"
    )


def test_케어_완료_취소는_항목_이름을_항목_행에서_읽는다():
    data = {
        "items": [{"careArtclSn": 7, "careArtclNm": "산책"}],
        "completions": [{"careCmptnHstrySn": 90, "cmptnYmd": "2026-09-29"}],
    }
    data["completions"][0]["careArtclSn"] = 7

    text = target_of("cancel_care_completion", {"petSn": CHOCO, "careCmptnHstrySn": 90}, data)

    assert text == "산책 · 09-29(화)"


def test_READ_행이_없으면_대상_글도_없다():
    assert target_of("delete_expense", {"expndSn": 3}, []) is None
