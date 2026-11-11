import asyncio
import json
import re

import httpx2
import pytest

from app.chat import repository, rules, tools
from app.chat.clients import AnthropicToolAgent, ToolDecision
from app.chat.repository import JavaToolReader
from app.chat.service import DISCLAIMER, READ_MAX_PETS, READ_NO_PET, READ_PET_ASK
from app.core.backend import external_error
from app.core.config import Settings
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_llm_clients import MODEL, FakeAnthropic, sse
from tests.chat.test_messages import MessageJava, deltas, events, send
from tests.chat.test_register import CHOCO, TODAY
from tests.chat.test_tools import CONTEXT, room_of, sse_response, tool_sse, use_agent

ANSWER = "안내서대로 답할게요."


class FakeToolReader:
    """[가짜 READ 실행]
    - data : 돌려줄 Java data, fail : 502
    - 받은 경로·query(calls) 기록"""

    def __init__(
        self,
        data: object = None,
        fail: bool = False,
        by_path: dict[str, object] | None = None,
        fail_paths: tuple[str, ...] = (),
    ) -> None:
        self.data = [] if data is None else data
        self.fail = fail
        # 경로별 data(없으면 data), 이 경로들만 502
        self.by_path = by_path or {}
        self.fail_paths = fail_paths
        self.calls: list[tuple[str, dict]] = []

    async def read(self, path: str, params: dict) -> object:
        self.calls.append((path, params))
        if self.fail or path in self.fail_paths:
            raise external_error()
        return self.by_path.get(path, self.data)


def payload(text: str | None) -> object:
    """READ 결과 글 : 첫 줄은 '조회한 반려동물: 이름', 나머지는 JSON"""
    head, body = (text or "").split("\n", 1)
    assert head.startswith("조회한 반려동물: ")
    return json.loads(body)


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


def use_reader(client, reader: FakeToolReader) -> FakeToolReader:
    client.app.dependency_overrides[repository.get_tool_reader] = lambda: reader
    return reader


# 실행 흐름


def test_READ_도구를_고르면_경로와_query로_Java를_부르고_결과로_SEARCH_답변해야_한다(client, java):
    raw = {"from_ymd": "2026-10-01", "to_ymd": "10월 말", "schdl_knd_cd": "HLTC0057", "size": 10}
    agent = use_agent(client, FakeToolAgent("list_my_care_schedules", raw))
    reader = use_reader(client, FakeToolReader([{"schdlNm": "병원"}]))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "이번 달 병원 일정 있어?"))

    assert evs[0][1]["kind"] == "SEARCH"
    assert reader.calls == [
        (
            "/api/care-schedules",
            {"fromYmd": "2026-10-01", "schdlKndCd": "HLTC0057", "size": 10, "petSns": "1"},
        )
    ]
    assert payload(agent.results[0]) == [{"schdlNm": "병원"}]
    # 일정 조회는 기록만 읽어 주는 답이라 고지 없음(2026-11-11, 도구 notice)
    assert deltas(evs) == ANSWER
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [ANSWER]


# 여러 아이 일정(list_my_care_schedules, pet_list hook) : Java 1번 호출


def test_여러_아이_일정은_이름이_둘이면_그_번호들을_쉼표로_한_번에_불러야_한다(client, java):
    agent = use_agent(client, FakeToolAgent("list_my_care_schedules", {}))
    reader = use_reader(client, FakeToolReader([{"schdlSn": 7, "petSn": 2}]))
    java.pets.append({"petSn": 3, "petNm": "보리", "careArtclNms": []})
    room = room_of(client, java)

    events(send(client, room, "초코랑 뭉치 다음 병원 언제야?"))

    assert reader.calls == [("/api/care-schedules", {"petSns": "1,2"})]
    head, body = (agent.results[0] or "").split("\n", 1)
    assert head == "조회한 반려동물: 초코(petSn 1), 뭉치(petSn 2)"
    assert json.loads(body) == [{"schdlSn": 7, "petSn": 2}]


def test_여러_아이_일정은_펫_태그_방에서_이름이_없으면_그_아이_번호만_보내야_한다(client, java):
    use_agent(client, FakeToolAgent("list_my_care_schedules", {}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java, pet_sn=CHOCO)

    events(send(client, room, "다음 병원 언제야?"))

    assert reader.calls == [("/api/care-schedules", {"petSns": "1"})]


def test_여러_아이_일정은_이름도_태그도_없으면_petSns_없이_한_번_불러야_한다(client, java):
    agent = use_agent(client, FakeToolAgent("list_my_care_schedules", {}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java)

    events(send(client, room, "우리 애들 이번 주 일정 뭐 있어?"))

    assert reader.calls == [("/api/care-schedules", {})]
    assert (agent.results[0] or "").startswith("조회한 반려동물: 초코(petSn 1), 뭉치(petSn 2)\n")


def test_여러_아이_일정은_열_마리를_넘어도_되묻지_않고_한_번_불러야_한다(client, java):
    use_agent(client, FakeToolAgent("list_my_care_schedules", {}))
    reader = use_reader(client, FakeToolReader())
    many_pets(java, READ_MAX_PETS + 1)
    room = room_of(client, java)

    events(send(client, room, "이번 달 일정 알려 줘"))

    assert reader.calls == [("/api/care-schedules", {})]


def test_여러_아이_일정은_반려동물이_없으면_등록을_안내해야_한다(client, java):
    use_agent(client, FakeToolAgent("list_my_care_schedules", {}))
    reader = use_reader(client, FakeToolReader())
    java.pets = []
    room = room_of(client, java)

    evs = events(send(client, room, "이번 달 일정 알려 줘"))

    assert reader.calls == []
    assert deltas(evs) == READ_NO_PET


def test_참거짓_조건은_소문자_글자로_보내야_한다(client, java):
    use_agent(client, FakeToolAgent("list_expenses", {"common": True}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java)

    events(send(client, room, "공용 지출 알려 줘"))

    assert reader.calls == [("/api/expenses", {"common": "true"})]


def test_케어_항목_목록은_메인_표시_조건을_보내지_않아야_한다(client, java):
    use_agent(client, FakeToolAgent("list_care_items", {"main_expsr_yn": True}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java, pet_sn=CHOCO)

    events(send(client, room, "등록된 케어 뭐 있어?"))

    assert reader.calls == [("/api/pets/1/care-items", {})]


def test_도구_결과에서_메모_같은_내용_칸은_중첩까지_지워야_한다(client, java):
    data = [
        {
            "schdlNm": "정기검진",
            "memoCn": "비밀 메모",
            "lastCycle": {"ckupMemoCn": "자유 입력", "obsrvSz": 1.5, "cyclCnt": 2},
        }
    ]
    agent = use_agent(client, FakeToolAgent("list_my_care_schedules", {}))
    use_reader(client, FakeToolReader(data))
    room = room_of(client, java, pet_sn=CHOCO)

    events(send(client, room, "다음 병원 언제야?"))

    assert payload(agent.results[0]) == [
        {"schdlNm": "정기검진", "lastCycle": {"obsrvSz": 1.5, "cyclCnt": 2}}
    ]


def test_Java_READ가_실패하면_불러오지_못함을_도구_결과로_넘겨야_한다(client, java):
    agent = use_agent(client, FakeToolAgent("get_health_indicators", {}))
    use_reader(client, FakeToolReader(fail=True))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "체중 어때?"))

    assert evs[0][1]["kind"] == "SEARCH"
    assert agent.results == [rules.READ_FAILED]
    assert deltas(evs) == ANSWER


# 반려동물 결정


def test_문장_속_이름으로_반려동물을_정해야_한다(client, java):
    use_agent(client, FakeToolAgent("get_health_indicators", {}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java)

    events(send(client, room, "뭉치 요즘 체중 어때?"))

    assert reader.calls == [("/api/pets/2/health-indicators", {})]


def many_pets(java, count: int) -> str:
    java.pets = [{"petSn": 100 + i, "petNm": f"아이{i}", "careArtclNms": []} for i in range(count)]
    return ", ".join(p["petNm"] for p in java.pets)


def test_이름_없이_열_마리를_넘으면_Java_READ를_부르지_않고_이름을_되물어야_한다(client, java):
    agent = use_agent(client, FakeToolAgent("get_health_indicators", {}))
    reader = use_reader(client, FakeToolReader())
    names = many_pets(java, READ_MAX_PETS + 1)
    room = room_of(client, java)

    evs = events(send(client, room, "요즘 체중 어때?"))

    assert evs[0][1]["kind"] == "SEARCH"
    assert reader.calls == []
    assert agent.results == []
    assert deltas(evs) == READ_PET_ASK.format(names=names)


def test_이름이_둘이면_그_아이들을_마리마다_읽고_이름_줄을_붙여야_한다(client, java):
    agent = use_agent(client, FakeToolAgent("get_health_indicators", {}))
    reader = use_reader(
        client,
        FakeToolReader(
            by_path={
                "/api/pets/1/health-indicators": {"weight": 4},
                "/api/pets/2/health-indicators": {"weight": 6},
            }
        ),
    )
    room = room_of(client, java)

    events(send(client, room, "초코랑 뭉치 요즘 체중 어때?"))

    assert sorted(path for path, _ in reader.calls) == [
        "/api/pets/1/health-indicators",
        "/api/pets/2/health-indicators",
    ]
    first, second = (agent.results[0] or "").split("\n\n")
    assert first.startswith("조회한 반려동물: 초코\n")
    assert json.loads(first.split("\n", 1)[1]) == {"weight": 4}
    assert second.startswith("조회한 반려동물: 뭉치\n")
    assert json.loads(second.split("\n", 1)[1]) == {"weight": 6}


def test_전체_방에서_이름이_없으면_모든_아이를_읽어야_한다(client, java):
    use_agent(client, FakeToolAgent("get_health_indicators", {}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java)

    events(send(client, room, "전체 반려동물 체중 알려 줘"))

    assert sorted(path for path, _ in reader.calls) == [
        "/api/pets/1/health-indicators",
        "/api/pets/2/health-indicators",
    ]


def test_펫_태그_방에서_이름이_없으면_그_아이만_읽어야_한다(client, java):
    use_agent(client, FakeToolAgent("get_health_indicators", {}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java, pet_sn=CHOCO)

    events(send(client, room, "요즘 체중 어때?"))

    assert reader.calls == [("/api/pets/1/health-indicators", {})]


def test_한_마리가_실패해도_다른_아이_결과는_남겨야_한다(client, java):
    agent = use_agent(client, FakeToolAgent("get_health_indicators", {}))
    use_reader(
        client,
        FakeToolReader({"weight": 4}, fail_paths=("/api/pets/2/health-indicators",)),
    )
    room = room_of(client, java)

    events(send(client, room, "전체 반려동물 체중 알려 줘"))

    first, second = (agent.results[0] or "").split("\n\n")
    assert json.loads(first.split("\n", 1)[1]) == {"weight": 4}
    assert second == f"조회한 반려동물: 뭉치\n{rules.READ_FAILED}"


def test_모든_아이가_실패하면_불러오지_못함_하나여야_한다(client, java):
    agent = use_agent(client, FakeToolAgent("get_health_indicators", {}))
    use_reader(client, FakeToolReader(fail=True))
    room = room_of(client, java)

    events(send(client, room, "전체 반려동물 체중 알려 줘"))

    assert agent.results == [rules.READ_FAILED]


def test_결과_상한은_마리_수로_나눠_마리마다_잘라야_한다(client, java):
    agent = use_agent(client, FakeToolAgent("get_health_indicators", {}))
    use_reader(client, FakeToolReader([{"schdlNm": "가" * 100}] * 100))
    room = room_of(client, java)

    events(send(client, room, "전체 반려동물 체중 알려 줘"))

    for block in (agent.results[0] or "").split("\n\n"):
        body = block.split("\n", 1)[1]
        assert len(body) == rules.READ_RESULT_MAX_CHARS // 2 + len(rules.READ_TRUNCATED)


def test_앞_결과의_번호로_상세를_읽을_때는_그_번호가_나온_아이만_불러야_한다(client, java):
    agent = use_agent(
        client,
        FakeToolAgent(
            "list_checkups", {}, follow_tool="get_checkup", follow_raw={"ckup_rcd_sn": 22}
        ),
    )
    reader = use_reader(
        client,
        FakeToolReader(
            by_path={
                "/api/pets/1/checkups": [{"ckupRcdSn": 11}],
                "/api/pets/2/checkups": [{"ckupRcdSn": 22}],
            }
        ),
    )
    room = room_of(client, java)

    events(send(client, room, "전체 반려동물 마지막 검진 자세히 알려 줘"))

    paths = [path for path, _ in reader.calls]
    assert sorted(paths[:2]) == ["/api/pets/1/checkups", "/api/pets/2/checkups"]
    assert paths[2:] == ["/api/pets/2/checkups/22"]
    assert len(agent.results) == 2


def test_READ_시간을_Java_호출_수와_함께_로그로_남겨야_한다(client, java, caplog):
    use_agent(client, FakeToolAgent("get_health_indicators", {}))
    use_reader(client, FakeToolReader())
    room = room_of(client, java)

    with caplog.at_level("INFO", logger="app.chat.service"):
        events(send(client, room, "전체 반려동물 체중 알려 줘"))

    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("READ 도구 시간")]
    assert len(lines) == 1
    assert re.fullmatch(r"READ 도구 시간: get_health_indicators Java 2번 \d+ms", lines[0])


def test_여러_아이_일정_READ는_시간_로그에_Java_1번으로_남겨야_한다(client, java, caplog):
    use_agent(client, FakeToolAgent("list_my_care_schedules", {}))
    use_reader(client, FakeToolReader([{"schdlSn": 7, "petSn": 2}]))
    room = room_of(client, java)

    with caplog.at_level("INFO", logger="app.chat.service"):
        events(send(client, room, "우리 애들 이번 달 일정 알려줘"))

    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("READ 도구 시간")]
    assert len(lines) == 1
    assert re.fullmatch(r"READ 도구 시간: list_my_care_schedules Java 1번 \d+ms", lines[0])


def test_반려동물이_없으면_등록을_안내해야_한다(client, java):
    java.pets = []
    use_agent(client, FakeToolAgent("get_health_indicators", {}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java)

    evs = events(send(client, room, "요즘 체중 어때?"))

    assert reader.calls == []
    assert deltas(evs) == READ_NO_PET


def test_반려동물_목록을_못_받으면_error_이벤트여야_한다(client, java):
    java.context_status = 0
    use_agent(client, FakeToolAgent("get_health_indicators", {}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "체중 어때?"))

    assert [name for name, _ in evs] == ["intent", "error"]
    assert reader.calls == []


# 결과 크기·Java 호출


def test_결과가_길면_앞부분만_잘라_표시해야_한다():
    data = [{"schdlNm": "가" * 100}] * 100

    text = rules.read_result_text(data)

    assert len(text) == rules.READ_RESULT_MAX_CHARS + len(rules.READ_TRUNCATED)
    assert text.endswith(rules.READ_TRUNCATED)


def test_결과의_날짜와_일시에_요일을_붙여야_한다():
    data = {"a": "2026-11-01", "b": "2026-11-11T09:30:00", "c": ["2026-11-11"]}

    text = rules.read_result_text(data)

    assert "2026-11-01 (일)" in text
    assert "2026-11-11 (수)T09:30:00" in text
    assert '["2026-11-11 (수)"]' in text


def test_날짜가_아닌_값은_요일을_붙이지_않아야_한다():
    data = {"a": "2026년", "b": "12-34", "c": "2026-13-01", "d": 20261101, "e": "x2026-11-01"}

    assert rules.read_result_text(data) == json.dumps(data, ensure_ascii=False)


def test_Java_READ는_브라우저_쿠키를_실어_공개_API_data를_읽어야_한다():
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={"status": "success", "data": [{"schdlSn": 1}]})

    backend = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    settings = Settings(_env_file=None, backend_base_url="http://backend.test")
    reader = JavaToolReader(backend, settings, "access_token=member-1")

    data = asyncio.run(reader.read("/api/pets/1/care-schedules", {"size": 10}))

    assert str(requests[0].url) == "http://backend.test/api/pets/1/care-schedules?size=10"
    assert requests[0].headers["cookie"] == "access_token=member-1"
    assert requests[0].headers["x-requested-with"] == "XMLHttpRequest"
    assert data == [{"schdlSn": 1}]


# 한 턴 READ 2번 : 목록 결과의 번호로 상세


def test_결과를_보고_읽기_도구를_한_번_더_고르면_앞_결과의_번호로_상세를_불러야_한다(client, java):
    agent = use_agent(
        client,
        FakeToolAgent(
            "list_checkups", {}, follow_tool="get_checkup", follow_raw={"ckup_rcd_sn": 7}
        ),
    )
    reader = use_reader(client, FakeToolReader([{"ckupRcdSn": 7, "hsptlNm": "메이"}]))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "마지막 검진 자세히 알려 줘"))

    assert reader.calls == [("/api/pets/1/checkups", {}), ("/api/pets/1/checkups/7", {})]
    assert len(agent.results) == 2
    assert payload(agent.results[1]) == [{"ckupRcdSn": 7, "hsptlNm": "메이"}]
    # 검진 기록은 날짜·병원만 읽어 주는 답이라 고지 없음(2026-11-11, 도구 notice)
    assert deltas(evs) == ANSWER


def test_앞_결과에_없는_번호면_Java를_부르지_않고_불러오지_못함이어야_한다(client, java):
    agent = use_agent(
        client,
        FakeToolAgent(
            "list_checkups", {}, follow_tool="get_checkup", follow_raw={"ckup_rcd_sn": 99}
        ),
    )
    reader = use_reader(client, FakeToolReader([{"ckupRcdSn": 7}]))
    room = room_of(client, java, pet_sn=CHOCO)

    events(send(client, room, "마지막 검진 자세히 알려 줘"))

    assert reader.calls == [("/api/pets/1/checkups", {})]
    assert agent.results[1] == rules.READ_FAILED


def test_첫_도구가_앞_결과_없이_번호를_넣으면_Java를_부르지_않아야_한다(client, java):
    agent = use_agent(client, FakeToolAgent("get_checkup", {"ckup_rcd_sn": 7}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java, pet_sn=CHOCO)

    events(send(client, room, "7번 검진 알려 줘"))

    assert reader.calls == []
    assert agent.results == [rules.READ_FAILED]


def test_선택_번호_칸도_앞_결과에_없으면_조건에서_빼야_한다(client, java):
    use_agent(client, FakeToolAgent("list_prescriptions", {"ckup_rcd_sn": 3}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java, pet_sn=CHOCO)

    events(send(client, room, "약 뭐 먹어?"))

    assert reader.calls == [("/api/pets/1/prescriptions", {})]


def test_결과를_보고_읽기_도구가_아닌_도구를_고르면_실행하지_않아야_한다(client, java):
    agent = use_agent(
        client,
        FakeToolAgent("list_checkups", {}, follow_tool="navigate", follow_raw={"screen_num": 1}),
    )
    reader = use_reader(client, FakeToolReader([{"ckupRcdSn": 7}]))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "검진 기록 알려 줘"))

    assert len(reader.calls) == 1
    assert agent.results[1] is None
    # 검진 기록은 고지 READ가 아님(2026-11-11, 도구 notice)
    assert deltas(evs) == ANSWER


# 가계부 READ


def test_가계부는_문장에_이름이_없으면_대화_펫_태그와_관계없이_전체를_불러야_한다(client, java):
    use_agent(client, FakeToolAgent("get_expense_total", {"start_ymd": "2026-11-01"}))
    reader = use_reader(client, FakeToolReader({"expndCnt": 2, "totalExpndAmt": 50000}))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "이번 달 가계부 얼마 썼어?"))

    assert reader.calls == [("/api/expenses/totals", {"startYmd": "2026-11-01"})]
    assert deltas(evs) == ANSWER


def test_가계부는_문장_속_이름이_하나면_petSn_조건을_붙여야_한다(client, java):
    use_agent(client, FakeToolAgent("list_expenses", {}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java)

    events(send(client, room, "뭉치 지난달 지출 알려 줘"))

    assert reader.calls == [("/api/expenses", {"petSn": 2})]


def test_가계부는_이름이_둘이면_전체를_불러야_한다(client, java):
    use_agent(client, FakeToolAgent("list_expenses", {}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java)

    events(send(client, room, "초코랑 뭉치 지출 알려 줘"))

    assert reader.calls == [("/api/expenses", {})]


def test_반려동물_칸이_없는_가계부_도구는_반려동물_목록을_받지_않아야_한다(client, java):
    java.context_status = 0
    use_agent(client, FakeToolAgent("list_expense_months", {}))
    reader = use_reader(client, FakeToolReader([{"yearMonth": "2026-11"}]))
    room = room_of(client, java)

    evs = events(send(client, room, "가계부 언제부터 썼어?"))

    assert reader.calls == [("/api/expenses/months", {})]
    assert deltas(evs) == ANSWER


# 의료 고지 범위 (FN-AIM-002-03 : 건강 관련 응답만)


def test_가계부_READ_답변은_고지_없이_저장해야_한다(client, java):
    use_agent(client, FakeToolAgent("list_expenses", {}))
    use_reader(client, FakeToolReader([{"expndSn": 1}]))
    room = room_of(client, java)

    evs = events(send(client, room, "지난달 지출 알려 줘"))

    assert deltas(evs) == ANSWER
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [ANSWER]


def test_건강_READ_실패만이면_고지_없이_저장해야_한다(client, java):
    # 고지 READ(도구 notice)로 : 검진 기록(list_checkups)은 2026-11-11부터 고지 READ가 아님
    use_agent(client, FakeToolAgent("list_inspection_values", {}))
    use_reader(client, FakeToolReader(fail=True))
    room = room_of(client, java, pet_sn=CHOCO)

    events(send(client, room, "피검사 결과 알려 줘"))

    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [ANSWER]


def test_건강_READ_다음_가계부_READ면_고지가_붙어야_한다(client, java):
    # 고지 READ(도구 notice)로 : 검진 기록(list_checkups)은 2026-11-11부터 고지 READ가 아님
    use_agent(client, FakeToolAgent("list_inspection_values", {}, follow_tool="list_expenses"))
    reader = use_reader(client, FakeToolReader([{"inspArtclCd": "ALT"}]))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "피검사 결과하고 병원비 알려 줘"))

    assert len(reader.calls) == 2
    assert deltas(evs) == ANSWER + DISCLAIMER
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [ANSWER + DISCLAIMER]


def test_가계부_READ_다음_건강_READ면_고지가_붙어야_한다(client, java):
    # 고지 READ(도구 notice)로 : 검진 기록(list_checkups)은 2026-11-11부터 고지 READ가 아님
    use_agent(client, FakeToolAgent("list_expenses", {}, follow_tool="list_inspection_values"))
    reader = use_reader(client, FakeToolReader([{"expndSn": 1}]))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "병원비랑 피검사 결과 알려 줘"))

    assert len(reader.calls) == 2
    assert deltas(evs) == ANSWER + DISCLAIMER


# 고지 READ는 도구 notice로 정함(2026-11-11) : 기록만 읽어 주는 건강 READ는 고지 없음


@pytest.mark.parametrize(
    ("tool", "question"),
    [
        ("list_my_care_schedules", "다음 주 일정 뭐 있어?"),
        ("list_care_items", "케어 항목 뭐 있어?"),
        ("list_daily_health_records", "어제 산책 기록 있어?"),
        ("list_checkups", "마지막 검진 언제야?"),
    ],
)
def test_기록만_읽어_주는_건강_READ_답변은_고지_없이_저장해야_한다(client, java, tool, question):
    use_agent(client, FakeToolAgent(tool, {}))
    reader = use_reader(client, FakeToolReader([{"sn": 1}]))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, question))

    assert len(reader.calls) == 1
    assert deltas(evs) == ANSWER
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [ANSWER]


def test_검사_수치_READ_답변은_고지를_붙여_저장해야_한다(client, java):
    use_agent(client, FakeToolAgent("list_inspection_values", {}))
    use_reader(client, FakeToolReader([{"inspArtclCd": "ALT"}]))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "초코 피검사 결과 어때?"))

    assert deltas(evs) == ANSWER + DISCLAIMER
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [ANSWER + DISCLAIMER]


def test_일정_READ_다음_검사_READ면_고지가_붙어야_한다(client, java):
    use_agent(
        client,
        FakeToolAgent("list_my_care_schedules", {}, follow_tool="list_inspection_values"),
    )
    reader = use_reader(client, FakeToolReader([{"schdlSn": 1}]))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "병원 일정하고 피검사 결과 알려 줘"))

    assert len(reader.calls) == 2
    assert deltas(evs) == ANSWER + DISCLAIMER


def test_반려동물_되물음은_고지_없이_저장해야_한다(client, java):
    use_agent(client, FakeToolAgent("get_health_indicators", {}))
    use_reader(client, FakeToolReader())
    names = many_pets(java, READ_MAX_PETS + 1)
    room = room_of(client, java)

    events(send(client, room, "체중 어때?"))

    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [READ_PET_ASK.format(names=names)]


def test_연월은_YYYY_MM만_보내야_한다(client, java):
    use_agent(client, FakeToolAgent("get_expense_statistics", {"year_month": "2026-11"}))
    reader = use_reader(client, FakeToolReader({"totalExpndAmt": 1}))
    room = room_of(client, java)

    events(send(client, room, "이번 달 한도 넘었어?"))

    assert reader.calls == [("/api/expenses/statistics", {"yearMonth": "2026-11"})]


def test_연월_형식이_틀리면_필수_칸이_비어_Java를_부르지_않아야_한다(client, java):
    agent = use_agent(client, FakeToolAgent("get_expense_statistics", {"year_month": "11월"}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java)

    events(send(client, room, "이번 달 한도 넘었어?"))

    assert reader.calls == []
    assert agent.results == [rules.READ_FAILED]


def test_지출_상세는_결과에_남겨야_한다(client, java):
    data = [{"expndSn": 1, "dtlMttr": "사료 2kg", "expndAmt": 30000, "recptSn": None}]
    agent = use_agent(client, FakeToolAgent("list_expenses", {}))
    use_reader(client, FakeToolReader(data))
    room = room_of(client, java)

    events(send(client, room, "사료 언제 샀어?"))

    assert json.loads(agent.results[0] or "") == data


def test_영수증은_지출_목록의_번호로_부르고_이름이_있어도_petSn을_붙이지_않아야_한다(client, java):
    agent = use_agent(
        client,
        FakeToolAgent("list_expenses", {}, follow_tool="get_receipt", follow_raw={"recpt_sn": 5}),
    )
    reader = use_reader(client, FakeToolReader([{"expndSn": 1, "petSn": 2, "recptSn": 5}]))
    room = room_of(client, java)

    events(send(client, room, "뭉치 병원비 영수증 내용 알려 줘"))

    assert reader.calls == [("/api/expenses", {"petSn": 2}), ("/api/receipts/5", {})]
    assert len(agent.results) == 2


# Anthropic 요청 : 결과 답변의 두 번째 도구


def _read_decision() -> ToolDecision:
    use = {"type": "tool_use", "id": "toolu_1", "name": "list_checkups", "input": {}}
    return ToolDecision(call=tools.parse("list_checkups", {}, "toolu_1"), content=(use,))


def test_follow가_있으면_결과_답변에서_고른_읽기_도구_결과를_붙여_다시_답해야_한다():
    bodies = [tool_sse("get_checkup", {"ckup_rcd_sn": 7}), sse(["7번 검진은 ", "메이병원이에요."])]
    fake = FakeAnthropic(lambda _: sse_response(bodies[len(fake.requests) - 1]))
    calls: list[tools.ToolCall] = []

    async def follow(call: tools.ToolCall) -> str | None:
        calls.append(call)
        return "상세 결과"

    async def run():
        agent = AnthropicToolAgent(fake.client(), MODEL)
        stream = agent.answer(CONTEXT, _read_decision(), "목록 결과", 4500, TODAY, follow)
        return [t async for t in stream]

    assert asyncio.run(run()) == ["7번 검진은 ", "메이병원이에요."]
    assert [c.name for c in calls] == ["get_checkup"]
    first, second = fake.requests
    assert first["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert second["tool_choice"] == {"type": "none"}
    assert second["messages"][3]["content"][0]["type"] == "tool_use"
    assert second["messages"][4]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "toolu_1",
        "content": "상세 결과",
    }


def test_follow가_있어도_첫_블록이_글이면_한_번만_불러야_한다():
    fake = FakeAnthropic(lambda _: sse_response(sse(["목록대로요."])))

    async def follow(call: tools.ToolCall) -> str | None:
        raise AssertionError("follow called")

    async def run():
        agent = AnthropicToolAgent(fake.client(), MODEL)
        stream = agent.answer(CONTEXT, _read_decision(), "목록 결과", 4500, TODAY, follow)
        return [t async for t in stream]

    assert asyncio.run(run()) == ["목록대로요."]
    assert len(fake.requests) == 1


def test_두_번째가_읽기_도구가_아니면_실행하지_않음을_도구_결과로_붙여야_한다():
    bodies = [tool_sse("decline", {}), sse(["받은 결과로요."])]
    fake = FakeAnthropic(lambda _: sse_response(bodies[len(fake.requests) - 1]))

    async def follow(call: tools.ToolCall) -> str | None:
        return None

    async def run():
        agent = AnthropicToolAgent(fake.client(), MODEL)
        stream = agent.answer(CONTEXT, _read_decision(), "목록 결과", 4500, TODAY, follow)
        return [t async for t in stream]

    assert asyncio.run(run()) == ["받은 결과로요."]
    assert fake.requests[1]["messages"][4]["content"][0]["content"] == rules.READ_NOT_RUN


# 재현(방 143, 2026-11-06) : 답 없는 질문 두 개가 이력에 있으면 LLM이 tool_use를 2개 낸다
# 첫 블록만 실행하고 tool_result를 1개만 보내면 Anthropic 400
# "tool_use ids were found without tool_result blocks immediately after"


def multi_tool_sse(calls: list[tuple[str, dict]]) -> bytes:
    """Anthropic 스트리밍 tool_use 여러 개 응답 흉내"""
    start = {
        "type": "message_start",
        "message": {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": MODEL,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 1},
        },
    }
    evs: list[tuple[str, dict]] = [("message_start", start)]
    for index, (name, raw) in enumerate(calls):
        block = {"type": "tool_use", "id": f"toolu_{index + 1}", "name": name, "input": {}}
        delta = {"type": "input_json_delta", "partial_json": json.dumps(raw, ensure_ascii=False)}
        evs += [
            (
                "content_block_start",
                {"type": "content_block_start", "index": index, "content_block": block},
            ),
            (
                "content_block_delta",
                {"type": "content_block_delta", "index": index, "delta": delta},
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": index}),
        ]
    evs += [
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                "usage": {"output_tokens": 5},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    body = "".join(f"event: {n}\ndata: {json.dumps(d, ensure_ascii=False)}\n\n" for n, d in evs)
    return body.encode()


def _unanswered_tool_uses(body: dict) -> set[str]:
    # assistant 메시지마다 바로 다음 user 메시지에 tool_result가 없는 tool_use id
    missing: set[str] = set()
    messages = body["messages"]
    for index, message in enumerate(messages):
        if message["role"] != "assistant" or not isinstance(message["content"], list):
            continue
        uses = {b["id"] for b in message["content"] if b.get("type") == "tool_use"}
        after = messages[index + 1]["content"] if index + 1 < len(messages) else []
        results = {b["tool_use_id"] for b in after if b.get("type") == "tool_result"}
        missing |= uses - results
    return missing


def test_도구_고르기가_tool_use를_여럿_내면_결과_답변_요청에_모두의_tool_result가_있어야_한다():
    calls = [("get_expense_total", {"start_ymd": "2026-11-01"}), ("list_expenses", {})]
    bodies = [multi_tool_sse(calls), sse(["지난달 지출은요."])]
    fake = FakeAnthropic(lambda _: sse_response(bodies[len(fake.requests) - 1]))
    two_questions = [
        {"role": "user", "content": "이번 달 가계부 얼마 썼어?"},
        {"role": "user", "content": "탄이 지난달 지출 목록 알려 줘"},
    ]

    async def run():
        agent = AnthropicToolAgent(fake.client(), MODEL)
        decision = await agent.decide(two_questions, 4500, TODAY)
        stream = agent.answer(two_questions, decision, "결과", 4500, TODAY)
        return [t async for t in stream]

    asyncio.run(run())

    assert _unanswered_tool_uses(fake.requests[1]) == set()


def test_결과_답변에서_tool_use를_여럿_내면_마지막_요청에_모두의_tool_result가_있어야_한다():
    calls = [("get_checkup", {"ckup_rcd_sn": 7}), ("list_prescriptions", {})]
    bodies = [multi_tool_sse(calls), sse(["상세는요."])]
    fake = FakeAnthropic(lambda _: sse_response(bodies[len(fake.requests) - 1]))

    async def follow(call: tools.ToolCall) -> str | None:
        return "상세 결과"

    async def run():
        agent = AnthropicToolAgent(fake.client(), MODEL)
        stream = agent.answer(CONTEXT, _read_decision(), "목록 결과", 4500, TODAY, follow)
        return [t async for t in stream]

    asyncio.run(run())

    assert _unanswered_tool_uses(fake.requests[1]) == set()


def _definition(name: str) -> dict:
    return next(d for d in tools.tool_definitions() if d["name"] == name)


@pytest.mark.parametrize("name", ["get_health_indicators", "list_daily_health_records"])
def test_health_read_description_has_units(name: str) -> None:
    """건강 READ 도구 설명 : 지표 단위와 반올림 규칙 (2026-11-09 실측 683.024)"""
    description = _definition(name)["description"]
    for unit in ("체중 kg", "식사량 g", "음수량 ml", "산책 분"):
        assert unit in description
    assert "반올림" in description


def test_health_indicators_description_has_creatinine_unit() -> None:
    assert "unitNm" in _definition("get_health_indicators")["description"]


def test_tool_system_hides_guide_numbers() -> None:
    """도구 흐름 시스템 글 : 안내서 번호·'안내서'라는 말을 답에 쓰지 않는 규칙"""
    from app.chat.clients import tool_system

    system = tool_system()
    assert "[13-1]" in system
    assert "'안내서'라는 말을 쓰지 않는다" in system


def test_tool_system_no_apology_for_server_ask() -> None:
    """도구 흐름 시스템 글 : 서버 되물음을 자기 실수로 보고 사과하지 않는 규칙"""
    from app.chat.clients import tool_system

    system = tool_system()
    assert "어느 아이의" in system
    assert "사과·해명 없이" in system


# 반려동물·커뮤니티 READ(2026-11-11)


def test_반려동물_상세는_펫_태그_방의_아이_번호로_Java를_한_번_불러야_한다(client, java):
    use_agent(client, FakeToolAgent("get_pet", {}))
    reader = use_reader(client, FakeToolReader({"petSn": CHOCO, "petBdwg": 4.2}))
    room = room_of(client, java, pet_sn=CHOCO)

    events(send(client, room, "등록 몸무게 몇이야?"))

    assert reader.calls == [(f"/api/pets/{CHOCO}", {})]


def test_글_상세는_앞_글_목록에_없는_번호면_Java를_부르지_않아야_한다(client, java):
    agent = use_agent(
        client, FakeToolAgent("list_posts", {}, follow_tool="get_post", follow_raw={"pst_sn": 99})
    )
    reader = use_reader(client, FakeToolReader([{"pstSn": 7, "pstTtl": "산책 코스 추천"}]))
    room = room_of(client, java)

    events(send(client, room, "최근 글 내용 알려 줘"))

    assert reader.calls == [("/api/posts", {})]
    assert agent.results[1] == rules.READ_FAILED


def test_글_상세는_앞_글_목록의_번호로_불러야_한다(client, java):
    use_agent(
        client, FakeToolAgent("list_posts", {}, follow_tool="get_post", follow_raw={"pst_sn": 7})
    )
    reader = use_reader(client, FakeToolReader([{"pstSn": 7, "pstTtl": "산책 코스 추천"}]))
    room = room_of(client, java)

    events(send(client, room, "최근 글 내용 알려 줘"))

    assert reader.calls == [("/api/posts", {}), ("/api/posts/7", {})]


def test_캐릭터_상세는_앞_캐릭터_목록의_번호로_불러야_한다(client, java):
    use_agent(
        client,
        FakeToolAgent(
            "list_pixel_characters",
            {},
            follow_tool="get_pixel_character",
            follow_raw={"pixel_char_sn": 3},
        ),
    )
    reader = use_reader(client, FakeToolReader([{"pixelCharSn": 3, "petNm": "초코"}]))
    room = room_of(client, java)

    events(send(client, room, "내 캐릭터 지금 뭐 입고 있어?"))

    assert reader.calls == [("/api/pixel-characters", {}), ("/api/pixel-characters/3", {})]


# 장소 검색·즐겨찾기 전체 분류(백엔드 #227, 2026-11-11)


def test_장소_검색은_좌표_없이_분류와_낱말로_Java를_한_번_불러야_한다(client, java):
    use_agent(client, FakeToolAgent("list_places", {"plc_clsf_cd": "PLCC0002", "keyword": "전주"}))
    reader = use_reader(client, FakeToolReader([{"plcConm": "전주 멍멍살롱", "plcAddr": "전주시"}]))
    room = room_of(client, java)

    events(send(client, room, "전주 애견미용실 찾아 줘"))

    assert reader.calls == [("/api/places", {"plcClsfCd": "PLCC0002", "keyword": "전주"})]


def test_분류를_말하지_않은_즐겨찾기는_전체_분류로_Java를_불러야_한다(client, java):
    use_agent(client, FakeToolAgent("list_place_bookmarks", {}))
    reader = use_reader(client, FakeToolReader([{"plcConm": "해피동물병원", "plcAddr": "전주시"}]))
    room = room_of(client, java)

    events(send(client, room, "즐겨찾기한 장소 다 보여 줘"))

    assert reader.calls == [("/api/place-bookmarks", {})]
