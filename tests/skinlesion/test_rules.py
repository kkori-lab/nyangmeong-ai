import pytest

from app.skinlesion import rules

TABLE = rules.parse_table(
    {
        "rule_version": "test-1",
        "notice": "참고용",
        "lesions": [
            {"key": "normal", "name": "이상 없음", "risk": "NONE"},
            {"key": "dandruff", "name": "각질", "risk": "OBSERVE"},
            {"key": "scab", "name": "딱지", "risk": "OBSERVE"},
            {"key": "hair_loss", "name": "털 빠짐", "risk": "VISIT"},
            {"key": "lump", "name": "혹", "risk": "VISIT"},
            {"key": "wound", "name": "상처", "risk": "URGENT"},
        ],
        "guide": {
            "OBSERVE": ["관찰"],
            "VISIT": ["진료"],
            "URGENT": ["빨리"],
            "UNCLEAR": ["다시 찍기"],
            "NOT_PET_SKIN": ["피부 사진"],
        },
    }
)


def keys(result: rules.Evaluation) -> list[tuple[str, str]]:
    return [(lesion.key, cnfdnc) for lesion, cnfdnc in result.findings]


@pytest.mark.parametrize(
    ("findings", "rslt", "grade"),
    [
        ([("normal", "HIGH")], "ANALYZED", "OBSERVE"),  # 이상 없음만 → OBSERVE
        ([("dandruff", "MEDIUM")], "ANALYZED", "OBSERVE"),
        ([("dandruff", "HIGH"), ("hair_loss", "MEDIUM")], "ANALYZED", "VISIT"),  # 최고 위험군
        ([("wound", "MEDIUM"), ("dandruff", "HIGH")], "ANALYZED", "URGENT"),
        ([("wound", "LOW"), ("dandruff", "HIGH")], "ANALYZED", "OBSERVE"),  # LOW는 등급에서 뺌
        ([("wound", "LOW")], "UNCLEAR", None),  # LOW만
        ([("nope", "HIGH")], "UNCLEAR", None),  # 목록 밖 키
        ([], "UNCLEAR", None),
    ],
)
def test_evaluate_등급(findings, rslt, grade):
    result = rules.evaluate(True, findings, TABLE)
    assert (result.rslt, result.grade) == (rslt, grade)
    assert result.guide == TABLE.guide[grade or rslt]


def test_evaluate_반려동물_피부가_아니면_NOT_PET_SKIN():
    result = rules.evaluate(False, [("wound", "HIGH")], TABLE)
    assert (result.rslt, result.grade, result.findings) == ("NOT_PET_SKIN", None, ())
    assert result.guide == ("피부 사진",)


def test_evaluate_판정이_없으면_UNCLEAR():
    result = rules.evaluate(None, [], TABLE)
    assert (result.rslt, result.grade, result.guide) == ("UNCLEAR", None, ("다시 찍기",))


def test_evaluate_다른_병변이_있으면_이상_없음은_뺀다():
    result = rules.evaluate(True, [("normal", "HIGH"), ("scab", "MEDIUM")], TABLE)
    assert keys(result) == [("scab", "MEDIUM")]


def test_evaluate_위험군_높은_순_같으면_확신도_순_최대_3개():
    findings = [
        ("dandruff", "MEDIUM"),
        ("scab", "HIGH"),
        ("lump", "MEDIUM"),
        ("hair_loss", "HIGH"),
    ]
    result = rules.evaluate(True, findings, TABLE)
    assert keys(result) == [("hair_loss", "HIGH"), ("lump", "MEDIUM"), ("scab", "HIGH")]


def test_evaluate_같은_키가_두_번이면_높은_확신도():
    result = rules.evaluate(True, [("scab", "MEDIUM"), ("scab", "HIGH")], TABLE)
    assert keys(result) == [("scab", "HIGH")]


def test_parse_table_알_수_없는_위험군은_오류():
    data = {
        "rule_version": "x",
        "notice": "n",
        "lesions": [{"key": "a", "name": "A", "risk": "SEVERE"}],
        "guide": {},
    }
    with pytest.raises(ValueError):
        rules.parse_table(data)


def test_load_table_목록_파일이_규칙에_맞다():
    table = rules.load_table()
    assert table.rule_version
    assert table.notice
    assert table.find("normal") is not None
    assert len({lesion.key for lesion in table.lesions}) == len(table.lesions)
    for name in ("OBSERVE", "VISIT", "URGENT", "UNCLEAR", "NOT_PET_SKIN"):
        assert table.guide[name]
