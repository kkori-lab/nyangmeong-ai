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
        ("1.2", "1.2"),
        ("1,234", "1234"),
        (" 45 ", "45"),
        ("<0.5", None),
        ("음성", None),
        (None, None),
    ],
)
def test_숫자_문자열만_남긴다(value: str | None, expected: str | None) -> None:
    assert rules.normalize_number(value) == expected


def test_참고범위가_한쪽만_있으면_둘_다_null() -> None:
    item = rules.to_item("CREA", "1.2", "mg/dL", "0.5", None, True)
    assert item is not None
    assert (item.ref_min_vl, item.ref_max_vl) == (None, None)


def test_참고범위가_양쪽이면_그대로() -> None:
    item = rules.to_item("CREA", "1.2", "mg/dL", "0.5", "1.8", True)
    assert item is not None
    assert (item.ref_min_vl, item.ref_max_vl) == ("0.5", "1.8")


def test_12종은_모델이_혈액검사가_아니라고_해도_혈액검사() -> None:
    item = rules.to_item("Glucose", "100", "mg/dL", None, None, False)
    assert item is not None
    assert item.blood_yn == "Y"


def test_목록_밖_비혈액_항목은_N() -> None:
    item = rules.to_item("요비중", "1.030", None, None, None, False)
    assert item is not None
    assert item.blood_yn == "N"


def test_이름이_없으면_행을_만들지_않는다() -> None:
    assert rules.to_item(None, "1", None, None, None, True) is None
    assert rules.to_item("  ", "1", None, None, None, True) is None


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
