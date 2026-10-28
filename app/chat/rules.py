import re
from dataclasses import dataclass
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
    # 키워드·사전은 공백을 뺀 문장에 대조한다("털 깎기" = "털깎기")
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
    # FN-AIM-004-08 : AI 분류 결과는 매핑표의 라우팅 가능 행에 있는 화면만 인정한다
    for row in routing_table():
        if row.routable and row.scr_id == scr_id and row.param == param:
            return row
    return None
