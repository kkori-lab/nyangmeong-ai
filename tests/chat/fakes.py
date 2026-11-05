import re
from collections.abc import AsyncIterator
from datetime import date

from app.chat import tools
from app.chat.clients import Classified, ClassifiedKind, ClassifyError, ToolDecision
from app.chat.rules import RouteRow

TITLE_LENGTH = 30
# 가짜 분류기가 질문으로 보는 표현
QUESTION = re.compile(r"[?？]|뭐|왜|어떻게|알려|어때|될까|되나|나요|까요")


class FakeTitleGenerator:
    """LLM 없이 첫 메시지 앞부분을 제목으로 사용. 요약은 답변 앞부분, 받은 질문·답변 기록"""

    def __init__(self) -> None:
        self.summaries: list[tuple[str, str]] = []

    async def generate(self, first_message: str) -> str:
        return first_message.strip()[:TITLE_LENGTH]

    async def summarize(self, question: str, answer: str) -> str:
        self.summaries.append((question, answer))
        return f"요약 {answer.strip()}"[:TITLE_LENGTH]


class FakeIntentClassifier:
    """질문 표현이 있으면 검색, 아니면 판단 못 함. 받은 힌트 기록"""

    def __init__(self) -> None:
        self.hints: list[RouteRow | None] = []

    async def classify(self, text: str, hint: RouteRow | None = None) -> Classified:
        self.hints.append(hint)
        if QUESTION.search(text):
            return Classified(ClassifiedKind.SEARCH)
        return Classified(ClassifiedKind.UNKNOWN)


class FakeAnswerGenerator:
    """받은 컨텍스트 크기를 알리는 고정 문장을 몇 조각으로 분할"""

    async def stream(self, messages: list[dict], max_tokens: int) -> AsyncIterator[str]:
        for chunk in ("(가짜 답변) ", f"대화 메시지 {len(messages)}개를 받았습니다."):
            yield chunk


class FakeRegisterExtractor:
    """아무 칸도 채우지 않음(빈 칸은 되물음)"""

    async def extract(self, text: str, today: date) -> dict:
        return {}


async def _chunks(texts) -> AsyncIterator[str]:
    for text in texts:
        yield text


class FakeToolAgent:
    """[가짜 도구 고르기 LLM]
    - tool·raw : 고를 도구와 원 인자, texts : 도구 대신 글 답변, fail : ClassifyError
    - 받은 호출(decides)과 서버 도구 결과(results) 기록"""

    def __init__(
        self,
        tool: str | None = None,
        raw: dict | None = None,
        texts: tuple[str, ...] | None = None,
        fail: bool = False,
        answer_chunks: tuple[str, ...] = ("안내서대로 ", "답할게요."),
    ) -> None:
        self.tool = tool
        self.raw = raw or {}
        self.texts = texts
        self.fail = fail
        self.answer_chunks = answer_chunks
        self.decides: list[tuple[list[dict], date, RouteRow | None]] = []
        self.results: list[str] = []

    async def decide(
        self, messages: list[dict], max_tokens: int, today: date, hint: RouteRow | None = None
    ) -> ToolDecision:
        self.decides.append((messages, today, hint))
        if self.fail:
            raise ClassifyError("api_error")
        if self.texts is not None:
            return ToolDecision(text=_chunks(self.texts))
        if self.tool is None:
            return ToolDecision()
        use = {"type": "tool_use", "id": "toolu_1", "name": self.tool, "input": self.raw}
        return ToolDecision(call=tools.parse(self.tool, self.raw, "toolu_1"), content=(use,))

    def answer(
        self, messages: list[dict], decision: ToolDecision, result: str, max_tokens: int, today
    ) -> AsyncIterator[str]:
        self.results.append(result)
        return _chunks(self.answer_chunks)
