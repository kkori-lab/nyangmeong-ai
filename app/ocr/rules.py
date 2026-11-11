import re

# 낱말 분리 기준 : 글자 간격이 글자 폭의 이 배수 초과 (수량 "1"과 금액이 붙는 경우)
SYMBOL_GAP_RATIO = 0.8
# 같은 줄 기준 : 낱말 높이 중심 차이가 높이의 이 배수 이내
ROW_RATIO = 0.5
# 띄어쓰기 기준 : 같은 줄 낱말 간격이 높이의 이 배수 초과
SPACE_RATIO = 0.3


def _box(bounding_box: dict) -> tuple[int, int, int, int]:
    xs = [v.get("x", 0) for v in bounding_box.get("vertices", [])] or [0]
    ys = [v.get("y", 0) for v in bounding_box.get("vertices", [])] or [0]
    return min(xs), max(xs), min(ys), max(ys)


def _tokens(page: dict) -> list[tuple[float, int, int, int, str]]:
    """(중심 y, 왼쪽 x, 오른쪽 x, 높이, 글자), 글자 간격이 크면 낱말 분리"""
    tokens = []
    for block in page.get("blocks", []):
        for paragraph in block.get("paragraphs", []):
            for word in paragraph.get("words", []):
                pieces: list[list[tuple[int, int, int, int, str]]] = [[]]
                for symbol in word.get("symbols", []):
                    x0, x1, y0, y1 = _box(symbol.get("boundingBox", {}))
                    current = pieces[-1]
                    if current and x0 - current[-1][1] > (x1 - x0) * SYMBOL_GAP_RATIO:
                        pieces.append(current := [])
                    current.append((x0, x1, y0, y1, symbol.get("text", "")))
                for piece in pieces:
                    if not piece:
                        continue
                    top = min(s[2] for s in piece)
                    bottom = max(s[3] for s in piece)
                    text = "".join(s[4] for s in piece)
                    tokens.append(
                        ((top + bottom) / 2, piece[0][0], piece[-1][1], bottom - top, text)
                    )
    return tokens


def layout_text(annotation: dict) -> str:
    """[Vision fullTextAnnotation -> 영수증 줄 모양 글자]
    - Vision text는 표의 칸을 따로 읽어 품목·금액 순서가 섞임 -> 낱말 위치로 줄 재구성
    - 낱말 위치 없으면 Vision text 그대로
    """
    tokens = [t for page in annotation.get("pages", []) for t in _tokens(page)]
    if not tokens:
        return annotation.get("text") or ""
    rows: list[tuple[float, list[tuple[int, int, int, str]]]] = []
    for y, x0, x1, height, text in sorted(tokens):
        if rows and abs(rows[-1][0] - y) < height * ROW_RATIO:
            rows[-1][1].append((x0, x1, height, text))
        else:
            rows.append((y, [(x0, x1, height, text)]))
    lines = []
    for _, words in rows:
        words.sort()
        line = words[0][3]
        for before, after in zip(words, words[1:], strict=False):
            line += (" " if after[0] - before[1] > before[2] * SPACE_RATIO else "") + after[3]
        lines.append(line)
    return "\n".join(lines)


# FN-AIM-008-06 : 최종 결제 금액 줄 (띄어쓰기 무시). 청구금액·합계·소계는 할인 전이라 넣지 않는다
PAID_WORDS = ("결제금액", "결제요청", "결제예정", "받을금액", "승인금액")
# 나눠 낸 영수증의 수단별 줄은 한 부분만이라 뺀다
PAID_EXCLUDE_WORDS = ("카드", "현금")
# 줄 끝 금액 : 364,000 / 364,000원. 날짜·시각 조각(2026-11-20, 12:30)은 금액으로 보지 않는다
LINE_END_AMOUNT = re.compile(r"(?<![\d,.\-/:])(\d{1,3}(?:,\d{3})+|\d+)\s*원?\s*$")


def paid_amount(text: str) -> int | None:
    """[OCR 글자 -> 결제 줄 금액]
    - 결제 단어가 있고 카드·현금이 없는 줄의 줄 끝 금액, 여럿이면 가장 아래 줄
    - 0원·줄 끝 금액 없음은 건너뜀, 결제 줄이 없으면 None
    """
    found = None
    for line in text.splitlines():
        compact = "".join(line.split())
        if not any(word in compact for word in PAID_WORDS):
            continue
        if any(word in compact for word in PAID_EXCLUDE_WORDS):
            continue
        match = LINE_END_AMOUNT.search(line)
        if match is None:
            continue
        amount = int(match.group(1).replace(",", ""))
        if amount > 0:
            found = amount
    return found
