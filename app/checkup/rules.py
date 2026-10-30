import re
from functools import lru_cache
from pathlib import Path

import yaml

from app.checkup.schemas import LabResultItem
from app.core.response import AppError

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
MAX_PDF_BYTES = 10 * 1024 * 1024
PDF_SIGNATURE = b"%PDF-"
_NUMBER = re.compile(r"-?\d+(\.\d+)?")


def validate_pdf(data: bytes, file_name: str | None) -> None:
    """FN-HLT-005-04 : 확장자 .pdf와 실제 형식(%PDF-)을 함께 검증, 10MB 이하 (REQ-NFR-003)"""
    if len(data) > MAX_PDF_BYTES:
        raise AppError("FILE_SIZE_EXCEEDED", 400, "파일 용량은 10MB 이하여야 합니다.")
    _, dot, extension = (file_name or "").rpartition(".")
    if not dot or extension.lower() != "pdf" or not data.startswith(PDF_SIGNATURE):
        raise AppError("FILE_TYPE_NOT_ALLOWED", 400, "검사결과지 PDF만 분석할 수 있습니다.")


def _key(name: str) -> str:
    return re.sub(r"[\s\-_.]", "", name).upper()


@lru_cache
def _aliases() -> dict[str, str]:
    # FN-HLT-007-02 : 드롭다운 12종은 data/lab_items.yaml이 기준
    with (DATA_DIR / "lab_items.yaml").open(encoding="utf-8") as f:
        items = yaml.safe_load(f)["items"]
    table: dict[str, str] = {}
    for item in items:
        for name in [item["code"], *item["aliases"]]:
            table[_key(name)] = item["code"]
    return table


def normalize_name(name: str) -> str:
    """12종이면 표준 약어, 아니면 결과지 표기 그대로. '크레아티닌(CREA)'처럼 괄호 안팎도 본다"""
    name = name.strip()
    candidates = [name]
    match = re.fullmatch(r"(.*?)\s*\((.*)\)\s*", name)
    if match:
        candidates += [match.group(1), match.group(2)]
    for candidate in candidates:
        code = _aliases().get(_key(candidate))
        if code:
            return code
    return name


def is_standard(code: str) -> bool:
    return code in _aliases().values()


def normalize_number(value: str | None) -> str | None:
    """숫자 문자열만 남긴다(쉼표·공백 제거). '<0.5'·'음성'처럼 숫자가 아니면 null"""
    if value is None:
        return None
    text = re.sub(r"[\s,]", "", value)
    return text if _NUMBER.fullmatch(text) else None


def to_item(
    name: str | None,
    value: str | None,
    unit: str | None,
    ref_min: str | None,
    ref_max: str | None,
    blood: bool,
) -> LabResultItem | None:
    """FN-HLT-007-04 : 못 읽은 값은 null. 이름이 없으면 행을 만들지 않는다"""
    if not name or not name.strip():
        return None
    code = normalize_name(name)
    low, high = normalize_number(ref_min), normalize_number(ref_max)
    # FN-HLT-007-02 : 참고범위는 최소·최대를 함께, 한쪽만 읽히면 둘 다 비운다
    if low is None or high is None:
        low = high = None
    # FN-HLT-007-05 : 12종은 혈액검사. 그 밖은 모델 판정
    blood_yn = "Y" if blood or is_standard(code) else "N"
    unit_nm = unit.strip() if unit and unit.strip() else None
    return LabResultItem(
        insp_artcl_nm=code,
        rslt_vl=normalize_number(value),
        unit_nm=unit_nm,
        ref_min_vl=low,
        ref_max_vl=high,
        blood_yn=blood_yn,
    )
