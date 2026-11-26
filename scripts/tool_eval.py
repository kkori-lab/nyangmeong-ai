"""tool calling 1단계 평가(docs/design/tool-calling.md 7-1절). 실제 Anthropic 호출(비용이 든다)

돌리기: uv run python -m scripts.tool_eval [--sonnet] [--answer] [--only T01,T05]
        [--ptc [code|both]]
- 도구 흐름(service.judge_tools)을 잰다(옛 판정 service.judge는 2026-11-11 삭제)
- 도구 목록 : 테스트와 같은 가짜 Java 목록(스냅샷 + 코드 값), Java는 부르지 않는다
- 문항별 결과 : .cache/tool_eval/<시각>.jsonl (git 제외)
- --ptc (2026-11-26) : 프로그래밍식 도구 호출 시험. 지금 방식과 PTC를 가짜 Java 읽기
  (fakes.FakeEvalReader, 반려동물 10마리)로 나란히 잰다.
  code는 읽기 도구를 코드에서만, both는 direct·코드 둘 다
pytest 수집 제외(tests/ 밖), 테스트·CI에서 미호출(AGENTS.md 5번)
"""

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.chat import rules, service, tools, turnlog
from app.chat.clients import AnthropicToolAgent, ToolDecision, _code_calls
from app.chat.repository import get_ai_settings
from app.chat.schemas import IntentKind
from app.core.config import get_settings
from app.core.llm import get_anthropic_client
from tests.chat.fakes import FakeEvalPets, FakeEvalReader, fake_catalog

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tests/chat/data/tool_eval.jsonl"
OUT_DIR = ROOT / ".cache/tool_eval"
SONNET = "claude-sonnet-5-5"
# 도구 고르기 기준 문항(tool-calling.md 7-1절 4회차 판정) : T01~T44
CORE = 44
TYPES = ("사용법", "이동", "일정", "케어", "지식", "범위밖", "헷갈림", "수정", "조합")


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
) -> Result:
    # 도구 흐름 판정 그대로. 글 답변 스트림은 끝까지 읽어 지연·토큰에 넣는다(1회차와 같은 셈)
    # read 없음 : READ는 Java 없이 실행 안 하므로 고른 READ 이름으로,
    # ACTION은 카드 도구 이름·LLM 인자로
    # read 있음(--ptc) : 가짜 Java 읽기로 READ·코드 안 READ까지 실행(답변 지연·토큰 포함)
    # history : 문항 앞의 답 없는 회원 질문들(이력에 질문이 둘인 경우, 2026-11-26)
    usage = Usage()
    agent = _DecisionRecorder(client, model, on_usage=lambda _task, u: usage.add(u), ptc=ptc)
    ai = get_ai_settings()
    limits = get_settings()
    deps = service.ReadDeps(reader=FakeEvalReader(), contexts=FakeEvalPets()) if read else None
    context = [{"role": "user", "content": text} for text in (*history, q)]
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
    options = parser.parse_args()

    settings = get_settings()
    client = get_anthropic_client(settings)
    tools.use_catalog(fake_catalog())
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
                client, model, row["q"], today, options.answer, read=read, history=_history(row)
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
                ),
            )
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # 같은 초에 여럿 돌려도 덮어쓰지 않게 마이크로초까지(2026-11-20)
    out = OUT_DIR / f"{datetime.now():%Y%m%d-%H%M%S-%f}.jsonl"
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
                    **mark,
                }
                if result.answer is not None:
                    record["answer"] = result.answer
                file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            sums.append(summary(name, rows, results, scores))
    print()
    print_tables(rows, sums)
    print(f"\n문항별 결과: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
