import asyncio
import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from app.chat import clients, rules
from app.chat.clients import GUIDE_RULES
from app.chat.schemas import IntentKind
from app.chat.service import DISCLAIMER, guide_text, judge_tools
from tests.chat.conftest import as_member
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_messages import MessageJava, deltas, events, names, send

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


def routing_row(scr_id: str) -> rules.RouteRow:
    return next(r for r in rules.routing_table() if r.scr_id == scr_id and r.routable)


def judged(text: str, agent: FakeToolAgent):
    # 도구 흐름 판정 : 가짜 도구 고르기가 고른 도구로
    context = [{"role": "user", "content": text}]
    return asyncio.run(judge_tools(text, context, agent, 4500, date(2026, 11, 11), 5.0))


def guided(text: str, chunk_id: str | None = None):
    # search_guide 도구로 목차 청크를 고른(또는 안 고른) 경우
    return judged(text, FakeToolAgent("search_guide", {"chunk_id": chunk_id}))


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


def test_M1_새_평가_세트_회귀_하한():
    # 2026-11-05 프론트 대조 반영 뒤 값(hit@3 21/44). 안내서·키워드를 보지 않고 만든 세트
    # 정답 None은 안내서에 없는 기능(비밀번호 찾기)이라 뺀다. 범위 밖은 분류 LLM이 먼저 거른다
    lines = (DATA / "guide_eval2.jsonl").read_text(encoding="utf-8").splitlines()
    questions = [json.loads(line) for line in lines if line.strip()]
    labels = json.loads((DATA / "guide_labels2.json").read_text(encoding="utf-8"))
    usage = [q for q in questions if labels[q["id"]]]
    out_of_scope = [q for q in questions if labels[q["id"]] == []]
    assert (len(questions), len(usage), len(out_of_scope)) == (50, 44, 5)
    hit = sum(
        any(chunk_id in labels[q["id"]] for chunk_id in rules.search_guide(q["q"])) for q in usage
    )
    assert hit >= 21


def test_새_평가_정답표의_청크_id는_안내서에_있다():
    labels = json.loads((DATA / "guide_labels2.json").read_text(encoding="utf-8"))
    for expected in labels.values():
        for chunk_id in expected or []:
            assert rules.find_guide(chunk_id) is not None, chunk_id


def test_평가_정답표의_청크_id는_안내서에_있다():
    labels = json.loads((DATA / "guide_labels.json").read_text(encoding="utf-8"))
    for expected in labels.values():
        for chunk_id in expected:
            assert rules.find_guide(chunk_id) is not None, chunk_id


# FN-AIM-002-02 안내서 청크 고르기(search_guide 도구 + M1)


def test_GUIDE면_M1_결과를_쓰고_SEARCH로_내보낸다():
    result = guided(PIXEL_QUESTION)
    assert result.intent.kind is IntentKind.SEARCH
    assert result.guide_ids == tuple(rules.search_guide(PIXEL_QUESTION))
    assert "6-1" in result.guide_ids


def test_M1_결과가_있어도_목차에서_고른_청크가_맨_앞():
    # 후속 2(2026-11-05) : M1이 엉뚱한 청크를 잡아도 목차 선택을 버리지 않는다(R03·R08·R19)
    m1 = rules.search_guide(PIXEL_QUESTION)
    assert m1 and "28-1" not in m1
    result = guided(PIXEL_QUESTION, "28-1")
    assert result.intent.kind is IntentKind.SEARCH
    assert result.guide_ids == ("28-1", *m1[: rules.GUIDE_TOP_K - 1])


def test_목차_선택이_M1_결과에_있으면_중복_없이_맨_앞():
    m1 = rules.search_guide(PIXEL_QUESTION)
    picked = m1[-1]
    result = guided(PIXEL_QUESTION, picked)
    assert result.guide_ids[0] == picked
    assert len(result.guide_ids) == len(set(result.guide_ids)) == len(m1)
    assert set(result.guide_ids) == set(m1)


@pytest.mark.parametrize("guide_id", [None, "99-9"])
def test_목차_선택이_없거나_없는_번호면_M1_결과_그대로(guide_id):
    result = guided(PIXEL_QUESTION, guide_id)
    assert result.guide_ids == tuple(rules.search_guide(PIXEL_QUESTION))


def test_합친_청크는_최대_3개():
    for guide_id in ("28-1", "C-1", "27-1"):
        result = guided(PIXEL_QUESTION, guide_id)
        assert len(result.guide_ids) <= rules.GUIDE_TOP_K
        assert result.guide_ids[0] == guide_id


def test_GUIDE이고_M1_결과가_없으면_목차에서_고른_청크를_쓴다():
    result = guided("ㅁㄴㅇㄹ", "27-1")
    assert result.intent.kind is IntentKind.SEARCH
    assert result.guide_ids == ("27-1",)


def test_GUIDE인데_M1도_목차_선택도_없으면_범위_안내():
    result = guided("ㅁㄴㅇㄹ")
    assert result.intent.kind is IntentKind.FALLBACK
    assert result.out_of_scope is True
    assert result.guide_ids == ()


def test_바로_답은_안내서를_쓰지_않는다():
    result = judged("고양이가 토해요", FakeToolAgent(texts=("답",)))
    assert result.intent.kind is IntentKind.SEARCH
    assert result.guide_ids == ()


# FN-AIM-002-04 바로가기


def test_첫_청크_화면이_라우팅_대상이면_그_화면으로_바로가기():
    result = guided("ㅁㄴㅇㄹ", "6-1")
    assert result.shortcut == routing_row("SCR-MYP-010").to_intent()


def test_첫_청크_화면이_라우팅_대상이_아니면_바로가기_없음():
    # 28 픽셀 캐릭터 상세는 라우팅 대상이 아닌 행
    assert not next(r for r in rules.routing_table() if r.no == 28).routable
    result = guided("ㅁㄴㅇㄹ", "28-1")
    assert result.guide_ids == ("28-1",)
    assert result.shortcut is None


def test_공통_청크는_바로가기_없음():
    result = guided("ㅁㄴㅇㄹ", "C-1")
    assert result.shortcut is None


# FN-AIM-002-02 답변


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


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


def test_사용법_질문은_SEARCH로_답하고_안내서를_도구_결과로_넘기고_바로가기를_준다(client, java):
    # 목차 청크를 안 골라도 M1 결과를 넘김. 사용법 안내는 고지 없음(2026-11-09, FN-AIM-002-03)
    agent = FakeToolAgent("search_guide", {"chunk_id": None})
    client.app.dependency_overrides[clients.get_tool_agent] = lambda: agent
    as_member(client, 1)
    room = java.add_room(1, "제목")
    evs = events(send(client, room, PIXEL_QUESTION))

    assert names(evs) == ["intent", "delta", "delta", "done"]
    assert evs[0][1]["kind"] == "SEARCH"
    assert evs[0][1]["scrId"] is None
    assert DISCLAIMER not in deltas(evs)
    assert evs[3][1]["shortcut"]["scrId"] == "SCR-MYP-010"
    assert agent.results == [guide_text(tuple(rules.search_guide(PIXEL_QUESTION)))]


def test_일반_질문_바로_답은_안내서를_넘기지_않는다(client, java):
    agent = FakeToolAgent(texts=("토하면 ", "지켜보세요."))
    client.app.dependency_overrides[clients.get_tool_agent] = lambda: agent
    as_member(client, 1)
    room = java.add_room(1, "제목")
    evs = events(send(client, room, "고양이가 토해요"))

    assert evs[0][1]["kind"] == "SEARCH"
    assert agent.results == []
