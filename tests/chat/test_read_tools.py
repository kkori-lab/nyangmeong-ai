import asyncio
import json

import httpx2
import pytest

from app.chat import repository, rules
from app.chat.repository import JavaToolReader
from app.chat.service import DISCLAIMER, READ_NO_PET, READ_PET_ASK
from app.core.backend import external_error
from app.core.config import Settings
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_messages import MessageJava, deltas, events, send
from tests.chat.test_register import CHOCO
from tests.chat.test_tools import room_of, use_agent

ANSWER = "안내서대로 답할게요."


class FakeToolReader:
    """[가짜 READ 실행]
    - data : 돌려줄 Java data, fail : 502
    - 받은 경로·query(calls) 기록"""

    def __init__(self, data: object = None, fail: bool = False) -> None:
        self.data = [] if data is None else data
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []

    async def read(self, path: str, params: dict) -> object:
        self.calls.append((path, params))
        if self.fail:
            raise external_error()
        return self.data


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


def use_reader(client, reader: FakeToolReader) -> FakeToolReader:
    client.app.dependency_overrides[repository.get_tool_reader] = lambda: reader
    return reader


# 실행 흐름


def test_READ_도구를_고르면_경로와_query로_Java를_부르고_결과로_SEARCH_답변해야_한다(client, java):
    raw = {"from_ymd": "2026-10-01", "to_ymd": "10월 말", "schdl_knd_cd": "HLTC0057", "size": 10}
    agent = use_agent(client, FakeToolAgent("list_care_schedules", raw))
    reader = use_reader(client, FakeToolReader([{"schdlNm": "병원"}]))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "이번 달 병원 일정 있어?"))

    assert evs[0][1]["kind"] == "SEARCH"
    assert reader.calls == [
        (
            "/api/pets/1/care-schedules",
            {"fromYmd": "2026-10-01", "schdlKndCd": "HLTC0057", "size": 10},
        )
    ]
    assert json.loads(agent.results[0]) == [{"schdlNm": "병원"}]
    assert deltas(evs) == ANSWER + DISCLAIMER
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [ANSWER + DISCLAIMER]


def test_참거짓_조건은_소문자_글자로_보내야_한다(client, java):
    use_agent(client, FakeToolAgent("list_care_items", {"main_expsr_yn": True}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java, pet_sn=CHOCO)

    events(send(client, room, "메인에 보이는 케어 뭐 있어?"))

    assert reader.calls == [("/api/pets/1/care-items", {"mainExpsrYn": "true"})]


def test_도구_결과에서_메모_같은_내용_칸은_중첩까지_지워야_한다(client, java):
    data = [
        {
            "schdlNm": "정기검진",
            "memoCn": "비밀 메모",
            "lastCycle": {"ckupMemoCn": "자유 입력", "obsrvSz": 1.5, "cyclCnt": 2},
        }
    ]
    agent = use_agent(client, FakeToolAgent("list_care_schedules", {}))
    use_reader(client, FakeToolReader(data))
    room = room_of(client, java, pet_sn=CHOCO)

    events(send(client, room, "다음 병원 언제야?"))

    assert json.loads(agent.results[0]) == [
        {"schdlNm": "정기검진", "lastCycle": {"obsrvSz": 1.5, "cyclCnt": 2}}
    ]


def test_Java_READ가_실패하면_불러오지_못함을_도구_결과로_넘겨야_한다(client, java):
    agent = use_agent(client, FakeToolAgent("get_health_indicators", {}))
    use_reader(client, FakeToolReader(fail=True))
    room = room_of(client, java, pet_sn=CHOCO)

    evs = events(send(client, room, "체중 어때?"))

    assert evs[0][1]["kind"] == "SEARCH"
    assert agent.results == [rules.READ_FAILED]
    assert deltas(evs) == ANSWER + DISCLAIMER


# 반려동물 결정


def test_문장_속_이름으로_반려동물을_정해야_한다(client, java):
    use_agent(client, FakeToolAgent("get_health_indicators", {}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java)

    events(send(client, room, "뭉치 요즘 체중 어때?"))

    assert reader.calls == [("/api/pets/2/health-indicators", {})]


def test_반려동물을_못_정하면_Java_READ를_부르지_않고_이름을_되물어야_한다(client, java):
    agent = use_agent(client, FakeToolAgent("get_health_indicators", {}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java)

    evs = events(send(client, room, "요즘 체중 어때?"))

    assert evs[0][1]["kind"] == "SEARCH"
    assert reader.calls == []
    assert agent.results == []
    assert deltas(evs) == READ_PET_ASK.format(names="초코, 뭉치") + DISCLAIMER


def test_반려동물이_없으면_등록을_안내해야_한다(client, java):
    java.pets = []
    use_agent(client, FakeToolAgent("get_health_indicators", {}))
    reader = use_reader(client, FakeToolReader())
    room = room_of(client, java)

    evs = events(send(client, room, "요즘 체중 어때?"))

    assert reader.calls == []
    assert deltas(evs) == READ_NO_PET + DISCLAIMER


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
