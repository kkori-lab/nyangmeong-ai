"""에이전트 ③ 서명 토큰 (docs/design/agent.md 4절) : 표준 라이브러리 HMAC, 키 없으면 만들지 않음"""

import pytest

from app.chat import agentstate
from app.chat.agentstate import AgentState, AgentStateError, sign, verify

KEY = "test-agent-key"
NOW = 1_800_000_000.0


def state(**kw) -> AgentState:
    base = {"room": 7, "q": 3, "said": "체중 기록하고 알려 줘", "left": 6}
    return AgentState(**{**base, **kw})


def test_서명한_토큰은_같은_키_같은_방에서_그대로_돌아와야_한다():
    original = state(seen={"schdlSn": [5]}, notes=["읽기 결과"], cards=[{"tool": "t", "input": {}}])

    token = sign(original, KEY, NOW)
    back = verify(token, KEY, 7, NOW + 10)

    assert back.room == 7 and back.q == 3 and back.left == 6
    assert back.seen == {"schdlSn": [5]}
    assert back.notes == ["읽기 결과"]
    assert back.cards == [{"tool": "t", "input": {}}]
    assert back.exp == int(NOW) + agentstate.TTL_SEC
    assert back.v == agentstate.VERSION


def test_키가_없으면_토큰을_만들지_않아야_한다():
    assert sign(state(), "", NOW) is None


def test_48KB를_넘으면_토큰을_만들지_않아야_한다():
    big = state(notes=["가" * agentstate.MAX_BYTES])

    assert sign(big, KEY, NOW) is None


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda t: t[:-2] + ("AA" if not t.endswith("AA") else "BB"), "signature"),
        (lambda t: "x" + t, "signature"),
        (lambda t: t.replace(".", ""), "shape"),
    ],
)
def test_고친_토큰은_거부해야_한다(change, reason):
    token = sign(state(), KEY, NOW)

    with pytest.raises(AgentStateError) as error:
        verify(change(token), KEY, 7, NOW)

    assert error.value.reason == reason


def test_다른_키로_서명한_토큰은_거부해야_한다():
    token = sign(state(), "other-key", NOW)

    with pytest.raises(AgentStateError) as error:
        verify(token, KEY, 7, NOW)

    assert error.value.reason == "signature"


def test_만료된_토큰은_거부해야_한다():
    token = sign(state(), KEY, NOW)

    with pytest.raises(AgentStateError) as error:
        verify(token, KEY, 7, NOW + agentstate.TTL_SEC + 1)

    assert error.value.reason == "expired"


def test_다른_방의_토큰은_거부해야_한다():
    token = sign(state(), KEY, NOW)

    with pytest.raises(AgentStateError) as error:
        verify(token, KEY, 8, NOW)

    assert error.value.reason == "room"


def test_버전이_다른_토큰은_거부해야_한다(monkeypatch):
    monkeypatch.setattr(agentstate, "VERSION", 99)
    token = sign(state(), KEY, NOW)
    monkeypatch.setattr(agentstate, "VERSION", 1)

    with pytest.raises(AgentStateError) as error:
        verify(token, KEY, 7, NOW)

    assert error.value.reason == "version"


def test_키가_없으면_검사도_거부해야_한다():
    token = sign(state(), KEY, NOW)

    with pytest.raises(AgentStateError) as error:
        verify(token, "", 7, NOW)

    assert error.value.reason == "no_key"


def test_env_키가_없으면_비지_않은_같은_프로세스_키를_써야_한다():
    first = agentstate.key_of("")

    assert first
    assert agentstate.key_of("") == first


def test_env_키가_있으면_그_값을_써야_한다():
    assert agentstate.key_of("x") == "x"
