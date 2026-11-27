"""에이전트 ③ 쓰기 결과 이어 가기 (docs/design/agent.md 2·4·5·6절, 2026-11-26)
- 바로 실행하는 카드이고 카드 뒤 할 일이 남은 문장이면 done.pending(서명 토큰)
- POST …/agent-continue : 결과를 LLM에 주고 읽기·쓰기를 이어 감(사용자 메시지 저장 안 함)
- 칸 오류 한 번 고치기, 같은 쓰기 반복 막기, 결과 data의 새 번호
- 말하지 않은 쓰기·루프가 고른 삭제는 확인 카드"""

from collections.abc import AsyncIterator

import pytest

from app.chat import agentstate, rules, tools
from app.chat.clients import ToolDecision
from app.chat.schemas import ROLE_USER
from app.core.config import get_settings
from tests.chat.conftest import as_member
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_action import AJAX, send
from tests.chat.test_action_multi import HEALTH, HOSPITAL, SCHEDULE, WEIGHT_RAW, done_of
from tests.chat.test_messages import MessageJava, events, names
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import CHOCO, TODAY
from tests.chat.test_tools import room_of, use_agent

KEY = "test-agent-key"
SAID = "초코 오늘 8시 반 체중 4.2kg 기록하고 지난주보다 늘었는지 알려 줘"
SIMPLE = "초코 오늘 8시 반 체중 4.2kg 기록해 줘"
READ = ("list_my_care_schedules", {"from_ymd": "2026-10-01", "to_ymd": "2026-10-31", "size": 10})
UPDATE = "draft_schedule_update"
DELETE_RECORD = "delete_daily_health_record"


async def _chunks(texts) -> AsyncIterator[str]:
    for text in texts:
        yield text


class ContinueAgent(FakeToolAgent):
    """첫 고르기는 first, 그 뒤 decide(이어 고르기)는 도구 없음
    이어 가기(resume)는 resumed를 차례로"""

    def __init__(self, first, resumed=(), answer_chunks=("지난주보다 ", "늘었어요.")) -> None:
        super().__init__(answer_chunks=answer_chunks)
        self.first = first
        self.resumed = list(resumed)
        self.answered: list[list[dict]] = []

    def _decision(self, pick, no: int) -> ToolDecision:
        if pick is None:
            return ToolDecision()
        if isinstance(pick, str):
            return ToolDecision(text=_chunks((pick,)))
        name, raw = pick
        use = {"type": "tool_use", "id": f"toolu_{no}", "name": name, "input": raw}
        return ToolDecision(call=tools.parse(name, raw, f"toolu_{no}"), content=(use,))

    async def decide(self, messages, max_tokens, today, hint=None) -> ToolDecision:
        self.decides.append((messages, today, hint))
        return self._decision(self.first if len(self.decides) == 1 else None, len(self.decides))

    async def answer(self, messages, decision, result, max_tokens, today, follow=None):
        # 결과 답변이 받은 메시지 : 이어 가기면 원래 질문 + 진행 기록
        self.answered.append(messages)
        async for chunk in super().answer(messages, decision, result, max_tokens, today, follow):
            yield chunk

    async def resume(self, messages, notes, max_tokens, today) -> ToolDecision:
        self.resumes.append(notes)
        self.decides.append((messages, today, None))
        no = len(self.resumes)
        pick = self.resumed[no - 1] if no <= len(self.resumed) else None
        return self._decision(pick, 100 + no)


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


def first_turn(client, java, agent: ContinueAgent, text: str = SAID) -> tuple[int, dict]:
    use_agent(client, agent)
    room = room_of(client, java, pet_sn=CHOCO)
    return room, done_of(send(client, room, text))


def cont(client, room: int, token: str, results: list[dict]):
    body = {"agentToken": token, "results": results}
    return client.post(f"/ai/conversations/{room}/agent-continue", json=body, headers=AJAX)


def user_count(java: MessageJava, room: int) -> int:
    return sum(m["roleCd"] == ROLE_USER for m in java.rooms[room]["messages"])


# A1·A4 done.pending


def test_키가_없어도_pending을_주고_같은_프로세스에서_이어_가야_한다(client, java, monkeypatch):
    monkeypatch.setenv("AGENT_STATE_KEY", "")
    get_settings.cache_clear()

    room, done = first_turn(client, java, ContinueAgent((HEALTH, WEIGHT_RAW)))
    res = cont(client, room, done["pending"]["agentToken"], [{"tool": HEALTH, "status": "DONE"}])

    assert done["execute"] is True
    assert done["pending"]["agentToken"]
    assert res.status_code == 200


def test_쓰기_뒤_할_일이_남은_명령이면_바로_실행하고_pending을_줘야_한다(client, java):
    _, done = first_turn(client, java, ContinueAgent((HEALTH, WEIGHT_RAW)))

    assert done["execute"] is True
    assert [card["tool"] for card in done["actions"]] == [HEALTH]
    assert done["pending"]["cards"] == 1
    assert done["pending"]["agentToken"]


def test_단순_명령이면_pending이_없어야_한다(client, java):
    _, done = first_turn(client, java, ContinueAgent((HEALTH, WEIGHT_RAW)), SIMPLE)

    assert done["execute"] is True
    assert done["pending"] is None


def test_빈_칸이_있으면_되묻고_pending이_없어야_한다(client, java):
    raw = {k: v for k, v in WEIGHT_RAW.items() if k != "rcd_nvl"}
    _, done = first_turn(client, java, ContinueAgent((HEALTH, raw)), SAID.replace(" 4.2kg", ""))

    assert done["execute"] is False
    assert done["pending"] is None


# A3·A5 agent-continue


def test_실행_결과로_읽기를_이어_가고_답을_저장해야_한다(client, java):
    agent = ContinueAgent((HEALTH, WEIGHT_RAW), [READ])
    reader = use_reader(client, FakeToolReader([{"schdlSn": 5, "schdlNm": "병원"}]))
    room, done = first_turn(client, java, agent)
    users = user_count(java, room)

    res = cont(client, room, done["pending"]["agentToken"], [{"tool": HEALTH, "status": "DONE"}])
    evs = events(res)

    assert names(evs)[0] == "intent"
    assert "step" in names(evs)
    assert evs[-1][0] == "done"
    text = "".join(data["text"] for name, data in evs if name == "delta")
    assert text.startswith("지난주보다 늘었어요.")
    assert evs[-1][1]["message"]["cnvrsCn"].startswith("지난주보다 늘었어요.")
    assert evs[-1][1]["pending"] is None
    assert reader.calls
    # 진행 기록 : 실행 완료 줄, 원래 질문 뒤에 붙임
    notes = agent.resumes[0]
    assert notes.startswith(rules.AGENT_NOTES_HEAD)
    assert "실행 완료" in notes and HEALTH in notes
    assert agent.decides[-1][0][-1]["content"] == SAID
    answered = agent.answered[-1][-1]["content"]
    assert answered.startswith(SAID)
    assert answered.endswith(notes)
    assert user_count(java, room) == users


def test_취소만이면_LLM_없이_짧은_글로_끝내야_한다(client, java):
    agent = ContinueAgent((HEALTH, WEIGHT_RAW), [READ])
    room, done = first_turn(client, java, agent)

    res = cont(
        client, room, done["pending"]["agentToken"], [{"tool": HEALTH, "status": "CANCELED"}]
    )
    done2 = done_of(res)

    assert done2["message"]["cnvrsCn"] == rules.AGENT_STOPPED
    assert agent.resumes == []


@pytest.mark.parametrize(
    "token",
    ["", "abc", "abc.def"],
)
def test_모양이_틀린_토큰은_400이어야_한다(client, java, token):
    room, _ = first_turn(client, java, ContinueAgent((HEALTH, WEIGHT_RAW)))

    res = cont(client, room, token, [{"tool": HEALTH, "status": "DONE"}])

    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"


def test_서명을_고친_토큰은_400이어야_한다(client, java):
    room, done = first_turn(client, java, ContinueAgent((HEALTH, WEIGHT_RAW)))
    token = done["pending"]["agentToken"]
    body, mac = token.split(".")

    res = cont(client, room, f"{body}.{mac[::-1]}", [{"tool": HEALTH, "status": "DONE"}])

    assert res.status_code == 400


def test_만료된_토큰은_400이어야_한다(client, java, monkeypatch):
    monkeypatch.setattr(agentstate, "TTL_SEC", -1)
    room, done = first_turn(client, java, ContinueAgent((HEALTH, WEIGHT_RAW)))

    res = cont(client, room, done["pending"]["agentToken"], [{"tool": HEALTH, "status": "DONE"}])

    assert res.status_code == 400


def test_다른_방의_토큰은_400이어야_한다(client, java):
    room, done = first_turn(client, java, ContinueAgent((HEALTH, WEIGHT_RAW)))
    other = java.add_room(1, "다른 방", pet_sn=CHOCO, cn="안녕")

    res = cont(client, other, done["pending"]["agentToken"], [{"tool": HEALTH, "status": "DONE"}])

    assert res.status_code == 400


def test_토큰에_없는_도구와_개수_초과는_400이어야_한다(client, java):
    room, done = first_turn(client, java, ContinueAgent((HEALTH, WEIGHT_RAW)))
    token = done["pending"]["agentToken"]

    wrong = cont(client, room, token, [{"tool": SCHEDULE, "status": "DONE"}])
    many = cont(client, room, token, [{"tool": HEALTH, "status": "DONE"}] * 4)
    twice = cont(client, room, token, [{"tool": HEALTH, "status": "DONE"}] * 2)

    assert wrong.status_code == 400
    assert many.status_code == 400
    assert twice.status_code == 400


def test_env_키가_바뀌면_이전_토큰은_400이어야_한다(client, java, monkeypatch):
    # 키를 비우면 프로세스 무작위 키로 바뀌어 KEY로 서명한 토큰은 서명 틀림(재시작과 같음)
    room, done = first_turn(client, java, ContinueAgent((HEALTH, WEIGHT_RAW)))
    monkeypatch.setenv("AGENT_STATE_KEY", "")
    get_settings.cache_clear()

    res = cont(client, room, done["pending"]["agentToken"], [{"tool": HEALTH, "status": "DONE"}])

    assert res.status_code == 400


def test_남의_대화는_404여야_한다(client, java):
    room, done = first_turn(client, java, ContinueAgent((HEALTH, WEIGHT_RAW)))
    as_member(client, 2)

    res = cont(client, room, done["pending"]["agentToken"], [{"tool": HEALTH, "status": "DONE"}])

    assert res.status_code == 404


# A6 결과 data의 새 번호


def test_실행_결과_data의_번호를_다음_카드_번호_칸에_써야_한다(client, java):
    agent = ContinueAgent((HEALTH, WEIGHT_RAW), [(UPDATE, {"schdl_sn": 5, "schdl_nm": "검진"})])
    room, done = first_turn(client, java, agent)

    results = [{"tool": HEALTH, "status": "DONE", "data": {"schdlSn": 5}}]
    done2 = done_of(cont(client, room, done["pending"]["agentToken"], results))

    assert done2["action"]["tool"] == UPDATE
    assert done2["action"]["input"]["schdlSn"] == 5
    assert "저장 결과" in agent.resumes[0] and "schdlSn" in agent.resumes[0]


def test_지어낸_번호는_카드에_쓰지_않아야_한다(client, java):
    agent = ContinueAgent((HEALTH, WEIGHT_RAW), [(UPDATE, {"schdl_sn": 999, "schdl_nm": "검진"})])
    room, done = first_turn(client, java, agent)

    results = [{"tool": HEALTH, "status": "DONE", "data": {"schdlSn": 5}}]
    done2 = done_of(cont(client, room, done["pending"]["agentToken"], results))

    assert done2["action"] is None


# A7 칸 오류 한 번 고치기


def test_칸_오류면_칸_이름으로_한_번_고친_카드를_바로_실행해야_한다(client, java):
    fixed = {**WEIGHT_RAW, "rcd_nvl": 4.3}
    agent = ContinueAgent((HEALTH, WEIGHT_RAW), [(HEALTH, fixed)])
    room, done = first_turn(client, java, agent)

    errors = [{"field": "rcdNvl", "message": "자바가 보낸 문구"}]
    results = [{"tool": HEALTH, "status": "FAILED", "errors": errors}]
    done2 = done_of(cont(client, room, done["pending"]["agentToken"], results))

    notes = agent.resumes[0]
    assert "다시 확인할 칸" in notes
    assert "자바가 보낸 문구" not in notes
    assert done2["action"]["tool"] == HEALTH
    assert done2["action"]["input"]["rcdNvl"] == 4.3
    assert done2["execute"] is True
    assert done2["pending"] is not None


def test_두_번째_칸_오류는_고치지_않고_끝내야_한다(client, java):
    fixed = {**WEIGHT_RAW, "rcd_nvl": 4.3}
    agent = ContinueAgent((HEALTH, WEIGHT_RAW), [(HEALTH, fixed), (HEALTH, fixed)])
    room, done = first_turn(client, java, agent)
    errors = [{"field": "rcdNvl"}]
    results = [{"tool": HEALTH, "status": "FAILED", "errors": errors}]
    done2 = done_of(cont(client, room, done["pending"]["agentToken"], results))

    done3 = done_of(cont(client, room, done2["pending"]["agentToken"], results))

    assert done3["message"]["cnvrsCn"] == rules.AGENT_STOPPED
    assert len(agent.resumes) == 1


def test_errors가_빈_실패는_고치지_않고_끝내야_한다(client, java):
    agent = ContinueAgent((HEALTH, WEIGHT_RAW), [(HEALTH, WEIGHT_RAW)])
    room, done = first_turn(client, java, agent)

    results = [{"tool": HEALTH, "status": "FAILED"}]
    done2 = done_of(cont(client, room, done["pending"]["agentToken"], results))

    assert done2["message"]["cnvrsCn"] == rules.AGENT_STOPPED
    assert agent.resumes == []


# A8 같은 쓰기 반복 막기


def test_이미_실행한_같은_카드는_다시_만들지_않아야_한다(client, java):
    agent = ContinueAgent((HEALTH, WEIGHT_RAW), [(HEALTH, WEIGHT_RAW)])
    room, done = first_turn(client, java, agent)

    done2 = done_of(
        cont(client, room, done["pending"]["agentToken"], [{"tool": HEALTH, "status": "DONE"}])
    )

    assert done2["action"] is None
    assert done2["execute"] is False
    assert rules.AGENT_ALREADY_DONE in agent.results


def test_READ_뒤에_이미_실행한_같은_카드를_고르면_이미_실행했다고_돌려줘야_한다(client, java):
    agent = ContinueAgent((HEALTH, WEIGHT_RAW), [READ])
    agent.follows = ((HEALTH, WEIGHT_RAW),)
    use_reader(client, FakeToolReader([{"schdlSn": 5}]))
    room, done = first_turn(client, java, agent)

    done2 = done_of(
        cont(client, room, done["pending"]["agentToken"], [{"tool": HEALTH, "status": "DONE"}])
    )

    assert done2["action"] is None
    assert rules.AGENT_ALREADY_DONE in agent.results


# A9 안전 규칙


def test_말하지_않은_쓰기는_바로_실행하지_않고_확인_카드로_멈춰야_한다(client, java):
    agent = ContinueAgent((HEALTH, WEIGHT_RAW), [(SCHEDULE, HOSPITAL)])
    room, done = first_turn(client, java, agent)

    done2 = done_of(
        cont(client, room, done["pending"]["agentToken"], [{"tool": HEALTH, "status": "DONE"}])
    )

    assert done2["action"]["tool"] == SCHEDULE
    assert done2["execute"] is False
    assert done2["pending"] is None


def test_루프가_고른_삭제는_바로_실행하지_않아야_한다(client, java):
    agent = ContinueAgent((HEALTH, WEIGHT_RAW), [(DELETE_RECORD, {"daily_hlth_rcd_sn": 51})])
    room, done = first_turn(
        client, java, agent, "초코 오늘 8시 반 체중 4.2kg 기록하고 어제 기록도 확인해 줘"
    )
    assert done["pending"] is not None

    results = [{"tool": HEALTH, "status": "DONE", "data": {"dailyHlthRcdSn": 51}}]
    done2 = done_of(cont(client, room, done["pending"]["agentToken"], results))

    assert done2["action"]["tool"] == DELETE_RECORD
    assert done2["action"]["input"]["dailyHlthRcdSn"] == 51
    assert done2["execute"] is False
    assert done2["pending"] is None


def test_이어_가기에서_범위_밖을_고르면_범위_안내로_끝내야_한다(client, java):
    agent = ContinueAgent((HEALTH, WEIGHT_RAW), [(tools.DECLINE, {"unclear": False})])
    room, done = first_turn(client, java, agent)

    res = cont(client, room, done["pending"]["agentToken"], [{"tool": HEALTH, "status": "DONE"}])
    evs = events(res)

    assert evs[0] == ("intent", {**evs[0][1], "kind": "FALLBACK"})
    assert evs[-1][1]["action"] is None
    assert evs[-1][1]["message"]["cnvrsCn"]


@pytest.mark.parametrize(
    ("text", "more", "command"),
    [
        (SAID, True, True),
        ("검진기록 만들고 수치도 넣어 줘", True, True),
        ("코코 체중 기록하고 이번 주 일정 보여 줘", True, True),
        (SIMPLE, False, False),
        ("산책 30분 기록해 줘", False, False),
        ("내일 코코 병원 일정 있으면 저녁 7시로 바꿔 줘", False, False),
        ("체중 기록하고 싶은데 어떻게 해?", False, False),
        ("체중 기록 알려줘", False, False),
    ],
)
def test_카드_뒤_할_일이_남은_꼴만_이어_가기_대상이어야_한다(text, more, command):
    assert rules.agent_more(text) is more
    assert rules.agent_command(text) is command
