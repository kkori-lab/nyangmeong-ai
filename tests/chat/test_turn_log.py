"""SCR-AIM-004 턴 기록 한 줄·실패 태그·재요청 후보·주 단위 집계 (추가 요청, 2026-11-26)

턴마다 app.chat.turnlog 한 줄(도구·읽기 횟수·결과·태그), 회원 문장·답변 글은 남지 않는다."""

import asyncio
import re
from datetime import date

import pytest

from app.chat import rules, service, turnlog
from app.chat.clients import ToolDecision
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_action import action_result, weight_agent
from tests.chat.test_messages import MessageJava, events, limits, send
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import CHOCO, TODAY
from tests.chat.test_tools import room_of, use_agent

LOGGER = "app.chat.turnlog"
SECRET = "비밀문장"


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


def turn_lines(caplog) -> list[dict[str, str]]:
    found = []
    for record in caplog.records:
        message = record.getMessage()
        assert SECRET not in message
        if record.name == LOGGER and message.startswith("턴 "):
            found.append(dict(re.findall(r"(\w+)=(\S+)", message)))
    return found


def one_turn(caplog) -> dict[str, str]:
    lines = turn_lines(caplog)
    assert len(lines) == 1
    assert lines[0]["ms"].isdigit()
    return lines[0]


# 턴 기록 한 줄


def test_글_답변_턴은_SEARCH_ok_도구_없음이어야_한다(client, java, caplog):
    use_agent(client, FakeToolAgent(texts=("반가워요",)))
    room = room_of(client, java)
    with caplog.at_level("INFO", logger=LOGGER):
        events(send(client, room, f"안녕 {SECRET}"))

    line = one_turn(caplog)
    assert (line["room"], line["kind"], line["tools"]) == (str(room), "SEARCH", "-")
    assert (line["reads"], line["java"], line["result"], line["cards"]) == ("0", "0", "ok", "0")
    assert (line["tags"], line["prev"], line["retry"], line["reply"]) == ("-", "-", "0", "-")


def test_READ_턴은_고른_도구와_읽기_횟수_Java_호출_수를_남겨야_한다(client, java, caplog):
    use_agent(client, FakeToolAgent("get_health_indicators", {}))
    use_reader(client, FakeToolReader([{"rcdNvl": 4.2}]))
    room = room_of(client, java, pet_sn=CHOCO)
    with caplog.at_level("INFO", logger=LOGGER):
        events(send(client, room, f"체중 어때? {SECRET}"))

    line = one_turn(caplog)
    assert (line["kind"], line["tools"], line["reads"], line["java"]) == (
        "SEARCH",
        "get_health_indicators",
        "1",
        "1",
    )
    assert (line["result"], line["tags"]) == ("ok", "-")


def test_READ_Java_실패_턴은_read_failed여야_한다(client, java, caplog):
    use_agent(client, FakeToolAgent("get_health_indicators", {}))
    use_reader(client, FakeToolReader(fail=True))
    room = room_of(client, java, pet_sn=CHOCO)
    with caplog.at_level("INFO", logger=LOGGER):
        events(send(client, room, "체중 어때?"))

    line = one_turn(caplog)
    assert (line["reads"], line["java"], line["tags"]) == ("1", "1", "read_failed")


def test_쓰기_카드_턴은_ACTION_card와_카드_수여야_한다(client, java, caplog):
    use_agent(client, weight_agent())
    room = room_of(client, java)
    with caplog.at_level("INFO", logger=LOGGER):
        events(send(client, room, f"초코 오늘 체중 4.2kg 기록해줘 {SECRET}"))

    line = one_turn(caplog)
    assert (line["kind"], line["tools"], line["result"], line["cards"]) == (
        "ACTION",
        "draft_daily_health_record",
        "card",
        "1",
    )


def test_폴백_턴은_fallback_태그여야_한다(client, java, caplog):
    use_agent(client, FakeToolAgent())
    room = room_of(client, java)
    with caplog.at_level("INFO", logger=LOGGER):
        events(send(client, room, "ㅁㄴㅇㄹ"))

    line = one_turn(caplog)
    assert (line["kind"], line["tags"], line["result"]) == ("FALLBACK", "fallback", "ok")


class _SlowAgent(FakeToolAgent):
    async def decide(self, messages, max_tokens, today) -> ToolDecision:
        await asyncio.sleep(1)
        return await super().decide(messages, max_tokens, today)


def test_도구_고르기_시간_초과_턴은_timeout_error여야_한다(client, java, caplog, monkeypatch):
    limits(monkeypatch, 0.05, 30)
    use_agent(client, _SlowAgent())
    room = room_of(client, java)
    with caplog.at_level("INFO", logger=LOGGER):
        events(send(client, room, "강아지 귀 냄새가 나요"))

    line = one_turn(caplog)
    assert (line["kind"], line["result"], line["tags"]) == ("-", "error", "timeout,error")


class _BrokenAgent(FakeToolAgent):
    async def decide(self, messages, max_tokens, today) -> ToolDecision:
        raise RuntimeError("고장")


def test_처리_중_예외_턴은_exception_error여야_한다(client, java, caplog):
    use_agent(client, _BrokenAgent())
    room = room_of(client, java)
    with caplog.at_level("INFO", logger=LOGGER):
        events(send(client, room, "강아지 귀 냄새가 나요"))

    line = one_turn(caplog)
    assert (line["result"], line["tags"]) == ("error", "exception,error")


# 재요청 후보


def test_실패_글_뒤_아니_여기서_해_줘는_retry_1과_직전_태그여야_한다(client, java, caplog):
    use_agent(client, FakeToolAgent())
    room = room_of(client, java)
    events(send(client, room, "ㅁㄴㅇㄹ"))
    with caplog.at_level("INFO", logger=LOGGER):
        events(send(client, room, "아니 여기서 해 줘"))

    line = turn_lines(caplog)[-1]
    assert (line["prev"], line["retry"]) == ("fallback", "1")


def test_실패_아닌_글_뒤_아니는_retry_0이어야_한다(client, java, caplog):
    use_agent(client, FakeToolAgent(texts=("반가워요",)))
    room = room_of(client, java)
    events(send(client, room, "안녕"))
    with caplog.at_level("INFO", logger=LOGGER):
        events(send(client, room, "아니"))

    line = turn_lines(caplog)[-1]
    assert (line["prev"], line["retry"]) == ("-", "0")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("아니 그거 말고", True),
        ("여기서 해 줘", True),
        ("대화창에서 해줘", True),
        ("그게 아니라 체중이요", True),
        ("체중 알려줘", False),
        ("어 아니야", False),
    ],
)
def test_재요청_말_판정(text, expected):
    assert turnlog.is_retry(text) is expected


# 태그 표


def _message_constants() -> set[str]:
    # service의 회원에게 보이는 글 상수 : 한글이 든 대문자 이름 문자열
    return {
        name
        for name, value in vars(service).items()
        if name.isupper() and isinstance(value, str) and re.search("[가-힣]", value)
    }


def test_service_문구_상수는_모두_태그_표나_QUIET에_있어야_한다():
    tagged = {name for names in turnlog.TEXT_TAGS.values() for name in names}
    assert tagged.isdisjoint(turnlog.QUIET)
    assert _message_constants() - tagged - turnlog.QUIET == set()
    assert (tagged | turnlog.QUIET) - set(vars(service)) == set()


@pytest.mark.parametrize(
    ("tag", "name"),
    [(tag, name) for tag, names in turnlog.TEXT_TAGS.items() for name in names],
)
def test_문구_상수를_채운_글은_그_태그여야_한다(tag, name):
    filled = re.sub(r"\{[^{}]*\}", "초코", getattr(service, name))
    assert tag in turnlog.text_tags(f"앞 글\n{filled}")


def test_실패_문구가_없는_글은_태그가_없어야_한다():
    assert turnlog.text_tags("체중은 4.2kg이에요.") == []
    assert turnlog.text_tags(None) == []


# 카드 결과 한 줄


def _result_lines(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == LOGGER and r.getMessage().startswith("카드 결과 ")
    ]


@pytest.mark.parametrize("status", ["DONE", "FAILED"])
def test_카드_결과는_도구와_상태만_한_줄이어야_한다(client, java, caplog, status):
    room = room_of(client, java)
    with caplog.at_level("INFO", logger=LOGGER):
        res = action_result(client, room, "draft_expense_limit", status, {"mmExpndLimAmt": 300000})

    assert res.status_code == 201
    assert _result_lines(caplog) == [
        f"카드 결과 room={room} tool=draft_expense_limit status={status} errors=0"
    ]
    assert all("300000" not in line for line in _result_lines(caplog))


# 읽기·집계


def _turn(**fields) -> str:
    base = {
        "room": "7",
        "kind": "SEARCH",
        "reply": "-",
        "tools": "get_health_indicators",
        "reads": "1",
        "java": "2",
        "result": "ok",
        "cards": "0",
        "tags": "-",
        "prev": "-",
        "retry": "0",
        "ms": "1200",
    } | fields
    body = " ".join(f"{k}={v}" for k, v in base.items())
    return f"10:30:00.123 [1] INFO app.chat.turnlog - 턴 {body}\n"


def _card(status: str, tool: str = "draft_expense_limit") -> str:
    head = "10:30:01.000 [1] INFO app.chat.turnlog - 카드 결과"
    return f"{head} room=7 tool={tool} status={status} errors=0\n"


SUNDAY = date(2026, 11, 22)
MONDAY = date(2026, 11, 23)


def test_집계는_ISO_주로_묶고_다른_줄과_깨진_줄은_건너뛰어야_한다():
    lines = [
        (SUNDAY, _turn()),
        (MONDAY, _turn(kind="FALLBACK", tools="-", reads="0", java="0", tags="fallback")),
        (MONDAY, _turn(tags="read_failed,timeout", reads="3", prev="fallback", retry="1")),
        (MONDAY, _card("FAILED")),
        (MONDAY, _card("DONE")),
        (MONDAY, "10:30:00.000 [1] INFO app.chat.service - 턴 room=7 kind=SEARCH\n"),
        (MONDAY, "10:30:00.000 [1] INFO app.chat.turnlog - 턴 room=7 kind=SEARCH\n"),
        (MONDAY, _turn(reads="x")),
        (MONDAY, "깨진 줄\n"),
    ]

    weeks = turnlog.summarize(lines)

    assert list(weeks) == ["2026-W47", "2026-W48"]
    assert weeks["2026-W47"].turns == 1
    week = weeks["2026-W48"]
    assert week.turns == 2
    assert week.kinds == {"FALLBACK": 1, "SEARCH": 1}
    assert week.tools == {"get_health_indicators": 1}
    assert (week.reads, week.reads_max, week.java) == (3, 3, 2)
    assert week.tags == {"fallback": 1, "read_failed": 1, "timeout": 1}
    assert week.failed == 2
    assert week.retries == {"fallback": 1}
    assert week.cards == {"FAILED": 1, "DONE": 1}
    assert week.card_fails == {"draft_expense_limit": 1}
    text = turnlog.render(weeks)
    assert "## 2026-W48" in text
    assert "- 턴: 2" in text
    assert "- 재요청 후보: 1 (직전 태그: fallback 1)" in text


def test_만든_줄은_읽기_함수가_그대로_읽어야_한다():
    record = turnlog.TurnRecord(7, kind="ACTION", tools=["draft_expense_limit"], cards=1)
    record.tag("missing_fields")
    line = f"10:30:00.000 [1] INFO app.chat.turnlog - {turnlog.format_turn(record)}"
    result = f"10:30:00.000 [1] INFO app.chat.turnlog - {turnlog.format_result(7, 't', 'DONE', 1)}"

    head, fields = turnlog.parse_line(line)
    assert head == "턴"
    assert (fields["kind"], fields["tools"], fields["tags"], fields["cards"]) == (
        "ACTION",
        "draft_expense_limit",
        "missing_fields",
        "1",
    )
    assert turnlog.parse_line(result) == (
        "카드 결과",
        {"room": "7", "tool": "t", "status": "DONE", "errors": "1"},
    )


def test_로그_폴더는_기간_안_날짜_파일만_읽어야_한다(tmp_path):
    (tmp_path / "ai_2026-11-23.log").write_text(_turn(), encoding="utf-8")
    (tmp_path / "ai_2026-10-01.log").write_text(_turn(), encoding="utf-8")
    (tmp_path / "ai_memo.log").write_text(_turn(), encoding="utf-8")

    since = turnlog.week_start(date(2026, 11, 26), 1)
    days = [day for day, _ in turnlog.log_lines(tmp_path, since)]

    assert since == MONDAY
    assert days == [MONDAY]


def test_집계_명령은_없는_폴더면_0건이어야_한다(tmp_path):
    from scripts import turn_stats

    assert turn_stats.main([str(tmp_path / "없음")], date(2026, 11, 26)) == "턴 기록 0건"


def test_집계_명령은_이번_주_턴을_보여야_한다(tmp_path):
    from scripts import turn_stats

    (tmp_path / "ai_2026-11-26.log").write_text(_turn() + _turn(), encoding="utf-8")

    out = turn_stats.main([str(tmp_path), "--weeks", "1"], date(2026, 11, 26))

    assert "## 2026-W48" in out
    assert "- 턴: 2" in out
