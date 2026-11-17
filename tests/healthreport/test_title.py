from app.healthreport import rules


def test_지금_뒤에_다른_말이_붙으면_떼지_않고_고정_문구() -> None:
    for title in ("지금까지 잘 지내요", "지금껏 건강해요", "지금의 관리가 좋아요"):
        assert rules.clip_title(title) == rules.FALLBACK_TITLE


def test_지금도_지금처럼은_정리한다() -> None:
    assert rules.clip_title("지금도 잘 먹어요") == "잘 먹어요"
    assert rules.clip_title("지금처럼만 하면 돼요") == "평소처럼만 하면 돼요"
