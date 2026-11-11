import asyncio
from datetime import date

import pytest

from app.chat import rules
from app.chat.rules import is_register_request
from app.chat.schemas import IntentKind, MoveType
from app.chat.service import judge_tools
from tests.chat.fakes import FakeToolAgent


def judged(text: str, agent: FakeToolAgent | None = None):
    # 도구 흐름 판정 : 가짜 도구 고르기가 고른 도구로(기본은 도구도 글도 없음)
    agent = agent or FakeToolAgent()
    context = [{"role": "user", "content": text}]
    return asyncio.run(judge_tools(text, context, agent, 4500, date(2026, 11, 11), 5.0))


def hints(agent: FakeToolAgent) -> list[str | None]:
    # 도구 고르기에 넘긴 키워드 힌트 행의 화면 ID
    return [hint.scr_id if hint else None for _, _, hint in agent.decides]


def route_of(text: str):
    # FN-AIM-004-01 룰 매칭 : 도구 고르기 힌트이자 장애 때 이동할 행
    row = rules.match_route(text)
    assert row is not None, text
    return row.to_intent()


def row_no(scr_id: str) -> int:
    return next(r.no for r in rules.routing_table() if r.scr_id == scr_id)


@pytest.mark.parametrize(
    "text",
    [
        "내일 3시 병원 일정 잡아줘",  # FN-AIM-012-01 날짜 + 시간
        "다음 주 화요일 병원 일정 잡아줘",  # 화면설계서 SCR-AIM-004 처리 조건 예시
        "매일 산책 추가해 주세요",  # 주기(일상관리), 어미 변형
        "2주마다 구충 넣어줘",  # 주기(정기관리)
        "10월 30일 미용 예약해줘",  # 절대 날짜
        "오후 2시 반 목욕 등록해줘",  # 시각
    ],
)
def test_등록_동사와_날짜_시간_주기가_함께_있으면_힌트_없이_도구_고르기(text):
    # FN-AIM-012-01, FN-AIM-004-13 : 라우팅 키워드(병원·구충·미용)가 있어도 등록이 먼저
    # 칸은 쓰기 도구 인자로(SCR-AIM-012)
    assert is_register_request(text)
    agent = FakeToolAgent()
    judged(text, agent)
    assert hints(agent) == [None]


@pytest.mark.parametrize(
    "text",
    [
        "일정 등록할래",  # 날짜 없음
        "내일 병원",  # 등록 동사 없음
        "병원 잡아줘",  # 날짜·시간·주기 없음
    ],
)
def test_둘_중_하나라도_없으면_등록_요청이_아니다(text):
    # FN-AIM-012-01 : 한쪽만 있으면 라우팅·검색 판정으로 진행
    assert not is_register_request(text)


def test_날짜_없는_일정_등록은_케어_캘린더로_라우팅():
    # FN-AIM-004-13
    intent = route_of("일정 등록할래")

    assert intent.kind is IntentKind.ROUTE
    assert intent.scr_id == "SCR-HLT-003"


@pytest.mark.parametrize(
    ("text", "scr_id", "param"),
    [
        # 화면설계서 v0.11 SCR-AIM-004 ⑤ 예시 11개
        ("종합 건강기록 보여줘", "SCR-HLT-011", None),
        ("병원 찾아줘", "SCR-HOS-001", "?cat=hospital"),  # FN-AIM-004-10
        ("근처 애견미용실", "SCR-HOS-001", "?cat=beauty"),  # FN-AIM-004-10
        ("게시판 보여줘", "SCR-CMU-001-01", None),
        ("내 정보", "SCR-MYP-001", None),
        ("캐릭터 꾸미러 갈래", "SCR-MYP-010", None),
        ("문의하고 싶어", "SCR-CSC-001", None),  # 매핑표 No.7(10-01 정비) 기준
        ("알림 꺼줘", "SCR-COM-008", None),
        ("펫시터 구해줘", "SCR-CMU-004", None),
        ("채팅 보여줘", "SCR-COM-009", None),
        ("이번 달 얼마 썼어", "SCR-MYP-030", None),
        # FN-AIM-004-01 최장 일치 : 병원비(3) > 병원(2)
        ("이번 달 병원비 얼마 썼어", "SCR-MYP-030", None),
        # FN-AIM-004-01 최장 일치 : 병원 예약(4) > 약(1)
        ("병원 예약 보여줘", "SCR-HLT-003", None),
        # 공백을 빼고 대조 : "털 깎" = "털깎"
        ("털깎으러 가고 싶어", "SCR-HOS-001", "?cat=beauty"),
        ("처방약 보여줘", "SCR-HLT-011", None),
        ("설정 열어줘", "SCR-COM-008", None),
    ],
)
def test_룰_기반_매칭은_매핑표의_화면과_파라미터를_돌려준다(text, scr_id, param):
    # FN-AIM-004-01·10
    intent = route_of(text)

    assert intent.kind is IntentKind.ROUTE
    assert (intent.scr_id, intent.param) == (scr_id, param)
    assert intent.scr_nm


def test_채팅은_본창에서_모달로_연다():
    # 부록 A No.10 : SCR-COM-009는 화면 이동이 아니라 모달
    intent = route_of("채팅 보여줘")

    assert intent.move_type is MoveType.MODAL
    assert route_of("병원 찾아줘").move_type is MoveType.PAGE


def test_같은_길이면_매핑표_위쪽_행이_이긴다():
    # FN-AIM-004-01 : 건강기록(No.1, 4자)과 검진기록(No.13, 4자)이 함께 있으면 No.1
    assert route_of("검진기록 건강기록").scr_id == "SCR-HLT-011"


def test_데이터_컨텍스트는_해석하지_않고_화면_단위로_간다():
    # FN-AIM-004-11 : "초코 체중 그래프" → 건강 일지, 반려동물 지정 없음
    intent = route_of("초코 체중 그래프 보여줘")

    assert intent.kind is IntentKind.ROUTE
    assert (intent.scr_id, intent.param) == ("SCR-HLT-002", None)


def test_룰이_맞으면_그_행을_힌트로_도구_고르기에_넘긴다():
    # 추가 요청(2026-11-06) : 키워드에 걸린 문장은 힌트와 함께 도구 고르기
    agent = FakeToolAgent()
    judged("병원 찾아줘", agent)

    assert hints(agent) == ["SCR-HOS-001"]


def test_어디에도_해당하지_않으면_FALLBACK():
    # FN-AIM-004-12, FN-AIM-005-01 : 도구도 글도 고르지 않음
    assert judged("ㅁㄴㅇㄹ").intent.kind is IntentKind.FALLBACK


def test_AI가_매핑표의_화면을_주면_ROUTE():
    agent = FakeToolAgent("navigate", {"screen_num": row_no("SCR-MYP-020")})
    intent = judged("ㅁㄴㅇㄹ", agent).intent

    assert intent.kind is IntentKind.ROUTE
    assert intent.scr_id == "SCR-MYP-020"
    assert len(agent.decides) == 1


@pytest.mark.parametrize("scr_id", ["SCR-HLT-005", None])
def test_AI가_매핑표에_없는_화면을_주면_FALLBACK(scr_id):
    # FN-AIM-004-08 : 라우팅 가능 행에 있는 화면만 인정(제외 행·없는 번호)
    num = row_no(scr_id) if scr_id else max(r.no for r in rules.routing_table()) + 1
    agent = FakeToolAgent("navigate", {"screen_num": num})

    assert judged("ㅁㄴㅇㄹ", agent).intent.kind is IntentKind.FALLBACK


# 범위 밖 질문 차단(2026-10-30 LJS 추가 요청) : 키워드에 걸린 질문꼴은 AI로 서비스 범위 확인


def test_키워드에_걸린_범위_밖_질문은_FALLBACK():
    agent = FakeToolAgent("decline", {"unclear": False})
    intent = judged("가계부 작성 방법 알려줘", agent).intent

    assert intent.kind is IntentKind.FALLBACK
    assert hints(agent) == ["SCR-MYP-030"]


@pytest.mark.parametrize("text", ["가계부 보여줘", "가계부"])
def test_이동_지시나_키워드만_있어도_힌트와_함께_도구_고르기(text):
    # 추가 요청(2026-11-06) : 질문꼴이 아니어도 도구 고르기, 이동은 navigate로
    agent = FakeToolAgent("navigate", {"screen_num": row_no("SCR-MYP-030")})
    intent = judged(text, agent).intent

    assert intent.kind is IntentKind.ROUTE
    assert intent.scr_id == "SCR-MYP-030"
    assert hints(agent) == ["SCR-MYP-030"]


def test_키워드에_걸린_범위_안_질문은_AI가_navigate면_ROUTE():
    agent = FakeToolAgent("navigate", {"screen_num": row_no("SCR-MYP-030")})
    intent = judged("반려동물 가계부 쓰는 법 알려줘", agent).intent

    assert intent.kind is IntentKind.ROUTE
    assert intent.scr_id == "SCR-MYP-030"
    assert len(agent.decides) == 1


def test_키워드에_걸린_범위_안_질문은_AI가_바로_답하면_SEARCH():
    agent = FakeToolAgent(texts=("답",))
    intent = judged("반려동물 가계부 쓰는 법 알려줘", agent).intent

    assert intent.kind is IntentKind.SEARCH


def test_도구_고르기_장애면_키워드에_걸린_행으로_ROUTE():
    # FN-AIM-002-10 : 룰 라우팅은 LLM 장애와 무관
    intent = judged("가계부 작성 방법 알려줘", FakeToolAgent(fail=True)).intent

    assert intent.kind is IntentKind.ROUTE
    assert intent.scr_id == "SCR-MYP-030"


def test_룰에_안_걸리는_범위_밖_질문은_FALLBACK():
    agent = FakeToolAgent("decline", {"unclear": False})
    intent = judged("파이썬 코딩 알려줘", agent).intent

    assert intent.kind is IntentKind.FALLBACK
    assert hints(agent) == [None]


@pytest.mark.parametrize("text", ["가계부 작성 방법 알려줘", "파이썬 코딩 알려줘"])
def test_범위_밖_분류는_FALLBACK이고_범위_밖으로_표시(text):
    result = judged(text, FakeToolAgent("decline", {"unclear": False}))

    assert result.intent.kind is IntentKind.FALLBACK
    assert result.out_of_scope is True


def test_판단_못_함은_범위_밖으로_표시하지_않는다():
    result = judged("ㅁㄴㅇㄹ", FakeToolAgent("decline", {"unclear": True}))

    assert result.intent.kind is IntentKind.FALLBACK
    assert result.out_of_scope is False
