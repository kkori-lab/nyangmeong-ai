import hashlib
import json
from datetime import date, datetime, timedelta, timezone

from app.healthreport.schemas import HealthReportInput

# 분석 기간(기준일 포함 14일)은 Java가 baseYmd로 자른다 : docs/api/internal.md
# 서비스 기준 시간대 (자정 갱신 기준일)
KST = timezone(timedelta(hours=9))

TITLE_MAX = 20
TIP_MAX = 15
TIPS_MAX = 3

# LLM 팁이 모두 길이 초과로 버려졌을 때
FALLBACK_TIP = "기록을 꾸준히 이어 가요"
# 제목 앞머리 "지금"을 떼고 남은 게 없을 때 : 화면은 "{이름}는 지금 ___"
FALLBACK_TITLE = "건강을 살피고 있어요"

# MANC0007 "진단 아님, 수의사 상담 안내 포함" : LLM에 맡기지 않고 항상 붙인다
NOTICE = "AI 코멘트는 진단이 아니에요. 걱정되는 변화가 있으면 수의사와 상담해 주세요."

# 14일 기록이 하나도 없을 때 (LLM 미호출·저장 안 함)
DATA_LACK_TITLE = "기록을 기다리고 있어요"
DATA_LACK_TIPS = ["기록하면 분석해 드려요"]


def today_kst() -> date:
    return datetime.now(KST).date()


def has_data(data: HealthReportInput) -> bool:
    return any(
        (data.weights, data.meals, data.waters, data.walks, data.stools, data.insp_out_of_range)
    )


def input_hash(base_ymd: date, data: HealthReportInput) -> str:
    """기준일 + 분석 입력의 SHA-256 : 키·목록 순서와 무관 (값이 하나라도 다르면 다른 해시)"""
    payload = {
        "baseYmd": base_ymd.isoformat(),
        "input": data.model_dump(mode="json", by_alias=True),
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _canonical(value: object) -> str:
    return json.dumps(_normalize(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _normalize(value: object) -> object:
    # 목록은 원소의 정규 문자열로 정렬 : Java 조회 순서가 바뀌어도 같은 해시
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return sorted((_normalize(v) for v in value), key=_canonical)
    return value


def clip_title(title: str) -> str:
    """화면 "{이름}는 지금 ___"에 "지금"이 겹치지 않게 앞머리 "지금"을 정리한 뒤 자른다"""
    cleaned = title.strip()
    if cleaned.startswith("지금"):
        rest = cleaned[len("지금") :]
        if rest.startswith("처럼"):
            cleaned = "평소" + rest
        elif rest == "" or rest[0].isspace() or rest[:2] in ("은 ", "도 "):
            # "지금 …"·"지금은 …"·"지금도 …"만 뗀다
            cleaned = rest.lstrip().removeprefix("은 ").removeprefix("도 ").strip()
        else:
            # "지금까지"·"지금의"·"지금껏" 등 : 떼면 문장이 깨지므로 고정 문구로
            cleaned = FALLBACK_TITLE
    return (cleaned or FALLBACK_TITLE)[:TITLE_MAX]


def clip_tips(tips: list[str]) -> list[str]:
    # 길이 초과 팁은 중간에서 자르지 않고 버린다 (잘린 문장이 화면에 나가지 않게)
    cleaned = [t.strip() for t in tips if t and t.strip()]
    kept = [t for t in cleaned if len(t) <= TIP_MAX]
    return kept[:TIPS_MAX] or [FALLBACK_TIP]
