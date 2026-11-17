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


def test_제목은_20자로_자르고_팁은_15자_넘으면_버리고_3개까지() -> None:
    assert len(rules.clip_title("가" * 30)) == 20
    tips = rules.clip_tips(["나" * 16, " ", "다" * 15, "라", "마", "바"])
    assert tips == ["다" * 15, "라", "마"]


def test_팁이_모두_버려지면_고정_팁_하나() -> None:
    assert rules.clip_tips(["산책을 매일 꾸준히 하고 있어서 아주 좋아요"]) == [rules.FALLBACK_TIP]
    assert rules.clip_tips([]) == [rules.FALLBACK_TIP]


def test_고정_팁은_모두_15자_이하() -> None:
    for tip in [*rules.DATA_LACK_TIPS, rules.FALLBACK_TIP]:
        assert len(tip) <= rules.TIP_MAX
    assert len(rules.FALLBACK_TITLE) <= rules.TITLE_MAX


def test_제목_앞머리_지금을_정리한다() -> None:
    assert rules.clip_title("지금처럼 건강해요") == "평소처럼 건강해요"
    assert rules.clip_title("지금 물을 더 마셔요") == "물을 더 마셔요"
    assert rules.clip_title("지금은 잘 지내요") == "잘 지내요"
    assert rules.clip_title(" 지금 ") == rules.FALLBACK_TITLE
    assert rules.clip_title("건강해요") == "건강해요"
