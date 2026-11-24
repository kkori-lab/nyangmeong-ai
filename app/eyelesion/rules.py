from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# 판정용 사진 : 긴 변 1024px (병변 세부가 보이게, Anthropic 이미지 상한·토큰 절약)
IMAGE_LONG_EDGE = 1024
MAX_FINDINGS = 3
# 등급에 쓰는 확신도 : LOW는 뺀다
USED_CNFDNC = ("HIGH", "MEDIUM")
RISK_ORDER = {"NONE": 0, "OBSERVE": 1, "VISIT": 2, "URGENT": 3}
CNFDNC_ORDER = {"HIGH": 0, "MEDIUM": 1}
NORMAL_RISK = "NONE"


@dataclass(frozen=True)
class Lesion:
    key: str
    name: str
    risk: str


@dataclass(frozen=True)
class LesionTable:
    """data/eye_lesions.yaml : 병변 목록·안내 문장·규칙 판"""

    rule_version: str
    lesions: tuple[Lesion, ...]
    notice: str
    guide: dict[str, tuple[str, ...]]

    def choices(self) -> list[tuple[str, str]]:
        return [(lesion.key, lesion.name) for lesion in self.lesions]

    def find(self, key: str) -> Lesion | None:
        return next((lesion for lesion in self.lesions if lesion.key == key), None)


@dataclass(frozen=True)
class Evaluation:
    rslt: str
    grade: str | None
    findings: tuple[tuple[Lesion, str], ...]
    guide: tuple[str, ...]


def parse_table(data: dict) -> LesionTable:
    lesions = tuple(Lesion(i["key"], i["name"], i["risk"]) for i in data["lesions"])
    for lesion in lesions:
        if lesion.risk not in RISK_ORDER:
            raise ValueError(f"알 수 없는 위험군: {lesion.key} {lesion.risk}")
    guide = {name: tuple(lines) for name, lines in data["guide"].items()}
    return LesionTable(str(data["rule_version"]), lesions, data["notice"], guide)


@lru_cache
def load_table() -> LesionTable:
    with (DATA_DIR / "eye_lesions.yaml").open(encoding="utf-8") as f:
        return parse_table(yaml.safe_load(f))


def evaluate(
    pet_eye: bool | None, findings: list[tuple[str, str]], table: LesionTable
) -> Evaluation:
    """판정 → 결과·등급. pet_eye None = 판정 없음(거절·깨진 출력)

    - 반려동물 눈이 아님 → NOT_PET_EYE
    - 목록 밖 키·확신도 LOW를 빼고 남은 병변이 없음 → UNCLEAR
    - 남은 병변 중 위험군 최고값이 등급 (이상 없음만이면 OBSERVE)
    """
    if pet_eye is None:
        return _without_grade("UNCLEAR", table)
    if not pet_eye:
        return _without_grade("NOT_PET_EYE", table)
    used: dict[str, tuple[Lesion, str]] = {}
    for key, cnfdnc in findings:
        lesion = table.find(key)
        if lesion is None or cnfdnc not in USED_CNFDNC:
            continue
        # 같은 키가 두 번 오면 높은 확신도만
        if key not in used or CNFDNC_ORDER[cnfdnc] < CNFDNC_ORDER[used[key][1]]:
            used[key] = (lesion, cnfdnc)
    if not used:
        return _without_grade("UNCLEAR", table)
    picked = list(used.values())
    # 다른 병변이 있으면 "이상 없음"은 뺀다
    if any(lesion.risk != NORMAL_RISK for lesion, _ in picked):
        picked = [p for p in picked if p[0].risk != NORMAL_RISK]
    picked.sort(key=lambda p: (-RISK_ORDER[p[0].risk], CNFDNC_ORDER[p[1]]))
    picked = picked[:MAX_FINDINGS]
    top = max(RISK_ORDER[lesion.risk] for lesion, _ in picked)
    grade = "OBSERVE" if top == RISK_ORDER[NORMAL_RISK] else _risk_name(top)
    return Evaluation("ANALYZED", grade, tuple(picked), table.guide.get(grade, ()))


def _without_grade(rslt: str, table: LesionTable) -> Evaluation:
    return Evaluation(rslt, None, (), table.guide.get(rslt, ()))


def _risk_name(order: int) -> str:
    return next(name for name, value in RISK_ORDER.items() if value == order)
