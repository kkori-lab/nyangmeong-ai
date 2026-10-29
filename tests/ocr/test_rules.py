import pytest

from app.ocr.rules import layout_text


def symbol(text: str, x: int, y: int, width: int = 10, height: int = 20) -> dict:
    vertices = [
        {"x": x, "y": y},
        {"x": x + width, "y": y},
        {"x": x + width, "y": y + height},
        {"x": x, "y": y + height},
    ]
    return {"text": text, "boundingBox": {"vertices": vertices}}


def word(text: str, x: int, y: int, gaps: dict[int, int] | None = None) -> dict:
    """글자 폭 10, 붙여 쓴 낱말. gaps={i: n}이면 i번째 글자 앞을 n만큼 띄운다"""
    symbols, cursor = [], x
    for i, ch in enumerate(text):
        cursor += (gaps or {}).get(i, 0)
        symbols.append(symbol(ch, cursor, y))
        cursor += 10
    return {"symbols": symbols}


def annotation(*words: dict, text: str = "") -> dict:
    # Vision은 칸(블록)마다 따로 읽는다 : 낱말마다 다른 블록에 둔다
    blocks = [{"paragraphs": [{"words": [w]}]} for w in words]
    return {"text": text, "pages": [{"blocks": blocks}]}


def test_다른_블록으로_읽힌_품목과_금액을_같은_줄로_잇는다() -> None:
    result = layout_text(
        annotation(
            word("SDMA", 0, 100),
            word("요검사", 0, 140),
            word("60,000", 300, 102),
            word("100,000", 300, 141),
        )
    )
    assert result == "SDMA 60,000\n요검사 100,000"


@pytest.mark.parametrize(
    ("gaps", "expected"),
    [
        # FN-AIM-008-06 : 수량 1과 금액이 한 낱말로 붙어도 글자 간격이 넓으면 나눈다
        ({1: 40}, "1 60,000"),
        # 간격이 좁으면 한 낱말(160,000)
        ({1: 2}, "160,000"),
    ],
)
def test_글자_간격으로_수량과_금액을_나눈다(gaps: dict[int, int], expected: str) -> None:
    assert layout_text(annotation(word("160,000", 0, 0, gaps))) == expected


def test_좁게_붙은_낱말은_띄우지_않는다() -> None:
    result = layout_text(annotation(word("메이", 0, 0), word("동물", 21, 0), word("센터", 100, 0)))
    assert result == "메이동물 센터"


def test_낱말_위치가_없으면_Vision_text를_쓴다() -> None:
    assert layout_text({"text": "청구서\n합계 1,000"}) == "청구서\n합계 1,000"
    assert layout_text({}) == ""
