"""tool calling 1단계 평가(docs/design/tool-calling.md 7-1절). 실제 Anthropic 호출(비용이 든다)

돌리기: uv run python -m scripts.tool_eval [--sonnet] [--answer] [--only T01,T05]
        [--ptc [code|both]] [--agent] [--off chain]
- 도구 흐름(service.judge_tools)을 잰다(옛 판정 service.judge는 2026-11-11 삭제)
- 도구 목록 : 테스트와 같은 가짜 Java 목록(스냅샷 + 코드 값), Java는 부르지 않는다
- 문항별 결과 : .cache/tool_eval/<시각>.jsonl (git 제외)
- --ptc (2026-11-26) : 프로그래밍식 도구 호출 시험. 지금 방식과 PTC를 가짜 Java 읽기
  (fakes.FakeEvalReader, 반려동물 10마리)로 나란히 잰다.
  code는 읽기 도구를 코드에서만, both는 direct·코드 둘 다
- --agent (2026-11-26) : 에이전트 ② 다단계 세트(docs/design/agent.md 7절, 읽기 꼴).
  가짜 Java 읽기로 루프를 끝까지 돌려 고른 도구 차례·끝(글·카드)·상한 걸림을 잰다
  ③ 쓰기 꼴 : 행의 results(멈춤마다 카드 결과 DONE·FAILED+errors·data)로 카드에서 멈춘 루프를
  service.agent_carry -> judge_tools(carry)로 이어 간다(agent-continue와 같은 길). pending은
  rules.agent_pending(첫 멈춤 카드 수)으로 보고(④), 이어 갈 일이 없으면 끝은 "멈춤"
- --off (2026-11-27) : 의도를 고르는 정규식 지름길을 이 실행 동안만 끄고 잰다(앱 코드는 그대로).
  chain은 이어 고르기 정규식(rules.chains_more·chains_after_move)을 늘 False로.
  기본 세트·--agent 둘 다. hint(키워드 행 힌트)는 ②(2026-11-28)에서 앱에서 지움
- 카드 유형(2026-11-28) : 행의 card(앞 턴 질문·카드 요약 글·돌려받은 카드)로 떠 있는 카드에
  확인·취소·고치기 말을 잰다. 정답은 run_card·drop_card 또는 고칠 쓰기 도구
pytest 수집 제외(tests/ 밖), 테스트·CI에서 미호출(AGENTS.md 5번)
"""

import argparse
import asyncio
import contextlib
import json
import statistics
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.chat import agentstate, rules, service, tools, turnlog
from app.chat.clients import TOOL_LIMIT, AnthropicToolAgent, ToolDecision, _code_calls
from app.chat.repository import get_ai_settings
from app.chat.schemas import ActionDraft, AgentResult, IntentKind
from app.core.config import get_settings
from app.core.llm import get_anthropic_client
from tests.chat.fakes import FakeEvalPets, FakeEvalReader, fake_catalog

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tests/chat/data/tool_eval.jsonl"
AGENT_DATA = ROOT / "tests/chat/data/agent_eval.jsonl"
# ③ 쓰기 꼴(가짜 실행 결과 results) : --agent가 읽기 꼴 뒤에 이어서 잰다
AGENT_WRITE_DATA = ROOT / "tests/chat/data/agent_write_eval.jsonl"
# 다단계 세트 기준 날짜 : 가짜 일정(2026-11-28 병원)이 "내일"
AGENT_TODAY = date(2026, 11, 27)
# 다단계 정답률 기준(agent.md 7절) : 못 넘으면 --sonnet 비교 뒤 사람이 정함
AGENT_PASS = 0.8
CARD_END = "카드:"
# 이어 갈 일이 없음(취소만·고칠 수 없는 실패만)으로 끝난 루프
STOP_END = "멈춤"
OUT_DIR = ROOT / ".cache/tool_eval"
SONNET = "claude-sonnet-5-5"
# 도구 고르기 기준 문항(tool-calling.md 7-1절 4회차 판정) : T01~T44
CORE = 44
# 새도구 : 2026-11-27 백엔드 새 도구 41개(T97~T137), ②(T138~T140), ③ #326 10개(T141~T150)
# --off로 끌 수 있는 지름길(2026-11-27 정규식 지름길 줄이기 ①)
OFF_NAMES = ("chain",)
TYPES = (
    "사용법",
    "이동",
    "일정",
    "케어",
    "지식",
    "범위밖",
    "헷갈림",
    "수정",
    "조합",
    "새도구",
    "카드",
)


@dataclass
class Usage:
    input: int = 0
    cache: int = 0
    output: int = 0

    def add(self, usage: Any) -> None:
        read = getattr(usage, "cache_read_input_tokens", 0) or 0
        write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.input += usage.input_tokens + read + write
        self.cache += read
        self.output += usage.output_tokens


@dataclass
class Result:
    tool: str
    args: dict = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)
    ms: float = 0.0
    answer: str | None = None
    error: str | None = None
    # 글 답변 뒤에 도구 호출이 붙은 응답 수
    text_then_tool: int = 0
    # 지연 나누기(2026-11-20) : 첫 블록까지·도구 고르기 끝까지. LLM을 안 부른 문항은 None
    first_ms: float | None = None
    decide_ms: float | None = None
    # 프로그래밍식 도구 호출(--ptc) : 첫 글자까지, 코드 안 도구 호출 수·이름, 글 뒤 코드
    text_ms: float | None = None
    code_calls: int = 0
    code_tools: list[str] = field(default_factory=list)
    text_then_code: int = 0


def off_names(value: str) -> tuple[str, ...]:
    # --off 값 : 쉼표 목록, OFF_NAMES 밖 이름은 argparse 오류(종료 2)
    names = tuple(dict.fromkeys(name.strip() for name in value.split(",") if name.strip()))
    wrong = [name for name in names if name not in OFF_NAMES]
    if not names or wrong:
        raise argparse.ArgumentTypeError(
            f"끌 수 있는 지름길은 {', '.join(OFF_NAMES)}: {', '.join(wrong) or value!r}"
        )
    return names


def off_line(names: tuple[str, ...]) -> str:
    return f"끈 지름길: {', '.join(names) or '없음'}"


def off_tag(names: tuple[str, ...]) -> str:
    # 결과 파일 이름 끝 : -off-chain
    return f"-off-{'-'.join(names)}" if names else ""


def _never(_text: str) -> bool:
    return False


@contextlib.contextmanager
def shortcuts_off(names: tuple[str, ...]) -> Iterator[None]:
    """이 블록 동안만 지름길을 끄고, 끝나면 원래 함수로 되돌린다"""
    saved: list[tuple[object, str, object]] = []

    def put(owner: object, attr: str, value: object) -> None:
        saved.append((owner, attr, getattr(owner, attr)))
        setattr(owner, attr, value)

    try:
        if "chain" in names:
            put(rules, "chains_more", _never)
            put(rules, "chains_after_move", _never)
        yield
    finally:
        for owner, attr, value in reversed(saved):
            setattr(owner, attr, value)


def _register_kind(values: dict) -> str:
    return tools.DRAFT_CARE_ITEM if values.get("care_zone_cd") else tools.DRAFT_SCHEDULE


def _search_tool(judged: service.Judged) -> tuple[str, dict]:
    if judged.guide_ids:
        scr_id = judged.shortcut.scr_id if judged.shortcut else None
        return tools.SEARCH_GUIDE, {"scr_id": scr_id}
    return "answer", {}


class _DecisionRecorder(AnthropicToolAgent):
    """도구 고르기 결과를 남긴다 : READ(Java 없이 실행 불가)·ACTION을 고른 도구 이름으로 세려고"""

    decision: ToolDecision | None = None
    text_then_tool: int = 0
    # 첫 고르기 호출의 첫 블록 시각·고르기 끝 시각(time.monotonic)
    first_at: float | None = None
    decided_at: float | None = None
    # 첫 글자(text_delta) 시각, 코드 안에서 부른 도구 이름(순서대로)
    text_at: float | None = None
    code_tools: list[str] | None = None

    async def _events(self, request: dict):
        async for event in super()._events(request):
            kind = getattr(event, "type", None)
            if self.first_at is None and kind == "content_block_start":
                self.first_at = time.monotonic()
            delta = getattr(event, "delta", None) if kind == "content_block_delta" else None
            if self.text_at is None and getattr(delta, "type", None) == "text_delta":
                self.text_at = time.monotonic()
            yield event

    async def _continue(self, current, final, code):
        if self.code_tools is None:
            self.code_tools = []
        self.code_tools += [b.name for b in _code_calls(final)]
        return await super()._continue(current, final, code)

    async def decide(self, *args, **kwargs) -> ToolDecision:
        # 첫 고르기만 남김 : 쓰기 카드 뒤 이어 고르기(한 메시지 여러 명령 ②)는 정답 셈에서 뺌
        decision = await super().decide(*args, **kwargs)
        if self.decision is None:
            self.decision = decision
            self.decided_at = time.monotonic()
        return decision

    def _log(self, final, task: str, started: float, length: int | None = None) -> None:
        if length is not None and any(block.type == "tool_use" for block in final.content):
            self.text_then_tool += 1
        super()._log(final, task, started, length)


def _picked(agent: _DecisionRecorder) -> tuple[str, dict] | None:
    call = agent.decision.call if agent.decision is not None else None
    if call is None or call.args is None:
        return None
    return call.name, call.args.model_dump(exclude_none=True)


async def run_tools(
    client,
    model: str,
    q: str,
    today,
    keep_answer: bool,
    ptc: str | None = None,
    read: bool = False,
    history: tuple[str, ...] = (),
    card: dict | None = None,
) -> Result:
    # 도구 흐름 판정 그대로. 글 답변 스트림은 끝까지 읽어 지연·토큰에 넣는다(1회차와 같은 셈)
    # read 없음 : READ는 Java 없이 실행 안 하므로 고른 READ 이름으로,
    # ACTION은 카드 도구 이름·LLM 인자로
    # read 있음(--ptc) : 가짜 Java 읽기로 READ·코드 안 READ까지 실행(답변 지연·토큰 포함)
    # history : 문항 앞의 답 없는 회원 질문들(이력에 질문이 둘인 경우, 2026-11-26)
    # card : 떠 있는 확인 카드(2026-11-28) {"q": 카드를 만든 말, "ai": 카드 요약 글, "actions": […]}
    #   앞 턴 두 메시지를 이력에 넣고 actions를 돌려받은 카드(priors)로
    usage = Usage()
    agent = _DecisionRecorder(client, model, on_usage=lambda _task, u: usage.add(u), ptc=ptc)
    ai = get_ai_settings()
    limits = get_settings()
    deps = service.ReadDeps(reader=FakeEvalReader(), contexts=FakeEvalPets()) if read else None
    priors = tuple(ActionDraft.model_validate(a) for a in card["actions"]) if card else ()
    before = (
        [{"role": "user", "content": card["q"]}, {"role": "assistant", "content": card["ai"]}]
        if card
        else []
    )
    context = [*before, *({"role": "user", "content": text} for text in (*history, q))]
    record = turnlog.start(0, q, None)
    started = time.monotonic()
    try:
        judged = await service.judge_tools(
            q,
            context,
            agent,
            ai.max_tokens,
            today,
            limits.answer_first_token_sec,
            read=deps,
            priors=priors,
        )
        text = None
        if judged.stream is not None:
            parts = [part async for part in judged.stream]
            text = "".join(parts)
    except Exception as error:
        turnlog.finish(record)
        return Result(
            "error",
            usage=usage,
            error=type(error).__name__,
            text_then_tool=agent.text_then_tool,
            code_calls=record.code,
        )
    turnlog.finish(record)
    ms = (time.monotonic() - started) * 1000
    result = _result(judged, agent, usage, ms, text if keep_answer else None)
    result.text_then_tool = agent.text_then_tool
    result.code_calls = record.code
    result.code_tools = agent.code_tools or []
    result.text_then_code = int(turnlog.TEXT_THEN_CODE in record.tags)
    if result.tool == "answer" and result.code_tools:
        # 코드 안에서 읽고 글로 답함 : 처음 부른 읽기 도구를 고른 도구로 셈
        result.tool = result.code_tools[0]
    if agent.text_at is not None:
        result.text_ms = (agent.text_at - started) * 1000
    if agent.first_at is not None:
        result.first_ms = (agent.first_at - started) * 1000
    if agent.decided_at is not None:
        result.decide_ms = (agent.decided_at - started) * 1000
    return result


def _result(
    judged: service.Judged, agent: _DecisionRecorder, usage: Usage, ms: float, answer: str | None
) -> Result:
    kind = judged.intent.kind
    if kind is IntentKind.ROUTE:
        return Result(tools.NAVIGATE, {"scr_id": judged.intent.scr_id}, usage, ms, answer)
    if kind is IntentKind.SEARCH:
        picked = _picked(agent)
        if picked is not None and tools.read_entry(picked[0]) is not None:
            # 가짜 Java 읽기(--ptc)로 READ를 실행해 글로 답한 경우
            return Result(picked[0], picked[1], usage, ms, answer)
        name, args = _search_tool(judged)
        return Result(name, args, usage, ms, answer)
    if kind is IntentKind.REGISTER:
        values = judged.ai_values or {}
        return Result(judged.tool or _register_kind(values), values, usage, ms, answer)
    picked = _picked(agent)
    if kind is IntentKind.ACTION and picked is not None:
        return Result(picked[0], picked[1], usage, ms, answer)
    if picked is not None and tools.read_entry(picked[0]) is not None:
        return Result(picked[0], picked[1], usage, ms, answer)
    return Result(tools.DECLINE, {"unclear": not judged.out_of_scope}, usage, ms, answer)


def tool_kind(tool: str) -> str:
    # 지연을 고른 도구 종류별로 보려고(2026-11-20)
    if tool in (tools.DECLINE, tools.NAVIGATE, tools.SEARCH_GUIDE):
        return tool
    if tool in tools.REGISTER_TOOLS or tools.card_entry(tool) is not None:
        return "쓰기 카드"
    if tools.read_entry(tool) is not None:
        return "READ"
    return "바로 답" if tool == "answer" else tool


def _median(values: list[float | None]) -> float | None:
    kept = [v for v in values if v is not None]
    return statistics.median(kept) if kept else None


def _ms(value: float | None) -> str:
    return "-" if value is None else f"{value:,.0f}ms"


def expected_tools(row: dict) -> list[str]:
    # 정답 도구 : 글자 하나, 또는 같은 사실을 답할 수 있는 READ 여럿의 목록(2026-11-13)
    tool = row["tool"]
    return list(tool) if isinstance(tool, list) else [tool]


def score(row: dict, result: Result) -> dict:
    tool_ok = result.tool in expected_tools(row)
    # 아래 갈래는 정답일 때만 : 고른 도구가 곧 정답 도구
    picked = result.tool
    if not tool_ok:
        args_ok = False
    elif picked in (tools.NAVIGATE, tools.SEARCH_GUIDE):
        args_ok = result.args.get("scr_id") == row.get("scr_id")
    elif picked == tools.DECLINE:
        args_ok = result.args.get("unclear") == row.get("unclear", False)
    elif picked in tools.REGISTER_TOOLS or tools.card_entry(picked) is not None:
        args_ok = all(result.args.get(k) == v for k, v in row.get("args", {}).items())
    else:
        args_ok = True
    # 쓰기 도구 잘못 : 쓰기가 아닌 질문에 쓰기 도구, 또는 쓰기 도구끼리 뒤바뀜
    # 쓰기 도구 = 옛 등록 도구 + 확인 카드(ACTION) 도구 전부
    is_write = result.tool in tools.REGISTER_TOOLS or tools.card_entry(result.tool) is not None
    write_wrong = is_write and not tool_ok
    declined = row["tool"] == tools.DECLINE and result.tool == tools.DECLINE
    return {
        "tool_ok": tool_ok,
        "args_ok": args_ok,
        "write_wrong": write_wrong,
        "declined": declined,
    }


def summary(name: str, rows: list[dict], results: list[Result], scores: list[dict]) -> dict:
    measured = [r for r in results if r.error is None]
    n = len(measured) or 1
    return {
        "name": name,
        "tool_ok": sum(s["tool_ok"] for s in scores),
        "args_ok": sum(s["args_ok"] for s in scores),
        "write_wrong": sum(s["write_wrong"] for s in scores),
        "declined": sum(s["declined"] for s in scores),
        "decline_total": sum(row["tool"] == tools.DECLINE for row in rows),
        "input": sum(r.usage.input for r in measured) / n,
        "cache": sum(r.usage.cache for r in measured) / n,
        "output": sum(r.usage.output for r in measured) / n,
        "ms": statistics.median([r.ms for r in measured]) if measured else 0.0,
        "errors": len(results) - len(measured),
        "text_then_tool": sum(r.text_then_tool for r in results),
        "text_ms": _median([r.text_ms for r in measured]),
        "code_calls": sum(r.code_calls for r in measured) / n,
        "code_turns": sum(bool(r.code_calls) for r in measured),
        "text_then_code": sum(r.text_then_code for r in results),
        "core": _core(rows, results, scores),
        "by_kind": _by_kind(rows, results),
        "by_type": {
            t: sum(s["tool_ok"] for row, s in zip(rows, scores, strict=True) if row["type"] == t)
            for t in TYPES
        },
    }


def _core(rows: list[dict], results: list[Result], scores: list[dict]) -> dict:
    # T01~T44만 : 켜는 기준(정확 36/44·쓰기 잘못 0·지연 중앙값 1,640ms)과 비교
    picked = [
        (result, mark)
        for row, result, mark in zip(rows, results, scores, strict=True)
        if int(row["id"][1:]) <= CORE
    ]
    measured = [result for result, _ in picked if result.error is None]
    return {
        "total": len(picked),
        "tool_ok": sum(mark["tool_ok"] for _, mark in picked),
        "write_wrong": sum(mark["write_wrong"] for _, mark in picked),
        "ms": statistics.median([r.ms for r in measured]) if measured else 0.0,
        "first_ms": _median([r.first_ms for r in measured]),
        "decide_ms": _median([r.decide_ms for r in measured]),
    }


def _by_kind(rows: list[dict], results: list[Result]) -> dict:
    # 고른 도구 종류별 : 문항 수, 첫 블록·고르기 끝·전체 지연 중앙값(전체 문항·T01~T44)
    out: dict[str, dict] = {}
    for scope, core_only in (("all", False), ("core", True)):
        groups: dict[str, list[Result]] = {}
        for row, result in zip(rows, results, strict=True):
            if result.error is not None or (core_only and int(row["id"][1:]) > CORE):
                continue
            groups.setdefault(tool_kind(result.tool), []).append(result)
        out[scope] = {
            kind: {
                "count": len(group),
                "first_ms": _median([r.first_ms for r in group]),
                "decide_ms": _median([r.decide_ms for r in group]),
                "ms": statistics.median([r.ms for r in group]),
            }
            for kind, group in sorted(groups.items())
        }
    return out


def print_tables(rows: list[dict], sums: list[dict]) -> None:
    total = len(rows)
    print(
        "| 흐름 | 도구 정확 | 인자까지 정확 | 쓰기 도구 잘못 | 범위 밖 거절 "
        "| 판정 토큰 평균 입력(캐시)/출력 | 판정 지연 중앙값 |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for s in sums:
        tokens = f"{s['input']:,.0f}({s['cache']:,.0f}) / {s['output']:,.0f}"
        error = f" (오류 {s['errors']})" if s["errors"] else ""
        print(
            f"| {s['name']}{error} | {s['tool_ok']}/{total} | {s['args_ok']}/{total} "
            f"| {s['write_wrong']} | {s['declined']}/{s['decline_total']} "
            f"| {tokens} | {s['ms']:,.0f}ms |"
        )
    print()
    print(
        f"| 흐름 | T01~T{CORE} 도구 정확 | 쓰기 도구 잘못 | 판정 지연 중앙값 "
        "| 첫 블록 중앙값 | 고르기 끝 중앙값 | 글 뒤 도구 |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for s in sums:
        core = s["core"]
        print(
            f"| {s['name']} | {core['tool_ok']}/{core['total']} | {core['write_wrong']} "
            f"| {core['ms']:,.0f}ms | {_ms(core['first_ms'])} | {_ms(core['decide_ms'])} "
            f"| {s['text_then_tool']} |"
        )
    if any(s["code_turns"] or s["text_ms"] is not None for s in sums):
        print()
        print("| 흐름 | 첫 글자 중앙값 | 코드 쓴 문항 | 코드 안 호출 평균 | 글 뒤 코드 |")
        print("| --- | --- | --- | --- | --- |")
        for s in sums:
            print(
                f"| {s['name']} | {_ms(s['text_ms'])} | {s['code_turns']}/{total} "
                f"| {s['code_calls']:.2f} | {s['text_then_code']} |"
            )
    for s in sums:
        for scope, label in (("all", "전체"), ("core", f"T01~T{CORE}")):
            print()
            print(f"{s['name']} 고른 도구 종류별 ({label})")
            print("| 종류 | 문항 | 첫 블록 중앙값 | 고르기 끝 중앙값 | 판정 지연 중앙값 |")
            print("| --- | --- | --- | --- | --- |")
            for kind, k in s["by_kind"][scope].items():
                print(
                    f"| {kind} | {k['count']} | {_ms(k['first_ms'])} "
                    f"| {_ms(k['decide_ms'])} | {k['ms']:,.0f}ms |"
                )
    print()
    print("| 유형 | 문항 | " + " | ".join(s["name"] for s in sums) + " |")
    print("| --- | --- | " + " | ".join("---" for _ in sums) + " |")
    for t in TYPES:
        count = sum(row["type"] == t for row in rows)
        print(f"| {t} | {count} | " + " | ".join(str(s["by_type"][t]) for s in sums) + " |")


class _EmptyReader(FakeEvalReader):
    """경로에 이 말이 든 READ는 빈 목록 : 조건 쓰기의 '없으면 글' 꼴"""

    def __init__(self, empty: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.empty = empty

    async def read(self, path: str, params: dict, body: dict | None = None) -> object:
        if any(word in path for word in self.empty):
            self.calls.append((path, params))
            return []
        return await super().read(path, params, body)


@dataclass
class AgentRun:
    # 고른 도구 차례(첫 고르기·같은 응답 여럿·결과 뒤), 끝(글·카드:도구·판정), 턴 태그
    steps: list[str]
    end: str
    tags: list[str] = field(default_factory=list)
    ms: float = 0.0
    usage: Usage = field(default_factory=Usage)
    error: str | None = None
    # ③ : 첫 멈춤에 done.pending을 줄지(rules.agent_pending), 이어 간 횟수
    pending: bool = False
    continued: int = 0


def agent_cards(judged: service.Judged) -> list[dict]:
    """멈춘 카드의 {tool, input} : ACTION이면 첫 카드 + 이어 고른 카드, READ 뒤 카드면 그 카드"""
    if judged.intent.kind is IntentKind.ACTION and judged.tool:
        first = {"tool": judged.tool, "input": judged.action or {}}
        return [first, *({"tool": tool, "input": values} for tool, values, _ in judged.more)]
    return [{"tool": card.tool, "input": card.values} for card in judged.cards or []]


def agent_end(judged: service.Judged) -> str:
    if judged.intent.kind is IntentKind.ACTION and judged.tool:
        return CARD_END + judged.tool
    if judged.cards:
        return CARD_END + judged.cards[0].tool
    if judged.intent.kind is IntentKind.SEARCH:
        return "글"
    return judged.intent.kind.value


async def run_agent(client, model: str, row: dict, today: date) -> AgentRun:
    usage = Usage()
    agent = AnthropicToolAgent(client, model, on_usage=lambda _task, u: usage.add(u))
    ai = get_ai_settings()
    limits = get_settings()
    reader = _EmptyReader(tuple(row.get("empty", ())))
    pets = FakeEvalPets()
    trace = service._Trace()
    deps = service.ReadDeps(reader=reader, contexts=pets, trace=trace)
    context = [{"role": "user", "content": row["q"]}]
    record = turnlog.start(0, row["q"], None)
    started = time.monotonic()
    error = None
    end = "오류"
    pending = False
    continued = 0
    sec = limits.answer_first_token_sec
    try:
        judged = await service.judge_tools(
            row["q"], context, agent, ai.max_tokens, today, sec, read=deps
        )
        await _drain(judged)
        end = agent_end(judged)
        # 에이전트 ④ : 첫 멈춤 카드 수로 남은 일 판정(service._pending과 같은 규칙)
        first = agent_cards(judged)
        pending = bool(first) and rules.agent_pending(row["q"], len(first))
        notes: list[str] = []
        fixed = False
        for stop in row.get("results", []) if pending else []:
            cards = agent_cards(judged)
            if not cards or not end.startswith(CARD_END):
                break
            calls = trace.follow.calls if trace.follow is not None else trace.used + 1
            calls += len(judged.more)
            state = agentstate.AgentState(
                room=0,
                q=0,
                said=row["q"],
                left=TOOL_LIMIT - calls,
                seen={name: sorted(ids) for name, ids in trace.seen().items()},
                notes=[*notes, *trace.notes],
                cards=cards,
                done=list(trace.done),
                fixed=fixed,
            )
            results = [
                AgentResult.model_validate({"tool": card["tool"], **result})
                for card, result in zip(cards, stop, strict=False)
            ]
            carry = service.agent_carry(state, results)
            continued += 1
            if carry.stop or state.left <= 0:
                end = STOP_END
                break
            notes = carry.notes_list
            fixed = carry.fixed
            trace = service._trace_of(carry)
            deps = service.ReadDeps(reader=reader, contexts=pets, trace=trace)
            judged = await service.judge_tools(
                row["q"], context, agent, ai.max_tokens, today, sec, read=deps, carry=carry
            )
            await _drain(judged)
            end = agent_end(judged)
    except Exception as failure:
        error = type(failure).__name__
    turnlog.finish(record)
    ms = (time.monotonic() - started) * 1000
    run = AgentRun(list(record.tools), end, list(record.tags), ms, usage, error)
    run.pending = pending
    run.continued = continued
    return run


async def _drain(judged: service.Judged) -> None:
    if judged.stream is not None:
        async for _ in judged.stream:
            pass


def _matches(want: str | list[str], got: str) -> bool:
    return got in want if isinstance(want, list) else got == want


def _in_order(expected: list, steps: list[str]) -> bool:
    rest = iter(steps)
    return all(any(_matches(want, got) for got in rest) for want in expected)


def _is_write(name: str) -> bool:
    return name in tools.REGISTER_TOOLS or tools.card_entry(name) is not None


def score_agent(row: dict, run: AgentRun) -> dict:
    # 정답 : 끝이 같고 기대 도구가 모두 나옴(ordered면 그 차례로). 다른 도구를 더 읽어도 정답
    # 쓰기 잘못 : 기대한 카드가 아닌 쓰기 도구를 고름(말하지 않은 쓰기)
    expected = row["steps"]
    present = all(any(_matches(want, got) for got in run.steps) for want in expected)
    steps_ok = present and (not row.get("ordered") or _in_order(expected, run.steps))
    end_ok = run.end == row["end"]
    want_card = row["end"].removeprefix(CARD_END) if row["end"].startswith(CARD_END) else None
    # ③ 쓰기 꼴 : 행의 writes는 이 턴에 고를 수 있는 쓰기 도구(이어 가기 전 카드 등)
    allowed = {want_card, *row.get("writes", ())}
    wrong = [name for name in run.steps if _is_write(name) and name not in allowed]
    # pending 기대가 있으면(단순 명령은 false) 같아야 정답
    pending_ok = "pending" not in row or run.pending == row["pending"]
    return {
        "ok": run.error is None and end_ok and steps_ok and pending_ok,
        "end_ok": end_ok,
        "steps_ok": steps_ok,
        "write_wrong": len(wrong),
        "limited": turnlog.AGENT_LIMIT in run.tags,
    }


def agent_summary(name: str, runs: list[AgentRun], scores: list[dict]) -> dict:
    total = len(runs)
    ok = sum(s["ok"] for s in scores)
    measured = [run.ms for run in runs if run.error is None]
    rate = ok / total if total else 0.0
    write_wrong = sum(s["write_wrong"] for s in scores)
    return {
        "name": name,
        "total": total,
        "ok": ok,
        "rate": rate,
        "write_wrong": write_wrong,
        "limited": sum(s["limited"] for s in scores),
        "errors": sum(run.error is not None for run in runs),
        "ms": statistics.median(measured) if measured else 0.0,
        "passed": rate >= AGENT_PASS and write_wrong == 0,
    }


def print_agent_table(sums: list[dict]) -> None:
    print(
        f"| 흐름 | 다단계 정답 | 쓰기 잘못 | 상한 걸림 | 오류 | 턴 시간 중앙값 "
        f"| 기준({AGENT_PASS:.0%}·쓰기 잘못 0) |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for s in sums:
        mark = "넘음" if s["passed"] else "못 넘음"
        print(
            f"| {s['name']} | {s['ok']}/{s['total']} ({s['rate']:.0%}) | {s['write_wrong']} "
            f"| {s['limited']} | {s['errors']} | {s['ms']:,.0f}ms | {mark} |"
        )


async def agent_main(client, options) -> None:
    rows = []
    for path in (AGENT_DATA, AGENT_WRITE_DATA):
        text = path.read_text(encoding="utf-8")
        rows += [json.loads(line) for line in text.splitlines() if line]
    if options.only:
        only = set(options.only.split(","))
        rows = [row for row in rows if row["id"] in only]
    models = [get_settings().llm_model] + ([SONNET] if options.sonnet else [])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"agent-{datetime.now():%Y%m%d-%H%M%S-%f}{off_tag(options.off)}.jsonl"
    sums = []
    with out.open("w", encoding="utf-8") as file:
        for model in models:
            name = f"에이전트 {model}"
            runs, scores = [], []
            for row in rows:
                run = await run_agent(client, model, row, AGENT_TODAY)
                mark = score_agent(row, run)
                runs.append(run)
                scores.append(mark)
                status = "O" if mark["ok"] else "X"
                print(f"[{name}] {row['id']} {status} {' → '.join(run.steps) or '-'} ⇒ {run.end}")
                record = {
                    "flow": name,
                    "id": row["id"],
                    "steps": run.steps,
                    "end": run.end,
                    "expected": {"steps": row["steps"], "end": row["end"]},
                    "tags": run.tags,
                    "ms": round(run.ms),
                    "error": run.error,
                    "off": list(options.off),
                    **mark,
                }
                file.write(json.dumps(record, ensure_ascii=False) + "\n")
            sums.append(agent_summary(name, runs, scores))
    print()
    print(off_line(options.off))
    print_agent_table(sums)
    print(f"\n문항별 결과: {out}")


def _history(row: dict) -> tuple[str, ...]:
    return tuple(row.get("history", ()))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sonnet", action="store_true", help="도구 흐름을 Sonnet 5.5로도 잰다")
    parser.add_argument("--answer", action="store_true", help="글 답변 본문을 결과 파일에 남긴다")
    parser.add_argument("--only", help="이 문항만 잰다(쉼표로 구분, 예: T01,T05)")
    parser.add_argument("--core", action="store_true", help=f"T01~T{CORE}만 잰다")
    parser.add_argument(
        "--ptc",
        nargs="?",
        const=tools.PTC_CODE,
        choices=(tools.PTC_CODE, tools.PTC_BOTH),
        help="프로그래밍식 도구 호출을 지금 방식과 나란히(가짜 Java 읽기). code(기본)·both",
    )
    parser.add_argument(
        "--agent", action="store_true", help="에이전트 다단계 세트(agent_eval.jsonl)를 잰다"
    )
    parser.add_argument(
        "--off",
        type=off_names,
        default=(),
        help=f"이 지름길을 끄고 잰다(쉼표로 구분: {', '.join(OFF_NAMES)})",
    )
    options = parser.parse_args()
    with shortcuts_off(options.off):
        await _measure(options)


async def _measure(options) -> None:
    settings = get_settings()
    client = get_anthropic_client(settings)
    tools.use_catalog(fake_catalog())
    if options.agent:
        await agent_main(client, options)
        return
    print("도구 순서:", ", ".join(d["name"] for d in tools.tool_definitions()))
    rows = [json.loads(line) for line in DATA.read_text(encoding="utf-8").splitlines() if line]
    if options.only:
        only = set(options.only.split(","))
        rows = [row for row in rows if row["id"] in only]
    if options.core:
        rows = [row for row in rows if int(row["id"][1:]) <= CORE]
    today = rules.today_kst()

    read = options.ptc is not None
    model = settings.llm_model
    flows = [
        (
            f"도구 {model}",
            lambda row: run_tools(
                client,
                model,
                row["q"],
                today,
                options.answer,
                read=read,
                history=_history(row),
                card=row.get("card"),
            ),
        ),
    ]
    if options.ptc is not None:
        mode = options.ptc
        flows.append(
            (
                f"PTC({mode}) {model}",
                lambda row: run_tools(
                    client,
                    model,
                    row["q"],
                    today,
                    options.answer,
                    ptc=mode,
                    read=True,
                    history=_history(row),
                    card=row.get("card"),
                ),
            )
        )
    if options.sonnet:
        flows.append(
            (
                f"도구 {SONNET}",
                lambda row: run_tools(
                    client,
                    SONNET,
                    row["q"],
                    today,
                    options.answer,
                    read=read,
                    history=_history(row),
                    card=row.get("card"),
                ),
            )
        )

    if options.sonnet and options.ptc is not None:
        # 추가-1 (2026-11-26) : Sonnet 5.5의 PTC 흐름도
        sonnet_mode = options.ptc
        flows.append(
            (
                f"PTC({sonnet_mode}) {SONNET}",
                lambda row: run_tools(
                    client,
                    SONNET,
                    row["q"],
                    today,
                    options.answer,
                    ptc=sonnet_mode,
                    read=True,
                    history=_history(row),
                    card=row.get("card"),
                ),
            )
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # 같은 초에 여럿 돌려도 덮어쓰지 않게 마이크로초까지(2026-11-20)
    out = OUT_DIR / f"{datetime.now():%Y%m%d-%H%M%S-%f}{off_tag(options.off)}.jsonl"
    sums = []
    with out.open("w", encoding="utf-8") as file:
        for name, run in flows:
            results, scores = [], []
            for row in rows:
                result = await run(row)
                mark = score(row, result)
                results.append(result)
                scores.append(mark)
                status = "O" if mark["args_ok"] else ("△" if mark["tool_ok"] else "X")
                print(f"[{name}] {row['id']} {status} {result.tool} {result.args or ''}")
                record = {
                    "flow": name,
                    "id": row["id"],
                    "expected": row["tool"],
                    "tool": result.tool,
                    "args": result.args,
                    "ms": round(result.ms),
                    "first_ms": None if result.first_ms is None else round(result.first_ms),
                    "decide_ms": None if result.decide_ms is None else round(result.decide_ms),
                    "error": result.error,
                    "text_ms": None if result.text_ms is None else round(result.text_ms),
                    "code_calls": result.code_calls,
                    "code_tools": result.code_tools,
                    "text_then_code": result.text_then_code,
                    "off": list(options.off),
                    **mark,
                }
                if result.answer is not None:
                    record["answer"] = result.answer
                file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            sums.append(summary(name, rows, results, scores))
    print()
    print(off_line(options.off))
    print_tables(rows, sums)
    print(f"\n문항별 결과: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
