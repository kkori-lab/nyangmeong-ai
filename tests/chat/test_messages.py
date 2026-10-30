import asyncio
import json

import httpx2
import pytest

from app.chat import clients, repository, service
from app.chat.clients import AnswerError, Classified, ClassifiedKind, ClassifyError
from app.chat.schemas import ROLE_AI, ConversationMessage
from app.chat.service import (
    ANSWER_ERROR_MESSAGE,
    DISCLAIMER,
    FALLBACK_MESSAGE,
    OUT_OF_SCOPE_MESSAGE,
    build_context,
    route_message,
)
from app.core.config import get_settings
from tests.chat.conftest import AJAX, ROLE_USER, FakeJava, _ok, as_member, member_of
from tests.chat.fakes import FakeIntentClassifier, FakeTitleGenerator

SEARCH_TEXT = "강아지 포도 먹어도 돼?"


class MessageJava(FakeJava):
    """FakeJava에 메시지 추가(POST .../messages) 확장. 메시지에 cmptnYn 기록"""

    def __init__(self) -> None:
        super().__init__()
        self.fail_ai_save = False

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if not (request.method == "POST" and path.endswith("/messages")):
            return super().__call__(request)
        self.requests.append(request)
        mbr_sn = member_of(request)
        room = self.rooms.get(int(path.split("/")[-2]))
        if room is None or room["mbrSn"] != mbr_sn:
            return httpx2.Response(404, json={"status": "error", "httpCode": 404})
        body = json.loads(request.content)
        if self.fail_ai_save and body["roleCd"] == ROLE_AI:
            return httpx2.Response(400, json={"status": "error", "httpCode": 400})
        message = {
            "aiCnvrsMsgSn": self._next_msg,
            "roleCd": body["roleCd"],
            "cnvrsCn": body["cnvrsCn"],
            "msgSeq": len(room["messages"]) + 1,
            "regDt": self._tick(),
            "cmptnYn": body.get("cmptnYn", True),
        }
        self._next_msg += 1
        room["messages"].append(message)
        return _ok(message, 201)

    def ai_messages(self, room_sn: int) -> list[dict]:
        return [m for m in self.rooms[room_sn]["messages"] if m["roleCd"] == ROLE_AI]


class Answers:
    """가짜 답변 생성기. chunks 출력, fail이면 그 자리에서 AnswerError, hang이면 정지"""

    def __init__(self, chunks=("포도는 ", "강아지에게 위험해요."), fail=None, hang=None):
        self.chunks = chunks
        self.fail = fail  # 몇 번째 조각 앞에서 실패할지
        self.hang = hang  # 몇 번째 조각 앞에서 멈출지
        self.calls: list[tuple[list[dict], int]] = []

    async def stream(self, messages, max_tokens):
        self.calls.append((messages, max_tokens))
        for i, chunk in enumerate(self.chunks):
            if self.fail == i:
                raise AnswerError("api_error")
            if self.hang == i:
                await asyncio.sleep(5)
            yield chunk


class FixedClassifier:
    def __init__(self, result: Classified) -> None:
        self.result = result

    async def classify(self, text: str, hint=None) -> Classified:
        return self.result


class BrokenClassifier:
    # LLM 장애 흉내 : AnthropicIntentClassifier는 API 오류·시간 초과면 ClassifyError
    def __init__(self) -> None:
        self.calls = 0

    async def classify(self, text: str, hint=None) -> Classified:
        self.calls += 1
        raise ClassifyError("api_error")


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture
def answers(client) -> Answers:
    fake = Answers()
    client.app.dependency_overrides[clients.get_answer_generator] = lambda: fake
    return fake


def use(client, answers: Answers) -> Answers:
    client.app.dependency_overrides[clients.get_answer_generator] = lambda: answers
    return answers


def limits(monkeypatch, first: float, total: float) -> None:
    monkeypatch.setenv("ANSWER_FIRST_TOKEN_SEC", str(first))
    monkeypatch.setenv("ANSWER_TOTAL_SEC", str(total))
    get_settings.cache_clear()


def send(client, room_sn: int, cn: str | None = None, headers=AJAX):
    body = {} if cn is None else {"cnvrsCn": cn}
    return client.post(f"/ai/conversations/{room_sn}/messages", json=body, headers=headers)


def events(res) -> list[tuple[str, dict]]:
    assert res.headers["content-type"].startswith("text/event-stream")
    out = []
    for block in res.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def names(evs) -> list[str]:
    return [name for name, _ in evs]


def deltas(evs) -> str:
    return "".join(data["text"] for name, data in evs if name == "delta")


# 메시지 전송과 판정별 응답


def test_검색은_판정_조각_고지_완료_순으로_흐르고_고지를_붙여_저장(client, java, answers):
    # FN-AIM-002-02·03
    as_member(client, 1)
    room = java.add_room(1, "제목", cn="안녕")
    res = send(client, room, SEARCH_TEXT)

    assert res.status_code == 200
    evs = events(res)
    assert names(evs) == ["intent", "delta", "delta", "delta", "done"]
    assert evs[0][1]["kind"] == "SEARCH"
    assert evs[-2][1]["text"] == DISCLAIMER
    assert deltas(evs) == "포도는 강아지에게 위험해요." + DISCLAIMER
    saved = java.ai_messages(room)
    assert [m["cnvrsCn"] for m in saved] == ["포도는 강아지에게 위험해요." + DISCLAIMER]
    assert saved[0]["cmptnYn"] is True
    done = evs[-1][1]
    assert done["message"]["cnvrsCn"] == saved[0]["cnvrsCn"]
    assert done["message"]["cmptnYn"] is True


def test_고지_문구는_화면설계서_그대로():
    assert DISCLAIMER.strip() == (
        "※ 참고 정보이며 의료 진단이 아닙니다. 이상 징후가 있다면 수의사와 상담하세요."
    )


def test_본문이_있으면_사용자_메시지로_먼저_저장(client, java, answers):
    as_member(client, 1)
    room = java.add_room(1, "제목", cn="첫 질문")
    send(client, room, SEARCH_TEXT)

    messages = java.rooms[room]["messages"]
    assert [(m["roleCd"], m["cnvrsCn"]) for m in messages[:2]] == [
        (ROLE_USER, "첫 질문"),
        (ROLE_USER, SEARCH_TEXT),
    ]
    # 답할 질문은 방금 저장한 메시지
    assert answers.calls[0][0][-1] == {"role": "user", "content": SEARCH_TEXT}


def test_본문이_없으면_저장_없이_마지막_사용자_메시지에_답한다(client, java, answers):
    # 첫 메시지 직후(POST /ai/conversations가 이미 저장)·다시 시도·다시 생성
    as_member(client, 1)
    room = java.add_room(1, "제목", cn=SEARCH_TEXT)
    evs = events(send(client, room))

    assert evs[0][1]["kind"] == "SEARCH"
    assert [m["roleCd"] for m in java.rooms[room]["messages"]] == [ROLE_USER, ROLE_AI]
    assert answers.calls[0][0] == [{"role": "user", "content": SEARCH_TEXT}]


def test_답할_사용자_메시지가_없는_방은_400(client, java, answers):
    as_member(client, 1)
    room = java.add_room(1, "제목")
    java.rooms[room]["messages"] = []
    res = send(client, room)

    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"
    assert answers.calls == []


@pytest.mark.parametrize("body", [{"cnvrsCn": ""}, {"cnvrsCn": "  "}, {"cnvrsCn": "가" * 1001}])
def test_본문_검증_실패는_400(client, java, answers, body):
    as_member(client, 1)
    room = java.add_room(1, "제목")
    res = client.post(f"/ai/conversations/{room}/messages", json=body, headers=AJAX)

    assert res.status_code == 400
    assert len(java.rooms[room]["messages"]) == 1


def test_남의_방은_Java_404_그대로이고_LLM을_부르지_않는다(client, java, answers):
    room = java.add_room(2, "남의 방")
    as_member(client, 1)
    res = send(client, room, SEARCH_TEXT)

    assert res.status_code == 404
    assert answers.calls == []


def test_로그인_안_하면_401이고_LLM을_부르지_않는다(client, java, answers):
    room = java.add_room(1, "제목")
    res = send(client, room, SEARCH_TEXT)

    assert res.status_code == 401
    assert answers.calls == []
    assert java.requests == []


def test_X_Requested_With_없으면_403이고_LLM을_부르지_않는다(client, java, answers):
    as_member(client, 1)
    room = java.add_room(1, "제목")
    res = send(client, room, SEARCH_TEXT, headers={})

    assert res.status_code == 403
    assert answers.calls == []
    assert len(java.rooms[room]["messages"]) == 1


def test_라우팅_문장은_이동_안내를_저장하고_LLM_답변을_부르지_않는다(client, java, answers):
    # FN-AIM-004 : 다시 열어도 답이 남게 이동 안내를 AI 메시지로 저장(2026-10-29 결정)
    as_member(client, 1)
    room = java.add_room(1, "제목")
    evs = events(send(client, room, "일정 등록할래"))

    assert names(evs) == ["intent", "done"]
    intent = evs[0][1]
    assert intent["kind"] == "ROUTE"
    assert intent["scrId"] == "SCR-HLT-003"
    expected = route_message(intent["scrNm"])
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [expected]
    assert evs[1][1]["message"]["cnvrsCn"] == expected
    assert evs[1][1]["shortcut"] is None
    assert answers.calls == []


@pytest.mark.parametrize(
    ("scr_nm", "expected"),
    [
        ("동물병원 찾기", "동물병원 찾기로 이동할게요"),
        ("케어 캘린더", "케어 캘린더로 이동할게요"),
        ("건강기록", "건강기록으로 이동할게요"),
        ("일정 관리", "일정 관리로 이동할게요"),
        ("FAQ", "FAQ로 이동할게요"),
    ],
)
def test_이동_안내는_받침에_맞춰_조사를_붙인다(scr_nm, expected):
    assert route_message(scr_nm) == expected


def test_분류_LLM_장애면_폴백이_아니라_error_이벤트(client, java, answers):
    # 2026-10-29 결정 : 장애는 사용자 입력 실패(폴백·연속 실패)로 미집계
    broken = BrokenClassifier()
    client.app.dependency_overrides[clients.get_intent_classifier] = lambda: broken
    as_member(client, 1)
    room = java.add_room(1, "제목")
    evs = events(send(client, room, SEARCH_TEXT))

    assert names(evs) == ["error"]
    assert evs[0][1] == {"code": "EXTERNAL_API_ERROR", "message": ANSWER_ERROR_MESSAGE}
    assert broken.calls == 1
    assert java.ai_messages(room) == []
    assert answers.calls == []


def test_LLM_장애여도_룰_라우팅은_ROUTE(client, java, answers):
    # FN-AIM-002-10 : 분류 LLM이 실패 상태여도 룰 매칭은 LLM 앞에서 종료
    broken = BrokenClassifier()
    client.app.dependency_overrides[clients.get_intent_classifier] = lambda: broken
    as_member(client, 1)
    room = java.add_room(1, "제목")
    evs = events(send(client, room, "일정 등록할래"))

    assert evs[0][1]["kind"] == "ROUTE"
    assert broken.calls == 0


def test_등록_요청은_판정만_준다(client, java, answers):
    # 등록 흐름은 SCR-AIM-012에서 이어짐
    as_member(client, 1)
    room = java.add_room(1, "제목")
    evs = events(send(client, room, "매일 산책 추가해 주세요"))

    assert names(evs) == ["intent", "done"]
    assert evs[0][1]["kind"] == "REGISTER"
    assert answers.calls == []


def test_매칭_실패는_안내_문구를_AI_메시지로_저장(client, java, answers):
    # FN-AIM-005-01·02
    as_member(client, 1)
    room = java.add_room(1, "제목")
    evs = events(send(client, room, "ㅁㄴㅇㄹ"))

    assert names(evs) == ["intent", "done"]
    assert evs[0][1]["kind"] == "FALLBACK"
    assert evs[1][1]["message"]["cnvrsCn"] == FALLBACK_MESSAGE
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [FALLBACK_MESSAGE]
    assert answers.calls == []


@pytest.mark.parametrize("text", ["가계부 작성 방법 알려줘", "파이썬 코딩 알려줘"])
def test_서비스_범위_밖_질문은_범위_안내_문구를_저장(client, java, answers, text):
    # 2026-10-30 추가 요청 : 의도는 FALLBACK 그대로, 문구만 범위 안내
    client.app.dependency_overrides[clients.get_intent_classifier] = lambda: FixedClassifier(
        Classified(ClassifiedKind.OUT_OF_SCOPE)
    )
    as_member(client, 1)
    room = java.add_room(1, "제목")
    evs = events(send(client, room, text))

    assert names(evs) == ["intent", "done"]
    assert evs[0][1]["kind"] == "FALLBACK"
    assert evs[1][1]["message"]["cnvrsCn"] == OUT_OF_SCOPE_MESSAGE
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [OUT_OF_SCOPE_MESSAGE]
    assert answers.calls == []


def test_연관_화면이_있으면_완료에_바로가기를_주고_저장하지_않는다(client, java, answers):
    # FN-AIM-002-04
    related = Classified(ClassifiedKind.SEARCH, related_scr_id="SCR-HLT-003")
    client.app.dependency_overrides[clients.get_intent_classifier] = lambda: FixedClassifier(
        related
    )
    as_member(client, 1)
    room = java.add_room(1, "제목")
    evs = events(send(client, room, SEARCH_TEXT))

    done = evs[-1][1]
    assert done["shortcut"]["kind"] == "ROUTE"
    assert done["shortcut"]["scrId"] == "SCR-HLT-003"
    assert "SCR-HLT-003" not in java.ai_messages(room)[0]["cnvrsCn"]


def test_매핑표에_없는_연관_화면은_바로가기_없음(client, java, answers):
    related = Classified(ClassifiedKind.SEARCH, related_scr_id="SCR-NONE-999")
    client.app.dependency_overrides[clients.get_intent_classifier] = lambda: FixedClassifier(
        related
    )
    as_member(client, 1)
    room = java.add_room(1, "제목")
    evs = events(send(client, room, SEARCH_TEXT))

    assert evs[-1][1]["shortcut"] is None


# FN-AIM-002-07 오류·시간 초과


def test_첫_글자_전_오류는_error_이벤트이고_저장하지_않는다(client, java):
    use(client, Answers(fail=0))
    as_member(client, 1)
    room = java.add_room(1, "제목")
    evs = events(send(client, room, SEARCH_TEXT))

    assert names(evs) == ["intent", "error"]
    assert evs[1][1] == {"code": "EXTERNAL_API_ERROR", "message": ANSWER_ERROR_MESSAGE}
    assert java.ai_messages(room) == []
    # 사용자 메시지 유지 : [다시 시도]가 본문 없이 재호출 가능
    assert java.rooms[room]["messages"][-1]["cnvrsCn"] == SEARCH_TEXT


def test_첫_글자_시간_초과는_error_이벤트이고_저장하지_않는다(client, java, monkeypatch):
    limits(monkeypatch, first=0.1, total=5)
    use(client, Answers(hang=0))
    as_member(client, 1)
    room = java.add_room(1, "제목")
    evs = events(send(client, room, SEARCH_TEXT))

    assert names(evs) == ["intent", "error"]
    assert java.ai_messages(room) == []


def test_답변_도중_오류는_부분_답변을_미완료로_저장(client, java):
    use(client, Answers(chunks=("부분 ", "답변 ", "나머지"), fail=2))
    as_member(client, 1)
    room = java.add_room(1, "제목")
    evs = events(send(client, room, SEARCH_TEXT))

    assert names(evs) == ["intent", "delta", "delta", "done"]
    assert deltas(evs) == "부분 답변 "
    saved = java.ai_messages(room)
    assert saved[0]["cnvrsCn"] == "부분 답변 "
    assert saved[0]["cmptnYn"] is False
    assert evs[-1][1]["message"]["cmptnYn"] is False


def test_전체_시간_초과는_부분_답변을_미완료로_저장(client, java, monkeypatch):
    limits(monkeypatch, first=5, total=0.3)
    use(client, Answers(chunks=("부분 ", "나머지"), hang=1))
    as_member(client, 1)
    room = java.add_room(1, "제목")
    evs = events(send(client, room, SEARCH_TEXT))

    assert names(evs) == ["intent", "delta", "done"]
    saved = java.ai_messages(room)
    assert saved[0]["cnvrsCn"] == "부분 "
    assert saved[0]["cmptnYn"] is False
    # 미완료 답변은 고지 제외
    assert DISCLAIMER not in saved[0]["cnvrsCn"]


class SlowAnswers(Answers):
    """조각 사이에 잠깐 휴지. 연결이 끊긴 뒤에도 생성 유지"""

    async def stream(self, messages, max_tokens):
        async for chunk in super().stream(messages, max_tokens):
            await asyncio.sleep(0.05)
            yield chunk


def test_연결이_끊겨도_답변을_끝까지_만들어_완료로_저장(client, java):
    # architecture.md "질문 한 번의 순서" : 연결이 끊겨도 생성·저장은 끝까지 진행
    # TestClient로는 스트림 중간 끊김 재현 불가 : 서비스를 직접 호출(client는 설정값용)
    room = java.add_room(1, "제목", cn=SEARCH_TEXT)
    settings = get_settings()
    limits = service.AnswerLimits(settings.answer_first_token_sec, settings.answer_total_sec)
    answers = SlowAnswers(chunks=("끝까지 ", "만든 ", "답변"))

    async def disconnect_after_intent():
        backend = httpx2.AsyncClient(transport=httpx2.MockTransport(java))
        repo = repository.JavaConversationRepository(backend, settings, "access_token=member-1")
        turn = await service.prepare_turn(repo, room, None)
        events = service.answer_turn(
            turn, repo, FakeIntentClassifier(), answers, repository.AiSettings(), limits
        )
        first = await anext(events)
        # 연결이 끊기면 StreamingResponse가 이벤트 제너레이터 종료
        await events.aclose()
        await asyncio.gather(*service._running)
        return first

    first = asyncio.run(disconnect_after_intent())

    assert first[0] == "intent"
    saved = java.ai_messages(room)
    assert saved[0]["cnvrsCn"] == "끝까지 만든 답변" + DISCLAIMER
    assert saved[0]["cmptnYn"] is True


def test_답변_저장이_실패해도_스트림은_끝나고_message는_null(client, java, answers):
    # 1,000자 상한 없음(2026-10-28) : Java가 거절하면 저장만 누락
    java.fail_ai_save = True
    as_member(client, 1)
    room = java.add_room(1, "제목")
    evs = events(send(client, room, SEARCH_TEXT))

    assert names(evs)[-1] == "done"
    assert evs[-1][1]["message"] is None
    assert deltas(evs).endswith(DISCLAIMER)


def test_답변은_길이를_자르지_않고_저장_요청(client, java):
    long_answer = "가" * 3000
    use(client, Answers(chunks=(long_answer,)))
    as_member(client, 1)
    room = java.add_room(1, "제목")
    send(client, room, SEARCH_TEXT)

    assert java.ai_messages(room)[0]["cnvrsCn"] == long_answer + DISCLAIMER


def test_미완료_답변은_다음_컨텍스트에서_빠진다(client, java):
    use(client, Answers(chunks=("부분 ", "나머지"), fail=1))
    as_member(client, 1)
    room = java.add_room(1, "제목", cn=SEARCH_TEXT)
    send(client, room)
    retry = use(client, Answers())
    send(client, room)  # [다시 생성]

    assert retry.calls[0][0] == [{"role": "user", "content": SEARCH_TEXT}]


# FN-AIM-002-11·011-15 컨텍스트


def message(seq: int, role: str, cn: str, cmptn: bool = True) -> ConversationMessage:
    return ConversationMessage(
        ai_cnvrs_msg_sn=seq,
        role_cd=role,
        cnvrs_cn=cn,
        msg_seq=seq,
        reg_dt="2026-10-28T10:00:00",
        cmptn_yn=cmptn,
    )


def conversation(turns: int) -> list[ConversationMessage]:
    out = []
    for t in range(turns):
        out.append(message(len(out) + 1, ROLE_USER, f"질문{t}"))
        out.append(message(len(out) + 1, ROLE_AI, f"답변{t}"))
    return out


def test_컨텍스트는_최근_6턴_12메시지만():
    messages = conversation(8)
    messages.append(message(17, ROLE_USER, "새 질문"))
    context = build_context(messages, 17, 6)

    assert len(context) <= 12
    assert context[-1] == {"role": "user", "content": "새 질문"}
    assert context[0]["role"] == "user"
    assert {"role": "user", "content": "질문0"} not in context


def test_컨텍스트는_사용자_메시지로_시작하고_역할을_바꿔_쓴다():
    messages = conversation(6) + [message(13, ROLE_USER, "새 질문")]
    context = build_context(messages, 13, 6)

    # 마지막 12개는 답변0부터라 맨 앞 AI 메시지 제외
    assert context[0] == {"role": "user", "content": "질문1"}
    assert len(context) == 11
    assert context[1] == {"role": "assistant", "content": "답변1"}


def test_컨텍스트는_미완료와_답할_메시지_뒤를_뺀다():
    messages = [
        message(1, ROLE_USER, "질문"),
        message(2, ROLE_AI, "끊긴 답", cmptn=False),
        message(3, ROLE_AI, "뒤 메시지"),
    ]
    assert build_context(messages, 1, 6) == [{"role": "user", "content": "질문"}]


def test_컨텍스트는_답변_끝의_의료_고지를_뗀다():
    messages = [
        message(1, ROLE_USER, "질문"),
        message(2, ROLE_AI, "답변" + DISCLAIMER),
        message(3, ROLE_USER, "새 질문"),
    ]
    context = build_context(messages, 3, 6)

    assert context[1] == {"role": "assistant", "content": "답변"}


def test_컨텍스트는_고지_없는_답변과_사용자_메시지를_그대로_넘긴다():
    messages = [
        message(1, ROLE_USER, "질문" + DISCLAIMER),
        message(2, ROLE_AI, "답변"),
        message(3, ROLE_USER, "새 질문"),
    ]
    context = build_context(messages, 3, 6)

    assert context == [
        {"role": "user", "content": "질문" + DISCLAIMER},
        {"role": "assistant", "content": "답변"},
        {"role": "user", "content": "새 질문"},
    ]


def test_턴_수는_설정값을_따른다():
    messages = conversation(3) + [message(7, ROLE_USER, "새 질문")]
    assert len(build_context(messages, 7, 1)) == 1


def test_설정값_기본은_4500토큰과_6턴(client, java, answers):
    # 가짜 설정(Java 설정값 조회 API 연결 전) : 명세 기본값
    assert repository.get_ai_settings() == repository.AiSettings(4500, 6)
    as_member(client, 1)
    room = java.add_room(1, "제목")
    send(client, room, SEARCH_TEXT)

    assert answers.calls[0][1] == 4500


def test_대화_상세에_미완료_여부가_나온다(client, java):
    use(client, Answers(chunks=("부분 ", "나머지"), fail=1))
    as_member(client, 1)
    room = java.add_room(1, "제목", cn=SEARCH_TEXT)
    send(client, room)
    detail = client.get(f"/ai/conversations/{room}").json()["data"]

    assert [m["cmptnYn"] for m in detail["messages"]] == [True, False]


def test_mock_모드는_LLM_없이_조각을_흘린다(client, java):
    # 기본 mock 답변 생성기 : 받은 컨텍스트 크기를 알림
    as_member(client, 1)
    room = java.add_room(1, "제목", cn="첫 질문")
    evs = events(send(client, room, SEARCH_TEXT))

    assert names(evs).count("delta") >= 3
    assert "대화 메시지 2개" in deltas(evs)
    assert deltas(evs).endswith(DISCLAIMER)


# 첫 답변 요약 제목 (추가 요청, SCR-AIM-011)


@pytest.fixture
def titles(client) -> FakeTitleGenerator:
    fake = FakeTitleGenerator()
    client.app.dependency_overrides[clients.get_title_generator] = lambda: fake
    return fake


def title_patches(java: FakeJava) -> list[dict]:
    return [json.loads(r.content) for r in java.requests if r.method == "PATCH"]


class FailingSummary(FakeTitleGenerator):
    """요약 실패 흉내 : result를 돌려주거나 raise면 예외"""

    def __init__(self, result: str = "", raise_error: bool = False) -> None:
        super().__init__()
        self.result = result
        self.raise_error = raise_error

    async def summarize(self, question: str, answer: str) -> str:
        if self.raise_error:
            raise RuntimeError("boom")
        return self.result


def test_첫_검색_답변이_끝나면_질문과_답변_요약으로_제목을_한_번_바꾼다(
    client, java, answers, titles
):
    as_member(client, 1)
    room = java.add_room(1, "강아지 포도", cn=SEARCH_TEXT)
    evs = events(send(client, room))

    assert names(evs)[-1] == "done"
    # 고지 문구는 요약 입력에서 뺀다
    assert titles.summaries == [(SEARCH_TEXT, "포도는 강아지에게 위험해요.")]
    expected = "요약 포도는 강아지에게 위험해요."
    assert title_patches(java) == [{"cnvrsTtl": expected}]
    assert java.rooms[room]["cnvrsTtl"] == expected
    patch = next(r for r in java.requests if r.method == "PATCH")
    assert patch.url.path == f"/internal/ai/conversations/{room}"
    assert patch.headers["X-Requested-With"] == "XMLHttpRequest"


def test_두_번째_검색_답변부터는_제목을_바꾸지_않는다(client, java, answers, titles):
    as_member(client, 1)
    room = java.add_room(1, "강아지 포도", cn=SEARCH_TEXT)
    events(send(client, room))
    events(send(client, room, "고양이는 어때?"))

    assert len(titles.summaries) == 1
    assert len(title_patches(java)) == 1


@pytest.mark.parametrize("first", ["일정 등록할래", "ㅁㄴㅇㄹ"])
def test_첫_답변이_이동이나_폴백이면_뒤의_검색도_제목을_바꾸지_않는다(
    client, java, answers, titles, first
):
    as_member(client, 1)
    room = java.add_room(1, "제목")
    events(send(client, room, first))
    events(send(client, room, SEARCH_TEXT))

    assert titles.summaries == []
    assert title_patches(java) == []
    assert java.rooms[room]["cnvrsTtl"] == "제목"


def test_미완료_답변이면_제목을_바꾸지_않는다(client, java, titles):
    use(client, Answers(chunks=("부분 ", "답변 ", "나머지"), fail=2))
    as_member(client, 1)
    room = java.add_room(1, "제목")
    events(send(client, room, SEARCH_TEXT))

    assert titles.summaries == []
    assert title_patches(java) == []


def test_첫_글자_전_실패_뒤_다시_시도가_끝나면_제목을_바꾼다(client, java, titles):
    # 첫 글자 전 실패는 AI 메시지를 저장하지 않으므로 다시 시도가 첫 답변
    as_member(client, 1)
    room = java.add_room(1, "제목", cn=SEARCH_TEXT)
    use(client, Answers(fail=0))
    events(send(client, room))
    assert title_patches(java) == []

    use(client, Answers())
    events(send(client, room))
    assert len(title_patches(java)) == 1


@pytest.mark.parametrize(
    "summary", [FailingSummary(""), FailingSummary("  "), FailingSummary(raise_error=True)]
)
def test_요약이_실패해도_답변과_done은_그대로이고_제목은_유지(client, java, answers, summary):
    client.app.dependency_overrides[clients.get_title_generator] = lambda: summary
    as_member(client, 1)
    room = java.add_room(1, "제목", cn=SEARCH_TEXT)
    evs = events(send(client, room))

    assert names(evs) == ["intent", "delta", "delta", "delta", "done"]
    assert evs[-1][1]["message"]["cmptnYn"] is True
    assert len(java.ai_messages(room)) == 1
    assert title_patches(java) == []
    assert java.rooms[room]["cnvrsTtl"] == "제목"


def test_제목_수정이_실패해도_답변과_done은_그대로(client, java, answers, titles):
    java.title_status = 500
    as_member(client, 1)
    room = java.add_room(1, "제목", cn=SEARCH_TEXT)
    evs = events(send(client, room))

    assert names(evs) == ["intent", "delta", "delta", "delta", "done"]
    assert evs[-1][1]["message"]["cnvrsCn"] == "포도는 강아지에게 위험해요." + DISCLAIMER
    assert len(title_patches(java)) == 1
    assert java.rooms[room]["cnvrsTtl"] == "제목"


def test_요약_제목은_30자로_자른다(client, java, answers):
    long = FailingSummary("가" * 250)
    client.app.dependency_overrides[clients.get_title_generator] = lambda: long
    as_member(client, 1)
    room = java.add_room(1, "제목", cn=SEARCH_TEXT)
    events(send(client, room))

    assert title_patches(java) == [{"cnvrsTtl": "가" * 30}]


# 키 없는 PC·CI : 가짜를 끼우지 않으면 실제 API 대신 502


@pytest.mark.parametrize("getter", [clients.get_intent_classifier, clients.get_answer_generator])
def test_LLM_키가_없으면_메시지_전송은_502(client, java, getter):
    del client.app.dependency_overrides[getter]
    as_member(client, 1)
    room = java.add_room(1, "제목")
    res = client.post(f"/ai/conversations/{room}/messages", json={"cnvrsCn": "안녕"}, headers=AJAX)

    assert res.status_code == 502
    assert res.json()["code"] == "EXTERNAL_API_ERROR"


def test_LLM_키가_없어도_쿠키가_없으면_401(client, java):
    del client.app.dependency_overrides[clients.get_intent_classifier]
    room = java.add_room(1, "제목")
    res = client.post(f"/ai/conversations/{room}/messages", json={"cnvrsCn": "안녕"}, headers=AJAX)

    assert res.status_code == 401


def test_LLM_키가_없으면_대화_생성은_502(client):
    del client.app.dependency_overrides[clients.get_title_generator]
    as_member(client, 1)
    res = client.post("/ai/conversations", json={"cnvrsCn": "안녕"}, headers=AJAX)

    assert res.status_code == 502
    assert res.json()["code"] == "EXTERNAL_API_ERROR"


def test_LLM_키가_없어도_대화_목록은_된다(client, java):
    as_member(client, 1)
    java.add_room(1, "제목")
    for getter in (clients.get_title_generator, clients.get_intent_classifier):
        del client.app.dependency_overrides[getter]
    res = client.get("/ai/conversations", headers=AJAX)

    assert res.status_code == 200
