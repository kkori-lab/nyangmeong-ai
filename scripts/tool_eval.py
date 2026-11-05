"""tool calling 1단계 평가(docs/design/tool-calling.md 7-1절). 실제 Anthropic 호출(비용이 든다)

돌리기: uv run python -m scripts.tool_eval [--sonnet] [--answer]
- 지금 흐름(service.judge)과 도구 흐름(service.judge_tools)을 같은 세트로 잰다
- 도구 목록 : 테스트와 같은 가짜 Java 목록(스냅샷 + 코드 값), Java는 부르지 않는다
- 문항별 결과 : .cache/tool_eval/<시각>.jsonl (git 제외)
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

from app.chat import rules, service, tools
from app.chat.clients import (
    AnthropicIntentClassifier,
    AnthropicRegisterExtractor,
    AnthropicToolAgent,
    ClassifyError,
)
from app.chat.repository import get_ai_settings
from app.chat.schemas import IntentKind
from app.core.config import get_settings
from app.core.llm import get_anthropic_client
from tests.chat.fakes import fake_catalog

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tests/chat/data/tool_eval.jsonl"
OUT_DIR = ROOT / ".cache/tool_eval"
SONNET = "claude-sonnet-5-5"
TYPES = ("사용법", "이동", "일정", "케어", "지식", "범위밖", "헷갈림")


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


class _RecordingMessages:
    # 지금 흐름 분류기의 토큰 집계용 : messages.parse 응답의 usage를 기록
    def __init__(self, messages: Any, usage: Usage) -> None:
        self._messages = messages
        self._usage = usage

    async def parse(self, **kwargs):
        response = await self._messages.parse(**kwargs)
        self._usage.add(response.usage)
        return response


class _RecordingClient:
    def __init__(self, client: Any, usage: Usage) -> None:
        self.messages = _RecordingMessages(client.messages, usage)


def _register_kind(values: dict) -> str:
    return tools.DRAFT_CARE_ITEM if values.get("care_zone_cd") else tools.DRAFT_SCHEDULE


def _search_tool(judged: service.Judged) -> tuple[str, dict]:
    if judged.guide_ids:
        scr_id = judged.shortcut.scr_id if judged.shortcut else None
        return tools.SEARCH_GUIDE, {"scr_id": scr_id}
    return "answer", {}


async def run_current(client, model: str, q: str, today) -> Result:
    # 7-1절 대응표 : ROUTE → navigate, 안내서 SEARCH → search_guide, 그 밖 SEARCH → 글 답변,
    # REGISTER → 카드 종류, FALLBACK → decline
    usage = Usage()
    classifier = AnthropicIntentClassifier(_RecordingClient(client, usage), model)  # type: ignore[arg-type]
    started = time.monotonic()
    try:
        judged = await service.judge(q, False, classifier)
    except ClassifyError as error:
        return Result("error", usage=usage, error=error.reason)
    ms = (time.monotonic() - started) * 1000
    kind = judged.intent.kind
    if kind is IntentKind.ROUTE:
        return Result(tools.NAVIGATE, {"scr_id": judged.intent.scr_id}, usage, ms)
    if kind is IntentKind.SEARCH:
        name, args = _search_tool(judged)
        return Result(name, args, usage, ms)
    if kind is IntentKind.REGISTER:
        # build_card와 같은 길 : 규칙 추출 → 필수 칸이 비면 AI 추출(판정 토큰·지연에는 안 셈)
        values = rules.parse_register(q, today, []).values()
        if service._missing(values):
            raw = await AnthropicRegisterExtractor(client, model).extract(q, today)
            for name, value in rules.clean_ai_fields(raw).values().items():
                values.setdefault(name, value)
        return Result(_register_kind(values), values, usage, ms)
    return Result(tools.DECLINE, {"unclear": not judged.out_of_scope}, usage, ms)


async def run_tools(client, model: str, q: str, today, keep_answer: bool) -> Result:
    # 도구 흐름 판정 그대로. 글 답변 스트림은 끝까지 읽어 지연·토큰에 넣는다(1회차와 같은 셈)
    usage = Usage()
    agent = AnthropicToolAgent(client, model, on_usage=lambda _task, u: usage.add(u))
    ai = get_ai_settings()
    limits = get_settings()
    started = time.monotonic()
    try:
        judged = await service.judge_tools(
            q,
            [{"role": "user", "content": q}],
            agent,
            ai.max_tokens,
            today,
            limits.answer_first_token_sec,
        )
        text = None
        if judged.stream is not None:
            parts = [part async for part in judged.stream]
            text = "".join(parts)
    except Exception as error:
        return Result("error", usage=usage, error=type(error).__name__)
    ms = (time.monotonic() - started) * 1000
    answer = text if keep_answer else None
    kind = judged.intent.kind
    if kind is IntentKind.ROUTE:
        return Result(tools.NAVIGATE, {"scr_id": judged.intent.scr_id}, usage, ms, answer)
    if kind is IntentKind.SEARCH:
        name, args = _search_tool(judged)
        return Result(name, args, usage, ms, answer)
    if kind is IntentKind.REGISTER:
        values = judged.ai_values or {}
        return Result(judged.tool or _register_kind(values), values, usage, ms, answer)
    return Result(tools.DECLINE, {"unclear": not judged.out_of_scope}, usage, ms, answer)


def score(row: dict, result: Result) -> dict:
    tool_ok = result.tool == row["tool"]
    if not tool_ok:
        args_ok = False
    elif row["tool"] in (tools.NAVIGATE, tools.SEARCH_GUIDE):
        args_ok = result.args.get("scr_id") == row.get("scr_id")
    elif row["tool"] == tools.DECLINE:
        args_ok = result.args.get("unclear") == row.get("unclear", False)
    elif row["tool"] in tools.REGISTER_TOOLS:
        args_ok = all(result.args.get(k) == v for k, v in row.get("args", {}).items())
    else:
        args_ok = True
    # 쓰기 도구 잘못 : 등록이 아닌 질문에 등록 도구, 또는 일정↔케어 뒤바뀜
    write_wrong = result.tool in tools.REGISTER_TOOLS and not tool_ok
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
        "by_type": {
            t: sum(s["tool_ok"] for row, s in zip(rows, scores, strict=True) if row["type"] == t)
            for t in TYPES
        },
    }


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
    print("| 유형 | 문항 | " + " | ".join(s["name"] for s in sums) + " |")
    print("| --- | --- | " + " | ".join("---" for _ in sums) + " |")
    for t in TYPES:
        count = sum(row["type"] == t for row in rows)
        print(f"| {t} | {count} | " + " | ".join(str(s["by_type"][t]) for s in sums) + " |")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sonnet", action="store_true", help="도구 흐름을 Sonnet 5.5로도 잰다")
    parser.add_argument("--answer", action="store_true", help="글 답변 본문을 결과 파일에 남긴다")
    options = parser.parse_args()

    settings = get_settings()
    client = get_anthropic_client(settings)
    tools.use_catalog(fake_catalog())
    print("도구 순서:", ", ".join(d["name"] for d in tools.tool_definitions()))
    rows = [json.loads(line) for line in DATA.read_text(encoding="utf-8").splitlines() if line]
    today = rules.today_kst()

    flows = [
        (
            f"지금 흐름({settings.llm_model})",
            lambda q: run_current(client, settings.llm_model, q, today),
        ),
        (
            f"도구 {settings.llm_model}",
            lambda q: run_tools(client, settings.llm_model, q, today, options.answer),
        ),
    ]
    if options.sonnet:
        flows.append(
            (f"도구 {SONNET}", lambda q: run_tools(client, SONNET, q, today, options.answer))
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    sums = []
    with out.open("w", encoding="utf-8") as file:
        for name, run in flows:
            results, scores = [], []
            for row in rows:
                result = await run(row["q"])
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
                    "error": result.error,
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
