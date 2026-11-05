import json
import re
from collections.abc import AsyncIterator
from datetime import date

from app.chat import catalog, tools
from app.chat.clients import Classified, ClassifiedKind, ClassifyError, ToolDecision
from app.chat.rules import RouteRow
from app.core.backend import external_error

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


# 가짜 Java 도구 목록(docs/design/tool-catalog.md 3-2절) : 스냅샷 구조 + 공통코드 값
# 코드 값은 백엔드 db insert_base_data v0.13 기준(HLTG01·13·15·19)
FAKE_CODES: dict[str, list[dict]] = {
    "HLTG19": [
        {"cd": "HLTC0057", "nm": "병원"},
        {"cd": "HLTC0058", "nm": "미용·목욕"},
        {"cd": "HLTC0059", "nm": "케어·투약"},
        {"cd": "HLTC0060", "nm": "기타"},
    ],
    "HLTG01": [
        {"cd": "HLTC0001", "nm": "정기검진"},
        {"cd": "HLTC0002", "nm": "예방접종"},
        {"cd": "HLTC0003", "nm": "질병진료"},
        {"cd": "HLTC0004", "nm": "검사"},
        {"cd": "HLTC0005", "nm": "기타 진료"},
    ],
    "HLTG13": [{"cd": "HLTC0036", "nm": "일상관리"}, {"cd": "HLTC0037", "nm": "정기관리"}],
    "HLTG15": [
        {"cd": "HLTC0038", "nm": "1주"},
        {"cd": "HLTC0039", "nm": "2주"},
        {"cd": "HLTC0040", "nm": "한달"},
        {"cd": "HLTC0041", "nm": "1년"},
        {"cd": "HLTC0042", "nm": "직접입력"},
    ],
}


def fake_catalog_json(structure_version: str | None = None) -> dict:
    raw = json.loads((catalog.DATA_DIR / "tools.snapshot.json").read_text(encoding="utf-8"))
    for tool in raw["tools"]:
        for param in tool["params"].values():
            if param["type"] == "code":
                param["codes"] = FAKE_CODES[param["group"]]
    if structure_version is not None:
        raw["structureVersion"] = structure_version
    return raw


class FakeToolCatalogClient:
    """[가짜 Java 도구 목록]
    - response : 돌려줄 JSON(기본 스냅샷 + 코드 값), fail : 502
    - 받은 횟수(calls) 기록"""

    def __init__(self, response: dict | None = None, fail: bool = False) -> None:
        self.response = fake_catalog_json() if response is None else response
        self.fail = fail
        self.calls = 0

    async def fetch(self) -> catalog.ToolCatalogResponse:
        self.calls += 1
        if self.fail:
            raise external_error()
        return catalog.ToolCatalogResponse.model_validate(self.response)


def fake_catalog() -> catalog.Catalog:
    return catalog.build(catalog.ToolCatalogResponse.model_validate(fake_catalog_json()))
