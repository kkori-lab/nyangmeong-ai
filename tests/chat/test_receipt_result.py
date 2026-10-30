import json

import pytest

from app.chat import clients
from app.chat.schemas import ROLE_AI, ROLE_USER
from tests.chat.conftest import AJAX, as_member
from tests.chat.test_messages import Answers, BrokenClassifier, MessageJava

URL = "/ai/conversations/{}/receipt-result"


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture
def spies(client):
    # FN-AIM-013-02 : 영수증 결과 저장은 의도 판정·답변 생성 미호출
    classifier, answers = BrokenClassifier(), Answers()
    client.app.dependency_overrides[clients.get_intent_classifier] = lambda: classifier
    client.app.dependency_overrides[clients.get_answer_generator] = lambda: answers
    return classifier, answers


def post(client, room_sn: int, body: dict):
    return client.post(URL.format(room_sn), json=body, headers=AJAX)


def saved_messages(java: MessageJava) -> list[tuple[str, str]]:
    # Java에 저장 요청한 메시지(역할, 내용) 순서
    return [
        (json.loads(r.content)["roleCd"], json.loads(r.content)["cnvrsCn"])
        for r in java.requests
        if r.method == "POST" and r.url.path.endswith("/messages")
    ]


# FN-AIM-013-02 영수증 분석 분기 : 함께 보낸 텍스트는 사용자 메시지로


def test_텍스트가_있으면_사용자_다음_AI_요약_순으로_저장(client, java, spies):
    as_member(client, 1)
    room = java.add_room(1, "제목", pet_sn=1)
    body = {
        "result": "RECOGNIZED",
        "cnvrsCn": "이거 지난주 병원비야",
        "hsptlNm": "메이 동물병원",
        "ckupYmd": "2026-10-20",
        "recptAmt": 145000,
    }

    res = post(client, room, body)

    assert res.status_code == 201
    summary = "영수증 분석 — 메이 동물병원, 10월 20일, 145,000원"
    assert saved_messages(java) == [(ROLE_USER, "이거 지난주 병원비야"), (ROLE_AI, summary)]
    data = res.json()["data"]
    assert [(m["roleCd"], m["cnvrsCn"]) for m in data] == saved_messages(java)
    classifier, answers = spies
    assert classifier.calls == 0
    assert answers.calls == []


def test_텍스트가_없으면_AI_요약만_저장(client, java, spies):
    as_member(client, 1)
    room = java.add_room(1, "제목")

    res = post(client, room, {"result": "FAILED"})

    assert res.status_code == 201
    assert saved_messages(java) == [(ROLE_AI, "영수증 분석 — 영수증을 읽지 못했어요")]
    assert len(res.json()["data"]) == 1


def test_다시_열면_텍스트와_요약이_이어서_보인다(client, java):
    as_member(client, 1)
    room = java.add_room(1, "제목")
    post(client, room, {"result": "RECOGNIZED", "cnvrsCn": "영수증", "recptAmt": 30000})

    detail = client.get(f"/ai/conversations/{room}", headers=AJAX).json()["data"]

    assert [m["cnvrsCn"] for m in detail["messages"][-2:]] == [
        "영수증",
        "영수증 분석 — 30,000원",
    ]


@pytest.mark.parametrize("cn", ["가" * 1001, "   ", ""])
def test_텍스트_길이를_어기면_400이고_저장하지_않는다(client, java, cn):
    as_member(client, 1)
    room = java.add_room(1, "제목")

    res = post(client, room, {"result": "RECOGNIZED", "cnvrsCn": cn})

    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"
    assert saved_messages(java) == []


def test_1000자는_저장한다(client, java):
    as_member(client, 1)
    room = java.add_room(1, "제목")

    res = post(client, room, {"result": "ERROR", "cnvrsCn": "가" * 1000})

    assert res.status_code == 201


def test_쿠키가_없으면_401이고_저장하지_않는다(client, java):
    room = java.add_room(1, "제목")

    res = post(client, room, {"result": "FAILED", "cnvrsCn": "영수증"})

    assert res.status_code == 401
    assert java.rooms[room]["messages"][1:] == []


# FN-AIM-013-09 결과 이력 저장 : 요약 한 줄


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            {
                "result": "RECOGNIZED",
                "hsptlNm": "메이 동물병원",
                "ckupYmd": "2026-10-20",
                "recptAmt": 145000,
            },
            "영수증 분석 — 메이 동물병원, 10월 20일, 145,000원",
        ),
        (
            {"result": "RECOGNIZED", "hsptlNm": "메이 동물병원", "recptAmt": 0},
            "영수증 분석 — 메이 동물병원, 0원",
        ),
        ({"result": "RECOGNIZED", "ckupYmd": "2026-01-05"}, "영수증 분석 — 1월 5일"),
        ({"result": "RECOGNIZED"}, "영수증 분석 — 결과를 확인해 주세요"),
        ({"result": "FAILED"}, "영수증 분석 — 영수증을 읽지 못했어요"),
        ({"result": "ERROR"}, "영수증 분석 — 일시적인 오류로 분석하지 못했어요"),
        ({"result": "CANCELED"}, "영수증 분석 — 취소했어요"),
        # RECOGNIZED가 아니면 값 무시
        ({"result": "CANCELED", "hsptlNm": "메이 동물병원"}, "영수증 분석 — 취소했어요"),
    ],
)
def test_결과별_요약_문구(client, java, body, expected):
    as_member(client, 1)
    room = java.add_room(1, "제목")

    res = post(client, room, body)

    assert res.status_code == 201
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [expected]


def test_결과값이_허용값_밖이면_400(client, java):
    as_member(client, 1)
    room = java.add_room(1, "제목")

    res = post(client, room, {"result": "X"})

    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"
    assert saved_messages(java) == []


def test_남의_대화에_저장하면_404(client, java):
    as_member(client, 1)
    others = java.add_room(2, "남의 방")

    res = post(client, others, {"result": "FAILED", "cnvrsCn": "영수증"})

    assert res.status_code == 404
    assert java.rooms[others]["messages"][1:] == []
