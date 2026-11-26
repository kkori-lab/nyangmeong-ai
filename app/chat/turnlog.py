"""턴 기록 한 줄·실패 종류 태그·재요청 후보·주 단위 집계 (SCR-AIM-004 추가 요청, 2026-11-26)

- 대화 턴마다 `턴 room=… kind=… tools=… reads=… java=… result=… cards=… tags=… prev=… retry=… ms=…`
  한 줄, 확인 카드 결과마다 `카드 결과 room=… tool=… status=… errors=…` 한 줄
- 회원 문장·답변 글·도구 인자 값은 남기지 않는다. 칸 값은 도구 이름·태그·숫자뿐
- 태그 표(TEXT_TAGS)는 이 파일 한 곳 : service의 회원에게 보이는 문구 상수 이름 -> 태그
- 줄 만들기(format_*)와 읽기(parse_line)·집계(summarize)를 한 곳에 두어 모양이 어긋나지 않게
  (집계 명령 : uv run python -m scripts.turn_stats <LOG_DIR> [--weeks 4])
"""

import logging
import re
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

TURN_HEAD = "턴"
RESULT_HEAD = "카드 결과"
EMPTY = "-"

# 회원에게 보이는 실패·되물음 문구 상수(app.chat.service의 이름) -> 태그
# 새 문구 상수는 여기나 QUIET 중 한 곳에 넣는다(tests/chat/test_turn_log.py가 대조)
TEXT_TAGS: dict[str, tuple[str, ...]] = {
    "fallback": ("FALLBACK_MESSAGE",),
    "out_of_scope": ("OUT_OF_SCOPE_MESSAGE",),
    "error": ("ANSWER_ERROR_MESSAGE",),
    "pet_ask": ("READ_PET_ASK",),
    "no_pet": ("READ_NO_PET",),
    "target_missing": (
        "TARGET_MISSING_MESSAGE",
        "ADD_TARGET_MISSING_MESSAGE",
        "DELETE_TARGET_MISSING_MESSAGE",
        # LLM에 주는 tool_result 글 : 답변 글에는 안 나와 그 자리에서 태그(tag)
        "ACTION_TARGET_MISSING",
        "ACTION_ADD_TARGET_MISSING",
        "ACTION_DELETE_TARGET_MISSING",
    ),
    "read_empty": ("READ_EMPTY_MESSAGE", "READ_EMPTY_CARD_MESSAGE"),
    "missing_fields": (
        "ACTION_ASK_MISSING",
        "ACTION_ASK_MISSING_REST",
        "ACTION_ASK_MISSING_UNNAMED",
        "ACTION_ASK_MISSING_UNNAMED_NO",
        "ACTION_ASK_MISSING_NO",
        "ACTION_ASK_MISSING_REST_NO",
    ),
    "same_pet": ("ACTION_ASK_SAME_PET", "ACTION_ASK_SAME_PET_CHIP"),
    # 프로그래밍식 도구 호출 : 코드에 주는 tool_result 글이라 그 자리에서 태그(tag)
    "code_refused": ("CODE_NOT_READ",),
    "code_limit": ("CODE_LIMIT",),
    "action_failed": (
        "ACTION_FAILED_MESSAGE",
        "ACTION_FAILED_DELETE_MESSAGE",
        "ACTION_FAILED_FIX",
        "ACTION_FAILED_FIX_UNNAMED",
    ),
}

# 실패가 아닌 문구(안내·확인·결과·이름표·LLM 지시)와 턴 밖 화면(사진·검사결과지·병변 카드) 문구
QUIET = frozenset(
    {
        "DEFAULT_TITLE",
        "DISCLAIMER",
        "READ_PET_LABEL",
        "ROUTE_SHOWN",
        "ROUTE_EMPTY_MESSAGE",
        "ACTION_SHOWN",
        "ACTION_RUN_SHOWN",
        "ACTION_ASK_TEMPLATE",
        "PET_LABEL",
        "ACTION_ASK_CONFIRM",
        "ACTION_EXECUTE_MESSAGE",
        "ACTION_EXECUTE_PHOTO_MESSAGE",
        "ACTION_ASK_PHOTO",
        "ACTION_ASK_PHOTO_NO",
        "ACTION_ROUNDED",
        "ACTION_DROP_MESSAGE",
        "ACTION_CHAINED",
        "ACTION_ASK_LINE",
        "ACTION_ASK_SAME_PET_NO",
        "ACTION_VERB_ADD",
        "ACTION_VERB_UPDATE",
        "ACTION_VERB_MIXED",
        "ACTION_VERB_DELETE",
        "ACTION_ASK_DELETE",
        "ACTION_DELETE_CONFIRM",
        "SUMMARY_PREFIX",
        "SUMMARY_SUFFIX",
        "DUPLICATE_NOTICE",
        "CANCELED_MESSAGE",
        "RECEIPT_PREFIX",
        "ACTION_CANCELED_MESSAGE",
        "ACTION_CANCELED_DELETE_MESSAGE",
        "ARRAY_COUNT",
        "IMAGE_MARK",
        "IMAGE_TITLE",
        "PDF_MARK",
        "PDF_TITLE",
        "CHARACTER_PHOTO_UNFIT_MESSAGE",
        "CHECKUP_PREFIX",
        "CHECKUP_COUNT",
        "CHECKUP_EMPTY",
        "CHECKUP_ASK",
        "CHECKUP_MORE_ROWS",
        "CHECKUP_SKIPPED",
        "CHECKUP_EXCLUDED",
        "CHECKUP_NO_TOOL",
        "CHECKUP_NO_ROWS",
        "CHECKUP_NO_RECORD",
        "CHECKUP_ONE_RECORD",
        "CHECKUP_PICK_RECORD",
        "CHECKUP_NO_DATE",
        "EYE_REGION_NAME",
        "LESION_ASK",
        "LESION_EYE_REGION",
        "LESION_NO_TOOL",
        "OBSERVATION_ONGOING",
        "LESION_ONGOING_HEAD",
        "LESION_ONGOING_ASK",
    }
)

# 코드 자리에서 붙이는 태그(LLM이 다시 쓰는 실패라 글로 못 맞춤)
READ_FAILED = "read_failed"
READ_NO_ARGS = "read_no_args"
READ_UNAVAILABLE = "read_unavailable"
BAD_ARGS = "bad_args"
TIMEOUT = "timeout"
INCOMPLETE = "incomplete"
EXCEPTION = "exception"
ERROR = "error"
# 프로그래밍식 도구 호출 : 글을 흘린 뒤 코드 실행이 이어짐, 코드 실행 왕복 상한
TEXT_THEN_CODE = "text_then_code"
CODE_ROUNDS = "code_rounds"
# 동사형 명령 : 첫 턴에 확인 말 없이 실행 지시 (2026-11-26)
RUN_NOW = "run_now"
# 에이전트 루프 : 한 턴 도구 상한(TOOL_LIMIT)에 걸림 (docs/design/agent.md 3절)
AGENT_LIMIT = "agent_limit"

# 재요청 말 : 앞이 "아니", 또는 띄어쓰기를 뺀 글에 이 말
RETRY_HEAD = "아니"
RETRY_WORDS = ("여기서해", "대화창에서해", "그게아니라")

_SLOT = re.compile(r"\{[^{}]*\}")
_patterns: list[tuple[str, re.Pattern[str]]] | None = None


def _pattern(template: str) -> re.Pattern[str]:
    # 서식 문자열 : {칸} 자리는 한 글자 이상 아무 글
    parts = _SLOT.split(template.strip())
    return re.compile(".+?".join(re.escape(part) for part in parts))


def text_patterns() -> list[tuple[str, re.Pattern[str]]]:
    # service를 늦게 읽음 : service가 이 모듈을 import
    global _patterns
    if _patterns is None:
        from app.chat import service

        _patterns = [
            (tag, _pattern(getattr(service, name)))
            for tag, names in TEXT_TAGS.items()
            for name in names
        ]
    return _patterns


def text_tags(text: str | None) -> list[str]:
    """회원에게 보인 글 -> 그 글에 든 실패 문구의 태그(표 순서, 중복 없음)"""
    if not text:
        return []
    found = {tag for tag, pattern in text_patterns() if pattern.search(text)}
    return [tag for tag in TEXT_TAGS if tag in found]


def is_retry(text: str) -> bool:
    """실패 뒤 다시 해 달라는 말 : "아니…"·"여기서 해 줘"·"대화창에서 해"·"그게 아니라" """
    stripped = text.strip()
    if stripped.startswith(RETRY_HEAD):
        return True
    joined = "".join(stripped.split())
    return any(word in joined for word in RETRY_WORDS)


@dataclass
class TurnRecord:
    room: int
    kind: str = EMPTY
    # 확인·취소 말 턴 : confirm·cancel
    reply: str = EMPTY
    tools: list[str] = field(default_factory=list)
    reads: int = 0
    java: int = 0
    # 코드 실행 안 도구 호출 수(프로그래밍식 도구 호출, 0이면 줄에 안 씀)
    code: int = 0
    result: str = "ok"
    cards: int = 0
    tags: list[str] = field(default_factory=list)
    prev: str = EMPTY
    retry: bool = False
    started: float = field(default_factory=time.perf_counter)

    def tag(self, name: str) -> None:
        if name not in self.tags:
            self.tags.append(name)

    def see(self, event: tuple[str, object]) -> None:
        # SSE 이벤트에서 종류·결과·고정 문구 태그
        name, value = event
        if name == "intent":
            kind = getattr(value, "kind", None)
            self.kind = getattr(kind, "value", EMPTY)
        elif name == "error":
            self.result = ERROR
            self.tag(ERROR)
        elif name == "done":
            actions = getattr(value, "actions", None)
            action = getattr(value, "action", None)
            self.cards = len(actions) if actions else (1 if action is not None else 0)
            if getattr(value, "execute", False):
                self.result = "execute"
            elif self.cards:
                self.result = "card"
            message = getattr(value, "message", None)
            for tag in text_tags(getattr(message, "cnvrs_cn", None)):
                self.tag(tag)

    def wrap(self, emit: Callable[[object], None]) -> Callable[[object], None]:
        def recorded(event: object) -> None:
            if event is not None:
                self.see(event)  # type: ignore[arg-type]
            emit(event)

        return recorded


_current: ContextVar[TurnRecord | None] = ContextVar("turn_record", default=None)


def start(room: int, text: str, previous: str | None) -> TurnRecord:
    """턴 시작 : previous는 이번 질문 바로 앞 AI 메시지 글(없으면 None)"""
    record = TurnRecord(room)
    prev_tags = text_tags(previous)
    if prev_tags:
        record.prev = prev_tags[0]
        record.retry = is_retry(text)
    _current.set(record)
    return record


def current() -> TurnRecord | None:
    return _current.get()


def tag(name: str) -> None:
    record = _current.get()
    if record is not None:
        record.tag(name)


def picked(name: str) -> None:
    # LLM이 고른 도구 이름(순서대로)
    record = _current.get()
    if record is not None:
        record.tools.append(name)


def read(java_calls: int) -> None:
    # READ 도구 실행 한 번과 그 Java 호출 수
    record = _current.get()
    if record is not None:
        record.reads += 1
        record.java += java_calls


def code_call() -> None:
    # 코드 실행 안 도구 호출 한 번(READ면 그 실행은 read()로도 셈)
    record = _current.get()
    if record is not None:
        record.code += 1


def _joined(values: list[str]) -> str:
    return ",".join(values) if values else EMPTY


def format_turn(record: TurnRecord) -> str:
    ms = round((time.perf_counter() - record.started) * 1000)
    return (
        f"{TURN_HEAD} room={record.room} kind={record.kind} reply={record.reply}"
        f" tools={_joined(record.tools)} reads={record.reads} java={record.java}"
        f" result={record.result} cards={record.cards} tags={_joined(record.tags)}"
        f" prev={record.prev} retry={int(record.retry)} ms={ms}"
        + (f" code={record.code}" if record.code else "")
    )


def finish(record: TurnRecord) -> None:
    logger.info(format_turn(record))
    _current.set(None)


def format_result(room: int, tool: str, status: str, errors: int) -> str:
    return f"{RESULT_HEAD} room={room} tool={tool} status={status} errors={errors}"


def card_result(room: int, tool: str, status: str, errors: int) -> None:
    logger.info(format_result(room, tool, status, errors))


# 읽기·집계


_FIELD = re.compile(r"(\w+)=(\S+)")
_LINE = re.compile(rf" - ({TURN_HEAD}|{RESULT_HEAD}) (room=.*)$")
TURN_FIELDS = ("room", "kind", "tools", "reads", "java", "result", "tags", "prev", "retry", "ms")
RESULT_FIELDS = ("room", "tool", "status", "errors")


def parse_line(line: str) -> tuple[str, dict[str, str]] | None:
    """로그 한 줄 -> ("턴"|"카드 결과", 칸). 이 모듈 줄이 아니거나 칸이 모자라면 None"""
    if f" {__name__} - " not in line:
        return None
    match = _LINE.search(line.rstrip("\n"))
    if match is None:
        return None
    head, rest = match.groups()
    fields = dict(_FIELD.findall(rest))
    need = TURN_FIELDS if head == TURN_HEAD else RESULT_FIELDS
    if any(name not in fields for name in need):
        return None
    numbers = ("room", "reads", "java", "retry", "ms", "errors", "cards", "code")
    if any(name in fields and not fields[name].isdigit() for name in numbers):
        return None
    return head, fields


def _split(value: str) -> list[str]:
    return [] if value == EMPTY else value.split(",")


@dataclass
class WeekStats:
    turns: int = 0
    kinds: Counter = field(default_factory=Counter)
    tools: Counter = field(default_factory=Counter)
    reads: int = 0
    reads_max: int = 0
    java: int = 0
    # 코드 실행 안 도구 호출 : 합계와 그런 턴 수
    code: int = 0
    code_turns: int = 0
    results: Counter = field(default_factory=Counter)
    tags: Counter = field(default_factory=Counter)
    # 실패 태그가 하나라도 붙은 턴
    failed: int = 0
    # 재요청 후보 : 직전 태그별
    retries: Counter = field(default_factory=Counter)
    cards: Counter = field(default_factory=Counter)
    card_fails: Counter = field(default_factory=Counter)
    ms: list[int] = field(default_factory=list)

    def add(self, head: str, fields: dict[str, str]) -> None:
        if head == RESULT_HEAD:
            self.cards[fields["status"]] += 1
            if fields["status"] == "FAILED":
                self.card_fails[fields["tool"]] += 1
            return
        self.turns += 1
        self.kinds[fields["kind"]] += 1
        self.tools.update(_split(fields["tools"]))
        reads = int(fields["reads"])
        self.reads += reads
        self.reads_max = max(self.reads_max, reads)
        self.java += int(fields["java"])
        code = int(fields.get("code", "0"))
        self.code += code
        if code:
            self.code_turns += 1
        self.results[fields["result"]] += 1
        tags = _split(fields["tags"])
        self.tags.update(tags)
        if tags:
            self.failed += 1
        if fields["retry"] == "1":
            self.retries[fields["prev"]] += 1
        self.ms.append(int(fields["ms"]))


def week_of(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def summarize(lines: Iterable[tuple[date, str]]) -> dict[str, WeekStats]:
    """(로그 날짜, 줄) -> ISO 주별 집계. 다른 로거 줄·깨진 줄은 건너뜀"""
    weeks: dict[str, WeekStats] = {}
    for day, line in lines:
        parsed = parse_line(line)
        if parsed is None:
            continue
        weeks.setdefault(week_of(day), WeekStats()).add(*parsed)
    return dict(sorted(weeks.items()))


LOG_PREFIX = "ai_"


def log_lines(folder: Path, since: date) -> Iterator[tuple[date, str]]:
    """LOG_DIR의 ai_YYYY-MM-DD.log 중 since 이후 날짜 파일의 줄. 줄에는 날짜가 없어 파일 이름으로"""
    if not folder.is_dir():
        return
    for path in sorted(folder.glob(f"{LOG_PREFIX}*.log")):
        try:
            day = date.fromisoformat(path.stem[len(LOG_PREFIX) :])
        except ValueError:
            continue
        if day < since:
            continue
        with open(path, encoding="utf-8", errors="replace") as stream:
            for line in stream:
                yield day, line


def week_start(today: date, weeks: int) -> date:
    # 이번 주 포함 weeks주 : 그 첫 주 월요일
    monday = today - timedelta(days=today.weekday())
    return monday - timedelta(weeks=max(weeks, 1) - 1)


def _top(counter: Counter, limit: int = 10) -> str:
    if not counter:
        return EMPTY
    return ", ".join(f"{name} {count}" for name, count in counter.most_common(limit))


def _rate(count: int, total: int) -> str:
    return f"{count} ({count * 100 / total:.1f}%)" if total else str(count)


def render(weeks: dict[str, WeekStats]) -> str:
    if not weeks:
        return "턴 기록 0건"
    out: list[str] = []
    for week, stats in weeks.items():
        ms = sorted(stats.ms)
        median = ms[len(ms) // 2] if ms else 0
        avg = stats.reads / stats.turns if stats.turns else 0
        out += [
            f"## {week}",
            f"- 턴: {stats.turns} (ms 중앙값 {median})",
            f"- 종류: {_top(stats.kinds)}",
            f"- 결과: {_top(stats.results)}",
            f"- 도구: {_top(stats.tools)}",
            f"- READ: 턴당 평균 {avg:.2f}번, 최대 {stats.reads_max}번, Java {stats.java}번",
            *(
                [f"- 코드 안 도구 호출: {stats.code}번 ({_rate(stats.code_turns, stats.turns)} 턴)"]
                if stats.code
                else []
            ),
            f"- 실패 태그 붙은 턴: {_rate(stats.failed, stats.turns)}",
            *(
                f"  - {name}: {_rate(count, stats.turns)}"
                for name, count in stats.tags.most_common()
            ),
            f"- 재요청 후보: {sum(stats.retries.values())} (직전 태그: {_top(stats.retries)})",
            f"- 카드 결과: {_top(stats.cards)} (실패 도구: {_top(stats.card_fails)})",
            "",
        ]
    return "\n".join(out).rstrip() + "\n"
