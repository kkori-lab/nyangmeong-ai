import asyncio
import json
from pathlib import Path

import pytest
import yaml

from app.chat import clients, rules
from app.chat.clients import (
    ANSWER_SYSTEM,
    GUIDE_RULES,
    AnthropicIntentClassifier,
    Classified,
    ClassifiedKind,
    classify_system,
)
from app.chat.schemas import IntentKind
from app.chat.service import DISCLAIMER, guide_text, judge
from tests.chat.conftest import as_member
from tests.chat.test_llm_clients import (
    MODEL,
    FakeAnthropic,
    answer,
    classify,
    replying,
    streaming,
)
from tests.chat.test_messages import FixedClassifier, MessageJava, events, names, send

DATA = Path(__file__).parent / "data"
PIXEL_QUESTION = "픽셀 캐릭터 생성 어디서 해?"


def guide_files() -> list[dict]:
    return [
        yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(rules.GUIDE_DIR.glob("*.yaml"))
    ]


def guide_screens() -> list[dict]:
    return [screen for data in guide_files() for screen in data.get("screens") or ()]


def guide_tasks() -> list[dict]:
    tasks = [task for data in guide_files() for task in data.get("common") or ()]
    return tasks + [task for screen in guide_screens() for task in screen["tasks"]]


def guide_result(guide_id: str | None = None, related_num: int | None = None) -> FakeAnthropic:
    return replying(json.dumps({"kind": "GUIDE", "guide_id": guide_id, "related_num": related_num}))


def routing_row(scr_id: str) -> rules.RouteRow:
    return next(r for r in rules.routing_table() if r.scr_id == scr_id and r.routable)


def judged(text: str, classified: Classified):
    return asyncio.run(judge(text, False, FixedClassifier(classified)))


# FN-AIM-002-02 안내서 데이터


def test_안내서_청크_id는_모두_다르다():
    ids = [task["id"] for task in guide_tasks()]
    assert len(ids) == len(set(ids)) == len(rules.guide_chunks())


def test_안내서_화면은_매핑표_행과_번호·이름·화면_ID·파라미터가_같다():
    # 라우팅 대상이 아닌 행(상세 화면 등)도 안내서에 허용
    rows = {row.no: row for row in rules.routing_table()}
    for screen in guide_screens():
        row = rows[screen["num"]]
        assert (screen["name"], screen["scr_id"], screen.get("param")) == (
            row.name,
            row.scr_id,
            row.param,
        )


def test_안내서_화면_번호는_겹치지_않는다():
    nums = [screen["num"] for screen in guide_screens()]
    assert len(nums) == len(set(nums))


def test_안내서_순서·참고·검색어는_모두_비지_않은_문자열():
    # 따옴표 없는 "(예: …)" 줄이 사전으로 읽힌 초안이 있었다
    for task in guide_tasks():
        assert isinstance(task["task"], str) and task["task"].strip()
        assert task["steps"], task["id"]
        for field in ("steps", "notes", "faq_keywords"):
            for value in task.get(field) or ():
                assert isinstance(value, str) and value.strip(), (task["id"], field, value)


def test_안내서에는_사람용_메모를_넣지_않는다():
    for screen in guide_screens():
        assert not {"diffs", "todo", "source"} & screen.keys(), screen["num"]


def test_청크_글에는_화면·들어가는_길·순서가_들어간다():
    chunk = rules.find_guide("6-1")
    assert chunk is not None and chunk.num == 6
    assert chunk.text.startswith("[6-1] 픽셀 캐릭터 관리 · 캐릭터 만들기")
    assert "들어가는 길(PC): 프로필 > [마이페이지] > 왼쪽 메뉴 [픽셀 캐릭터]" in chunk.text
    assert "\n1. 마이페이지 > [픽셀 캐릭터]로 가요" in chunk.text


def test_준비_중인_화면은_청크에_준비_상태를_적는다():
    screen = next(s for s in guide_screens() if s.get("status") != "정상")
    chunk = rules.find_guide(screen["tasks"][0]["id"])
    assert f"준비 상태: {screen['status']}" in chunk.text


def test_공통_task는_화면_번호가_없다():
    chunk = rules.find_guide("C-1")
    assert chunk is not None and chunk.num is None
    assert chunk.text.startswith("[C-1] 공통 · ")


# FN-AIM-002-02 1단계 M1 키워드 색인


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (PIXEL_QUESTION, "6-1"),
        ("가족 초대 어떻게 해?", "27-1"),
        ("ai 버튼 어디 있어", "C-1"),
    ],
)
def test_M1은_검색어가_든_청크를_상위_3개_안에_찾는다(text, expected):
    found = rules.search_guide(text)
    assert expected in found
    assert len(found) <= rules.GUIDE_TOP_K


@pytest.mark.parametrize("text", ["고양이가 토해요", "ㅁㄴㅇㄹ", "가"])
def test_M1은_검색어가_없으면_빈_목록(text):
    assert rules.search_guide(text) == []


def test_M1_평가_세트_회귀_하한():
    # 2026-11-05 재실행 값(hit@3 25/45, 범위 밖 5/5). 이 세트에 맞춘 키워드 보강 금지
    lines = (DATA / "guide_eval.jsonl").read_text(encoding="utf-8").splitlines()
    questions = [json.loads(line) for line in lines if line.strip()]
    labels = json.loads((DATA / "guide_labels.json").read_text(encoding="utf-8"))
    hit, rejected, usage, out_of_scope = 0, 0, 0, 0
    for question in questions:
        found = rules.search_guide(question["q"])
        expected = labels[question["id"]]
        if expected:
            usage += 1
            hit += any(chunk_id in expected for chunk_id in found)
        else:
            out_of_scope += 1
            rejected += found == []
    assert (usage, out_of_scope) == (45, 5)
    assert hit >= 25
    assert rejected == 5


def test_평가_정답표의_청크_id는_안내서에_있다():
    labels = json.loads((DATA / "guide_labels.json").read_text(encoding="utf-8"))
    for expected in labels.values():
        for chunk_id in expected:
            assert rules.find_guide(chunk_id) is not None, chunk_id


# FN-AIM-004-02 분류 보강, 2단계 목차 선택


def test_분류_프롬프트에_GUIDE와_안내서_목차가_들어간다():
    system = classify_system()
    assert "- GUIDE:" in system
    assert "guide_id" in system
    for chunk in rules.guide_chunks():
        assert f"\n- {chunk.id} {chunk.screen or '공통'} · {chunk.title}" in system


def test_키워드_힌트에도_위치·사용법_질문은_GUIDE():
    row = routing_row("SCR-MYP-010")
    fake = guide_result("6-1")
    asyncio.run(AnthropicIntentClassifier(fake.client(), MODEL).classify("캐릭터 어디서 해?", row))
    hint = fake.requests[0]["system"][len(classify_system()) :]
    assert "위치·사용법을 묻는 질문" in hint
    assert "GUIDE" in hint


def test_분류가_GUIDE면_목차_번호와_연관_화면을_돌려준다():
    row = routing_row("SCR-MYP-010")
    result = classify(guide_result("6-1", row.no))
    assert result == Classified(
        ClassifiedKind.GUIDE,
        related_scr_id=row.scr_id,
        related_param=row.param,
        guide_id="6-1",
    )


@pytest.mark.parametrize("guide_id", ["99-9", "", None])
def test_목차에_없는_번호는_버린다(guide_id):
    assert classify(guide_result(guide_id)) == Classified(ClassifiedKind.GUIDE)


def test_분류_요청은_system을_문자열로_보낸다():
    # 추가-1(2026-11-05) : 분류 캐시를 켜지 않음
    fake = guide_result("6-1")
    classify(fake, PIXEL_QUESTION)
    body = fake.requests[0]
    assert body["system"] == classify_system()
    assert "cache_control" not in body


def test_GUIDE면_M1_결과를_쓰고_SEARCH로_내보낸다():
    result = judged(PIXEL_QUESTION, Classified(ClassifiedKind.GUIDE, guide_id="28-1"))
    assert result.intent.kind is IntentKind.SEARCH
    assert result.guide_ids == tuple(rules.search_guide(PIXEL_QUESTION))
    assert "6-1" in result.guide_ids


def test_GUIDE이고_M1_결과가_없으면_목차에서_고른_청크를_쓴다():
    result = judged("ㅁㄴㅇㄹ", Classified(ClassifiedKind.GUIDE, guide_id="27-1"))
    assert result.intent.kind is IntentKind.SEARCH
    assert result.guide_ids == ("27-1",)


def test_GUIDE인데_M1도_목차_선택도_없으면_범위_안내():
    result = judged("ㅁㄴㅇㄹ", Classified(ClassifiedKind.GUIDE))
    assert result.intent.kind is IntentKind.FALLBACK
    assert result.out_of_scope is True
    assert result.guide_ids == ()


def test_SEARCH는_안내서를_쓰지_않는다():
    result = judged("고양이가 토해요", Classified(ClassifiedKind.SEARCH))
    assert result.intent.kind is IntentKind.SEARCH
    assert result.guide_ids == ()


# FN-AIM-002-04 바로가기


def test_첫_청크_화면이_라우팅_대상이면_그_화면으로_바로가기():
    result = judged("ㅁㄴㅇㄹ", Classified(ClassifiedKind.GUIDE, guide_id="6-1"))
    assert result.shortcut == routing_row("SCR-MYP-010").to_intent()


def test_첫_청크_화면이_라우팅_대상이_아니면_연관_화면으로_바로가기():
    # 28 픽셀 캐릭터 상세는 라우팅 대상이 아닌 행
    assert not next(r for r in rules.routing_table() if r.no == 28).routable
    row = routing_row("SCR-MYP-010")
    result = judged(
        "ㅁㄴㅇㄹ",
        Classified(ClassifiedKind.GUIDE, guide_id="28-1", related_scr_id=row.scr_id),
    )
    assert result.guide_ids == ("28-1",)
    assert result.shortcut == row.to_intent()


def test_라우팅_대상_화면도_연관_화면도_없으면_바로가기_없음():
    result = judged("ㅁㄴㅇㄹ", Classified(ClassifiedKind.GUIDE, guide_id="28-1"))
    assert result.shortcut is None


def test_공통_청크는_연관_화면이_없으면_바로가기_없음():
    result = judged("ㅁㄴㅇㄹ", Classified(ClassifiedKind.GUIDE, guide_id="C-1"))
    assert result.shortcut is None


# FN-AIM-002-02 답변


def test_안내서가_있으면_답변_system_둘째_블록에_규칙과_청크_글():
    fake = streaming(["마이페이지에서 ", "만들어요."])

    async def collect():
        generator = clients.AnthropicAnswerGenerator(fake.client(), MODEL)
        stream = generator.stream([{"role": "user", "content": "q"}], 100, guide_text(("6-1",)))
        return [chunk async for chunk in stream]

    assert asyncio.run(collect()) == ["마이페이지에서 ", "만들어요."]
    system = fake.requests[0]["system"]
    assert system[0] == {"type": "text", "text": ANSWER_SYSTEM}
    assert system[1]["text"] == GUIDE_RULES + rules.find_guide("6-1").text


def test_안내서가_없으면_답변_system은_지금과_같다():
    fake = streaming(["답"])
    answer(fake)
    assert fake.requests[0]["system"] == ANSWER_SYSTEM


def test_안내_규칙은_지어내지_않고_고객센터를_안내한다():
    assert "지어내지 않는다" in GUIDE_RULES
    assert "1:1 문의" in GUIDE_RULES
    assert "[ ]" in GUIDE_RULES


def test_청크_글은_순서대로_빈_줄로_잇고_없는_id는_뺀다():
    first, second = rules.find_guide("6-1"), rules.find_guide("27-1")
    assert guide_text(("6-1", "없음", "27-1")) == f"{first.text}\n\n{second.text}"
    assert guide_text(()) is None
    assert guide_text(("없음",)) is None


# 메시지 전송 흐름


class GuideAnswers:
    """안내서 인자까지 기록하는 가짜 답변 생성기"""

    def __init__(self) -> None:
        self.guides: list[str | None] = []

    async def stream(self, messages, max_tokens, guide=None):
        self.guides.append(guide)
        yield "마이페이지에서 만들어요."


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


def test_사용법_질문은_SEARCH로_답하고_안내서를_답변에_넘기고_바로가기를_준다(client, java):
    answers = GuideAnswers()
    client.app.dependency_overrides[clients.get_answer_generator] = lambda: answers
    client.app.dependency_overrides[clients.get_intent_classifier] = lambda: FixedClassifier(
        Classified(ClassifiedKind.GUIDE)
    )
    as_member(client, 1)
    room = java.add_room(1, "제목")
    evs = events(send(client, room, PIXEL_QUESTION))

    assert names(evs) == ["intent", "delta", "delta", "done"]
    assert evs[0][1]["kind"] == "SEARCH"
    assert evs[0][1]["scrId"] is None
    assert evs[2][1]["text"] == DISCLAIMER
    assert evs[3][1]["shortcut"]["scrId"] == "SCR-MYP-010"
    assert answers.guides == [guide_text(tuple(rules.search_guide(PIXEL_QUESTION)))]


def test_일반_검색_질문은_안내서_없이_답변한다(client, java):
    answers = GuideAnswers()
    client.app.dependency_overrides[clients.get_answer_generator] = lambda: answers
    client.app.dependency_overrides[clients.get_intent_classifier] = lambda: FixedClassifier(
        Classified(ClassifiedKind.SEARCH)
    )
    as_member(client, 1)
    room = java.add_room(1, "제목")
    evs = events(send(client, room, "고양이가 토해요"))

    assert evs[0][1]["kind"] == "SEARCH"
    assert answers.guides == [None]
