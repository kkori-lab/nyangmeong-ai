from datetime import date

import pytest

from app.chat import rules
from app.chat.rules import clean_ai_fields, next_due, parse_register

# 화면설계서 SCR-AIM-012 예시의 기준일 : 2026-09-29(화)
TODAY = date(2026, 9, 29)
PETS = ["초코", "뭉치"]


def parse(text: str) -> dict:
    return parse_register(text, TODAY, PETS).values()


def test_일정_예시_병원_예방접종_다음주_화요일_오후_3시():
    # FN-AIM-012-02 : 화면설계서 ① → ② 카드 칸
    values = parse("다음 주 화요일 오후 3시에 메이 동물병원 예방접종 잡아줘")

    assert values == {
        "schdl_knd_cd": rules.SCHEDULE_HOSPITAL,
        "schdl_ymd": date(2026, 10, 6),
        "schdl_tm": "15:00",
        "ckup_type_cd": "HLTC0002",
        "hsptl_nm": "메이 동물병원",
    }


def test_케어_항목_예시_2주마다_발톱_깎기_지난주_토요일에_했어():
    # FN-AIM-012-07 : 화면설계서 ⑥. 주기가 있으면 케어 항목, "했어" 앞 날짜는 마지막으로 한 날
    values = parse("뭉치 2주마다 발톱 깎기 넣어줘, 지난주 토요일에 했어")

    assert values == {
        "care_artcl_nm": "발톱 깎기",
        "care_zone_cd": rules.ZONE_PERIODIC,
        "care_cycle_cd": rules.CYCLE_2W,
        "last_cmptn_ymd": date(2026, 9, 26),
    }
    due = next_due(rules.ZONE_PERIODIC, rules.CYCLE_2W, None, values["last_cmptn_ymd"])
    assert due == date(2026, 10, 10)


def test_필수_칸이_빌_때_예시_금요일에_병원_예약():
    # FN-AIM-012-05 : 화면설계서 ⑦. 병원명·검진유형은 비어 되묻는다
    values = parse("금요일에 병원 예약 잡아줘")

    assert values == {"schdl_knd_cd": rules.SCHEDULE_HOSPITAL, "schdl_ymd": date(2026, 10, 2)}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("4시로 바꿔줘", "16:00"),  # 오전·오후가 없는 1~7시는 오후
        ("오전 10시", "10:00"),
        ("2시 반", "14:30"),
        ("저녁 7시 20분", "19:20"),
        ("09:45", "09:45"),
    ],
)
def test_시간_해석(text, expected):
    assert parse(text)["schdl_tm"] == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("내일", date(2026, 9, 30)),
        ("모레", date(2026, 10, 1)),
        ("3일 후", date(2026, 10, 2)),
        ("10월 15일", date(2026, 10, 15)),
        ("10/6", date(2026, 10, 6)),
        ("다음달 5일", date(2026, 10, 5)),
        ("2026-11-03", date(2026, 11, 3)),
        ("이번 주 금요일", date(2026, 10, 2)),
    ],
)
def test_날짜_해석(text, expected):
    assert parse(text)["schdl_ymd"] == expected


@pytest.mark.parametrize(
    ("text", "zone", "cycle", "days"),
    [
        ("매일 산책 추가해 주세요", rules.ZONE_DAILY, None, None),
        ("매주 목욕 넣어줘", rules.ZONE_PERIODIC, rules.CYCLE_1W, None),
        ("격주로 귀 청소 넣어줘", rules.ZONE_PERIODIC, rules.CYCLE_2W, None),
        ("매달 심장사상충 약 넣어줘", rules.ZONE_PERIODIC, rules.CYCLE_MONTH, None),
        ("매년 종합 검진 넣어줘", rules.ZONE_PERIODIC, rules.CYCLE_YEAR, None),
        ("10일마다 귀 청소 넣어줘", rules.ZONE_PERIODIC, rules.CYCLE_CUSTOM, 10),
        ("3주마다 미용 넣어줘", rules.ZONE_PERIODIC, rules.CYCLE_CUSTOM, 21),
    ],
)
def test_주기는_케어구역_케어주기_코드로(text, zone, cycle, days):
    values = parse(text)

    assert values["care_zone_cd"] == zone
    assert values.get("care_cycle_cd") == cycle
    assert values.get("cycle_days") == days


def test_항목명은_반려동물_이름과_동사를_뺀_나머지():
    assert parse("매일 산책 추가해 주세요")["care_artcl_nm"] == "산책"
    assert parse("초코는 매달 심장사상충 약 넣어줘")["care_artcl_nm"] == "심장사상충 약"


@pytest.mark.parametrize(
    ("text", "kind", "name"),
    [
        ("모레 2시 반 목욕 예약해줘", "HLTC0058", "목욕"),
        ("내일 영양제 등록해줘", "HLTC0059", "영양제"),
    ],
)
def test_병원이_아닌_일정은_키워드를_일정명으로(text, kind, name):
    values = parse(text)

    assert values["schdl_knd_cd"] == kind
    assert values["schdl_nm"] == name


@pytest.mark.parametrize(
    "text", ["내일 동물병원 예약해줘", "내일 3시 병원 일정 잡아줘", "초코 병원 내일 잡아줘"]
)
def test_날짜_반려동물_일반명사는_병원명이_아니다(text):
    assert "hsptl_nm" not in parse(text)


def test_예약의_약은_투약으로_읽지_않는다():
    assert "schdl_knd_cd" not in parse("내일 3시 산책 예약해줘")


def test_AI가_준_칸은_서버에서_다시_검증한다():
    # FN-AIM-012-03 : 없는 날짜·허용값 밖 코드·잘못된 시간은 빈 칸, 길이는 컬럼에 맞춘다
    fields = clean_ai_fields(
        {
            "schdl_ymd": "2026-02-30",
            "schdl_tm": "25:00",
            "schdl_knd_cd": "HLTC9999",
            "ckup_type_cd": "HLTC0002",
            "hsptl_nm": "가" * 100,
            "cycle_days": 0,
            "last_cmptn_ymd": "2026-09-26",
        }
    )

    assert fields.schdl_ymd is None
    assert fields.schdl_tm is None
    assert fields.schdl_knd_cd is None
    assert fields.ckup_type_cd == "HLTC0002"
    assert fields.hsptl_nm == "가" * 80
    assert fields.cycle_days is None
    assert fields.last_cmptn_ymd == date(2026, 9, 26)


@pytest.mark.parametrize(
    ("zone", "cycle", "days", "last", "expected"),
    [
        (rules.ZONE_DAILY, None, None, date(2026, 9, 29), date(2026, 9, 30)),
        (rules.ZONE_PERIODIC, rules.CYCLE_1W, None, date(2026, 9, 29), date(2026, 10, 6)),
        (rules.ZONE_PERIODIC, rules.CYCLE_MONTH, None, date(2026, 1, 31), date(2026, 2, 28)),
        (rules.ZONE_PERIODIC, rules.CYCLE_YEAR, None, date(2028, 2, 29), date(2029, 2, 28)),
        (rules.ZONE_PERIODIC, rules.CYCLE_CUSTOM, 10, date(2026, 9, 29), date(2026, 10, 9)),
    ],
)
def test_다음_예정일은_마지막으로_한_날_더하기_주기(zone, cycle, days, last, expected):
    assert next_due(zone, cycle, days, last) == expected
