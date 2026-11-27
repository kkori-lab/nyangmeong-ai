import calendar
import json
import re
from dataclasses import dataclass, fields
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import yaml

from app.chat.schemas import Intent, IntentKind, MoveType, RouteItem

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


# AIMG09 이동 방식 : 이 둘 밖(라우팅 대상 아님·제외·보류·모르는 코드)은 이동 안 함
MOVE_TYPES = {"AIMC0032": MoveType.PAGE, "AIMC0033": MoveType.MODAL}
# 부록 A의 "키워드에 따라 탭" 같은 자리표시 파라미터
PARAM_PLACEHOLDER = "…"

_routes: tuple[RouteRow, ...] | None = None


def _route_param(value: str | None) -> str | None:
    # Java는 "cat=hospital", React에 주는 꼴은 "?cat=hospital"
    value = (value or "").strip()
    if not value or PARAM_PLACEHOLDER in value:
        return None
    return value if value.startswith("?") else f"?{value}"


def route_rows(items: list[RouteItem]) -> tuple[RouteRow, ...]:
    # FN-AIM-004-01 : 같은 길이 키워드는 위쪽 행 우선이라 prrtSeq 순서 유지
    ordered = sorted(items, key=lambda item: (item.prrt_seq, item.ai_rout_mpng_sn))
    return tuple(
        RouteRow(
            no=item.ai_rout_mpng_sn,
            name=item.trgt_scrn_nm,
            scr_id=item.scrn_id or "",
            param=_route_param(item.scrn_param_cn),
            move_type=MOVE_TYPES.get(item.mvmn_mthd_cd, MoveType.PAGE),
            routable=item.mvmn_mthd_cd in MOVE_TYPES and bool(item.scrn_id),
            keywords=tuple(k.strip() for k in item.inst_kwrds if k.strip()),
        )
        for item in ordered
    )


@lru_cache
def snapshot_routes() -> tuple[RouteRow, ...]:
    # Java에 닿지 못할 때의 매핑표 : data/routes.snapshot.json(Java 응답 모양)
    raw = json.loads((DATA_DIR / "routes.snapshot.json").read_text(encoding="utf-8"))
    return route_rows([RouteItem.model_validate(item) for item in raw])


def use_routes(rows: tuple[RouteRow, ...] | None) -> None:
    global _routes
    _routes = rows


def routing_table() -> tuple[RouteRow, ...]:
    # FN-AIM-004-09 : 매핑표는 Java(관리자 SCR-ADM-080)에서 받은 표, 받기 전·실패면 스냅샷
    return _routes if _routes is not None else snapshot_routes()


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


# 추가 요청(2026-11-09) : 문장 전체가 인사·감사·맞장구면 잡담. 건강 질문이 섞이면 잡담 아님
_SMALL_TALK = re.compile(
    r"(안녕(하세요|하십니까|히계세요|히가세요)?|하이|헬로|반가워요?|반갑습니다"
    r"|고마워요?|고맙습니다|감사(해요|합니다)?|땡큐|ㄳ|ㄱㅅ"
    r"|좋아요?|좋네요?|알겠어요?|알겠습니다|알았어요?|응|네|넵|예|ㅇ|ㅇㅋ|오케이|굿"
    r"|잘자|잘가|바이|수고하세요|수고했어)+"
)
_SMALL_TALK_NOISE = re.compile(r"[\sㅋㅎㅠㅜ~!?.,^]+")


def is_small_talk(text: str) -> bool:
    # 웃음·기호만 있어도 잡담 : 그 밖의 글자가 하나라도 남으면 잡담 아님
    rest = _SMALL_TALK_NOISE.sub("", text)
    return rest == "" or _SMALL_TALK.fullmatch(rest) is not None


# FN-AIM-002-03 (2026-11-25 SJM 피드백) : 도구 없이 바로 쓴 답은 글에 건강 말이 있을 때만 고지
# ("오늘 날씨 어때?"에 고지 붙음). 키워드 밖 건강 질문은 고지가 빠지므로 넓게 잡는다
_HEALTH_TOPIC = re.compile(
    r"건강|아프|아파|아픈|아팠|통증|증상|질병|질환|병원|수의|진료|진단|치료|수술|입원|약|영양제"
    r"|먹|마셔|마시|사료|간식|음식|식욕|식사|음수|구토|토해|토하|토를|설사"
    r"|대변|변비|변이|변을|변 |배변|소변|오줌|혈뇨"
    r"|기침|재채기|콧물|열이|열나|체온|체중|몸무게|살이|살찌|비만|다이어트"
    r"|접종|백신|예방|구충|사상충|진드기|벼룩|기생충|중성화|임신|출산|발정|생리"
    r"|피부|털|가려|긁|각질|탈모|비듬|발진|상처|피가|피나|출혈|붓|부어|혹이|종양|암이|암에"
    r"|눈곱|눈물|충혈|눈이|귀가|귓|냄새|입냄새|이빨|치아|잇몸|치석|양치|발톱|발바닥"
    r"|절뚝|다리|관절|슬개골|허리|숨|호흡|헐떡|경련|발작|떨림|떨어요|떨고|기운|무기력|컨디션|노령|노견|노묘"
    r"|중독|독성|위험|알레르기|포도|초콜릿|양파|자일리톨|스트레스|불안|짖|물었|무는|깨물|공격|행동"
    r"|산책|운동|목욕|미용|검진|검사|수치"
)


def is_health_topic(text: str) -> bool:
    return _HEALTH_TOPIC.search(text) is not None


# 이동 먼저 고른 섞인 메시지(2026-11-17) : 이어 주는 이동 말 뒤에 다른 일이 이어지는지
_CHAIN_AFTER_MOVE = re.compile(r"(열어서|열고|가서|가고|들어가서|이동해서|이동하고|띄워서)(.*)")
_CHAIN_REST = re.compile(r"[\w가-힣]")


def chains_after_move(text: str) -> bool:
    # "가계부 열어서 지출 알려 줘"는 참, "가계부 열어 줘"·"가계부 열어서"는 거짓
    match = _CHAIN_AFTER_MOVE.search(text)
    return match is not None and _CHAIN_REST.search(match.group(2)) is not None


# 한 메시지 여러 명령 ② : 쓰기 요청을 이어 말하는 말("기록하고 일정도 잡아줘")
_CHAIN_MORE = re.compile(r"하고|그리고|이랑|[가-힣]랑\s|및|또\s|[가-힣]고\s|[가-힣]도\s|,")


def chains_more(text: str) -> bool:
    """쓰기 도구 뒤에 다른 쓰기 요청이 이어질 수 있는 문장인지 : 거짓이면 LLM을 더 부르지 않음"""
    return _CHAIN_MORE.search(text) is not None


# 추가 요청(2026-11-09) : "<질문>" 같은 자리 표시·기호뿐인 글은 도구 고르기 없이 unclear 안내
_PLACEHOLDER = re.compile(r"<[^<>]*>|[\W_]*")


def is_placeholder(text: str) -> bool:
    return _PLACEHOLDER.fullmatch(text.strip()) is not None


def find_route(scr_id: str, param: str | None) -> RouteRow | None:
    # FN-AIM-004-08 : 매핑표의 라우팅 가능 행에 있는 화면만 인정
    for row in routing_table():
        if row.routable and row.scr_id == scr_id and row.param == param:
            return row
    return None


GUIDE_DIR = DATA_DIR / "guide"
GUIDE_TOP_K = 3
# docs/design/service-guide-search.md 2절 : task 검색어 1.0, 화면 검색어 0.3
TASK_TERM_WEIGHT = 1.0
SCREEN_TERM_WEIGHT = 0.3
ENTRY_LABELS = {"pc": "PC", "mobile": "모바일", "other": "그 밖"}


@dataclass(frozen=True)
class GuideChunk:
    """[안내서 청크]
    - task 하나 -> 답변 근거 글(text)과 M1 검색어
    - num은 안내서 화면 번호(스냅샷 매핑표 번호와 같음), 공통 task는 None
    - 매핑표와는 scr_id·param으로 이음 : 관리자가 행을 바꿔도 번호와 무관"""

    id: str
    num: int | None
    screen: str | None
    scr_id: str | None
    param: str | None
    title: str
    text: str
    task_terms: tuple[str, ...]
    screen_terms: tuple[str, ...]


def _guide_text(chunk_id: str, task: dict, screen: dict | None) -> str:
    lines = [f"[{chunk_id}] {screen['name'] if screen else '공통'} · {task['task']}"]
    if screen:
        lines.append(f"화면 설명: {screen['summary']}")
        for key, label in ENTRY_LABELS.items():
            for entry in (screen.get("entry") or {}).get(key) or ():
                lines.append(f"들어가는 길({label}): {entry}")
        if screen.get("status") not in (None, "정상"):
            ready = ", ".join(screen.get("not_ready") or ())
            suffix = f" (준비 중: {ready})" if ready else ""
            lines.append(f"준비 상태: {screen['status']}{suffix}")
    lines += [f"{i}. {step}" for i, step in enumerate(task["steps"], 1)]
    lines += [f"- {note}" for note in task.get("notes") or ()]
    return "\n".join(lines)


def _guide_chunk(task: dict, screen: dict | None, keywords: dict) -> GuideChunk:
    key = (screen["scr_id"], screen.get("param")) if screen else None
    screen_terms = (screen["name"], *keywords.get(key, ())) if screen else ()
    return GuideChunk(
        id=task["id"],
        num=screen["num"] if screen else None,
        screen=screen["name"] if screen else None,
        scr_id=screen["scr_id"] if screen else None,
        param=screen.get("param") if screen else None,
        title=task["task"],
        text=_guide_text(task["id"], task, screen),
        task_terms=(task["task"], *(task.get("faq_keywords") or ())),
        screen_terms=screen_terms,
    )


def guide_chunks() -> tuple[GuideChunk, ...]:
    return _guide_chunks(routing_table())


@lru_cache(maxsize=2)
def _guide_chunks(table: tuple[RouteRow, ...]) -> tuple[GuideChunk, ...]:
    # FN-AIM-002-02 : 사용법 안내서(data/guide/*.yaml). 순서 = 공통 task, 화면 num 순
    # 화면 검색어 = 같은 화면(scr_id·param) 행들의 지시어
    keywords: dict[tuple[str, str | None], tuple[str, ...]] = {}
    for row in table:
        key = (row.scr_id, row.param)
        keywords[key] = (*keywords.get(key, ()), *row.keywords)
    common: list[dict] = []
    screens: list[dict] = []
    for path in sorted(GUIDE_DIR.glob("*.yaml")):
        data = _load(f"guide/{path.name}")
        common += data.get("common") or ()
        screens += data.get("screens") or ()
    chunks = [_guide_chunk(task, None, keywords) for task in common]
    for screen in sorted(screens, key=lambda s: s["num"]):
        chunks += [_guide_chunk(task, screen, keywords) for task in screen["tasks"]]
    return tuple(chunks)


def find_guide(chunk_id: str | None) -> GuideChunk | None:
    return next((chunk for chunk in guide_chunks() if chunk.id == chunk_id), None)


def _guide_key(text: str) -> str:
    # 라우팅과 같은 공백 제거 + 영문 대소문자 무시("ai 버튼" = "AI 버튼")
    return _compact(text).lower()


def _guide_index() -> dict[str, tuple[tuple[int, float], ...]]:
    return _guide_index_of(guide_chunks())


@lru_cache(maxsize=2)
def _guide_index_of(chunks: tuple[GuideChunk, ...]) -> dict[str, tuple[tuple[int, float], ...]]:
    # 검색어 -> (청크 순번, 가중치). 2글자 미만 검색어 제외
    index: dict[str, list[tuple[int, float]]] = {}
    for pos, chunk in enumerate(chunks):
        for terms, weight in (
            (chunk.task_terms, TASK_TERM_WEIGHT),
            (chunk.screen_terms, SCREEN_TERM_WEIGHT),
        ):
            for term in {_guide_key(t) for t in terms}:
                if len(term) >= 2:
                    index.setdefault(term, []).append((pos, weight))
    return {term: tuple(posts) for term, posts in index.items()}


def search_guide(text: str) -> list[str]:
    # FN-AIM-002-02 : M1 키워드 색인. 입력에 든 검색어마다 글자 수 × 가중치, 상위 3개
    # 같은 점수면 안내서 앞쪽 청크. 점수 0이면 빈 목록(2단계 LLM 목차 선택으로)
    key = _guide_key(text)
    scores: dict[int, float] = {}
    for term, posts in _guide_index().items():
        if term in key:
            for pos, weight in posts:
                scores[pos] = scores.get(pos, 0.0) + len(term) * weight
    ranked = sorted(scores, key=lambda pos: (-scores[pos], pos))[:GUIDE_TOP_K]
    chunks = guide_chunks()
    return [chunks[pos].id for pos in ranked]


def merge_guide(picked_id: str | None, text: str) -> list[str]:
    # FN-AIM-002-02 : LLM이 목차에서 고른 청크를 앞에, M1 결과를 중복 없이 뒤에(최대 3개)
    # M1이 엉뚱한 청크를 잡아도 목차 선택을 버리지 않는다. 없는 번호는 버린다
    picked = find_guide(picked_id)
    ids = [picked.id] if picked else []
    ids += [chunk_id for chunk_id in search_guide(text) if chunk_id not in ids]
    return ids[:GUIDE_TOP_K]


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


# 지금 시각을 뜻하는 말 : 날짜는 오늘, 시각을 말하지 않았으면 지금 (2026-11-13)
_NOW_WORDS = r"방금|지금|아까|금방"

_RELATIVE_DAYS = {"오늘": 0, "내일": 1, "모레": 2, "글피": 3, "어제": -1, "그제": -2, "그저께": -2}

# 순서대로 대조, 맞은 자리는 가림 (뒤 규칙의 재판독 방지). 띄어쓰기 허용
_DATE_RULES = (
    (r"(\d{4})-(\d{1,2})-(\d{1,2})", lambda m, t: _ymd(int(m[1]), int(m[2]), int(m[3]))),
    (r"(이번|다음|지난)\s*주\s*([월화수목금토일])요일", lambda m, t: _week_day(t, m[1], m[2])),
    (r"다음\s*달\s*(\d{1,2})\s*일", lambda m, t: _next_month_day(t, int(m[1]))),
    (r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", lambda m, t: _ymd(t.year, int(m[1]), int(m[2]))),
    (r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])", lambda m, t: _ymd(t.year, int(m[1]), int(m[2]))),
    (r"(\d{1,3})\s*일\s*(후|뒤)", lambda m, t: t + timedelta(days=int(m[1]))),
    (
        r"오늘|내일|모레|글피|어제|그저께|그제",
        lambda m, t: t + timedelta(days=_RELATIVE_DAYS[m[0]]),
    ),
    # '방금·지금·아까·금방' : 오늘 (시각은 mentions_now로 지금, 2026-11-13 추가 요청)
    (_NOW_WORDS, lambda m, t: t),
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


# 돌려받은 확인 카드에 대한 짧은 답 (2026-11-13 채팅으로 확인) : 띄어쓰기·끝 문장부호를 뗀 문장 전체
ACTION_CONFIRM = "confirm"
ACTION_CANCEL = "cancel"
_YES = r"(응|어|네|넵|예|ㅇㅇ|ㅇㅋ|오케이|좋아요?|그래요?|맞아요?|확인)"
_DO = (
    r"(등록|수정|변경|저장|추가|기록|체크|완료|진행|그대로)"
    r"(해|해줘|해주세요|해줄래|해요|하자|해주라|ㄱ)?"
)
# 삭제 카드의 확인 말 (2026-11-25) : 삭제 카드가 없으면 service.py가 확인 말로 보지 않음
_DEL = (
    r"(삭제(해|해줘|해주세요|해줄래|해요|하자|ㄱ)?|지워(줘|주세요|줄래|요)?"
    r"|없애(줘|주세요|줄래)?)"
)
_CONFIRM = re.compile(rf"^(?:{_YES}(?:{_DO}|{_DEL})?|{_DO}|{_DEL})$")
_DELETE_WORD = re.compile(r"삭제|지워|지우|없애")
_PROCEED_WORD = re.compile(r"진행")
_NO = r"(아니|아니요|아뇨|아니야)"
_STOP = (
    r"(취소|취소해|취소해줘|취소해주세요|됐어|됐어요|그만|그만해"
    r"|하지마|하지마요|안할래|등록하지마|저장하지마|등록안해|안해|삭제하지마|지우지마|삭제안해)"
)
_CANCEL = re.compile(rf"^(?:{_NO}{_STOP}?|{_STOP})$")


def _compact_reply(text: str) -> str:
    return re.sub(r"[\s.!~?ㅎㅋ^]+", "", text)


# 동사형 명령 (2026-11-26 팀 합의) : 첫 턴에 확인 말 없이 바로 실행. 문장 끝이 쓰기 명령형
# 하다형 동사 + 해 줘 등, 어형 동사(바꿔·지워 …)는 꼬리 없이도, 끝이 맨 "기록"이어도 명령
_RUN_HA = r"(등록|수정|변경|저장|추가|기록|체크|완료|삭제)"
_RUN_EO = r"(바꿔|바꾸어|고쳐|넣어|적어|남겨|지워|없애|올려|잡아)"
_RUN_ASK = r"(해줄래|해줄래요|해주실래요|줄래|줄래요|주실래요)"
_RUN_HA_TAIL = rf"(해줘|해줘요|해주세요|해주라|해둬|해놔|해|해요|하자|ㄱ|{_RUN_ASK})"
_RUN_EO_TAIL = rf"(줘|줘요|주세요|주라|둬|놔|요|{_RUN_ASK})?"
_RUN_NOW = re.compile(rf"(?:{_RUN_HA}{_RUN_HA_TAIL}|{_RUN_EO}{_RUN_EO_TAIL}|기록)$")
_RUN_ASKING = re.compile(rf"{_RUN_ASK}$")


def commands_now(text: str) -> bool:
    """쓰기 명령형 문장("…기록해 줘"·"…지워 줘"·"…4kg 기록") : 빈 칸이 없으면 첫 턴에 바로 실행
    - 물음표로 끝나면 "해 줄래?"처럼 부탁꼴만 명령, "등록해?"는 물음
    - 동사 없는 말("코코 체중 4kg")·물음꼴("등록할까?")은 거짓"""
    compact = _compact_reply(text)
    if not _RUN_NOW.search(compact):
        return False
    asking = text.rstrip().endswith("?")
    return not asking or bool(_RUN_ASKING.search(compact))


def says_delete(text: str) -> bool:
    """삭제 동사(삭제·지워·없애)가 든 말 : 삭제 카드는 이 말이어야 실행 (2026-11-25)"""
    return bool(_DELETE_WORD.search(_compact_reply(text)))


def says_proceed(text: str) -> bool:
    """'진행' 말 : 등록·삭제가 섞인 카드의 확인 말"""
    return bool(_PROCEED_WORD.search(_compact_reply(text)))


def action_reply_kind(text: str) -> str | None:
    """확인 말이면 ACTION_CONFIRM, 취소 말이면 ACTION_CANCEL, 그 밖(칸 고치기 등)이면 None"""
    compact = re.sub(r"[\s.!~?ㅎㅋ^]+", "", text)
    if _CONFIRM.match(compact):
        return ACTION_CONFIRM
    if _CANCEL.match(compact):
        return ACTION_CANCEL
    return None


def mentions_now(text: str) -> bool:
    """문장에 '방금·지금·아까·금방'이 있는지 : 날짜·시각을 비우면 오늘·지금으로 채운다"""
    return re.search(_NOW_WORDS, text) is not None


def now_kst() -> datetime:
    return datetime.now(KST)


def mentions_date(text: str) -> bool:
    """문장에 날짜 말("어제"·"10월 3일"·"다음 주 화요일" 등)이 있는지 (_DATE_RULES와 같은 규칙)"""
    return any(re.search(pattern, text) for pattern, _ in _DATE_RULES)


def said_dates(text: str, today: date) -> list[date]:
    """문장의 날짜 말을 날짜로 (_DATE_RULES 순서, 맞은 자리는 가림). 같은 날은 한 번, 나온 순서대로
    - 쓰기 카드에서 LLM이 비운 날짜를 채울 때 씀(2026-11-23, '오늘 음수량 50ml'에 날짜 빔)"""
    masked = text
    found: list[tuple[int, date]] = []
    for pattern, convert in _DATE_RULES:
        for m in re.finditer(pattern, masked):
            day = convert(m, today)
            masked = _mask(masked, *m.span())
            if day is not None:
                found.append((m.start(), day))
    days: list[date] = []
    for _, day in sorted(found, key=lambda item: item[0]):
        if day not in days:
            days.append(day)
    return days


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


# READ 도구 결과 (docs/design/tool-calling.md 5절 개인 데이터 범위 : 날짜·이름·수치만)
# 6000자 : 미측정 기준(2026-11-06 LJS 결정)
READ_RESULT_MAX_CHARS = 6000
READ_TRUNCATED = "\n(결과가 길어 앞부분만 보냄)"
# Java 공개 API 실패 : 답변 오류 대신 LLM이 화면 확인 안내
READ_FAILED = "기록을 불러오지 못함. 앱의 해당 화면에서 확인하라고 안내한다."
# 결과를 받은 뒤 읽기 도구가 아닌 도구를 고름 : 실행하지 않고 받은 결과로 답하게
READ_NOT_RUN = "이 도구는 실행하지 않음. 앞서 받은 결과만으로 답한다."
# 첫 응답에 읽기 도구와 같이 고른 카드·이동 (2026-11-26 동시 도구) : 결과를 본 뒤 다시 고르게
READ_LATER = "이 도구는 아직 실행하지 않음. 읽은 결과를 본 뒤 필요하면 다시 고른다."
# 한 턴 도구 상한에 걸림 : 더 부르지 않고 지금까지 받은 결과로 답하게 (에이전트 루프)
TOOL_LIMIT_REACHED = (
    "이 턴에는 도구를 더 부를 수 없어 실행하지 않음. 지금까지 받은 결과만으로 답하고, "
    "못 확인한 것은 앱 화면에서 보라고 안내한다."
)


# 에이전트 ③ (docs/design/agent.md 2·5·6절, 2026-11-26)
# 카드 뒤 할 일이 남은 문장 : 쓰기 동사 뒤 이어 주는 말 + 다른 일(읽기·비교·다른 쓰기)
_AGENT_MORE = re.compile(
    r"(하고|한\s*뒤|한\s*다음|하고\s*나서|그리고|고\s*나서|만들고|넣고|바꾸고|고치고|지우고|잡고)"
    r".*(알려|확인|비교|보여|봐|어때|어떤지|얼마|늘었|줄었|넣어|추가|등록|기록|만들어|바꿔|수정)"
)
# 쓰기 동사 : 원래 문장에 쓰기가 몇 개 있는지(말하지 않은 쓰기 막기)
_WRITE_VERB = re.compile(
    r"기록|등록|추가|넣|만들|수정|바꾸|바꿔|변경|고쳐|삭제|지워|지우|체크|저장|잡아|잡고"
)


def agent_more(text: str) -> bool:
    """카드를 실행한 뒤 LLM이 할 일이 남았을 수 있는 문장인지 : 참일 때만 done.pending
    - "체중 4.2kg 기록하고 지난주보다 늘었는지 알려 줘"·"검진기록 만들고 수치도 넣어 줘" : 참
    - "산책 30분 기록해 줘" 같은 단순 명령 하나 : 거짓(지금 흐름과 같음)"""
    return _AGENT_MORE.search(text) is not None


# 쓰기 뒤 묻는 말 : 카드를 실행한 뒤 읽기·답이 남음 (에이전트 ④)
_AGENT_ASK = re.compile(
    r"(하고|한\s*뒤|한\s*다음|하고\s*나서|그리고|고\s*나서|만들고|넣고|바꾸고|고치고|지우고|잡고)"
    r".*(알려|확인|비교|보여|봐|어때|어떤지|얼마|늘었|줄었)"
)


def agent_pending(text: str, executed: int) -> bool:
    """done.pending을 줄 문장인지 (에이전트 ④, 2026-11-26)
    - executed : 이 턴에서 실행이 끝났거나 이번에 실행할 카드 수
    - 쓰기 뒤 묻는 말이 있거나(읽기·답이 남음) 문장의 쓰기 동사가 executed보다 많을 때만 참
    - "체중 기록하고 산책도 기록해 줘"를 카드 두 장으로 실행하면 거짓(남은 일 없음)"""
    if not agent_more(text):
        return False
    return _AGENT_ASK.search(text) is not None or write_count(text) > executed


# 쓰기 동사 + 이어 주는 말("기록하고"·"만들고") : 카드 뒤 다른 일이 이어지는 명령
_AGENT_COMMAND = re.compile(
    r"(기록하|등록하|추가하|수정하|변경하|삭제하|체크하|저장하|만들|넣|바꾸|고치|지우|잡)고"
)


def agent_command(text: str) -> bool:
    """에이전트 이어 가기용 명령 : "체중 4.2kg 기록하고 늘었는지 알려 줘"처럼 쓰기 동사 뒤 다른 일
    - 문장 끝이 읽기 말("알려 줘")이라 commands_now는 거짓이지만 앞 쓰기는 명령이다
    - 물음표로 끝나면 부탁꼴만(commands_now와 같음). 이어 가기 키가 있을 때만 쓴다"""
    compact = _compact_reply(text)
    if not _AGENT_COMMAND.search(compact) or not agent_more(text):
        return False
    asking = text.rstrip().endswith("?")
    return not asking or bool(_RUN_ASKING.search(compact))


def write_count(text: str) -> int:
    """문장 속 쓰기 동사 수 : 이어 가기에서 이미 실행한 카드 수보다 많을 때만 새 카드를 바로 실행"""
    return len(_WRITE_VERB.findall(text))


# 이어 가기 LLM에 주는 진행 기록 : 원래 질문 뒤에 붙임(회원이 새로 한 말이 아님)
AGENT_NOTES_HEAD = (
    "[이 턴 진행 기록 — 서버가 붙인 것, 회원이 새로 한 말이 아님]\n"
    "위 질문을 처리하던 중 확인 카드를 실행했고 결과는 아래와 같다."
)
AGENT_NOTES_TAIL = (
    "질문에서 남은 일이 있으면 이어서 도구를 부르고, 다 했으면 결과를 바탕으로 짧게 답한다. "
    "'실행 완료'인 일은 이미 저장된 것이다. 다시 하지 않고, "
    "저장 전이라거나 확인 말을 해 달라고 하지 않는다. "
    "'취소'·'다시 하지 않음'이라고 적힌 일도 다시 하지 않는다. "
    "번호 칸(…_sn)은 진행 기록과 읽기 결과에 나온 번호만 쓴다."
)
AGENT_READ_NOTE = "읽기 {tool} 결과:\n{result}"
# 실행 전에 읽은 결과 : 실행한 기록이 빠져 있으므로 답에 쓰려면 같은 읽기 도구를 다시 부르게
AGENT_STALE_READ_NOTE = (
    "읽기 {tool} 결과(쓰기 실행 전이라 방금 실행한 기록은 빠져 있음. "
    "답에 쓰려면 이 읽기 도구를 다시 부른다):"
)
AGENT_DONE_NOTE = "- 실행 완료: {label} ({tool}) 입력 {input}"
AGENT_DONE_DATA = " · 저장 결과 {data}"
AGENT_FIX_NOTE = (
    "- 실행 실패: {label} ({tool}) 입력 {input}. 다시 확인할 칸: {names}. "
    "이 칸만 고친 같은 도구를 한 번 부른다."
)
AGENT_FAILED_NOTE = "- 실행 실패: {label} ({tool}). 다시 하지 않음."
AGENT_CANCELED_NOTE = "- 회원이 취소: {label} ({tool}). 다시 하지 않음."
# 바로 실행하고 결과를 받아 이어 가는 카드(done.pending)의 tool_result : 남은 일은 지금 답하지 않음
AGENT_RUN_SHOWN = (
    "확인 카드를 만듦. 카드 내용: {summary}. 회원이 바로 하라고 했으므로 이 턴에 실행된다. "
    "질문의 남은 일(조회·비교 등)은 실행 결과를 받은 뒤 이어서 하므로 지금 답하지 않는다. "
    "확인을 묻지 말고 카드 내용을 짧게 보여 준 뒤 '등록하고 이어서 알려 드릴게요.'로 끝낸다. "
    "카드에서 확인하라거나 확인 말을 해 달라고 하지 않는다."
)
# 같은 쓰기 반복 막기 (6절 7번) : 이미 실행한 카드와 같은 도구·같은 값
AGENT_ALREADY_DONE = (
    "이 일은 이 턴에서 이미 실행했으므로 카드를 다시 만들지 않음. "
    "다시 저장하지 말고 지금까지의 결과로 답한다."
)
# 이어 갈 일이 없음(취소만·고칠 수 없는 실패만) : LLM 없이 저장하는 짧은 글
AGENT_STOPPED = "남은 일은 이어서 하지 않았어요."

# 2026-11-27 frontend-dc ② : 바로 실행된 턴의 답에 확인 말 안내("'등록해 줘'라고 말해")가 남음
_ASKS_CONFIRM = re.compile(r"'(등록|수정|삭제|진행)해\s*줘'\s*라고")


def asks_confirm(text: str) -> bool:
    """답 글이 확인 말을 해 달라고 안내하는지 : 바로 실행(execute)된 턴이면 어긋난 안내"""
    return _ASKS_CONFIRM.search(text) is not None


# 2026-11-27 frontend-dc ③ : 이력에 같은 결과 글(✔)이 있는 쓰기는 바로 실행하지 않고 확인 카드로
WRITE_REPEAT_NOTICE = (
    "방금 같은 기록을 저장했어요. 한 번 더 저장하려면 '등록해 줘'라고 말해 주세요."
)
# READ 뒤 카드 길 : LLM에 주는 tool_result(ACTION_SHOWN 뒤에 붙임)
WRITE_REPEAT_SHOWN = (
    "이 대화에서 방금 같은 내용을 저장했으므로 바로 실행하지 않음. "
    "같은 기록을 이미 저장했다고 먼저 알린다."
)


_DATE_HEAD = re.compile(r"\d{4}-\d{2}-\d{2}(?![\d])")


def _with_weekday(text: str) -> str:
    # 날짜(일시)로 시작하는 값 : LLM이 요일을 직접 계산하지 않게 (요일) 붙임
    match = _DATE_HEAD.match(text)
    if match is None:
        return text
    try:
        day = date.fromisoformat(match.group())
    except ValueError:
        return text
    return f"{match.group()} ({WEEKDAYS[day.weekday()]}){text[match.end() :]}"


def _with_weekdays(value: object) -> object:
    # 날짜에 요일을 붙임. 내용(…Cn) 칸(알레르기·메모 등)도 그대로 넘김(2026-11-25 결정)
    if isinstance(value, dict):
        return {k: _with_weekdays(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_with_weekdays(item) for item in value]
    if isinstance(value, str):
        return _with_weekday(value)
    return value


def read_result_text(data: object, max_chars: int = READ_RESULT_MAX_CHARS) -> str:
    text = json.dumps(_with_weekdays(data), ensure_ascii=False, default=str)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + READ_TRUNCATED


# 반려동물 수정 카드의 목록 칸(알레르기·질환·특징) 합치기 (2026-11-25)
# Java PATCH는 칸 전체를 바꾸므로, 말한 항목을 지금 값에 더하거나 빼서 카드에 싣는다
LIST_ADD = "add"
LIST_REMOVE = "remove"
LIST_REPLACE = "replace"
_LIST_REMOVE_WORDS = re.compile(r"빼|삭제|지워|지우|제거|없애|없어졌|나았")
_LIST_ADD_WORDS = re.compile(r"추가|넣어|넣고|더해|생겼|도\s*있")
_LIST_REPLACE_WORDS = re.compile(r"바꿔|바꾸|변경|고쳐|수정|만\s*(남|있)")


def list_edit_mode(text: str) -> str:
    """빼는 말 > 더하는 말 > 바꾸는 말. 아무것도 없으면 더하기(지금 값을 잃지 않음)"""
    if _LIST_REMOVE_WORDS.search(text):
        return LIST_REMOVE
    if _LIST_ADD_WORDS.search(text):
        return LIST_ADD
    if _LIST_REPLACE_WORDS.search(text):
        return LIST_REPLACE
    return LIST_ADD


def _list_items(value: object) -> list[str]:
    if not isinstance(value, str):
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _list_key(item: str) -> str:
    return re.sub(r"\s+", "", item)


def merge_list(current: object, said: object, mode: str) -> str:
    """쉼표 목록 합치기 : 같은 항목은 띄어쓰기만 달라도 하나로. 다 빼면 빈 글(Java가 비움)"""
    new = _list_items(said)
    if mode == LIST_REPLACE:
        return ",".join(new)
    old = _list_items(current)
    if mode == LIST_REMOVE:
        gone = {_list_key(item) for item in new}
        return ",".join(item for item in old if _list_key(item) not in gone)
    keys = {_list_key(item) for item in old}
    added = []
    for item in new:
        if _list_key(item) not in keys:
            keys.add(_list_key(item))
            added.append(item)
    return ",".join(old + added)
