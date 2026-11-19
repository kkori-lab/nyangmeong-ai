"""한 메시지 여러 명령 ② (SCR-AIM-012, 2026-11-19 추가 요청) : 쓰기 확인 카드 여러 개
- 쓰기 도구 뒤 이어 주는 말이 있으면 남은 쓰기 도구를 이어 고름(최대 3장), done.actions 목록
- 확인 말 한 번에 모두 실행 지시, 빈 칸이 남은 카드가 있으면 그 카드 번호로 되물음
- 고치기 : 고른 도구가 돌려받은 목록 안이면 그 카드만 바뀌고 나머지 그대로"""

from collections.abc import AsyncIterator

import pytest

from app.chat import rules, tools
from app.chat.clients import ToolDecision
from app.chat.service import (
    ACTION_CHAINED,
    ACTION_DROP_MESSAGE,
    ACTION_EXECUTE_MESSAGE,
    ACTION_MAX_CARDS,
)
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_action import AJAX, send
from tests.chat.test_messages import MessageJava, events
from tests.chat.test_register import CHOCO, TODAY
from tests.chat.test_tools import room_of, use_agent

HEALTH = "draft_daily_health_record"
SCHEDULE = "draft_schedule"
CARE_ITEM = "draft_care_item"
LIMIT = "draft_expense_limit"
WEIGHT_RAW = {
    "daily_rcd_idct_cd": "HLTC0014",
    "rcd_ymd": TODAY.isoformat(),
    "rcd_tm": "08:30",
    "rcd_nvl": 4.2,
}
HOSPITAL = {
    "schdl_knd_cd": "HLTC0057",
    "ckup_type_cd": "HLTC0002",
    "hsptl_nm": "메이 동물병원",
    "schdl_ymd": "2026-10-06",
    "schdl_tm": "15:00",
}
CHAINED = "초코 오늘 8시 반 체중 4.2kg 기록하고 10월 6일 3시 병원 일정도 잡아줘"


async def _chunks(texts) -> AsyncIterator[str]:
    for text in texts:
        yield text


class SequenceAgent(FakeToolAgent):
    """고르기마다 picks를 차례로
    - (도구, 원 인자)면 그 도구, 글이면 글 답변, None·끝이면 도구 없음"""

    def __init__(self, *picks) -> None:
        super().__init__()
        self.picks = picks

    async def decide(self, messages, max_tokens, today, hint=None) -> ToolDecision:
        self.decides.append((messages, today, hint))
        no = len(self.decides)
        pick = self.picks[no - 1] if no <= len(self.picks) else None
        if pick is None:
            return ToolDecision()
        if isinstance(pick, str):
            return ToolDecision(text=_chunks((pick, " 더 씀")))
        name, raw = pick
        use = {"type": "tool_use", "id": f"toolu_{no}", "name": name, "input": raw}
        return ToolDecision(call=tools.parse(name, raw, f"toolu_{no}"), content=(use,))


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


def send_actions(client, room_sn: int, cn: str, actions: list[dict]):
    body = {"cnvrsCn": cn, "actions": actions}
    return client.post(f"/ai/conversations/{room_sn}/messages", json=body, headers=AJAX)


def returned(done: dict) -> list[dict]:
    # React가 다음 메시지에 돌려보내는 모양
    return [{"tool": card["tool"], "input": card["input"]} for card in done["actions"]]


def two_cards(client, java) -> tuple[int, dict]:
    use_agent(client, SequenceAgent((HEALTH, WEIGHT_RAW), (SCHEDULE, HOSPITAL)))
    room = room_of(client, java, pet_sn=CHOCO)
    return room, done_of(send(client, room, CHAINED))


@pytest.mark.parametrize(
    ("text", "chained"),
    [
        (CHAINED, True),
        ("몸무게 기록하고 일정 잡아줘", True),
        ("체중이랑 일정 넣어줘", True),
        ("초코 오늘 8시 반 체중 4.2kg 기록해줘", False),
        ("내일 3시 병원 일정 잡아줘", False),
    ],
)
def test_이어_주는_말을_가린다(text, chained):
    assert rules.chains_more(text) is chained


def test_이어_주는_말이_있으면_남은_쓰기_도구를_이어_골라_카드_목록을_준다(client, java):
    agent = SequenceAgent((HEALTH, WEIGHT_RAW), (SCHEDULE, HOSPITAL))
    use_agent(client, agent)
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, CHAINED))

    assert [card["tool"] for card in done["actions"]] == [HEALTH, SCHEDULE]
    assert done["action"] == done["actions"][0]
    assert done["execute"] is False
    text = done["message"]["cnvrsCn"]
    lines = text.split("\n")
    assert lines[0] == "이렇게 할까요?"
    assert lines[1].startswith("1. 초코 건강 일지 기록 — 체중")
    assert lines[2].startswith("2. 초코 일정 등록 — 병원")
    assert "'등록해 줘'" in lines[3]
    assert java.ai_messages(room)[-1]["cnvrsCn"] == text
    # 두 번째 고르기 : 첫 카드 도구에 이어 고르기 결과를 돌려줌, 세 번째에서 도구 없음으로 끝
    assert len(agent.decides) == 3
    result = agent.decides[1][0][-1]["content"][0]
    assert (result["tool_use_id"], result["content"]) == ("toolu_1", ACTION_CHAINED)


def test_이어_주는_말이_없으면_LLM_한_번에_카드_하나다(client, java):
    agent = SequenceAgent((HEALTH, WEIGHT_RAW), (SCHEDULE, HOSPITAL))
    use_agent(client, agent)
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "초코 오늘 8시 반 체중 4.2kg 기록해줘"))

    assert len(agent.decides) == 1
    assert [card["tool"] for card in done["actions"]] == [HEALTH]
    assert done["message"]["cnvrsCn"].startswith("이렇게 할까요?\n초코 건강 일지 기록 — 체중")


def test_같은_쓰기_도구를_두_번_고르면_카드는_하나다(client, java):
    agent = SequenceAgent((HEALTH, WEIGHT_RAW), (HEALTH, WEIGHT_RAW | {"rcd_nvl": 4.5}))
    use_agent(client, agent)
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, CHAINED))

    assert [card["tool"] for card in done["actions"]] == [HEALTH]
    assert done["actions"][0]["input"]["rcdNvl"] == 4.2


def test_카드는_최대_세_장이고_네_번째는_고르지_않는다(client, java):
    agent = SequenceAgent((HEALTH, WEIGHT_RAW), (SCHEDULE, HOSPITAL), (CARE_ITEM, {}), (LIMIT, {}))
    use_agent(client, agent)
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, CHAINED))

    assert [card["tool"] for card in done["actions"]] == [HEALTH, SCHEDULE, CARE_ITEM]
    assert len(agent.decides) == ACTION_MAX_CARDS


def test_이어_고르기에서_글을_쓰면_모은_카드만_준다(client, java):
    use_agent(client, SequenceAgent((HEALTH, WEIGHT_RAW), "더 할 일은 없어요."))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, CHAINED))

    assert [card["tool"] for card in done["actions"]] == [HEALTH]
    assert "더 할 일" not in done["message"]["cnvrsCn"]


def test_이어_고르기에서_쓰기_아닌_도구면_멈춘다(client, java):
    picks = ((HEALTH, WEIGHT_RAW), (tools.NAVIGATE, {"screen_num": 1}), (SCHEDULE, HOSPITAL))
    agent = SequenceAgent(*picks)
    use_agent(client, agent)
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, CHAINED))

    assert [card["tool"] for card in done["actions"]] == [HEALTH]
    assert len(agent.decides) == 2


def test_카드_여럿에_확인_말이면_모두_실행을_지시한다(client, java):
    room, first = two_cards(client, java)
    agent = SequenceAgent()
    use_agent(client, agent)

    done = done_of(send_actions(client, room, "등록해 줘", returned(first)))

    assert agent.decides == []
    assert done["execute"] is True
    assert done["message"]["cnvrsCn"] == ACTION_EXECUTE_MESSAGE
    assert returned(done) == returned(first)
    assert done["action"] == done["actions"][0]


def test_빈_칸이_남은_카드가_있으면_실행하지_않고_그_카드_번호로_묻는다(client, java):
    room, first = two_cards(client, java)
    cards = returned(first)
    cards[1]["input"] = {k: v for k, v in cards[1]["input"].items() if k != "schdlKndCd"}
    use_agent(client, SequenceAgent())

    done = done_of(send_actions(client, room, "응", cards))

    assert done["execute"] is False
    assert len(done["actions"]) == 2
    assert done["actions"][0]["missing"] == []
    assert done["actions"][1]["missing"]
    text = done["message"]["cnvrsCn"]
    assert text.startswith("아직 2번의 ")
    assert "1번" not in text


def test_카드_여럿에_취소_말이면_모두_버린다(client, java):
    room, first = two_cards(client, java)
    agent = SequenceAgent()
    use_agent(client, agent)

    done = done_of(send_actions(client, room, "아니 취소해", returned(first)))

    assert agent.decides == []
    assert done["actions"] is None
    assert done["action"] is None
    assert done["message"]["cnvrsCn"] == ACTION_DROP_MESSAGE


def test_한_카드만_고치면_나머지_카드는_그대로_돌려준다(client, java):
    room, first = two_cards(client, java)
    use_agent(client, SequenceAgent((SCHEDULE, HOSPITAL | {"schdl_tm": "16:00"})))

    done = done_of(send_actions(client, room, "일정은 4시로 바꿔줘", returned(first)))

    before = returned(first)
    after = returned(done)
    assert [card["tool"] for card in after] == [HEALTH, SCHEDULE]
    assert after[0] == before[0]
    assert after[1]["input"] != before[1]["input"]
    assert "16:00" in str(after[1]["input"])
    assert done["message"]["cnvrsCn"].startswith("이렇게 할까요?\n1. ")


def test_목록에_없는_쓰기_도구를_고르면_새_목록이다(client, java):
    room, first = two_cards(client, java)
    use_agent(client, SequenceAgent((CARE_ITEM, {})))

    done = done_of(send_actions(client, room, "발톱 깎기 항목 만들어 줘", returned(first)))

    assert [card["tool"] for card in done["actions"]] == [CARE_ITEM]


def test_카드_목록이_네_개면_400이다(client, java):
    room = room_of(client, java, pet_sn=CHOCO)
    cards = [{"tool": HEALTH, "input": {}}] * 4

    response = send_actions(client, room, "등록해 줘", cards)

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"
