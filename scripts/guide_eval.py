"""사용법 질문 평가. 실제 Anthropic API를 부른다(.env.local의 LLM_API_KEY, 비용이 든다)

M1 단독(키워드 색인)과 M1+LLM(실제 판정 흐름 `service.judge_tools`: 도구 고르기의 search_guide
목차 선택을 앞에, M1을 뒤에)의 hit@1·hit@3, 범위 밖 거절, 토큰을 표로 낸다.
답변 본문은 .cache/guide_eval/에 쓴다. 도구 목록은 테스트와 같은 가짜 Java 목록(Java 미호출).
답변 정확도는 사람이 그 파일을 읽고 매긴다(LLM 채점 안 함).

돌리기: uv run python -m scripts.guide_eval [세트 이름, 기본 guide_eval2] [--no-answer]
pytest 수집 제외(tests/ 밖), 테스트·CI에서 미호출(AGENTS.md 5번)
"""

import asyncio
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.chat import rules, service, tools
from app.chat.clients import AnthropicToolAgent, get_anthropic_client
from app.chat.repository import get_ai_settings
from app.core.config import get_settings
from tests.chat.fakes import fake_catalog

DATA = Path(__file__).resolve().parents[1] / "tests" / "chat" / "data"
OUT = Path(__file__).resolve().parents[1] / ".cache" / "guide_eval"


@dataclass
class Row:
    question: dict
    # 정답 청크. [] 범위 밖, None 범위 안이지만 안내서에 없는 기능(집계에서 따로 셈)
    expected: list[str] | None
    m1: list[str]
    kind: str = ""
    # ROUTE일 때 이동한 화면 ID
    route_scr: str | None = None
    ids: list[str] = field(default_factory=list)
    classify_usage: list[dict] = field(default_factory=list)
    answer_usage: dict | None = None
    answer: str = ""


def _usage(usage) -> dict:
    return {
        "input": usage.input_tokens,
        "cache_read": usage.cache_read_input_tokens or 0,
        "cache_write": usage.cache_creation_input_tokens or 0,
        "output": usage.output_tokens,
    }


class Recorder:
    # 도구 고르기·답변 응답의 usage를 지금 문항에 모은다(AnthropicToolAgent on_usage)
    def __init__(self) -> None:
        self.current: Row | None = None

    def __call__(self, task: str, usage) -> None:
        if task == "도구 고르기":
            self.row().classify_usage.append(_usage(usage))
        else:
            self.row().answer_usage = _usage(usage)

    def row(self) -> Row:
        assert self.current is not None
        return self.current


def load(name: str) -> list[Row]:
    lines = (DATA / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
    labels_name = name.replace("guide_eval", "guide_labels")
    labels = json.loads((DATA / f"{labels_name}.json").read_text(encoding="utf-8"))
    questions = [json.loads(line) for line in lines if line.strip()]
    return [Row(q, labels[q["id"]], rules.search_guide(q["q"])) for q in questions]


async def run_one(row: Row, agent, recorder: Recorder, with_answer: bool) -> None:
    recorder.current = row
    settings = get_settings()
    q = row.question["q"]
    judged = await service.judge_tools(
        q,
        [{"role": "user", "content": q}],
        agent,
        get_ai_settings().max_tokens,
        rules.today_kst(),
        settings.answer_first_token_sec,
    )
    row.kind = judged.intent.kind.value
    row.ids = list(judged.guide_ids)
    row.route_scr = judged.intent.scr_id
    if judged.stream is None:
        return
    if not with_answer or not row.ids:
        # 바로 답 글 스트림은 이미 시작한 호출 : 읽지 않고 닫는다
        await judged.stream.aclose()
        return
    row.answer = "".join([text async for text in judged.stream])


async def run(rows: list[Row], with_answer: bool) -> None:
    settings = get_settings()
    tools.use_catalog(fake_catalog())
    recorder = Recorder()
    agent = AnthropicToolAgent(get_anthropic_client(settings), settings.llm_model, recorder)
    # Recorder.current가 하나라 문항은 순차로 돈다(50문항 몇 분)
    for index, row in enumerate(rows, 1):
        await run_one(row, agent, recorder, with_answer)
        print(f"\r{index}/{len(rows)}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)


def route_ok(row: Row) -> bool:
    # 사용법 문항이 화면 이동이 됐을 때, 그 화면이 정답 청크의 화면이면 맞게 보낸 것
    screens = set()
    for chunk_id in row.expected or []:
        chunk = rules.find_guide(chunk_id)
        screens |= {r.scr_id for r in rules.routing_table() if chunk and r.no == chunk.num}
    return row.route_scr in screens


def hit(ids: list[str], expected: list[str] | None, k: int) -> bool:
    return any(chunk_id in (expected or []) for chunk_id in ids[:k])


def report(rows: list[Row]) -> str:
    groups: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        groups[row.question["type"]].append(row)
    usage_rows = [row for row in rows if row.expected]
    out_rows = [row for row in rows if row.expected == []]
    gap_rows = [row for row in rows if row.expected is None]
    lines = [
        "| 유형 | 문항 | M1 hit@1 | M1 hit@3 | M1+LLM hit@1 | M1+LLM hit@3 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, group in [*groups.items(), ("사용법 전체", usage_rows)]:
        group = [row for row in group if row.expected]
        if not group:
            continue
        lines.append(
            f"| {name} | {len(group)} "
            f"| {sum(hit(r.m1, r.expected, 1) for r in group)} "
            f"| {sum(hit(r.m1, r.expected, 3) for r in group)} "
            f"| {sum(hit(r.ids, r.expected, 1) for r in group)} "
            f"| {sum(hit(r.ids, r.expected, 3) for r in group)} |"
        )
    lines.append("")
    lines.append(
        f"범위 밖 거절(안내서 청크 없음): M1 {sum(r.m1 == [] for r in out_rows)}/{len(out_rows)}"
        f" · M1+LLM {sum(r.ids == [] for r in out_rows)}/{len(out_rows)}"
    )
    if gap_rows:
        lines.append(
            "안내서에 없는 기능(집계 제외): "
            + ", ".join(f"{r.question['id']} → {r.ids or '청크 없음'}" for r in gap_rows)
        )
    stages = defaultdict(int)
    # 실제 흐름 기준 : M1은 search_guide를 골랐을 때만 쓰인다(이동·바로 답이면 안 씀)
    for row in usage_rows:
        if row.ids and row.ids == row.m1:
            stages["M1"] += 1
        elif row.ids:
            stages["목차"] += 1
        else:
            stages[f"청크 없음({row.kind})"] += 1
    lines.append("사용법 문항 단계: " + " · ".join(f"{k} {v}" for k, v in stages.items()))
    routed = [row for row in usage_rows if not row.ids and row.kind == "ROUTE"]
    lines.append(
        f"화면 이동(ROUTE)된 사용법 문항: {len(routed)}개 중 정답 청크의 화면으로 "
        f"{sum(route_ok(r) for r in routed)}개 ("
        + ", ".join(f"{r.question['id']}→{r.route_scr}" for r in routed)
        + ")"
    )
    lines.append(_tokens("도구 고르기", [u for r in rows for u in r.classify_usage]))
    lines.append(_tokens("답변", [r.answer_usage for r in rows if r.answer_usage]))
    return "\n".join(lines)


def _tokens(name: str, usages: list[dict]) -> str:
    if not usages:
        return f"{name} 토큰: 호출 없음"
    n = len(usages)
    avg = {key: sum(u[key] for u in usages) / n for key in usages[0]}
    return (
        f"{name} 토큰(호출 {n}회 평균): 입력 {avg['input']:.0f} · 캐시 읽기 {avg['cache_read']:.0f}"
        f" · 캐시 쓰기 {avg['cache_write']:.0f} · 출력 {avg['output']:.0f}"
    )


def answers_file(name: str, rows: list[Row], table: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}-{datetime.now():%Y%m%d-%H%M}.md"
    parts = [f"# {name} 평가 결과\n", table, "\n정확도 칸에 맞음/부분/틀림을 적는다.\n"]
    for row in rows:
        q = row.question
        mark = "O" if hit(row.ids, row.expected, 3) else ("-" if not row.expected else "X")
        expected = "안내서에 없음" if row.expected is None else row.expected or "없음(범위 밖)"
        parts.append(
            f"## {q['id']} [{q['type']}] {q['q']}\n"
            f"- 의도: {q.get('intent')}\n"
            f"- 정답 청크: {expected} · M1 {row.m1} · "
            f"M1+LLM {row.ids} ({row.kind}) · hit@3 {mark}\n"
            f"- 정확도: \n\n{row.answer or '(답변 없음: 안내서 청크 없음)'}\n"
        )
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def main() -> None:
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    name = args[0] if args else "guide_eval2"
    with_answer = "--no-answer" not in sys.argv
    rows = load(name)
    asyncio.run(run(rows, with_answer))
    table = report(rows)
    print(table)
    print(f"\n답변 파일: {answers_file(name, rows, table)}")


if __name__ == "__main__":
    main()
