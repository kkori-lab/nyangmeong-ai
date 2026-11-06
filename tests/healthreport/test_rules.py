from datetime import date

from app.healthreport import rules
from app.healthreport.schemas import HealthReportInput
from tests.healthreport.fakes import BASE_YMD, sample_input


def test_키_순서와_목록_순서가_달라도_같은_해시() -> None:
    data = sample_input()
    reordered = HealthReportInput.model_validate(
        {
            **data.model_dump(by_alias=True),
            "weights": list(reversed(data.model_dump(by_alias=True)["weights"])),
        }
    )
    # dict 키 순서를 거꾸로 만든 입력
    flipped = HealthReportInput.model_validate(
        dict(reversed(list(data.model_dump(by_alias=True).items())))
    )

    assert rules.input_hash(BASE_YMD, data) == rules.input_hash(BASE_YMD, reordered)
    assert rules.input_hash(BASE_YMD, data) == rules.input_hash(BASE_YMD, flipped)


def test_값이_하나라도_다르면_다른_해시() -> None:
    assert rules.input_hash(BASE_YMD, sample_input(5.2)) != rules.input_hash(
        BASE_YMD, sample_input(5.1)
    )


def test_기준일이_다르면_다른_해시() -> None:
    data = sample_input()
    assert rules.input_hash(BASE_YMD, data) != rules.input_hash(date(2026, 11, 5), data)


def test_해시는_SHA_256_16진수_64자() -> None:
    value = rules.input_hash(BASE_YMD, sample_input())
    assert len(value) == 64
    int(value, 16)


def test_기록이_하나도_없으면_데이터_부족() -> None:
    assert not rules.has_data(HealthReportInput(pet_nm="나비", goal_bdwg=5.0))
    assert rules.has_data(sample_input())


def test_제목_20자_팁_3개_각_40자로_자른다() -> None:
    assert len(rules.clip_title("가" * 30)) == 20
    tips = rules.clip_tips(["나" * 50, " ", "다", "라", "마"])
    assert tips == ["나" * 40, "다", "라"]
