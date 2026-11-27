"""에이전트 ③ 다단계 평가 쓰기 꼴(scripts/tool_eval.py --agent, agent_write_eval.jsonl) : 키 없이
docs/design/agent.md 7절 : 쓰기 → 읽기, 칸 오류 1번·두 번, 단순 명령(pending 없음),
만들고 이어 쓰기, 말하지 않은 쓰기 없음"""

import json
from pathlib import Path

import pytest

from app.chat import rules, tools
from app.chat.schemas import ActionStatus, AgentResult
from scripts.tool_eval import AGENT_WRITE_DATA, CARD_END, STOP_END, AgentRun, score_agent


def _rows() -> list[dict]:
    text = Path(AGENT_WRITE_DATA).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line]


ROW = {
    "id": "Y1",
    "q": "코코 체중 기록하고 늘었는지 알려 줘",
    "steps": ["draft_daily_health_record", "get_health_indicators"],
    "ordered": True,
    "writes": ["draft_daily_health_record"],
    "pending": True,
    "end": "글",
}


def test_writes에_든_쓰기_도구는_쓰기_잘못이_아니어야_한다():
    run = AgentRun(["draft_daily_health_record", "get_health_indicators"], "글", pending=True)

    mark = score_agent(ROW, run)

    assert (mark["ok"], mark["write_wrong"]) == (True, 0)


def test_writes에_없는_쓰기_도구는_쓰기_잘못이어야_한다():
    steps = ["draft_daily_health_record", "draft_schedule", "get_health_indicators"]

    mark = score_agent(ROW, AgentRun(steps, "글", pending=True))

    assert mark["write_wrong"] == 1


def test_pending_기대가_다르면_오답이어야_한다():
    run = AgentRun(["draft_daily_health_record", "get_health_indicators"], "글", pending=False)

    assert not score_agent(ROW, run)["ok"]


def test_쓰기_꼴은_7개이고_id가_겹치지_않아야_한다():
    rows = _rows()

    assert len(rows) == 7
    assert len({row["id"] for row in rows}) == len(rows)
    assert all(row["id"].startswith("W") for row in rows)


@pytest.mark.parametrize("row", _rows(), ids=lambda row: row["id"])
def test_쓰기_꼴_문항의_도구_끝_결과가_맞는_모양이어야_한다(row):
    names = {d["name"] for d in tools.tool_definitions()}
    for want in row["steps"]:
        assert set(want if isinstance(want, list) else [want]) <= names
    end = row["end"]
    assert end in ("글", STOP_END) or (
        end.startswith(CARD_END) and tools.card_entry(end[len(CARD_END) :])
    )
    for write in row.get("writes", ()):
        assert tools.card_entry(write) is not None
    # 결과 칸은 agent-continue 요청과 같은 모양
    for stop in row["results"]:
        for result in stop:
            parsed = AgentResult.model_validate({"tool": "draft_schedule", **result})
            assert parsed.status in ActionStatus
    # pending 기대는 rules.agent_pending(첫 멈춤 카드 수)과 같아야 (에이전트 ④)
    first = len(row["results"][0]) if row["results"] else 1
    assert rules.agent_pending(row["q"], first) is row["pending"]
