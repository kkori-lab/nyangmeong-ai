"""떠 있는 카드 확인·취소를 도구 고르기 LLM이 정함 (2026-11-28, SCR-AIM-004·012 공통)
- run_card : 카드 실행 지시, drop_card : 카드 버림, 카드 없이 고르면 폴백
- 삭제류 카드는 "응"만으로 실행하지 않음. 카드 자기 동사("해제해 줘")는 확인 말
- 카드 턴에 도구 고르기 장애 : 실행하지 않고 카드를 그대로 다시 줌"""

import pytest

from app.chat import catalog, rules, service, tools
from app.chat.schemas import ActionCard
from tests.chat.fakes import CARDS_NOTE_HEAD, FakeCardReplyAgent, FakeToolAgent, fake_catalog
from tests.chat.test_action import send
from tests.chat.test_action_delete import done_of
from tests.chat.test_messages import MessageJava
from tests.chat.test_register import CHOCO, TODAY
from tests.chat.test_tools import room_of, use_agent

UNLINK_TOOL = "unlink_caregiver"
UNLINK = {
    "tool": UNLINK_TOOL,
    "input": {"petSn": CHOCO, "brupRelSn": 7},
    "targetText": "동생",
}
REPRESENT = {"tool": "set_representative_pet", "input": {"petSn": CHOCO}}


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


def _card(name: str, values: dict) -> ActionCard:
    entry = fake_catalog().entries[name]
    return ActionCard.model_validate(
        {
            "tool": name,
            "domain": entry.domain,
            "label": entry.label,
            "call": {"method": entry.call.method, "path": entry.call.path},
            "params": {},
            "input": values,
        }
    )


def test_도구_목록에_run_card_drop_card가_decline_바로_앞에_있어야_한다():
    names = [d["name"] for d in tools.tool_definitions()]

    assert names[-3:] == [tools.RUN_CARD, tools.DROP_CARD, tools.DECLINE]
    assert all(d["input_schema"]["properties"] == {} for d in tools.tool_definitions()[-3:-1])


def test_해제_카드에_해제해줘로_run_card를_고르면_실행_지시해야_한다(client, java):
    agent = use_agent(client, FakeToolAgent(tools.RUN_CARD))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "해제해줘", UNLINK))

    assert len(agent.decides) == 1
    assert done["execute"] is True
    assert done["message"]["cnvrsCn"] == "해제할게요."
    assert done["action"]["tool"] == UNLINK_TOOL


def test_해제_카드에_응으로_run_card를_고르면_실행_지시해야_한다(client, java):
    use_agent(client, FakeToolAgent(tools.RUN_CARD))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "응", UNLINK))

    assert done["execute"] is True
    assert done["message"]["cnvrsCn"] == "해제할게요."
    assert done["action"]["tool"] == UNLINK_TOOL


def test_삭제_카드에_응으로_run_card를_골라도_실행하지_않고_다시_안내해야_한다(client, java):
    use_agent(client, FakeToolAgent(tools.RUN_CARD))
    room = room_of(client, java, pet_sn=CHOCO)
    draft = {
        "tool": "delete_daily_health_record",
        "input": {"petSn": CHOCO, "dailyHlthRcdSn": 51},
        "targetText": "09-28(월) 08:30 · 체중 · 4.2kg",
    }

    done = done_of(send(client, room, "응", draft))

    assert done["execute"] is False
    assert done["message"]["cnvrsCn"] == service.ACTION_DELETE_CONFIRM


def test_첫_턴_해제_명령은_바로_실행하지_않고_카드여야_한다():
    card = _card(UNLINK_TOOL, UNLINK["input"])

    assert service.runs_now([card], "탄이 공동양육자 두부아빠 해제해줘") is False


def test_drop_card를_고르면_카드를_버려야_한다(client, java):
    use_agent(client, FakeToolAgent(tools.DROP_CARD))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "그냥 둘래", REPRESENT))

    assert done["execute"] is False
    assert done.get("action") is None
    assert done["message"]["cnvrsCn"] == "지정하지 않았어요."


def test_카드_없이_run_card를_고르면_실행_지시가_없어야_한다(client, java):
    use_agent(client, FakeToolAgent(tools.RUN_CARD))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "응"))

    assert done.get("execute") is not True
    assert done.get("action") is None


def test_카드_턴에_도구_고르기가_실패하면_실행하지_않고_카드를_그대로_다시_줘야_한다(client, java):
    use_agent(client, FakeToolAgent(fail=True))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "해제해줘", UNLINK))

    assert done["execute"] is False
    assert done["message"]["cnvrsCn"] == service.ACTION_RETRY_MESSAGE
    assert done["action"]["tool"] == UNLINK_TOOL
    assert done["action"]["input"] == UNLINK["input"]


def test_카드_값을_바꾸는_말은_카드_도구를_다시_골라야_한다(client, java):
    agent = use_agent(client, FakeCardReplyAgent())
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "다른 아이로 바꿔 줘", REPRESENT))

    assert len(agent.decides) == 1
    assert done.get("execute") is not True


def test_해제_카드_확인_안내는_해제_동사여야_한다():
    card = _card(UNLINK_TOOL, UNLINK["input"])

    assert service._confirm_line([card]) == "맞으면 '해제해 줘'라고 말해 주세요."


def test_삭제_카드_확인_안내는_그대로_삭제해_줘여야_한다():
    card = _card("delete_daily_health_record", {"petSn": CHOCO, "dailyHlthRcdSn": 51})

    assert service._confirm_line([card]) == service.ACTION_ASK_DELETE


def test_해제_대상을_못_찾으면_해제할_대상으로_안내해야_한다():
    entry: catalog.CatalogEntry = fake_catalog().entries[UNLINK_TOOL]

    assert service._target_missing(entry) == (
        "해제할 공동양육자를 찾지 못했어요. 이름을 넣어 다시 말해 주세요."
    )
    assert "지울" not in service._target_missing_note(entry)


def test_받침_있는_대상은_을_그대로여야_한다():
    entry: catalog.CatalogEntry = fake_catalog().entries["draft_observation_cycle"]

    assert service._target_missing(entry).startswith("기록할 관찰 항목을 ")


def test_카드가_떠_있으면_도구_고르기_마지막_회원_메시지에_카드_목록이_붙어야_한다(client, java):
    agent = use_agent(client, FakeCardReplyAgent())
    room = room_of(client, java, pet_sn=CHOCO)

    send(client, room, "아니 취소", UNLINK)

    last = agent.decides[0][0][-1]
    assert last["role"] == "user"
    assert last["content"].startswith("아니 취소")
    assert (
        service.CARDS_NOTE.format(cards="공동양육 해제(unlink_caregiver) — 동생")
        in (last["content"])
    )


def test_카드가_없으면_회원_메시지를_그대로_넘겨야_한다():
    context = [{"role": "user", "content": "아니 취소"}]

    assert service.with_cards(context, ()) == context


def test_가짜_에이전트가_떼는_알림_앞부분이_서비스_문구와_같아야_한다():
    assert service.CARDS_NOTE.startswith(CARDS_NOTE_HEAD)
