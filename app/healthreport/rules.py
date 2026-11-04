import hashlib
import json
from datetime import date, datetime, timedelta, timezone

from app.healthreport.schemas import HealthReportInput

# 분석 기간(기준일 포함 14일)은 Java가 baseYmd로 자른다 : docs/api/internal.md
# 서비스 기준 시간대 (자정 갱신 기준일)
KST = timezone(timedelta(hours=9))

TITLE_MAX = 20
TIP_MAX = 40
TIPS_MAX = 3

# MANC0007 "진단 아님, 수의사 상담 안내 포함" : LLM에 맡기지 않고 항상 붙인다
NOTICE = "AI 코멘트는 진단이 아니에요. 걱정되는 변화가 있으면 수의사와 상담해 주세요."

# 14일 기록이 하나도 없을 때 (LLM 미호출·저장 안 함)
DATA_LACK_TITLE = "기록을 기다리고 있어요"
DATA_LACK_TIPS = ["체중·식사량·음수량·산책을 기록하면 AI가 최근 건강을 분석해 드려요"]


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
    return title.strip()[:TITLE_MAX]


def clip_tips(tips: list[str]) -> list[str]:
    cleaned = [t.strip()[:TIP_MAX] for t in tips if t and t.strip()]
    return cleaned[:TIPS_MAX]
