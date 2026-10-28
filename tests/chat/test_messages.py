import asyncio
import json

import httpx2
import pytest

from app.chat import clients, repository, service
from app.chat.clients import AnswerError, Classified, ClassifiedKind
from app.chat.schemas import ROLE_AI, ConversationMessage
from app.chat.service import (
    ANSWER_ERROR_MESSAGE,
    DISCLAIMER,
    FALLBACK_MESSAGE,
    build_context,
)
from app.core.config import get_settings
from tests.chat.conftest import AJAX, ROLE_USER, FakeJava, _ok, as_member, member_of

SEARCH_TEXT = "강아지 포도 먹어도 돼?"


class MessageJava(FakeJava):
    """FakeJava에 메시지 추가(POST .../messages)를 더한다. 메시지에 cmptnYn을 남긴다"""

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
    """가짜 답변 생성기. chunks를 내고, fail이면 그 자리에서 AnswerError, hang이면 멈춘다"""

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

    async def classify(self, text: str) -> Classified:
        return self.result


class BrokenClassifier:
    # LLM 장애 흉내 : AnthropicIntentClassifier는 실패하면 UNKNOWN을 준다
    def __init__(self) -> None:
        self.calls = 0

    async def classify(self, text: str) -> Classified:
        self.calls += 1
        return Classified(ClassifiedKind.UNKNOWN)


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


def test_라우팅_문장은_판정만_주고_LLM_답변을_부르지_않는다(client, java, answers):
    # FN-AIM-004
    as_member(client, 1)
    room = java.add_room(1, "제목")
    evs = events(send(client, room, "일정 등록할래"))

    assert names(evs) == ["intent", "done"]
    assert evs[0][1]["kind"] == "ROUTE"
    assert evs[0][1]["scrId"] == "SCR-HLT-003"
    assert evs[1][1] == {"message": None, "shortcut": None}
    assert answers.calls == []
    assert java.ai_messages(room) == []


def test_LLM_장애여도_룰_라우팅은_ROUTE(client, java, answers):
    # FN-AIM-002-10 : 분류 LLM이 실패 상태여도 룰 매칭은 LLM 앞에서 끝난다
    broken = BrokenClassifier()
    client.app.dependency_overrides[clients.get_intent_classifier] = lambda: broken
    as_member(client, 1)
    room = java.add_room(1, "제목")
    evs = events(send(client, room, "일정 등록할래"))

    assert evs[0][1]["kind"] == "ROUTE"
    assert broken.calls == 0


def test_등록_요청은_판정만_준다(client, java, answers):
    # 등록 흐름은 SCR-AIM-012에서 잇는다
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
    # 사용자 메시지는 남아 [다시 시도]가 본문 없이 다시 부를 수 있다
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
    # 미완료 답변에는 고지를 붙이지 않는다
    assert DISCLAIMER not in saved[0]["cnvrsCn"]


class SlowAnswers(Answers):
    """조각 사이에 잠깐 쉰다. 연결이 끊긴 뒤에도 생성이 남아 있게 한다"""

    async def stream(self, messages, max_tokens):
        async for chunk in super().stream(messages, max_tokens):
            await asyncio.sleep(0.05)
            yield chunk


def test_연결이_끊겨도_답변을_끝까지_만들어_완료로_저장(client, java):
    # architecture.md "질문 한 번의 순서" : 브라우저 연결이 끊겨도 생성·저장은 끝까지 한다.
    # TestClient로는 스트림 중간에 끊을 수 없어 서비스를 직접 부른다(client는 설정값용)
    room = java.add_room(1, "제목", cn=SEARCH_TEXT)
    settings = get_settings()
    limits = service.AnswerLimits(settings.answer_first_token_sec, settings.answer_total_sec)
    answers = SlowAnswers(chunks=("끝까지 ", "만든 ", "답변"))

    async def disconnect_after_intent():
        backend = httpx2.AsyncClient(transport=httpx2.MockTransport(java))
        repo = repository.JavaConversationRepository(backend, settings, "access_token=member-1")
        turn = await service.prepare_turn(repo, room, None)
        events = service.answer_turn(
            turn, repo, clients.MockIntentClassifier(), answers, repository.AiSettings(), limits
        )
        first = await anext(events)
        # StreamingResponse는 연결이 끊기면 이벤트 제너레이터를 닫는다
        await events.aclose()
        await asyncio.gather(*service._running)
        return first

    first = asyncio.run(disconnect_after_intent())

    assert first[0] == "intent"
    saved = java.ai_messages(room)
    assert saved[0]["cnvrsCn"] == "끝까지 만든 답변" + DISCLAIMER
    assert saved[0]["cmptnYn"] is True


def test_답변_저장이_실패해도_스트림은_끝나고_message는_null(client, java, answers):
    # 1,000자 상한을 두지 않기로 함(2026-10-28) : Java가 거절하면 저장만 빠진다
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

    # 마지막 12개는 답변0부터라 맨 앞 AI 메시지를 버린다
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
    # 기본 mock 답변 생성기 : 받은 컨텍스트 크기를 알려 준다
    as_member(client, 1)
    room = java.add_room(1, "제목", cn="첫 질문")
    evs = events(send(client, room, SEARCH_TEXT))

    assert names(evs).count("delta") >= 3
    assert "대화 메시지 2개" in deltas(evs)
    assert deltas(evs).endswith(DISCLAIMER)
