"""SCR-AIM-002 답변 실패 이유 로그 (FN-AIM-002-07, 추가 요청)

첫 글자 전·도중 실패, 반려동물 목록 실패, 도구 고르기 시간 초과마다 이유 한 줄.
로그에는 이유 종류·글자 수·ms·방 번호만 남고 사용자 글·답변 글 원문은 없다."""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from datetime import date, datetime

import httpx2
import pytest

from app.chat import service
from app.chat.clients import AnswerError, AnthropicToolAgent, ClassifyError, ToolDecision
from app.chat.schemas import ROLE_USER, ConversationMessage
from app.core.backend import BackendError, external_error
from app.core.response import AppError
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_llm_clients import MODEL, FakeAnthropic
from tests.chat.test_messages import MessageJava, events, send
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import CHOCO
from tests.chat.test_tools import CONTEXT, room_of, sse_response, use_agent

QUESTION = "코코 식사량 알려줘 비밀문장"
ROOM = 7
SERVICE_LOGGER = "app.chat.service"


def _turn() -> service.Turn:
    msg = ConversationMessage(
        ai_cnvrs_msg_sn=1, role_cd=ROLE_USER, cnvrs_cn=QUESTION, msg_seq=1, reg_dt=datetime.now()
    )
    return service.Turn(ROOM, msg, [msg])


class _Repo:
    """미완료 답변 저장만 받는 가짜"""

    async def add_message(self, room_sn, role_cd, cn, cmptn_yn=True):
        return None


async def _stream(
    chunks: tuple[str, ...], error: Exception | None, delay: float = 0
) -> AsyncIterator[str]:
    for chunk in chunks:
        yield chunk
    if delay:
        await asyncio.sleep(delay)
    if error is not None:
        raise error


def _run(stream: AsyncIterator[str], first: float = 5, total: float = 30) -> list:
    emitted: list = []
    asyncio.run(
        service._search_answer(
            _turn(),
            _Repo(),
            service.AnswerLimits(first, total),
            None,
            emitted.append,
            stream,
        )
    )
    return emitted


def _lines(caplog, prefix: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith(prefix)]


def _no_text(caplog) -> None:
    for record in caplog.records:
        assert QUESTION not in record.getMessage()
        assert "부분 답" not in record.getMessage()


# 첫 글자 전 실패


def test_첫_글자_전_AnswerError면_그_이유를_한_줄_남겨야_한다(caplog):
    with caplog.at_level("WARNING", logger=SERVICE_LOGGER):
        emitted = _run(_stream((), AnswerError("read_pets")))

    assert [name for name, _ in emitted] == ["error"]
    lines = _lines(caplog, "답변 실패")
    assert len(lines) == 1
    assert re.fullmatch(rf"답변 실패: 첫 글자 전 read_pets room={ROOM} \(\d+ms\)", lines[0])
    _no_text(caplog)


def test_첫_글자_제한을_넘기면_first_token_timeout이어야_한다(caplog):
    with caplog.at_level("WARNING", logger=SERVICE_LOGGER):
        _run(_stream((), None, delay=1), first=0.05, total=30)

    lines = _lines(caplog, "답변 실패")
    assert len(lines) == 1
    assert lines[0].startswith("답변 실패: 첫 글자 전 first_token_timeout ")


def test_전체_제한이_먼저면_total_timeout이어야_한다(caplog):
    with caplog.at_level("WARNING", logger=SERVICE_LOGGER):
        _run(_stream((), None, delay=1), first=5, total=0.05)

    lines = _lines(caplog, "답변 실패")
    assert len(lines) == 1
    assert lines[0].startswith("답변 실패: 첫 글자 전 total_timeout ")


def test_글_없이_끝나면_empty여야_한다(caplog):
    with caplog.at_level("WARNING", logger=SERVICE_LOGGER):
        emitted = _run(_stream((), None))

    assert [name for name, _ in emitted] == ["error"]
    lines = _lines(caplog, "답변 실패")
    assert len(lines) == 1
    assert lines[0].startswith("답변 실패: 첫 글자 전 empty ")


def test_정상_답변이면_실패_로그가_없어야_한다(caplog):
    with caplog.at_level("WARNING", logger=SERVICE_LOGGER):
        _run(_stream(("부분 답", "끝"), None))

    assert _lines(caplog, "답변 실패") == []
    assert _lines(caplog, "답변 미완료") == []


# 도중 미완료


def test_도중_AnswerError면_이유와_글자_수를_남겨야_한다(caplog):
    with caplog.at_level("WARNING", logger=SERVICE_LOGGER):
        emitted = _run(_stream(("부분 답",), AnswerError("network")))

    assert emitted[-1][0] == "done"
    lines = _lines(caplog, "답변 미완료")
    assert len(lines) == 1
    assert re.fullmatch(rf"답변 미완료: 도중 network room={ROOM} 4자 \(\d+ms\)", lines[0])
    _no_text(caplog)


def test_도중_전체_제한을_넘기면_total_timeout이어야_한다(caplog):
    with caplog.at_level("WARNING", logger=SERVICE_LOGGER):
        _run(_stream(("부분 답",), None, delay=1), first=5, total=0.1)

    lines = _lines(caplog, "답변 미완료")
    assert len(lines) == 1
    assert lines[0].startswith(f"답변 미완료: 도중 total_timeout room={ROOM} 4자 ")


# 반려동물 목록 실패


class _Contexts:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def get_pets(self):
        raise self.error


def _pets(error: Exception) -> None:
    read = service.ReadDeps(None, _Contexts(error), None, datetime.now())
    asyncio.run(service._ReadPets(QUESTION, read).pets())


def test_반려동물_목록이_Java_오류면_상태_코드를_한_줄_남겨야_한다(caplog):
    error = BackendError(401, b"{}", "application/json", ["c=secret"])
    with caplog.at_level("WARNING", logger=SERVICE_LOGGER), pytest.raises(AnswerError) as raised:
        _pets(error)

    assert raised.value.reason == "read_pets"
    assert _lines(caplog, "READ 반려동물 목록 실패") == ["READ 반려동물 목록 실패: Java 401"]
    assert all("secret" not in r.getMessage() for r in caplog.records)


def test_반려동물_목록이_502면_원인을_한_줄_남겨야_한다(caplog):
    try:
        raise external_error() from httpx2.ReadTimeout("t")
    except AppError as error:
        bad = error
    with caplog.at_level("WARNING", logger=SERVICE_LOGGER), pytest.raises(AnswerError):
        _pets(bad)

    lines = _lines(caplog, "READ 반려동물 목록 실패")
    assert len(lines) == 1
    assert "제한 시간 초과" in lines[0]


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


def test_반려동물_목록_실패는_대화창에서_error와_두_줄이어야_한다(client, java, caplog):
    java.context_status = 0
    use_agent(client, FakeToolAgent("get_health_indicators", {}))
    use_reader(client, FakeToolReader())
    room = room_of(client, java, pet_sn=CHOCO)

    with caplog.at_level("WARNING", logger=SERVICE_LOGGER):
        evs = events(send(client, room, "체중 어때?"))

    assert [name for name, _ in evs] == ["intent", "error"]
    assert len(_lines(caplog, "READ 반려동물 목록 실패")) == 1
    assert len(_lines(caplog, "답변 실패: 첫 글자 전 read_pets ")) == 1


# 도구 고르기 시간 초과


class _SlowAgent:
    async def decide(self, messages, max_tokens, today, hint=None) -> ToolDecision:
        await asyncio.sleep(1)
        return ToolDecision()


def _judge(text: str) -> object:
    return asyncio.run(
        service.judge_tools(
            text, [{"role": "user", "content": text}], _SlowAgent(), 100, date.today(), 0.05
        )
    )


def test_도구_고르기_시간_초과에_행이_없으면_일시_오류로_한_줄(caplog):
    with (
        caplog.at_level("WARNING", logger=SERVICE_LOGGER),
        pytest.raises(ClassifyError, match="tool_decide"),
    ):
        _judge("강아지 포도 먹어도 돼?")

    assert _lines(caplog, "도구 고르기 시간 초과") == ["도구 고르기 시간 초과(0.05초): 일시 오류"]


def test_도구_고르기_시간_초과에_행이_있으면_행_이동으로_한_줄(caplog, monkeypatch):
    sample = next(r for r in service.rules.routing_table() if r.routable)
    monkeypatch.setattr(service.rules, "match_route", lambda text: sample)
    with caplog.at_level("WARNING", logger=SERVICE_LOGGER):
        judged = _judge("아무 문장")

    assert judged.intent == sample.to_intent()
    assert _lines(caplog, "도구 고르기 시간 초과") == ["도구 고르기 시간 초과(0.05초): 행 이동"]


# 클라이언트 : 결과 답변이 글도 도구도 없음


def _empty_sse() -> bytes:
    start = {
        "type": "message_start",
        "message": {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": MODEL,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 1},
        },
    }
    delta = {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
        "usage": {"output_tokens": 0},
    }
    events_ = [
        ("message_start", start),
        ("message_delta", delta),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in events_).encode()


def test_도구_결과_답변이_비면_no_output_실패를_로그로_남겨야_한다(caplog):
    fake = FakeAnthropic(lambda _: sse_response(_empty_sse()))
    use = {"type": "tool_use", "id": "toolu_1", "name": "list_checkups", "input": {}}
    decision = ToolDecision(
        call=service.tools.parse("list_checkups", {}, "toolu_1"), content=(use,)
    )

    async def follow(call):
        return None

    async def run():
        agent = AnthropicToolAgent(fake.client(), MODEL)
        return [
            t async for t in agent.answer(CONTEXT, decision, "결과", 4500, date.today(), follow)
        ]

    with (
        caplog.at_level("WARNING", logger="app.chat.clients"),
        pytest.raises(AnswerError, match="no_output"),
    ):
        asyncio.run(run())

    lines = _lines(caplog, "LLM 도구 결과 답변 실패")
    assert len(lines) == 1
    assert lines[0].startswith("LLM 도구 결과 답변 실패: no_output ")
