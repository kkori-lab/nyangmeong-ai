import pytest

from app.checkup import rules
from app.core.response import AppError

PDF = b"%PDF-1.7\n" + b"0" * 16


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("Creatinine", "CREA"),
        ("CRE", "CREA"),
        ("cre", "CREA"),
        ("크레아티닌(CREA)", "CREA"),
        ("ALT(GPT)", "ALT"),
        ("Blood Urea Nitrogen", "BUN"),
        ("WBC", "WBC"),
        ("혈당", "GLU"),
    ],
)
def test_12종_별칭을_표준_약어로_맞춘다(name: str, code: str) -> None:
    assert rules.normalize_name(name) == code


def test_목록_밖_항목은_결과지_표기_그대로() -> None:
    assert rules.normalize_name(" Cholesterol ") == "Cholesterol"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1.2", 1.2),
        ("1,234", 1234.0),
        (" 45 ", 45.0),
        ("<0.5", None),
        ("음성", None),
        (None, None),
        ("1.23456", None),
        ("123456789012", None),
    ],
)
def test_숫자만_남기고_decimal_15_4에_안_들어가면_null(
    value: str | None, expected: float | None
) -> None:
    assert rules.normalize_number(value) == expected


def test_드롭다운_항목은_HLTG12_공통코드() -> None:
    item = rules.to_item("Creatinine", "1.2", "mg/dL", "0.5", "1.8")
    assert item is not None
    assert (item.insp_artcl_cd, item.insp_artcl_drct_inpt_nm) == ("HLTC0030", None)
    assert (item.rslt_nvl, item.ref_llmt_nvl, item.ref_uplmt_nvl) == (1.2, 0.5, 1.8)


def test_HLTG12에_코드가_없는_SDMA는_직접입력명() -> None:
    item = rules.to_item("Symmetric Dimethylarginine", "16", "ug/dL", None, None)
    assert item is not None
    assert (item.insp_artcl_cd, item.insp_artcl_drct_inpt_nm) == (None, "SDMA")


def test_목록_밖_항목은_직접입력명_40자() -> None:
    item = rules.to_item("가" * 50, "1", None, None, None)
    assert item is not None
    assert item.insp_artcl_cd is None
    assert item.insp_artcl_drct_inpt_nm == "가" * 40


def test_참고범위가_한쪽만_있으면_둘_다_null() -> None:
    item = rules.to_item("CREA", "1.2", "mg/dL", "0.5", None)
    assert item is not None
    assert (item.ref_llmt_nvl, item.ref_uplmt_nvl) == (None, None)


def test_단위가_20자를_넘으면_null() -> None:
    item = rules.to_item("CREA", "1.2", "x" * 21, None, None)
    assert item is not None
    assert item.unit_nm is None


def test_12종은_모델이_혈액검사가_아니라고_해도_혈액검사() -> None:
    assert rules.is_blood("Glucose", False) is True


def test_목록_밖_비혈액_항목은_혈액검사_아님() -> None:
    assert rules.is_blood("요비중", False) is False


def test_이름이_없으면_행을_만들지_않는다() -> None:
    assert rules.to_item(None, "1", None, None, None) is None
    assert rules.to_item("  ", "1", None, None, None) is None


def test_PDF는_통과() -> None:
    rules.validate_pdf(PDF, "result.PDF")


@pytest.mark.parametrize(
    ("data", "name"),
    [
        (PDF, "result.png"),
        (PDF, "result"),
        (b"\x89PNG\r\n\x1a\n" + b"0" * 16, "result.pdf"),
    ],
)
def test_확장자와_실제_형식이_다르면_FILE_TYPE_NOT_ALLOWED(data: bytes, name: str) -> None:
    with pytest.raises(AppError) as error:
        rules.validate_pdf(data, name)
    assert error.value.code == "FILE_TYPE_NOT_ALLOWED"
    assert error.value.http_code == 400


def test_10MB_초과는_FILE_SIZE_EXCEEDED() -> None:
    with pytest.raises(AppError) as error:
        rules.validate_pdf(PDF + b"0" * rules.MAX_PDF_BYTES, "result.pdf")
    assert error.value.code == "FILE_SIZE_EXCEEDED"
