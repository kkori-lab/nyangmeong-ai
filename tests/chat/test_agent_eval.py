"""에이전트 ② 다단계 평가 세트(scripts/tool_eval.py --agent) 채점 : 키 없이 가짜 결과로
docs/design/agent.md 7절"""

import json
from pathlib import Path

import pytest

from app.chat import tools, turnlog
from scripts.tool_eval import (
    AGENT_DATA,
    AGENT_PASS,
    CARD_END,
    AgentRun,
    agent_summary,
    score_agent,
)

READ_ROW = {
    "id": "X1",
    "q": "코코 체중이랑 검진 같이",
    "steps": [["get_health_indicators", "list_daily_health_records"], "list_checkups"],
    "end": "글",
}
CARD_ROW = {
    "id": "X2",
    "q": "내일 병원 일정 있으면 7시로",
    "steps": ["list_my_care_schedules"],
    "ordered": True,
    "end": "카드:draft_schedule_update",
}


def _rows() -> list[dict]:
    return [json.loads(line) for line in Path(AGENT_DATA).read_text(encoding="utf-8").splitlines()]


def test_기대_도구가_모두_나오고_끝이_같으면_정답이어야_한다():
    run = AgentRun(["list_checkups", "get_health_indicators", "list_expenses"], "글")

    mark = score_agent(READ_ROW, run)

    assert mark == {
        "ok": True,
        "end_ok": True,
        "steps_ok": True,
        "write_wrong": 0,
        "limited": False,
    }


def test_기대_도구가_빠지면_오답이어야_한다():
    mark = score_agent(READ_ROW, AgentRun(["get_health_indicators"], "글"))

    assert (mark["ok"], mark["steps_ok"], mark["end_ok"]) == (False, False, True)


def test_ordered면_차례가_다르면_오답이어야_한다():
    row = {**READ_ROW, "steps": ["list_checkups", "get_checkup"], "ordered": True}

    assert score_agent(row, AgentRun(["list_checkups", "get_checkup"], "글"))["ok"]
    assert not score_agent(row, AgentRun(["get_checkup", "list_checkups"], "글"))["ok"]


def test_기대한_카드가_아닌_쓰기_도구는_쓰기_잘못이어야_한다():
    run = AgentRun(["list_my_care_schedules", "delete_schedule"], CARD_END + "delete_schedule")

    mark = score_agent(CARD_ROW, run)

    assert (mark["ok"], mark["end_ok"], mark["write_wrong"]) == (False, False, 1)


def test_기대한_카드로_끝나면_쓰기_잘못이_아니어야_한다():
    run = AgentRun(["list_my_care_schedules", "draft_schedule_update"], CARD_ROW["end"])

    mark = score_agent(CARD_ROW, run)

    assert (mark["ok"], mark["write_wrong"]) == (True, 0)


def test_상한_걸림과_오류를_세어야_한다():
    limited = AgentRun(["list_checkups"] * 8, "글", tags=[turnlog.AGENT_LIMIT])
    failed = AgentRun([], "오류", error="AnswerError")

    assert score_agent(READ_ROW, limited)["limited"]
    assert not score_agent(READ_ROW, failed)["ok"]


def test_요약은_정답률_기준과_쓰기_잘못_0을_같이_봐야_한다():
    runs = [AgentRun([], "글", ms=100.0), AgentRun([], "글", ms=300.0)]
    good = [{"ok": True, "write_wrong": 0, "limited": False}] * 2
    wrote = [{"ok": True, "write_wrong": 1, "limited": True}, good[0]]
    half = [{"ok": True, "write_wrong": 0, "limited": False}, {**good[0], "ok": False}]

    assert agent_summary("a", runs, good)["passed"]
    summary = agent_summary("b", runs, wrote)
    assert (summary["passed"], summary["write_wrong"], summary["limited"]) == (False, 1, 1)
    assert summary["ms"] == 200.0
    assert agent_summary("c", runs, half)["rate"] < AGENT_PASS


# 문항 파일


def test_다단계_문항은_8개_안팎이고_id가_겹치지_않아야_한다():
    rows = _rows()

    assert 6 <= len(rows) <= 12
    assert len({row["id"] for row in rows}) == len(rows)


@pytest.mark.parametrize("row", _rows(), ids=lambda row: row["id"])
def test_다단계_문항의_도구와_끝은_도구_목록에_있어야_한다(row):
    names = {d["name"] for d in tools.tool_definitions()}
    for want in row["steps"]:
        assert set(want if isinstance(want, list) else [want]) <= names
    end = row["end"]
    assert end == "글" or (end.startswith(CARD_END) and tools.card_entry(end[len(CARD_END) :]))
