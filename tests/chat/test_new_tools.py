"""2026-11-27 백엔드 새 도구 41개 싣기 (SCR-AIM-004·011·012 공통)
- 새 도구가 스냅샷 + 가짜 코드 값으로 모두 실린다
- 비슷한 도구끼리 "쓰지 않을 때"에 서로 이름을 적는다
- 숫자 배열 번호 칸(itemSns·hldItemSns·petSns) : 번호마다 이 턴 READ 결과 값만"""

import re

import pytest

from app.chat import catalog, service
from tests.chat.fakes import fake_catalog
from tests.chat.new_tools import NEW_ACTION, NEW_READ

# (도구, 그 도구의 "쓰지 않을 때"에 적어야 하는 도구)
SIBLINGS = [
    ("list_notices", "list_notifications"),
    ("list_notifications", "list_notices"),
    ("get_unread_notification_count", "get_chat_unread_count"),
    ("get_chat_unread_count", "get_unread_notification_count"),
    ("get_care_recruitment", "get_care_match"),
    ("get_care_match", "get_care_recruitment"),
    ("draft_checkup", "draft_inspection_values"),
    ("draft_checkup", "draft_prescription"),
    ("draft_checkup", "draft_etc_inspection"),
    ("draft_etc_inspection", "draft_inspection_values"),
    ("draft_inspection_values", "draft_etc_inspection"),
    ("draft_prescription", "draft_repeat_prevention"),
    ("end_observation_item", "delete_observation_cycle"),
    ("delete_observation_cycle", "end_observation_item"),
    ("cancel_last_dose", "cancel_care_completion"),
    ("cancel_care_completion", "cancel_last_dose"),
    ("draft_pet", "draft_pet_update"),
    ("draft_pet_update", "draft_pet"),
    ("cancel_caregiver_invitation", "reject_caregiver_invitation"),
    ("reject_caregiver_invitation", "cancel_caregiver_invitation"),
    ("accept_caregiver_invitation", "reject_caregiver_invitation"),
    ("draft_item_purchase", "draft_equipped_items"),
    ("draft_equipped_items", "draft_item_purchase"),
    ("list_shop_items", "draft_item_purchase"),
]
# 숫자 배열 번호 칸 : (도구, LLM 칸, Java 칸, READ 결과의 번호 칸)
ID_LISTS = [
    ("draft_item_purchase", "item_sns", "itemSns", "itemSn"),
    ("draft_equipped_items", "hld_item_sns", "hldItemSns", "hldItemSn"),
    ("accept_caregiver_invitation", "pet_sns", "petSns", "petSn"),
    ("draft_caregiver_invitation", "pet_sns", "petSns", "petSn"),
]


def _not_when(name: str) -> str:
    # "쓰지 않을 때:" 문단(다음 "인자:"·"말하는 법:" 전까지)
    text = catalog.tool_prompts()[name].description
    found = re.search(r"쓰지 않을 때:(.*?)(?:\n    (?:인자|말하는 법):|\Z)", text, re.S)
    assert found is not None, name
    return found.group(1)


def test_새_도구는_스냅샷과_코드_값으로_모두_실려야_한다():
    entries = fake_catalog().entries
    assert set(entries) >= NEW_READ | NEW_ACTION
    assert all(entries[name].kind == "READ" for name in NEW_READ)
    assert all(entries[name].kind == "CARD" for name in NEW_ACTION)
    assert all(entries[name].label for name in NEW_READ | NEW_ACTION)


@pytest.mark.parametrize(("name", "sibling"), SIBLINGS)
def test_비슷한_도구는_쓰지_않을_때에_서로를_적어야_한다(name, sibling):
    assert sibling in _not_when(name)


def test_마지막_투약_취소는_삭제_카드라_삭제_말이어야_실행한다():
    assert service.is_delete(fake_catalog().entries["cancel_last_dose"])


@pytest.mark.parametrize(("tool", "llm", "java", "key"), ID_LISTS)
def test_번호_목록_칸은_LLM_칸_하나로_이어지고_숫자_목록이어야_한다(tool, llm, java, key):
    entry = fake_catalog().entries[tool]
    assert entry.to_java_name[llm] == java
    schema = entry.definition["input_schema"]["properties"][llm]
    assert "array" in str(schema) and "integer" in str(schema)


@pytest.mark.parametrize(("tool", "llm", "java", "key"), ID_LISTS)
def test_번호_목록은_이_턴_READ_결과_번호만이면_그대로_싣는다(tool, llm, java, key):
    entry = fake_catalog().entries[tool]
    seen = {key: {11, 12, 13}}

    card = catalog.card_input(entry, {llm: [11, 13, 11]}, seen=seen)

    assert card[java] == [11, 13]


@pytest.mark.parametrize(("tool", "llm", "java", "key"), ID_LISTS)
def test_번호_목록에_READ에_없는_번호가_하나라도_있으면_칸을_비워_되묻는다(tool, llm, java, key):
    entry = fake_catalog().entries[tool]
    seen = {key: {11, 12}}

    card = catalog.card_input(entry, {llm: [11, 99]}, seen=seen)

    assert java not in card
    assert java in catalog.missing(entry, card)


def test_번호_목록이_숫자가_아니면_칸을_비운다():
    entry = fake_catalog().entries["draft_item_purchase"]

    card = catalog.card_input(entry, {"item_sns": ["11", True]}, seen={"itemSn": {11}})

    assert "itemSns" not in card


def test_입을_아이템_빈_목록은_다_벗기기라_그대로_싣는다():
    # hldItemSns : 최소 개수 없음(빈 목록 = 모두 벗기)
    entry = fake_catalog().entries["draft_equipped_items"]

    card = catalog.card_input(entry, {"hld_item_sns": []}, seen={})

    assert card["hldItemSns"] == []
    assert "hldItemSns" not in catalog.missing(entry, card)


def test_사려는_아이템_빈_목록은_되묻는다():
    entry = fake_catalog().entries["draft_item_purchase"]

    card = catalog.card_input(entry, {"item_sns": []}, seen={})

    assert "itemSns" in catalog.missing(entry, card)


def test_READ_결과의_petSn도_번호로_모은다():
    # 초대 수락 petSns : 받은 초대 pets의 petSn만
    seen = catalog.seen_ids({"jntBrupInvtnSn": 5, "pets": [{"petSn": 7}, {"petSn": 8}]})

    assert seen == {"jntBrupInvtnSn": {5}, "petSn": {7, 8}}
