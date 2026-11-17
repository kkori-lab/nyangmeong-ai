import json
import re
from collections.abc import AsyncIterator
from datetime import date

from app.chat import catalog, tools
from app.chat.clients import FOLLOW_ROUNDS, ClassifyError, ReadMore, ToolDecision
from app.chat.rules import RouteRow
from app.core.backend import external_error

TITLE_LENGTH = 30
# 기본 가짜 도구 고르기가 질문으로 보는 표현
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
    - follow_tool·follow_raw : 결과를 받은 뒤 한 번 더 고를 도구(follow가 있을 때만)
    - follows : 결과 뒤 차례로 고를 (도구, 원 인자) 목록. 실제처럼 결과가 ReadMore일 때만
      다음 것을 고르고 FOLLOW_ROUNDS번까지 (follow_tool이 있으면 그 하나로)
    - 받은 호출(decides)과 서버 도구 결과(results, 두 번째 결과 포함) 기록"""

    def __init__(
        self,
        tool: str | None = None,
        raw: dict | None = None,
        texts: tuple[str, ...] | None = None,
        fail: bool = False,
        answer_chunks: tuple[str, ...] = ("안내서대로 ", "답할게요."),
        follow_tool: str | None = None,
        follow_raw: dict | None = None,
        follows: tuple[tuple[str, dict], ...] = (),
    ) -> None:
        self.tool = tool
        self.raw = raw or {}
        self.texts = texts
        self.fail = fail
        self.answer_chunks = answer_chunks
        self.follow_tool = follow_tool
        self.follow_raw = follow_raw or {}
        self.follows = ((follow_tool, self.follow_raw),) if follow_tool is not None else follows
        self.decides: list[tuple[list[dict], date, RouteRow | None]] = []
        self.results: list[str | None] = []

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

    async def answer(
        self,
        messages: list[dict],
        decision: ToolDecision,
        result: str,
        max_tokens: int,
        today,
        follow=None,
    ) -> AsyncIterator[str]:
        self.results.append(result)
        if follow is not None:
            for round_no, (name, raw) in enumerate(self.follows[:FOLLOW_ROUNDS], start=2):
                call = tools.parse(name, raw, f"toolu_{round_no}")
                second = await follow(call)
                self.results.append(second)
                if not isinstance(second, ReadMore):
                    break
        for chunk in self.answer_chunks:
            yield chunk


class FakeBasicToolAgent(FakeToolAgent):
    """[기본 가짜 도구 고르기] 테스트가 따로 끼우지 않을 때
    - 키워드에 걸린(hint) 질문꼴이 아닌 글 : 그 화면으로 navigate
    - 질문꼴 글 : 받은 컨텍스트 크기를 알리는 고정 글로 바로 답(몇 조각)
    - 그 밖 : 도구도 글도 없음(폴백)"""

    async def decide(
        self, messages: list[dict], max_tokens: int, today: date, hint: RouteRow | None = None
    ) -> ToolDecision:
        self.decides.append((messages, today, hint))
        if self.fail:
            raise ClassifyError("api_error")
        text = messages[-1]["content"]
        if hint is not None and not QUESTION.search(text):
            raw = {"screen_num": hint.no}
            use = {"type": "tool_use", "id": "toolu_1", "name": tools.NAVIGATE, "input": raw}
            return ToolDecision(call=tools.parse(tools.NAVIGATE, raw, "toolu_1"), content=(use,))
        if QUESTION.search(text):
            return ToolDecision(text=self.reply(messages, max_tokens))
        return ToolDecision()

    def reply(self, messages: list[dict], max_tokens: int) -> AsyncIterator[str]:
        # 바로 답 글 : 테스트가 조각·실패를 바꿀 때 덮어씀
        return _chunks(("(가짜 답변) ", f"대화 메시지 {len(messages)}개를 받았습니다."))


# 가짜 Java 도구 목록(docs/design/tool-catalog.md 3-2절) : 스냅샷 구조 + 공통코드 값
# 코드 값은 백엔드 로컬 GET /internal/ai/tools 응답 기준
# (2026-11-06, 백엔드 PR #174·#177·#179, LJS bd57d24)
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
    "HLTG21": [
        {"cd": "HLTC0079", "nm": "보라"},
        {"cd": "HLTC0080", "nm": "초록"},
        {"cd": "HLTC0081", "nm": "빨강"},
        {"cd": "HLTC0082", "nm": "파랑"},
        {"cd": "HLTC0083", "nm": "회색"},
    ],
    "HLTG22": [
        {"cd": "HLTC0065", "nm": "직접 등록"},
        {"cd": "HLTC0066", "nm": "검진기록 연동"},
        {"cd": "HLTC0067", "nm": "AI 생성"},
    ],
    "HLTG06": [
        {"cd": "HLTC0010", "nm": "복용중"},
        {"cd": "HLTC0011", "nm": "종료"},
    ],
    "HLTG09": [
        {"cd": "HLTC0014", "nm": "체중"},
        {"cd": "HLTC0015", "nm": "식사량"},
        {"cd": "HLTC0016", "nm": "음수량"},
        {"cd": "HLTC0017", "nm": "배변상태"},
        {"cd": "HLTC0018", "nm": "산책"},
    ],
    "HLTG12": [
        {"cd": "HLTC0024", "nm": "WBC"},
        {"cd": "HLTC0025", "nm": "RBC"},
        {"cd": "HLTC0026", "nm": "HGB"},
        {"cd": "HLTC0027", "nm": "HCT"},
        {"cd": "HLTC0028", "nm": "PLT"},
        {"cd": "HLTC0029", "nm": "BUN"},
        {"cd": "HLTC0030", "nm": "CREA"},
        {"cd": "HLTC0031", "nm": "ALT"},
        {"cd": "HLTC0032", "nm": "AST"},
        {"cd": "HLTC0033", "nm": "ALP"},
        {"cd": "HLTC0034", "nm": "GLU"},
        {"cd": "HLTC0078", "nm": "SDMA"},
        {"cd": "HLTC0035", "nm": "직접입력"},
    ],
    "HLTG18": [
        {"cd": "HLTC0055", "nm": "관찰중"},
        {"cd": "HLTC0056", "nm": "종료"},
    ],
    "HLTG10": [
        {"cd": "HLTC0019", "nm": "정상"},
        {"cd": "HLTC0020", "nm": "딱딱함"},
        {"cd": "HLTC0021", "nm": "무름"},
        {"cd": "HLTC0022", "nm": "설사"},
        {"cd": "HLTC0023", "nm": "변비"},
    ],
    "MYPG05": [
        {"cd": "MYPC0012", "nm": "병원"},
        {"cd": "MYPC0013", "nm": "사료"},
        {"cd": "MYPC0014", "nm": "간식"},
        {"cd": "MYPC0015", "nm": "용품"},
        {"cd": "MYPC0016", "nm": "미용"},
        {"cd": "MYPC0017", "nm": "돌봄"},
        {"cd": "MYPC0018", "nm": "기타"},
    ],
    "MYPG06": [
        {"cd": "MYPC0019", "nm": "직접입력"},
        {"cd": "MYPC0020", "nm": "OCR"},
    ],
    "HLTG17": [
        {"cd": "HLTC0052", "nm": "작아짐"},
        {"cd": "HLTC0053", "nm": "그대로"},
        {"cd": "HLTC0054", "nm": "커짐"},
    ],
    "PETG01": [
        {"cd": "PETC0001", "nm": "강아지"},
        {"cd": "PETC0002", "nm": "고양이"},
    ],
    "PETG02": [
        {"cd": "PETC0003", "nm": "수컷"},
        {"cd": "PETC0004", "nm": "암컷"},
    ],
    "PETG03": [
        {"cd": "PETC0005", "nm": "검정"},
        {"cd": "PETC0006", "nm": "흰색"},
        {"cd": "PETC0007", "nm": "갈색"},
        {"cd": "PETC0008", "nm": "크림"},
        {"cd": "PETC0009", "nm": "회색"},
        {"cd": "PETC0010", "nm": "블랙탄"},
        {"cd": "PETC0011", "nm": "얼룩"},
        {"cd": "PETC0012", "nm": "브린들"},
        {"cd": "PETC0013", "nm": "삼색"},
        {"cd": "PETC0014", "nm": "고등어"},
        {"cd": "PETC0015", "nm": "치즈"},
        {"cd": "PETC0016", "nm": "턱시도"},
        {"cd": "PETC0028", "nm": "황색"},
        {"cd": "PETC0029", "nm": "파티"},
        {"cd": "PETC0030", "nm": "세이블"},
        {"cd": "PETC0031", "nm": "멀"},
        {"cd": "PETC0032", "nm": "젖소"},
        {"cd": "PETC0033", "nm": "카오스"},
        {"cd": "PETC0034", "nm": "포인트"},
        {"cd": "PETC0017", "nm": "직접 입력"},
    ],
    "PCAG01": [
        {"cd": "PCAC0001", "nm": "모집중"},
        {"cd": "PCAC0002", "nm": "매칭완료"},
        {"cd": "PCAC0003", "nm": "거래완료"},
    ],
    "CSCG01": [
        {"cd": "CSCC0001", "nm": "이용방법"},
        {"cd": "CSCC0002", "nm": "계정"},
        {"cd": "CSCC0003", "nm": "신고/제재"},
        {"cd": "CSCC0004", "nm": "기타"},
    ],
    "CMUG03": [
        {"cd": "CMUC0006", "nm": "실종"},
        {"cd": "CMUC0007", "nm": "찾았어요"},
        {"cd": "CMUC0008", "nm": "만료"},
    ],
    "CMUG06": [
        {"cd": "CMUC0018", "nm": "건강"},
        {"cd": "CMUC0019", "nm": "생활"},
        {"cd": "CMUC0020", "nm": "정책"},
        {"cd": "CMUC0021", "nm": "여행"},
    ],
    "PLCG01": [
        {"cd": "PLCC0001", "nm": "병원"},
        {"cd": "PLCC0002", "nm": "미용"},
        {"cd": "PLCC0003", "nm": "용품"},
        {"cd": "PLCC0004", "nm": "동반"},
        {"cd": "PLCC0005", "nm": "호텔"},
    ],
    "CMUG01": [
        {"cd": "CMUC0001", "nm": "펫정보"},
        {"cd": "CMUC0002", "nm": "펫일상"},
        {"cd": "CMUC0024", "nm": "실종센터"},
        {"cd": "CMUC0028", "nm": "우리동네 펫돌봄"},
    ],
    "MYPG01": [
        {"cd": "MYPC0001", "nm": "머리"},
        {"cd": "MYPC0002", "nm": "얼굴"},
        {"cd": "MYPC0003", "nm": "목"},
        {"cd": "MYPC0004", "nm": "의상"},
        {"cd": "MYPC0005", "nm": "가방"},
        {"cd": "MYPC0006", "nm": "신발"},
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
