import re

import pytest

from app.chat.rules import match_route, routing_table

ROUTABLE = [row for row in routing_table() if row.routable]


def test_매핑표_45행을_모두_읽는다():
    # FN-AIM-004-09 : 부록 A 전체(대표 칩·일반·제외)
    assert [row.no for row in routing_table()] == list(range(1, 46))


def test_매핑표_라우팅_가능_행은_화면_ID와_키워드가_있다():
    for row in ROUTABLE:
        assert re.fullmatch(r"SCR-[A-Z]{3}-\d{3}(-\d{2})?", row.scr_id), row.no
        assert row.keywords, row.no


def test_매핑표_대표_칩_7종이_모두_라우팅_대상이다():
    # FN-AIM-001-02 칩 7종 = 건강기록·동물병원·플레이스·커뮤니티·마이페이지·캐릭터·고객센터
    chips = {(row.scr_id, row.param) for row in ROUTABLE if row.no <= 7}
    assert chips == {
        ("SCR-HLT-011", None),
        ("SCR-HOS-001", "?cat=hospital"),
        ("SCR-HOS-001", None),
        ("SCR-CMU-001-01", None),
        ("SCR-MYP-001", None),
        ("SCR-MYP-010", None),
        ("SCR-CSC-001", None),
    }


@pytest.mark.parametrize(
    "scr_id",
    ["SCR-HLT-000", "SCR-HLT-001", "SCR-HLT-005", "SCR-HLT-007", "SCR-AIM-008", "SCR-COM-007"],
)
def test_매핑표_결번_종속_화면_대화창은_라우팅_대상이_아니다(scr_id):
    # FN-AIM-004-08 : 제외·결번 행은 매핑하지 않는다
    assert all(not row.scr_id.startswith(scr_id) for row in ROUTABLE)
    assert all(not row.scr_id.startswith("SCR-AIM") for row in ROUTABLE)


@pytest.mark.parametrize("row", ROUTABLE, ids=lambda row: f"No{row.no}")
def test_매핑표_행마다_첫_키워드를_넣으면_그_행_화면으로_간다(row):
    # FN-AIM-004-08 : 라우팅 대상 = 매핑표의 라우팅 가능 행 전체(칩 7종 한정 아님)
    matched = match_route(row.keywords[0])

    assert matched is not None
    assert (matched.scr_id, matched.param) == (row.scr_id, row.param)
