"""새 도구 싣기 검증 1회차 고침 (2026-11-27)
- 아이템 구매 "사 줘"·"구매해 줘"도 명령형이라 빈 칸이 없으면 첫 턴에 바로 실행(사람 결정)
- 마지막 투약 취소 : 번호는 list_care_items에서 오늘 완료 수(todayCmptnCnt)가 있는 행의 careArtclSn
  (Java care-completions 목록에는 투약 완료가 안 나옴, 검증 2회차)"""

import pytest

from app.chat import catalog, rules
from app.core.config import get_settings
from tests.chat.fakes import fake_catalog
from tests.chat.test_agent_continue import KEY, ContinueAgent, first_turn
from tests.chat.test_messages import MessageJava
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import TODAY

PURCHASE = "draft_item_purchase"


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


@pytest.fixture(autouse=True)
def agent_key(monkeypatch):
    monkeypatch.setenv("AGENT_STATE_KEY", KEY)
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "text",
    [
        "탄이 캐릭터에 밀짚모자 아이템 사 줘",
        "빨간 리본 구매해 줘",
        "밀짚모자 사주세요",
        "모자 하나 사 줄래?",
    ],
)
def test_구매_명령은_바로_실행_명령이어야_한다(text):
    assert rules.commands_now(text)


@pytest.mark.parametrize("text", ["감사", "모자 살까?", "모자 사고 싶어", "고마워요 정말 감사"])
def test_구매_말이_아닌_사는_명령이_아니어야_한다(text):
    assert not rules.commands_now(text)


def test_READ_뒤_구매_명령이면_카드를_바로_실행해야_한다(client, java):
    agent = ContinueAgent(("list_pixel_characters", {}))
    agent.follows = ((PURCHASE, {"pixel_char_sn": 2, "item_sns": [7]}),)
    use_reader(client, FakeToolReader([{"pixelCharSn": 2, "itemSn": 7, "itemNm": "밀짚모자"}]))

    _, done = first_turn(client, java, agent, "초코 캐릭터에 밀짚모자 사 줘")

    assert done["action"]["tool"] == PURCHASE
    assert done["action"]["input"]["itemSns"] == [7]
    assert done["execute"] is True


def test_마지막_투약_취소는_오늘_완료_기록_번호로_카드를_만든다():
    entry = fake_catalog().entries["cancel_last_dose"]
    rows = [
        {"careArtclSn": 4, "careArtclNm": "종합백신", "todayCmptnCnt": 0, "dayMdcnNmtm": None},
        {"careArtclSn": 20107, "careArtclNm": "심장약", "todayCmptnCnt": 1, "dayMdcnNmtm": 2},
    ]

    card = catalog.card_input(entry, {"care_artcl_sn": 20107}, seen=catalog.seen_ids(rows))

    assert card["careArtclSn"] == 20107
    assert not catalog.missing_target_ids(entry, card | {"petSn": 2})


def test_마지막_투약_취소_설명은_오늘_완료_기록을_먼저_읽게_한다():
    text = catalog.tool_prompts()["cancel_last_dose"].description

    assert "list_care_items" in text
    assert "todayCmptnCnt" in text
    assert "dayMdcnNmtm" in text


def test_케어_항목_목록은_행마다_답에_안_쓰는_칸을_빼고_LLM에_넘긴다():
    entry = fake_catalog().entries["list_care_items"]
    rows = [
        {"careArtclSn": 4, "careArtclNm": "종합백신", "rprsIconId": "VACCINE", "careZoneCd": "X"},
    ]

    dropped = catalog.drop_result_fields(entry, rows)

    assert dropped == [{"careArtclSn": 4, "careArtclNm": "종합백신"}]
    assert rows[0]["rprsIconId"] == "VACCINE"
