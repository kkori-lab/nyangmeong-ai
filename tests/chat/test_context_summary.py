import asyncio
import json
from datetime import datetime

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.chat import service
from app.chat.repository import ConversationContext, JavaConversationRepository
from app.chat.schemas import ROLE_AI, ROLE_USER, ConversationMessage
from app.core.backend import get_backend_client
from app.core.config import get_settings
from app.main import create_app
from tests.chat.fakes import FakeToolAgent

ROOM = 804
AJAX = {"X-Requested-With": "XMLHttpRequest"}
SUMMARY = "11월 3일: 연탄 체중 5kg 상담"


def message(seq: int, role: str, cn: str, cmptn: bool = True) -> ConversationMessage:
    return ConversationMessage(
        ai_cnvrs_msg_sn=seq,
        role_cd=role,
        cnvrs_cn=cn,
        msg_seq=seq,
        reg_dt=datetime(2026, 11, 3, 10, 0),
        cmptn_yn=cmptn,
    )


def conversation(turns: int, start: int = 1) -> list[ConversationMessage]:
    # 질문·답변 쌍 turns개, msgSeq는 start부터
    out: list[ConversationMessage] = []
    for t in range(turns):
        out.append(message(start + len(out), ROLE_USER, f"질문{t}"))
        out.append(message(start + len(out), ROLE_AI, f"답변{t}"))
    return out


def turn_of(
    messages: list[ConversationMessage],
    summary: str | None = None,
    summary_end: int | None = None,
) -> service.Turn:
    question = next(m for m in reversed(messages) if m.role_cd == ROLE_USER)
    return service.Turn(ROOM, question, messages, summary=summary, summary_end=summary_end)


class FakeSummarizer:
    def __init__(self, text: str = "새 요약", fail: bool = False) -> None:
        self.text = text
        self.fail = fail
        self.calls: list[tuple[str | None, str]] = []

    async def summarize(self, previous: str | None, transcript: str) -> str:
        self.calls.append((previous, transcript))
        if self.fail:
            raise RuntimeError("down")
        return self.text


class FakeRepo:
    """메시지 저장·요약 저장만 기록하는 가짜 대화 저장소"""

    def __init__(self, next_seq: int, save_fails: bool = False) -> None:
        self.next_seq = next_seq
        self.save_fails = save_fails
        self.messages: list[ConversationMessage] = []
        self.summaries: list[tuple[int, str, int]] = []

    async def add_message(self, room_sn, role_cd, cn, cmptn_yn=True) -> ConversationMessage:
        saved = message(self.next_seq, role_cd, cn, cmptn_yn)
        self.next_seq += 1
        self.messages.append(saved)
        return saved

    async def save_summary(self, room_sn: int, cn: str, end_msg_seq: int) -> None:
        if self.save_fails:
            raise RuntimeError("java down")
        self.summaries.append((room_sn, cn, end_msg_seq))


def compact(turn, saved, repo, summarizer, turns: int = 15) -> None:
    asyncio.run(service.compact_summary(turn, saved, repo, summarizer, turns))


# build_context : 경계선 뒤 최근 15턴 + 요약


def test_요약이_없고_20턴이면_사용자_메시지_기준_최근_15턴만_넘겨야_한다():
    # Arrange
    messages = conversation(19) + [message(39, ROLE_USER, "새 질문")]

    # Act
    context = service.build_context(messages, 39, 15)

    # Assert
    users = [c for c in context if c["role"] == "user"]
    assert len(users) == 15
    assert context[0] == {"role": "user", "content": "질문5"}
    assert context[-1] == {"role": "user", "content": "새 질문"}


def test_경계선이_30이면_31번부터_넘기고_첫_사용자_메시지_앞에_요약을_붙여야_한다():
    # Arrange
    messages = conversation(15) + [message(31, ROLE_USER, "새 질문")]

    # Act
    context = service.build_context(messages, 31, 15, SUMMARY, 30)

    # Assert
    assert context == [
        {
            "role": "user",
            "content": service.SUMMARY_PREFIX + SUMMARY + service.SUMMARY_SUFFIX + "새 질문",
        }
    ]


def test_AI_메시지만_저장된_턴이_섞여도_사용자_메시지_15개로_세야_한다():
    # Arrange : 턴마다 카드 실행 결과(AI 메시지)가 하나 더 붙음
    messages: list[ConversationMessage] = []
    for t in range(16):
        messages.append(message(len(messages) + 1, ROLE_USER, f"질문{t}"))
        messages.append(message(len(messages) + 1, ROLE_AI, f"답변{t}"))
        messages.append(message(len(messages) + 1, ROLE_AI, f"실행 결과{t}"))
    messages.append(message(len(messages) + 1, ROLE_USER, "새 질문"))

    # Act
    context = service.build_context(messages, len(messages), 15)

    # Assert
    assert sum(c["role"] == "user" for c in context) == 15
    assert context[0] == {"role": "user", "content": "질문2"}


def test_요약이_있어도_미완료_답변은_컨텍스트에서_빼야_한다():
    # Arrange
    messages = [
        message(31, ROLE_USER, "질문"),
        message(32, ROLE_AI, "끊긴 답", cmptn=False),
        message(33, ROLE_USER, "새 질문"),
    ]

    # Act
    context = service.build_context(messages, 33, 15, SUMMARY, 30)

    # Assert
    assert {"role": "assistant", "content": "끊긴 답"} not in context
    assert context[-1] == {"role": "user", "content": "새 질문"}


# compact_summary : 15턴째 답변 뒤 요약 저장


def test_15턴째_답변을_저장하면_이전_요약과_함께_요약해_경계선을_답변_번호로_저장해야_한다():
    # Arrange : 경계선 30 뒤 14턴 + 이번 질문(59), 이번 턴에 답변 60 저장
    messages = conversation(14, start=31) + [message(59, ROLE_USER, "열다섯째 질문")]
    saved = [message(60, ROLE_AI, "열다섯째 답변")]
    repo = FakeRepo(61)
    summarizer = FakeSummarizer()

    # Act
    compact(turn_of(messages, SUMMARY, 30), saved, repo, summarizer)

    # Assert
    assert len(summarizer.calls) == 1
    previous, transcript = summarizer.calls[0]
    assert previous == SUMMARY
    assert "[11월 3일] 회원: 질문0" in transcript
    assert "AI: 열다섯째 답변" in transcript
    assert repo.summaries == [(ROOM, "새 요약", 60)]


def test_14턴째에는_요약하지_않아야_한다():
    # Arrange
    messages = conversation(13) + [message(27, ROLE_USER, "열넷째 질문")]
    saved = [message(28, ROLE_AI, "열넷째 답변")]
    repo = FakeRepo(29)
    summarizer = FakeSummarizer()

    # Act
    compact(turn_of(messages), saved, repo, summarizer)

    # Assert
    assert summarizer.calls == []
    assert repo.summaries == []


def test_앞선_요약이_실패해_16턴이_쌓였으면_경계선_뒤_전부를_요약해야_한다():
    # Arrange
    messages = conversation(15) + [message(31, ROLE_USER, "열여섯째 질문")]
    saved = [message(32, ROLE_AI, "열여섯째 답변")]
    repo = FakeRepo(33)
    summarizer = FakeSummarizer()

    # Act
    compact(turn_of(messages), saved, repo, summarizer)

    # Assert
    transcript = summarizer.calls[0][1]
    assert "회원: 질문0" in transcript
    assert "회원: 열여섯째 질문" in transcript
    assert repo.summaries == [(ROOM, "새 요약", 32)]


def test_AI_메시지만_저장된_턴이_섞여도_사용자_메시지_15개가_되면_요약해야_한다():
    # Arrange : 메시지는 44개(카드 실행 결과 포함)지만 사용자 메시지는 15개
    messages: list[ConversationMessage] = []
    for t in range(14):
        messages.append(message(len(messages) + 1, ROLE_USER, f"질문{t}"))
        messages.append(message(len(messages) + 1, ROLE_AI, f"답변{t}"))
        messages.append(message(len(messages) + 1, ROLE_AI, f"실행 결과{t}"))
    messages.append(message(len(messages) + 1, ROLE_USER, "마지막 질문"))
    saved = [message(len(messages) + 1, ROLE_AI, "마지막 답변")]
    repo = FakeRepo(len(messages) + 2)
    summarizer = FakeSummarizer()

    # Act
    compact(turn_of(messages), saved, repo, summarizer)

    # Assert
    assert repo.summaries == [(ROOM, "새 요약", len(messages) + 1)]


def test_미완료_답변은_요약_원문에서_빼야_한다():
    # Arrange
    messages = conversation(14) + [message(29, ROLE_USER, "질문")]
    saved = [message(30, ROLE_AI, "완료 답변")]
    messages[1] = message(2, ROLE_AI, "끊긴 답", cmptn=False)
    summarizer = FakeSummarizer()

    # Act
    compact(turn_of(messages), saved, FakeRepo(31), summarizer)

    # Assert
    assert "끊긴 답" not in summarizer.calls[0][1]


def test_답변_저장_전에_실패한_턴이면_요약하지_않아야_한다():
    # Arrange : 15번째 질문 뒤 답변이 저장되지 않음
    messages = conversation(14) + [message(29, ROLE_USER, "열다섯째 질문")]
    summarizer = FakeSummarizer()

    # Act
    compact(turn_of(messages), [], FakeRepo(30), summarizer)

    # Assert
    assert summarizer.calls == []


@pytest.mark.parametrize("summarizer", [FakeSummarizer(fail=True), FakeSummarizer(text="")])
def test_요약기가_실패하거나_빈_요약이면_저장하지_않고_예외를_올리지_않아야_한다(summarizer):
    # Arrange
    messages = conversation(14) + [message(29, ROLE_USER, "질문")]
    saved = [message(30, ROLE_AI, "답변")]
    repo = FakeRepo(31)

    # Act
    compact(turn_of(messages), saved, repo, summarizer)

    # Assert
    assert repo.summaries == []


def test_요약_저장이_실패해도_예외를_올리지_않아야_한다(caplog):
    # Arrange
    messages = conversation(14) + [message(29, ROLE_USER, "질문")]
    saved = [message(30, ROLE_AI, "답변")]

    # Act
    compact(turn_of(messages), saved, FakeRepo(31, save_fails=True), FakeSummarizer())

    # Assert
    assert "대화 요약 실패: room=804" in caplog.text


# answer_turn : 요약은 done 뒤, 실패해도 답변 그대로


def _run_answer(turn, repo, summarizer) -> list:
    async def run() -> list:
        agent = FakeToolAgent(texts=("열다섯째 ", "답변"))
        limits = service.AnswerLimits(10.0, 60.0)
        ai = service.AiSettings()
        evs = [
            ev
            async for ev in service.answer_turn(
                turn, repo, agent, ai, limits, summarizer=summarizer
            )
        ]
        await asyncio.gather(*list(service._running))
        return evs

    return asyncio.run(run())


def test_15턴째_답변이_끝나면_저장한_답변_번호로_요약을_저장해야_한다():
    # Arrange
    messages = conversation(14) + [message(29, ROLE_USER, "열다섯째 질문")]
    repo = FakeRepo(30)

    # Act
    evs = _run_answer(turn_of(messages), repo, FakeSummarizer())

    # Assert
    assert [name for name, _ in evs][-1] == "done"
    assert repo.summaries == [(ROOM, "새 요약", 30)]


def test_요약기가_실패해도_done과_답변_저장은_그대로여야_한다():
    # Arrange
    messages = conversation(14) + [message(29, ROLE_USER, "열다섯째 질문")]
    repo = FakeRepo(30)

    # Act
    evs = _run_answer(turn_of(messages), repo, FakeSummarizer(fail=True))

    # Assert
    assert [name for name, _ in evs][-1] == "done"
    assert len(repo.messages) == 1
    assert repo.messages[0].cnvrs_cn.startswith("열다섯째 답변")
    assert repo.summaries == []


def test_요약이_있는_방은_도구_고르기에_요약을_붙인_컨텍스트를_넘겨야_한다():
    # Arrange
    messages = conversation(15) + [message(31, ROLE_USER, "새 질문")]
    agent = FakeToolAgent(texts=("답",))

    async def run() -> None:
        limits = service.AnswerLimits(10.0, 60.0)
        turn = turn_of(messages, SUMMARY, 30)
        async for _ in service.answer_turn(turn, FakeRepo(32), agent, service.AiSettings(), limits):
            pass

    # Act
    asyncio.run(run())

    # Assert
    first = agent.decides[0][0][0]["content"]
    assert first.startswith(service.SUMMARY_PREFIX + SUMMARY)


# Java 계약 : 방 조회 응답의 요약 칸, PUT 본문, React 응답에서 빼기


class SummaryJava:
    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.method == "PUT":
            return httpx2.Response(200, json={"status": "success", "httpCode": 200})
        data = {
            "aiCnvrsRoomSn": ROOM,
            "petSn": None,
            "cnvrsTtl": "제목",
            "regDt": "2026-11-24T10:00:00",
            "messages": [
                {
                    "aiCnvrsMsgSn": 1,
                    "roleCd": ROLE_USER,
                    "cnvrsCn": "질문",
                    "msgSeq": 1,
                    "regDt": "2026-11-24T10:00:00",
                    "cmptnYn": True,
                }
            ],
            "smryCn": SUMMARY,
            "smryEndMsgSeq": 30,
        }
        return httpx2.Response(200, json={"status": "success", "httpCode": 200, "data": data})


def _repo(java: SummaryJava, monkeypatch) -> JavaConversationRepository:
    monkeypatch.setenv("BACKEND_BASE_URL", "http://backend.test")
    get_settings.cache_clear()
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(java))
    return JavaConversationRepository(client, get_settings(), "access_token=member-1")


def test_Java_방_조회_응답의_요약_칸을_읽어야_한다(monkeypatch):
    # Arrange
    repo = _repo(SummaryJava(), monkeypatch)

    # Act
    room = asyncio.run(repo.get_room(ROOM))

    # Assert
    assert isinstance(room, ConversationContext)
    assert (room.smry_cn, room.smry_end_msg_seq) == (SUMMARY, 30)


def test_요약_저장은_PUT_summary로_요약과_경계선을_보내야_한다(monkeypatch):
    # Arrange
    java = SummaryJava()
    repo = _repo(java, monkeypatch)

    # Act
    asyncio.run(repo.save_summary(ROOM, SUMMARY, 60))

    # Assert
    request = java.requests[-1]
    assert request.method == "PUT"
    assert request.url.path == f"/internal/ai/conversations/{ROOM}/summary"
    assert json.loads(request.content) == {"smryCn": SUMMARY, "smryEndMsgSeq": 60}
    assert request.headers["X-Requested-With"] == "XMLHttpRequest"


def test_React_대화_조회_응답에는_요약_칸이_없어야_한다(monkeypatch):
    # Arrange
    monkeypatch.setenv("BACKEND_BASE_URL", "http://backend.test")
    get_settings.cache_clear()
    app = create_app()
    backend = httpx2.AsyncClient(transport=httpx2.MockTransport(SummaryJava()))
    app.dependency_overrides[get_backend_client] = lambda: backend
    client = TestClient(app)
    client.cookies.set("access_token", "member-1")

    # Act
    res = client.get(f"/ai/conversations/{ROOM}", headers=AJAX)

    # Assert
    data = res.json()["data"]
    assert res.status_code == 200
    assert data["messages"][0]["cnvrsCn"] == "질문"
    assert "smryCn" not in data
    assert "smryEndMsgSeq" not in data
