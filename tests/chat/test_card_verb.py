"""카드 글 동사를 도구별로 (2026-11-27, 새 도구 싣기 ② SCR-AIM-004·011·012 공통)
- tool_prompts.yaml verb(지정·구매·수락·거절·종료·진행), 없으면 지금처럼 HTTP 메서드로
- 확인 안내·실행 글·취소 글·번호 못 찾음 글이 그 동사로
- 도구별 동사 확인 말("수락해 줘")은 그 동사의 카드가 있을 때만"""

import pytest

from app.chat import catalog, rules, service, tools
from app.chat.schemas import ActionCard
from tests.chat.fakes import FakeToolAgent, fake_catalog
from tests.chat.test_action import send
from tests.chat.test_action_delete import done_of, send_actions
from tests.chat.test_messages import MessageJava
from tests.chat.test_register import CHOCO, TODAY
from tests.chat.test_tools import room_of, use_agent

VERBS = {
    "set_representative_pet": "지정",
    "draft_item_purchase": "구매",
    "accept_caregiver_invitation": "수락",
    "reject_caregiver_invitation": "거절",
    "end_observation_item": "종료",
    "cancel_caregiver_invitation": "진행",
    # 영수증 저장 카드 (SCR-AIM-013 receipt-card, 2026-11-27)
    "draft_receipt_save": "저장",
    # 새 도구 싣기 ③ (2026-11-27)
    "unlink_caregiver": "해제",
    "delete_expenses_by_condition": "삭제",
    "draft_notification_settings": "변경",
    "mark_service_tutorial_viewed": "저장",
}
REPRESENT = {"tool": "set_representative_pet", "input": {"petSn": CHOCO}}
ACCEPT = {"tool": "accept_caregiver_invitation", "input": {"jntBrupInvtnSn": 5, "petSns": [CHOCO]}}
COMPLETE = {"tool": "draft_care_completion", "input": {"petSn": CHOCO, "careArtclSn": 7}}


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


@pytest.fixture
def entries(monkeypatch) -> dict[str, catalog.CatalogEntry]:
    found = fake_catalog().entries
    monkeypatch.setattr(tools, "card_entry", lambda name: found.get(name))
    return found


def _card(entries, name: str, values: dict | None = None) -> ActionCard:
    entry = entries[name]
    return ActionCard.model_validate(
        {
            "tool": name,
            "domain": entry.domain,
            "label": entry.label,
            "call": {"method": entry.call.method, "path": entry.call.path},
            "params": {},
            "input": values or {},
        }
    )


def test_설명의_동사는_확인_말로_알아듣는_동사여야_한다():
    prompts = catalog.tool_prompts()
    verbs = {name: prompt.verb for name, prompt in prompts.items() if prompt.verb is not None}

    assert verbs == VERBS
    assert set(verbs.values()) <= {*rules.CARD_VERBS, service.ACTION_VERB_MIXED}


@pytest.mark.parametrize(("name", "verb"), VERBS.items())
def test_도구별_동사가_카탈로그에_실려야_한다(entries, name, verb):
    assert service.entry_verb(entries[name]) == verb


def test_동사가_없는_도구는_지금처럼_메서드로_정한다(entries):
    assert service.entry_verb(entries["draft_care_completion"]) == service.ACTION_VERB_ADD
    assert service.entry_verb(entries["draft_pet_update"]) == service.ACTION_VERB_UPDATE
    assert service.entry_verb(entries["delete_place_bookmark"]) == service.ACTION_VERB_DELETE


def test_대표_지정_카드의_확인_안내는_지정해_줘여야_한다(entries):
    text = service.action_ask_message(_card(entries, "set_representative_pet", {"petSn": CHOCO}))

    assert "'지정해 줘'" in text
    assert "등록" not in text


def test_구매_카드의_실행_글은_구매할게요여야_한다(entries):
    card = _card(entries, "draft_item_purchase", {"pixelCharSn": 2, "itemSns": [7]})

    assert service.action_run_message([card]).endswith("구매할게요.")


def test_동사가_다른_카드가_섞이면_진행이어야_한다(entries):
    cards = [_card(entries, "draft_item_purchase"), _card(entries, "draft_care_completion")]

    assert service._execute_line(cards) == "진행할게요."


def test_동사_없는_카드의_확인_안내는_그대로여야_한다(entries):
    card = _card(entries, "draft_care_completion", {"petSn": CHOCO, "careArtclSn": 7})

    assert service._confirm_line([card]) == service.ACTION_ASK_CONFIRM


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("accept_caregiver_invitation", "수락할 받은 초대장을 찾지 못했어요."),
        ("reject_caregiver_invitation", "거절할 받은 초대장을 찾지 못했어요."),
        ("end_observation_item", "종료할 관찰 항목을 찾지 못했어요."),
        ("cancel_caregiver_invitation", "보낸 초대장을 찾지 못했어요."),
    ],
)
def test_번호를_못_찾으면_그_동사로_안내한다(entries, name, message):
    text = service._target_missing(entries[name])

    assert text.startswith(message)
    assert "기록할" not in text


def test_번호를_못_찾은_LLM_글도_그_동사로(entries):
    note = service._target_missing_note(entries["accept_caregiver_invitation"])

    assert "수락할 대상" in note
    assert "기록할" not in note


def test_동사_없는_등록_도구의_번호_못_찾음_글은_그대로여야_한다(entries):
    entry = entries["draft_observation_cycle"]

    assert service._target_missing(entry) == service.ADD_TARGET_MISSING_MESSAGE.format(
        target=entry.target
    )
    assert service._target_missing_note(entry) == service.ACTION_ADD_TARGET_MISSING


@pytest.mark.parametrize(
    ("text", "verb"),
    [
        ("수락해 줘", "수락"),
        ("응 구매해", "구매"),
        ("지정해주세요", "지정"),
        ("거절", "거절"),
        ("종료해 줘!", "종료"),
        ("수락할까?", None),
        ("등록해 줘", None),
        ("초대 수락해 줘", None),
    ],
)
def test_도구별_동사_확인_말을_알아듣는다(text, verb):
    assert rules.says_card_verb(text) == verb


@pytest.mark.parametrize(
    "text",
    ["대표 반려동물로 지정해 줘", "받은 초대 수락해 줘", "그 초대 거절해 줘", "혹 관찰 종료해 줘"],
)
def test_도구별_동사_명령도_바로_실행_명령이어야_한다(text):
    assert rules.commands_now(text)


@pytest.mark.parametrize("verb", ["지정", "구매", "수락", "거절", "종료"])
def test_바로_실행_턴에_도구별_동사_확인_안내가_남으면_찾는다(verb):
    assert rules.asks_confirm(f"맞으면 '{verb}해 줘'라고 말해 주세요.")


def test_대표_지정_카드에_응이면_지정할게요(client, java):
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "응", REPRESENT))

    assert done["execute"] is True
    assert done["message"]["cnvrsCn"] == "지정할게요."


def test_수락_카드에_수락해_줘면_실행_지시한다(client, java):
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "수락해 줘", ACCEPT))

    assert done["execute"] is True
    assert done["message"]["cnvrsCn"] == "수락할게요."


def test_대표_지정_카드_취소_말은_지정하지_않았어요(client, java):
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "아니", REPRESENT))

    assert done["message"]["cnvrsCn"] == "지정하지 않았어요."


def test_다른_동사_카드에_수락해_줘는_실행하지_않는다(client, java):
    use_agent(client, FakeToolAgent("decline", {"unclear": True}))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "수락해 줘", COMPLETE))

    assert not done.get("execute")


def test_수락과_등록이_섞인_카드에_수락해_줘면_실행_지시한다(client, java):
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send_actions(client, room, "수락해 줘", [ACCEPT, COMPLETE]))

    assert done["execute"] is True
    assert done["message"]["cnvrsCn"] == "진행할게요."
