import asyncio

import pytest

from app.chat.clients import Classified, ClassifiedKind, ClassifyError
from app.chat.rules import is_question, is_register_request
from app.chat.schemas import IntentKind, MoveType
from app.chat.service import judge as service_judge
from app.chat.service import judge_intent
from tests.chat.fakes import FakeIntentClassifier


class FakeClassifier:
    def __init__(self, result: Classified):
        self.result = result
        self.calls = 0

    async def classify(self, text: str, hint=None) -> Classified:
        self.calls += 1
        return self.result


def judge(text: str, has_image: bool = False, classifier=None):
    return asyncio.run(judge_intent(text, has_image, classifier or FakeIntentClassifier()))


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
def test_등록_동사와_날짜_시간_주기가_함께_있으면_REGISTER(text):
    # FN-AIM-012-01, FN-AIM-004-13 : 라우팅 키워드(병원·구충·미용)가 있어도 등록이 먼저
    assert judge(text).kind is IntentKind.REGISTER


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
    intent = judge("일정 등록할래")

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
    intent = judge(text)

    assert intent.kind is IntentKind.ROUTE
    assert (intent.scr_id, intent.param) == (scr_id, param)
    assert intent.scr_nm


def test_채팅은_본창에서_모달로_연다():
    # 부록 A No.10 : SCR-COM-009는 화면 이동이 아니라 모달
    intent = judge("채팅 보여줘")

    assert intent.move_type is MoveType.MODAL
    assert judge("병원 찾아줘").move_type is MoveType.PAGE


def test_같은_길이면_매핑표_위쪽_행이_이긴다():
    # FN-AIM-004-01 : 건강기록(No.1, 4자)과 검진기록(No.13, 4자)이 함께 있으면 No.1
    assert judge("검진기록 건강기록").scr_id == "SCR-HLT-011"


def test_데이터_컨텍스트는_해석하지_않고_화면_단위로_간다():
    # FN-AIM-004-11 : "초코 체중 그래프" → 건강 일지, 반려동물 지정 없음
    intent = judge("초코 체중 그래프 보여줘")

    assert intent.kind is IntentKind.ROUTE
    assert (intent.scr_id, intent.param) == ("SCR-HLT-002", None)


def test_룰이_맞으면_AI_분류를_부르지_않는다():
    # FN-AIM-004-02 : AI 분류는 룰 매칭에 실패한 입력에만
    classifier = FakeClassifier(Classified(ClassifiedKind.SEARCH))
    judge("병원 찾아줘", classifier=classifier)
    judge("내일 3시 병원 일정 잡아줘", classifier=classifier)

    assert classifier.calls == 0


def test_mock_분류기는_질문이면_SEARCH():
    # FN-AIM-001-05 ③
    assert judge("강아지가 포도 먹어도 돼?").kind is IntentKind.SEARCH


def test_어디에도_해당하지_않으면_FALLBACK():
    # FN-AIM-004-12, FN-AIM-005-01
    assert judge("ㅁㄴㅇㄹ").kind is IntentKind.FALLBACK


def test_AI가_매핑표의_화면을_주면_ROUTE():
    classifier = FakeClassifier(Classified(ClassifiedKind.ROUTE, "SCR-MYP-020"))
    intent = judge("ㅁㄴㅇㄹ", classifier=classifier)

    assert intent.kind is IntentKind.ROUTE
    assert intent.scr_id == "SCR-MYP-020"
    assert classifier.calls == 1


@pytest.mark.parametrize(
    ("scr_id", "param"),
    [
        ("SCR-HLT-005", None),  # 제외 행(검진상세)
        ("SCR-XXX-999", None),  # 매핑표에 없음
        ("SCR-HOS-001", "?cat=unknown"),  # 화면은 있으나 파라미터가 없음
    ],
)
def test_AI가_매핑표에_없는_화면을_주면_FALLBACK(scr_id, param):
    # FN-AIM-004-08 : 라우팅 가능 행에 있는 화면만 인정
    classifier = FakeClassifier(Classified(ClassifiedKind.ROUTE, scr_id, param))

    assert judge("ㅁㄴㅇㄹ", classifier=classifier).kind is IntentKind.FALLBACK


@pytest.mark.parametrize("text", ["병원 찾아줘", "내일 3시 병원 일정 잡아줘", "ㅁㄴㅇㄹ"])
def test_이미지가_첨부되면_문장과_관계없이_RECEIPT(text):
    # FN-AIM-001-05 : 이미지 첨부 전송은 의도 분기를 거치지 않는다(SCR-AIM-013)
    classifier = FakeClassifier(Classified(ClassifiedKind.SEARCH))

    assert judge(text, has_image=True, classifier=classifier).kind is IntentKind.RECEIPT
    assert classifier.calls == 0


# 범위 밖 질문 차단(2026-10-30 LJS 추가 요청) : 키워드에 걸린 질문꼴은 AI로 서비스 범위 확인


class HintClassifier:
    def __init__(self, result: Classified | None = None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.hints = []

    async def classify(self, text: str, hint=None) -> Classified:
        self.hints.append(hint)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("가계부 작성 방법 알려줘", True),
        ("가계부는 어떻게 써", True),
        ("병원비 왜 이렇게 비싸?", True),
        ("가계부 보여줘", False),
        ("가계부", False),
        ("이번 달 얼마 썼어", False),
        ("알림 꺼줘", False),
    ],
)
def test_질문꼴_판정(text, expected):
    assert is_question(text) is expected


def test_키워드에_걸린_범위_밖_질문은_FALLBACK():
    classifier = HintClassifier(Classified(ClassifiedKind.UNKNOWN))
    intent = judge("가계부 작성 방법 알려줘", classifier=classifier)

    assert intent.kind is IntentKind.FALLBACK
    assert [hint.scr_id for hint in classifier.hints] == ["SCR-MYP-030"]


@pytest.mark.parametrize("text", ["가계부 보여줘", "가계부"])
def test_이동_지시나_키워드만_있으면_AI_없이_ROUTE(text):
    classifier = HintClassifier(Classified(ClassifiedKind.UNKNOWN))
    intent = judge(text, classifier=classifier)

    assert intent.kind is IntentKind.ROUTE
    assert intent.scr_id == "SCR-MYP-030"
    assert classifier.hints == []


def test_키워드에_걸린_범위_안_질문은_AI가_ROUTE면_ROUTE():
    classifier = HintClassifier(Classified(ClassifiedKind.ROUTE, "SCR-MYP-030"))
    intent = judge("반려동물 가계부 쓰는 법 알려줘", classifier=classifier)

    assert intent.kind is IntentKind.ROUTE
    assert intent.scr_id == "SCR-MYP-030"
    assert len(classifier.hints) == 1


def test_키워드에_걸린_범위_안_질문은_AI가_SEARCH면_SEARCH():
    classifier = HintClassifier(Classified(ClassifiedKind.SEARCH))
    intent = judge("반려동물 가계부 쓰는 법 알려줘", classifier=classifier)

    assert intent.kind is IntentKind.SEARCH


def test_질문꼴_확인_중_분류_장애면_룰대로_ROUTE():
    # FN-AIM-002-10 : 룰 라우팅은 LLM 장애와 무관
    classifier = HintClassifier(error=ClassifyError("api_error"))
    intent = judge("가계부 작성 방법 알려줘", classifier=classifier)

    assert intent.kind is IntentKind.ROUTE
    assert intent.scr_id == "SCR-MYP-030"


def test_룰에_안_걸리는_범위_밖_질문은_FALLBACK():
    classifier = HintClassifier(Classified(ClassifiedKind.UNKNOWN))
    intent = judge("파이썬 코딩 알려줘", classifier=classifier)

    assert intent.kind is IntentKind.FALLBACK
    assert classifier.hints == [None]


@pytest.mark.parametrize("text", ["가계부 작성 방법 알려줘", "파이썬 코딩 알려줘"])
def test_범위_밖_분류는_FALLBACK이고_범위_밖으로_표시(text):
    classifier = HintClassifier(Classified(ClassifiedKind.OUT_OF_SCOPE))
    judged = asyncio.run(service_judge(text, False, classifier))

    assert judged.intent.kind is IntentKind.FALLBACK
    assert judged.out_of_scope is True


def test_판단_못_함은_범위_밖으로_표시하지_않는다():
    judged = asyncio.run(service_judge("ㅁㄴㅇㄹ", False, FakeIntentClassifier()))

    assert judged.intent.kind is IntentKind.FALLBACK
    assert judged.out_of_scope is False
