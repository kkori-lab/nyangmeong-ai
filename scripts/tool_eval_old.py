"""도구 고르기 평가(tool calling 1단계 실험). 실제 Anthropic API를 부른다
(.env.local의 LLM_API_KEY, 비용이 든다)

같은 질문 세트로 지금 흐름(`service.judge` + 등록 카드)과 도구 흐름(`service.judge_tools`,
Haiku·Sonnet)을 돌려 도구 정확도·인자 정확도·쓰기 도구 잘못 고른 수·범위 밖 거절·판정 토큰·지연을
표로 낸다. 지금 흐름의 판정은 도구 이름으로 환산한다(docs/design/tool-calling.md 6절 대응표).
문항별 결과는 .cache/tool_eval/.

돌리기: uv run python -m scripts.tool_eval [세트 이름, 기본 tool_eval] [--no-sonnet] [--answer]
--answer : search_guide 뒤 답변 호출까지 돌림. 기본은 판정만
(글 답변은 판정 호출과 같은 호출이라 항상 받음)
pytest 수집 제외(tests/ 밖), 테스트·CI에서 미호출(AGENTS.md 5번)
"""

import asyncio
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from app.chat import rules, service, tools
from app.chat.clients import (
    AnthropicIntentClassifier,
    AnthropicRegisterExtractor,
    AnthropicToolAgent,
    get_anthropic_client,
)
from app.chat.repository import PetInfo, get_ai_settings
from app.chat.schemas import IntentKind
from app.core.config import get_settings

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "chat" / "data"
OUT = ROOT / ".cache" / "tool_eval"
SONNET = "claude-sonnet-5-5"
WRITE_TOOLS = tools.REGISTER_TOOLS
# 첫 글자 제한 대신 넉넉히 : 평가는 시간 초과 아닌 판정을 잼
DECIDE_LIMIT_SEC = 60.0
PETS = [PetInfo(1, "초코"), PetInfo(2, "뭉치")]


class Pets:
    async def get_pets(self) -> list[PetInfo]:
        return PETS


@dataclass
class Pick:
    tool: str = ""
    scr_id: str | None = None
    args: dict = field(default_factory=dict)
    unclear: bool | None = None
    ms: float = 0.0
    # 판정 호출의 토큰(입력·캐시 읽기·캐시 쓰기·출력), 호출이 여럿이면 합
    usage: dict = field(default_factory=lambda: defaultdict(int))
    answer: str = ""
    error: str = ""


def _add(usage: dict, raw) -> None:
    usage["input"] += raw.input_tokens
    usage["cache_read"] += raw.cache_read_input_tokens or 0
    usage["cache_write"] += raw.cache_creation_input_tokens or 0
    usage["output"] += raw.output_tokens
    usage["calls"] += 1


def _chunk_scr(chunk_id: str | None) -> str | None:
    chunk = rules.find_guide(chunk_id)
    row = next((r for r in rules.routing_table() if chunk and r.no == chunk.num), None)
    return row.scr_id if row else None


async def _card_pick(pick: Pick, text: str, deps: service.RegisterDeps, ai_values) -> None:
    card = await service.build_card(text, 1, None, deps, ai_values)
    if card is None:
        pick.tool = "draft_schedule"
        return
    pick.tool = "draft_care_item" if card.care_zone_cd else "draft_schedule"
    keys = ("schdl_knd_cd", "care_zone_cd", "care_cycle_cd")
    pick.args = {key: getattr(card, key) for key in keys if getattr(card, key)}


async def _to_pick(pick: Pick, judged: service.Judged, text: str, deps, with_answer: bool) -> None:
    kind = judged.intent.kind
    if kind is IntentKind.ROUTE:
        pick.tool, pick.scr_id = "navigate", judged.intent.scr_id
    elif kind is IntentKind.SEARCH and judged.guide_ids:
        pick.tool, pick.scr_id = "search_guide", _chunk_scr(judged.guide_ids[0])
        if judged.stream is not None and with_answer:
            pick.answer = "".join([t async for t in judged.stream])
    elif kind is IntentKind.SEARCH:
        pick.tool = "answer"
        if judged.stream is not None:
            pick.answer = "".join([t async for t in judged.stream])
    elif kind is IntentKind.REGISTER:
        await _card_pick(pick, text, deps, judged.ai_values)
    else:
        pick.tool, pick.unclear = "decline", not judged.out_of_scope


class Runner:
    """흐름 하나(지금·도구+모델)의 문항별 판정"""

    def __init__(self, name: str, model: str, tool_flow: bool, with_answer: bool):
        self.name = name
        self.tool_flow = tool_flow
        self.with_answer = with_answer
        self.current: Pick | None = None
        settings = get_settings()
        client = get_anthropic_client(settings)
        if not tool_flow:
            # 분류·추출(parse) 응답의 usage를 지금 문항에
            original = client.messages.parse

            async def parse(*args, **kwargs):
                response = await original(*args, **kwargs)
                _add(self.current.usage, response.usage)
                return response

            self.client = _Patched(client, parse)
            self.classifier = AnthropicIntentClassifier(self.client, model)
            extractor = AnthropicRegisterExtractor(self.client, model)
        else:
            self.agent = AnthropicToolAgent(
                client, model, on_usage=lambda task, raw: _add(self.current.usage, raw)
            )
            extractor = AnthropicRegisterExtractor(client, model)
        self.deps = service.RegisterDeps(Pets(), extractor, rules.today_kst())

    async def run(self, text: str) -> Pick:
        pick = self.current = Pick()
        started = time.monotonic()
        try:
            if self.tool_flow:
                ai = get_ai_settings()
                context = [{"role": "user", "content": text}]
                judged = await service.judge_tools(
                    text, context, self.agent, ai.max_tokens, self.deps.today, DECIDE_LIMIT_SEC
                )
            else:
                judged = await service.judge(text, False, self.classifier)
            pick.ms = (time.monotonic() - started) * 1000
            await _to_pick(pick, judged, text, self.deps, self.with_answer)
        except Exception as error:
            pick.error = type(error).__name__
        return pick


class _Patched:
    """messages.parse만 바꾼 Anthropic 클라이언트 대리"""

    def __init__(self, client, parse):
        self._client = client
        self.messages = _Messages(client.messages, parse)

    def __getattr__(self, name):
        return getattr(self._client, name)


class _Messages:
    def __init__(self, messages, parse):
        self._messages = messages
        self.parse = parse

    def __getattr__(self, name):
        return getattr(self._messages, name)


def tool_ok(q: dict, pick: Pick) -> bool:
    return pick.tool == q["tool"]


def arg_ok(q: dict, pick: Pick) -> bool:
    if not tool_ok(q, pick):
        return False
    if q["tool"] in ("navigate", "search_guide"):
        return pick.scr_id == q.get("scr_id")
    if q["tool"] in WRITE_TOOLS:
        return all(pick.args.get(key) == value for key, value in (q.get("args") or {}).items())
    if q["tool"] == "decline" and "unclear" in q:
        return pick.unclear == q["unclear"]
    return True


def wrong_write(q: dict, pick: Pick) -> bool:
    # 가장 중요 : 쓰기 도구가 아닌 문항에 등록 카드, 또는 일정 ↔ 케어 항목 뒤바뀜
    return pick.tool in WRITE_TOOLS and pick.tool != q["tool"]


def _avg_tokens(picks: list[Pick]) -> str:
    used = [p.usage for p in picks if p.usage.get("calls")]
    if not used:
        return "—"
    n = len(picks)
    total_in = sum(u["input"] + u["cache_read"] + u["cache_write"] for u in used) / n
    cached = sum(u["cache_read"] for u in used) / n
    out = sum(u["output"] for u in used) / n
    return f"{total_in:.0f}(캐시 {cached:.0f}) / {out:.0f}"


def report(questions: list[dict], results: dict[str, list[Pick]]) -> str:
    n = len(questions)
    lines = [
        "| 흐름 | 도구 정확 | 인자까지 정확 | 쓰기 도구 잘못 | 범위 밖·판단 못 함 거절 "
        "| 오류 | 판정 토큰 평균 입력(캐시)/출력 | 판정 지연 중앙값 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    declines = [i for i, q in enumerate(questions) if q["tool"] == "decline"]
    for name, picks in results.items():
        pairs = list(zip(questions, picks, strict=True))
        ms = sorted(p.ms for p in picks if not p.error)
        median = f"{ms[len(ms) // 2]:.0f}ms" if ms else "—"
        lines.append(
            f"| {name} | {sum(tool_ok(q, p) for q, p in pairs)}/{n} "
            f"| {sum(arg_ok(q, p) for q, p in pairs)}/{n} "
            f"| {sum(wrong_write(q, p) for q, p in pairs)} "
            f"| {sum(picks[i].tool == 'decline' for i in declines)}/{len(declines)} "
            f"| {sum(bool(p.error) for p in picks)} | {_avg_tokens(picks)} | {median} |"
        )
    lines += ["", "유형별 도구 정확", "", "| 유형 | 문항 | " + " | ".join(results) + " |"]
    lines.append("| --- | --- |" + " --- |" * len(results))
    types: dict[str, list[int]] = defaultdict(list)
    for i, q in enumerate(questions):
        types[q["type"]].append(i)
    for name, idx in types.items():
        cells = [
            str(sum(tool_ok(questions[i], picks[i]) for i in idx)) for picks in results.values()
        ]
        lines.append(f"| {name} | {len(idx)} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _show(pick: Pick) -> str:
    if pick.error:
        return f"오류 {pick.error}"
    extra = pick.scr_id or (json.dumps(pick.args, ensure_ascii=False) if pick.args else "")
    if pick.unclear is not None:
        extra = f"unclear={pick.unclear}"
    return f"{pick.tool} {extra}".strip()


def details(name: str, questions: list[dict], results: dict[str, list[Pick]], table: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}-{datetime.now():%Y%m%d-%H%M}.md"
    parts = [f"# {name} 평가 결과 ({date.today()})\n", table, ""]
    for i, q in enumerate(questions):
        expected = q["tool"] + " " + (q.get("scr_id") or json.dumps(q.get("args") or {}))
        parts.append(f"## {q['id']} [{q['type']}] {q['q']}\n- 정답: {expected}")
        for flow, picks in results.items():
            pick = picks[i]
            mark = "O" if arg_ok(q, pick) else ("△" if tool_ok(q, pick) else "X")
            parts.append(f"- {flow}: {mark} {_show(pick)}")
            if pick.answer:
                parts.append(f"  - 답변: {pick.answer[:300]}")
        parts.append("")
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


async def run(questions: list[dict], runners: list[Runner]) -> dict[str, list[Pick]]:
    results: dict[str, list[Pick]] = {}
    for runner in runners:
        picks = []
        # Runner.current가 하나라 문항은 순차
        for index, q in enumerate(questions, 1):
            picks.append(await runner.run(q["q"]))
            print(f"\r{runner.name} {index}/{len(questions)}", end="", file=sys.stderr, flush=True)
        print(file=sys.stderr)
        results[runner.name] = picks
    return results


def main() -> None:
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    name = args[0] if args else "tool_eval"
    lines = (DATA / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
    questions = [json.loads(line) for line in lines if line.strip()]
    with_answer = "--answer" in sys.argv
    model = get_settings().llm_model
    runners = [
        Runner("지금 흐름", model, False, with_answer),
        Runner(f"도구 {model}", model, True, with_answer),
    ]
    if "--no-sonnet" not in sys.argv:
        runners.append(Runner(f"도구 {SONNET}", SONNET, True, with_answer))
    results = asyncio.run(run(questions, runners))
    table = report(questions, results)
    print(table)
    print(f"\n문항별 결과: {details(name, questions, results, table)}")


if __name__ == "__main__":
    main()
