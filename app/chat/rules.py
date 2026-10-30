import calendar
import re
from dataclasses import dataclass, fields
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import yaml

from app.chat.schemas import Intent, IntentKind, MoveType

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@dataclass(frozen=True)
class RouteRow:
    no: int
    name: str
    scr_id: str
    param: str | None
    move_type: MoveType
    routable: bool
    keywords: tuple[str, ...]

    def to_intent(self) -> Intent:
        return Intent(
            kind=IntentKind.ROUTE,
            scr_id=self.scr_id,
            scr_nm=self.name,
            param=self.param,
            move_type=self.move_type,
        )


def _compact(text: str) -> str:
    # 키워드·사전은 공백을 뺀 문장과 대조 ("털 깎기" = "털깎기")
    return re.sub(r"\s+", "", text)


def _load(name: str) -> dict:
    with (DATA_DIR / name).open(encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache
def routing_table() -> tuple[RouteRow, ...]:
    # FN-AIM-004-09 : 매핑표는 data/routing.yaml(부록 A)이 기준
    rows = _load("routing.yaml")["rows"]
    return tuple(
        RouteRow(
            no=row["num"],
            name=row["name"],
            scr_id=row["scr_id"],
            param=row.get("param"),
            move_type=MoveType(row.get("move_type", MoveType.PAGE)),
            routable=row.get("routable", True),
            keywords=tuple(row.get("keywords", ())),
        )
        for row in rows
    )


@lru_cache
def _register_patterns() -> tuple[re.Pattern[str], re.Pattern[str]]:
    data = _load("register_dict.yaml")
    verb = re.compile("|".join(data["verbs"]))
    when = re.compile("|".join(data["dates"] + data["times"] + data["cycles"]))
    return verb, when


def is_register_request(text: str) -> bool:
    # FN-AIM-012-01 : 등록 동사와 날짜·시간·주기 표현(부록 B)이 둘 다 있어야 등록 요청
    verb, when = _register_patterns()
    compact = _compact(text)
    return bool(verb.search(compact) and when.search(compact))


def match_route(text: str) -> RouteRow | None:
    # FN-AIM-004-01 : 키워드가 여럿 일치하면 가장 긴 키워드, 같은 길이면 매핑표 위쪽 행
    # FN-AIM-004-11 : 반려동물 이름 등 데이터 컨텍스트는 해석하지 않고 화면 단위로만 매칭
    compact = _compact(text)
    best: RouteRow | None = None
    best_len = 0
    for row in routing_table():
        if not row.routable:
            continue
        for keyword in row.keywords:
            length = len(_compact(keyword))
            if length > best_len and _compact(keyword) in compact:
                best, best_len = row, length
    return best


def find_route(scr_id: str, param: str | None) -> RouteRow | None:
    # FN-AIM-004-08 : AI 분류 결과는 매핑표의 라우팅 가능 행에 있는 화면만 인정
    for row in routing_table():
        if row.routable and row.scr_id == scr_id and row.param == param:
            return row
    return None


# 서버 서머타임 없음 : 고정 오프셋 사용 (Windows에는 tzdata 없음)
KST = timezone(timedelta(hours=9))
WEEKDAYS = "월화수목금토일"
# 공통코드(백엔드 db/20261029_insert_base_data_v0.10.sql)
SCHEDULE_HOSPITAL = "HLTC0057"  # HLTG19 병원
SCHEDULE_ETC = "HLTC0060"  # HLTG19 기타
CHECKUP_ETC = "HLTC0005"  # HLTG01 기타 진료
ZONE_DAILY = "HLTC0036"  # HLTG13 일상관리(매일)
ZONE_PERIODIC = "HLTC0037"  # HLTG13 정기관리(주기)
CYCLE_1W = "HLTC0038"
CYCLE_2W = "HLTC0039"
CYCLE_MONTH = "HLTC0040"
CYCLE_YEAR = "HLTC0041"
CYCLE_CUSTOM = "HLTC0042"  # 직접입력 n일마다
CYCLE_DAYS = {CYCLE_1W: 7, CYCLE_2W: 14}


def today_kst() -> date:
    return datetime.now(KST).date()


@dataclass
class RegisterFields:
    # 규칙·AI가 문장에서 뽑은 칸. None이면 뽑지 못함
    schdl_knd_cd: str | None = None
    schdl_ymd: date | None = None
    schdl_tm: str | None = None
    ckup_type_cd: str | None = None
    hsptl_nm: str | None = None
    schdl_nm: str | None = None
    care_artcl_nm: str | None = None
    care_zone_cd: str | None = None
    care_cycle_cd: str | None = None
    cycle_days: int | None = None
    last_cmptn_ymd: date | None = None

    def values(self) -> dict:
        # 뽑은 칸만
        return {f.name: getattr(self, f.name) for f in fields(self) if getattr(self, f.name)}


@lru_cache
def _register_dict() -> dict:
    return _load("register_dict.yaml")


def code_name(code: str | None) -> str:
    return _register_dict()["code_names"].get(code, "") if code else ""


def schedule_codes() -> frozenset[str]:
    return frozenset(row["code"] for row in _register_dict()["schedule_types"]) | {SCHEDULE_ETC}


def checkup_codes() -> frozenset[str]:
    return frozenset(row["code"] for row in _register_dict()["checkup_types"]) | {CHECKUP_ETC}


CYCLE_CODES = frozenset({CYCLE_1W, CYCLE_2W, CYCLE_MONTH, CYCLE_YEAR, CYCLE_CUSTOM})


def _first_keyword(compact: str, rows: list[dict]) -> tuple[str, str] | None:
    # 위 행부터 대조 : (코드, 맞은 키워드)
    for row in rows:
        for keyword in row["keywords"]:
            if keyword in compact:
                return row["code"], keyword
    return None


def _ymd(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _add_months(base: date, months: int) -> date:
    # 말일을 넘으면 그 달 말일(1-31 + 한달 = 2-28)
    month = base.month - 1 + months
    year, month = base.year + month // 12, month % 12 + 1
    return date(year, month, min(base.day, calendar.monthrange(year, month)[1]))


def _week_day(today: date, which: str, weekday: str) -> date:
    monday = today - timedelta(days=today.weekday())
    weeks = {"이번": 0, "다음": 1, "지난": -1}[which]
    return monday + timedelta(weeks=weeks, days=WEEKDAYS.index(weekday))


def _bare_weekday(today: date, weekday: str) -> date:
    # "금요일" : 오늘부터 가장 가까운 그 요일
    return today + timedelta(days=(WEEKDAYS.index(weekday) - today.weekday()) % 7)


def _next_month_day(today: date, day: int) -> date | None:
    month_of = _add_months(today.replace(day=1), 1)
    return _ymd(month_of.year, month_of.month, day)


_RELATIVE_DAYS = {"오늘": 0, "내일": 1, "모레": 2, "글피": 3, "어제": -1, "그제": -2}

# 순서대로 대조, 맞은 자리는 가림 (뒤 규칙의 재판독 방지). 띄어쓰기 허용
_DATE_RULES = (
    (r"(\d{4})-(\d{1,2})-(\d{1,2})", lambda m, t: _ymd(int(m[1]), int(m[2]), int(m[3]))),
    (r"(이번|다음|지난)\s*주\s*([월화수목금토일])요일", lambda m, t: _week_day(t, m[1], m[2])),
    (r"다음\s*달\s*(\d{1,2})\s*일", lambda m, t: _next_month_day(t, int(m[1]))),
    (r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", lambda m, t: _ymd(t.year, int(m[1]), int(m[2]))),
    (r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])", lambda m, t: _ymd(t.year, int(m[1]), int(m[2]))),
    (r"(\d{1,3})\s*일\s*(후|뒤)", lambda m, t: t + timedelta(days=int(m[1]))),
    (r"오늘|내일|모레|글피|어제|그제", lambda m, t: t + timedelta(days=_RELATIVE_DAYS[m[0]])),
    (r"([월화수목금토일])요일", lambda m, t: _bare_weekday(t, m[1])),
    (
        r"(?<!\d)(\d{1,2})\s*일(?!\s*(마다|에\s*한\s*번|간|동안))",
        lambda m, t: _ymd(t.year, t.month, int(m[1])),
    ),
)

# 날짜 뒤에 이 말이 오면 일정 날짜가 아니라 마지막으로 한 날("지난주 토요일에 했어")
_DONE_AFTER = re.compile(r"^\s*(에|날|쯤)?\s*(했|해\s*줬|함|하였)")

# (정규식, 케어구역, 케어주기, n에 곱할 일수). 케어주기 "weeks"는 n주마다
_CYCLE_RULES = (
    (r"매일|날마다|하루\s*에?\s*한\s*번", ZONE_DAILY, None, None),
    (r"격주", ZONE_PERIODIC, CYCLE_2W, None),
    (r"(\d{1,2})\s*주\s*(마다|에\s*한\s*번)", ZONE_PERIODIC, "weeks", 7),
    (r"매주|일주일\s*마다|한\s*주\s*마다", ZONE_PERIODIC, CYCLE_1W, None),
    (r"매달|매월|한\s*달\s*마다|(1|한)\s*개월\s*마다", ZONE_PERIODIC, CYCLE_MONTH, None),
    (r"매년|(1|한)\s*년\s*마다", ZONE_PERIODIC, CYCLE_YEAR, None),
    (r"(\d{1,2})\s*년\s*마다", ZONE_PERIODIC, CYCLE_CUSTOM, 365),
    (r"(\d{1,3})\s*일\s*(마다|에\s*한\s*번)", ZONE_PERIODIC, CYCLE_CUSTOM, 1),
)

_CLOCK = re.compile(r"(오전|오후|아침|저녁|밤|낮|새벽)?\s*(\d{1,2})\s*시\s*(반|(\d{1,2})\s*분)?")
_HH_MM = re.compile(r"(?<![\d:])([01]?\d|2[0-3]):([0-5]\d)(?![\d:])")

_HOSPITAL = re.compile(r"([가-힣A-Za-z0-9]+)\s?(동물병원|동물의료센터|메디컬센터|병원)")
# 병원명 앞말로 보지 않는 말
_NOT_HOSPITAL_PREFIX = re.compile(
    r"\d|요일|^(내일|오늘|모레|어제|다음|이번|지난|일정|예약|가까운|근처|단골|그|우리|동네|동물|주)$"
)
_PARTICLE_END = re.compile(r"(에서|에게|한테|으로|에|의|로|은|는|이|가|을|를|도)$")
# 등록·수정 동사부터 절 끝까지는 항목명 제외
_VERB_TAIL = re.compile(
    r"\s*(잡아|등록해|넣어|추가해|예약해|만들어|바꿔|변경해|수정해)\s*(줘|주세요|주|줄래|줄|요)?.*$"
)


def _mask(text: str, start: int, end: int) -> str:
    return text[:start] + " " * (end - start) + text[end:]


def _hour(period: str | None, hour: int) -> int | None:
    # 오전·오후가 없으면 1~7시는 오후 처리 : 반려동물 일정은 대개 낮 시간
    if hour > 24:
        return None
    if period in ("오후", "저녁", "밤") and hour < 12:
        return hour + 12
    if period == "낮" and hour <= 6:
        return hour + 12
    if period in ("오전", "아침", "새벽") and hour == 12:
        return 0
    if period is None and 1 <= hour <= 7:
        return hour + 12
    return hour % 24


def _parse_cycle(result: RegisterFields, masked: str) -> tuple[str, tuple[int, int] | None]:
    for pattern, zone, cycle, unit in _CYCLE_RULES:
        m = re.search(pattern, masked)
        if m is None:
            continue
        n = int(m[1]) if unit else 0
        if unit and n == 0:
            return _mask(masked, *m.span()), None
        result.care_zone_cd = zone
        if cycle == "weeks" and n in (1, 2):
            result.care_cycle_cd = CYCLE_1W if n == 1 else CYCLE_2W
        elif unit:
            result.care_cycle_cd, result.cycle_days = CYCLE_CUSTOM, n * unit
        else:
            result.care_cycle_cd = cycle
        return _mask(masked, *m.span()), m.span()
    return masked, None


def _parse_dates(result: RegisterFields, masked: str, today: date) -> str:
    for pattern, convert in _DATE_RULES:
        for m in re.finditer(pattern, masked):
            day = convert(m, today)
            done = _DONE_AFTER.match(masked[m.end() :])
            masked = _mask(masked, *m.span())
            if done:
                masked = _mask(masked, m.end(), m.end() + done.end())
                result.last_cmptn_ymd = result.last_cmptn_ymd or day
            else:
                result.schdl_ymd = result.schdl_ymd or day
    return masked


def _parse_time(result: RegisterFields, masked: str) -> str:
    m = _CLOCK.search(masked)
    if m is not None:
        hour = _hour(m[1], int(m[2]))
        minute = 30 if m[3] == "반" else int(m[4] or 0)
    else:
        m = _HH_MM.search(masked)
        if m is None:
            return masked
        hour, minute = int(m[1]), int(m[2])
    if hour is not None and minute < 60:
        result.schdl_tm = f"{hour:02d}:{minute:02d}"
    return _mask(masked, *m.span())


def parse_register(text: str, today: date, pet_names: list[str]) -> RegisterFields:
    # FN-AIM-012-02 : 일정 종류 키워드·날짜·시간·주기의 규칙 추출, 반려동물은 서비스가 결정
    result = RegisterFields()
    masked, cycle_span = _parse_cycle(result, text)
    masked = _parse_dates(result, masked, today)
    masked = _parse_time(result, masked)
    compact = _compact(text)
    data = _register_dict()
    kind = _first_keyword(compact, data["schedule_types"])
    if kind is not None:
        result.schdl_knd_cd = kind[0]
        if kind[0] != SCHEDULE_HOSPITAL:
            result.schdl_nm = kind[1]
    checkup = _first_keyword(compact, data["checkup_types"])
    if checkup is not None:
        result.ckup_type_cd = checkup[0]
    result.hsptl_nm = _hospital_name(text, pet_names)
    if result.ckup_type_cd or result.hsptl_nm:
        result.schdl_knd_cd, result.schdl_nm = SCHEDULE_HOSPITAL, None
    if cycle_span is not None:
        result.care_artcl_nm = care_item_name(masked, cycle_span[0], pet_names)
    return result


def _hospital_name(text: str, pet_names: list[str]) -> str | None:
    keywords = {k for row in _register_dict()["schedule_types"] for k in row["keywords"]}
    for m in _HOSPITAL.finditer(text):
        prefix = _PARTICLE_END.sub("", m[1]) or m[1]
        if _NOT_HOSPITAL_PREFIX.search(prefix) or prefix in pet_names or prefix in keywords:
            continue
        return re.sub(r"\s+", " ", m[0]).strip()[:80]
    return None


def care_item_name(masked: str, anchor: int, pet_names: list[str]) -> str | None:
    # 날짜·시간·주기를 가린 문장에서 anchor가 든 절의 반려동물 이름·동사를 뺀 나머지
    # ("뭉치 2주마다 발톱 깎기 넣어줘, 지난주 토요일에 했어" → 발톱 깎기)
    start = 0
    clause = masked
    for part in re.split(r"[,.!?\n]", masked):
        if start <= anchor <= start + len(part):
            clause = part
            break
        start += len(part) + 1
    name = _VERB_TAIL.sub("", clause)
    for pet in pet_names:
        name = re.sub(rf"{re.escape(pet)}(이|가|는|은|에게|한테|의)?(?=\s|$)", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) > 2:
        name = _PARTICLE_END.sub("", name).strip()
    return name[:40] or None


def valid_ymd(value) -> date | None:
    # FN-AIM-012-03 : AI가 준 날짜의 서버 재검증 (형식·실재 날짜)
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def valid_hm(value) -> str | None:
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", str(value or ""))
    return f"{int(m[1]):02d}:{m[2]}" if m else None


def next_due(zone: str | None, cycle: str | None, days: int | None, last: date) -> date | None:
    # FN-AIM-012-07 : 마지막으로 한 날 + 주기. 매일(일상관리)은 다음 날
    if zone == ZONE_DAILY:
        return last + timedelta(days=1)
    if cycle in CYCLE_DAYS:
        return last + timedelta(days=CYCLE_DAYS[cycle])
    if cycle == CYCLE_MONTH:
        return _add_months(last, 1)
    if cycle == CYCLE_YEAR:
        return _add_months(last, 12)
    if cycle == CYCLE_CUSTOM and days:
        return last + timedelta(days=days)
    return None


def clean_ai_fields(raw: dict) -> RegisterFields:
    # FN-AIM-012-03 : AI 출력 재검증 (코드는 허용값, 날짜·시간은 형식과 실재 날짜)
    # 글자 수는 컬럼 길이로 재조정, 틀린 칸은 비움
    def text(name: str, limit: int) -> str | None:
        value = raw.get(name)
        return value.strip()[:limit] or None if isinstance(value, str) else None

    def code(name: str, allowed: frozenset[str]) -> str | None:
        value = raw.get(name)
        return value if value in allowed else None

    days = raw.get("cycle_days")
    return RegisterFields(
        schdl_knd_cd=code("schdl_knd_cd", schedule_codes()),
        schdl_ymd=valid_ymd(raw.get("schdl_ymd")),
        schdl_tm=valid_hm(raw.get("schdl_tm")),
        ckup_type_cd=code("ckup_type_cd", checkup_codes()),
        hsptl_nm=text("hsptl_nm", 80),
        schdl_nm=text("schdl_nm", 40),
        care_artcl_nm=text("care_artcl_nm", 40),
        care_zone_cd=code("care_zone_cd", frozenset({ZONE_DAILY, ZONE_PERIODIC})),
        care_cycle_cd=code("care_cycle_cd", CYCLE_CODES),
        cycle_days=days if isinstance(days, int) and 1 <= days <= 3650 else None,
        last_cmptn_ymd=valid_ymd(raw.get("last_cmptn_ymd")),
    )
