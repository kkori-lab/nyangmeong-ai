import re
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

import yaml

from app.checkup.schemas import LabResultItem
from app.core.response import AppError

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
MAX_PDF_BYTES = 10 * 1024 * 1024
PDF_SIGNATURE = b"%PDF-"
_NUMBER = re.compile(r"-?\d+(\.\d+)?")
# INSP_NVL 컬럼 크기 : 수치 decimal(15,4), 직접입력명 40자, 단위 20자
MAX_INT_DIGITS = 11
MAX_FRACTION_DIGITS = 4
MAX_DRCT_INPT_NM = 40
MAX_UNIT_NM = 20


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
def _items() -> list[dict]:
    # FN-HLT-007-02 : 드롭다운 12종과 공통코드(HLTG12)는 data/lab_items.yaml이 기준
    with (DATA_DIR / "lab_items.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)["items"]


@lru_cache
def _aliases() -> dict[str, str]:
    table: dict[str, str] = {}
    for item in _items():
        for name in [item["code"], *item["aliases"]]:
            table[_key(name)] = item["code"]
    return table


@lru_cache
def _codes() -> dict[str, str]:
    """표준 약어 → HLTG12 공통코드. 코드가 없는 항목(SDMA)은 빠진다"""
    return {item["code"]: item["cd"] for item in _items() if item.get("cd")}


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


def normalize_number(value: str | None) -> float | None:
    """숫자만 남긴다(쉼표·공백 제거). '<0.5'·'음성'이나 decimal(15,4)에 안 들어가면 null"""
    if value is None:
        return None
    text = re.sub(r"[\s,]", "", value)
    if not _NUMBER.fullmatch(text):
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    integer, _, fraction = text.lstrip("-").partition(".")
    if len(integer.lstrip("0")) > MAX_INT_DIGITS or len(fraction) > MAX_FRACTION_DIGITS:
        return None
    return float(number)


def is_blood(name: str, blood: bool) -> bool:
    """FN-HLT-007-05 : 12종은 혈액검사. 그 밖은 모델 판정"""
    return blood or is_standard(normalize_name(name))


def to_item(
    name: str | None,
    value: str | None,
    unit: str | None,
    ref_min: str | None,
    ref_max: str | None,
) -> LabResultItem | None:
    """FN-HLT-007-04 : 못 읽은 값은 null. 이름이 없으면 행을 만들지 않는다"""
    if not name or not name.strip():
        return None
    code = normalize_name(name)
    # INSP_NVL : 공통코드가 있으면 코드, 없으면 직접입력명(40자)
    artcl_cd = _codes().get(code)
    drct_inpt_nm = None if artcl_cd else code[:MAX_DRCT_INPT_NM]
    low, high = normalize_number(ref_min), normalize_number(ref_max)
    # FN-HLT-007-02 : 참고범위는 하한·상한을 함께, 한쪽만 읽히면 둘 다 비운다
    if low is None or high is None:
        low = high = None
    unit_nm = unit.strip() if unit and unit.strip() else None
    if unit_nm and len(unit_nm) > MAX_UNIT_NM:
        unit_nm = None
    return LabResultItem(
        insp_artcl_cd=artcl_cd,
        insp_artcl_drct_inpt_nm=drct_inpt_nm,
        rslt_nvl=normalize_number(value),
        unit_nm=unit_nm,
        ref_llmt_nvl=low,
        ref_uplmt_nvl=high,
    )
