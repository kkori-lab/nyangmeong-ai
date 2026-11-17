import pytest

from app.chat import rules
from app.chat.clients import READ_LIMIT, ReadMore
from app.chat.service import ACTION_SHOWN, DISCLAIMER, ROUTE_SHOWN
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_messages import MessageJava, deltas, events, send
from tests.chat.test_read_tools import ANSWER, FakeToolReader, payload, use_reader
from tests.chat.test_register import CHOCO
from tests.chat.test_tools import room_of, row_of, use_agent

# 한 메시지 여러 일 ① (2026-11-13) : 한 턴 READ 최대 3번, 결과 뒤 이동·사용법은 바로가기

CHECKUPS = "/api/pets/1/checkups"


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


def _send(client, java: MessageJava, agent: FakeToolAgent, text: str, reader: FakeToolReader):
    use_agent(client, agent)
    use_reader(client, reader)
    room = room_of(client, java, pet_sn=CHOCO)
    return room, events(send(client, room, text))


# READ 상한


def test_한_턴_READ_상한은_3번이어야_한다():
    assert READ_LIMIT == 3


def test_결과를_보고_읽기_도구를_두_번_더_고르면_READ_3번_결과로_답해야_한다(client, java):
    agent = FakeToolAgent(
        "list_checkups",
        {},
        follows=(("get_checkup", {"ckup_rcd_sn": 7}), ("list_expenses", {})),
    )
    reader = FakeToolReader(
        [{"expndSn": 1}],
        by_path={
            CHECKUPS: [{"ckupRcdSn": 7}],
            f"{CHECKUPS}/7": {"ckupRcdSn": 7, "hsptlNm": "메이"},
        },
    )

    _, evs = _send(client, java, agent, "코코 마지막 검진 상세랑 병원비 알려 줘", reader)

    assert len(reader.calls) == 3
    assert reader.calls[:2] == [(CHECKUPS, {}), (f"{CHECKUPS}/7", {})]
    assert all(isinstance(result, ReadMore) for result in agent.results[1:])
    assert payload(agent.results[1]) == {"ckupRcdSn": 7, "hsptlNm": "메이"}
    # 가계부 결과는 반려동물 머리줄 없이 JSON
    assert '"expndSn": 1' in agent.results[2]
    assert evs[0][1]["kind"] == "SEARCH"


def test_READ_3번_뒤의_네_번째_읽기_도구는_실행하지_않아야_한다(client, java):
    agent = FakeToolAgent(
        "list_checkups",
        {},
        follows=(
            ("get_checkup", {"ckup_rcd_sn": 7}),
            ("list_expenses", {}),
            ("list_inspection_values", {}),
        ),
    )
    reader = FakeToolReader([{"ckupRcdSn": 7}])

    _, evs = _send(client, java, agent, "검진이랑 병원비랑 피검사 다 알려 줘", reader)

    assert len(reader.calls) == 3
    assert agent.results[3] is None
    assert evs[-1][0] == "done"


def test_READ_3번_뒤에도_쓰기_카드는_한_번_고를_수_있어야_한다(client, java):
    agent = FakeToolAgent(
        "list_care_items",
        {},
        follows=(
            ("list_expenses", {}),
            ("list_checkups", {}),
            ("draft_care_completion", {"care_artcl_sn": 7}),
        ),
    )
    reader = FakeToolReader([{"careArtclSn": 7, "careArtclNm": "산책"}])

    _, evs = _send(client, java, agent, "산책 완료 체크하고 병원비랑 검진도 알려 줘", reader)

    assert len(reader.calls) == 3
    assert agent.results[3].startswith(ACTION_SHOWN.split("{summary}")[0])
    action = evs[-1][1]["action"]
    assert action["tool"] == "draft_care_completion"
    assert action["input"] == {"petSn": CHOCO, "careArtclSn": 7}


# 결과 뒤 navigate : 화면을 옮기지 않고 바로가기


def test_READ_뒤_이동_도구는_이동하지_않고_그_화면을_바로가기로_보여야_한다(client, java):
    row = row_of("SCR-MYP-030")
    agent = FakeToolAgent(
        "list_checkups", {}, follow_tool="navigate", follow_raw={"screen_num": row.no}
    )
    reader = FakeToolReader([{"ckupRcdSn": 7}])

    room, evs = _send(client, java, agent, "검진 기록 알려 주고 가계부 열어 줘", reader)

    assert len(reader.calls) == 1
    assert evs[0][1]["kind"] == "SEARCH"
    assert agent.results[1] == ROUTE_SHOWN.format(name=row.name)
    assert isinstance(agent.results[1], ReadMore)
    # 첫 READ(검진) 화면보다 결과 뒤 고른 이동 화면이 우선
    assert evs[-1][1]["shortcut"]["scrId"] == "SCR-MYP-030"
    assert deltas(evs) == ANSWER
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [ANSWER]


def test_결과_뒤_이동_다음에도_읽기_도구를_이어서_고를_수_있어야_한다(client, java):
    row = row_of("SCR-MYP-030")
    agent = FakeToolAgent(
        "list_checkups",
        {},
        follows=(("navigate", {"screen_num": row.no}), ("list_expenses", {})),
    )
    reader = FakeToolReader([{"expndSn": 1}])

    _, evs = _send(client, java, agent, "가계부 열고 검진이랑 병원비 알려 줘", reader)

    # 이동은 READ 횟수에 세지 않음
    assert len(reader.calls) == 2
    assert evs[-1][1]["shortcut"]["scrId"] == "SCR-MYP-030"


def test_결과_뒤_이동_화면이_매핑표에_없으면_실행하지_않아야_한다(client, java):
    agent = FakeToolAgent(
        "list_checkups", {}, follow_tool="navigate", follow_raw={"screen_num": 999}
    )
    reader = FakeToolReader([{"ckupRcdSn": 7}])

    _, evs = _send(client, java, agent, "검진 기록 알려 줘", reader)

    assert agent.results[1] is None
    assert evs[0][1]["kind"] == "SEARCH"


# 결과 뒤 search_guide : 안내서 글을 결과로, 안내서 화면 바로가기


def test_READ_뒤_사용법_도구는_안내서_글을_결과로_주고_안내서_화면을_바로가기로(client, java):
    agent = FakeToolAgent(
        "list_checkups", {}, follow_tool="search_guide", follow_raw={"chunk_id": "6-1"}
    )
    reader = FakeToolReader([{"ckupRcdSn": 7}])

    _, evs = _send(client, java, agent, "검진 기록 알려 주고 캐릭터는 어디서 만들어?", reader)

    assert len(reader.calls) == 1
    assert rules.find_guide("6-1").text in agent.results[1]
    assert isinstance(agent.results[1], ReadMore)
    assert evs[-1][1]["shortcut"]["scrId"] == "SCR-MYP-010"
    # 검진 기록은 고지 READ가 아니고 안내서는 고지 없음
    assert deltas(evs) == ANSWER


def test_결과_뒤_이동과_사용법을_다_고르면_이동_화면이_바로가기여야_한다(client, java):
    row = row_of("SCR-MYP-030")
    agent = FakeToolAgent(
        "list_checkups",
        {},
        follows=(("search_guide", {"chunk_id": "6-1"}), ("navigate", {"screen_num": row.no})),
    )
    reader = FakeToolReader([{"ckupRcdSn": 7}])

    _, evs = _send(
        client, java, agent, "검진 알려 주고 캐릭터 어디서 만들어? 가계부도 열어", reader
    )

    assert len(reader.calls) == 1
    assert evs[-1][1]["shortcut"]["scrId"] == "SCR-MYP-030"


def test_결과_뒤_이동을_골라도_확인_카드가_나가는_턴은_바로가기가_없어야_한다(client, java):
    row = row_of("SCR-MYP-030")
    agent = FakeToolAgent(
        "list_care_items",
        {},
        follows=(
            ("navigate", {"screen_num": row.no}),
            ("draft_care_completion", {"care_artcl_sn": 7}),
        ),
    )
    reader = FakeToolReader([{"careArtclSn": 7, "careArtclNm": "산책"}])

    _, evs = _send(client, java, agent, "산책 완료 체크하고 가계부 열어 줘", reader)

    done = evs[-1][1]
    assert done["action"]["tool"] == "draft_care_completion"
    assert done["shortcut"] is None


# 사용법을 먼저 고른 섞인 메시지 : 사용법 답변에도 결과 뒤 도구(추가-5)


def test_사용법을_먼저_골라도_결과_뒤_읽기_도구로_함께_물은_기록을_읽어야_한다(client, java):
    agent = FakeToolAgent(
        "search_guide", {"chunk_id": "6-1"}, follow_tool="list_checkups", follow_raw={}
    )
    reader = FakeToolReader([{"ckupRcdSn": 7, "hsptlNm": "메이"}])

    room, evs = _send(client, java, agent, "캐릭터는 어디서 만들어? 코코 검진 기록도", reader)

    assert evs[0][1]["kind"] == "SEARCH"
    assert rules.find_guide("6-1").text in agent.results[0]
    assert reader.calls == [(CHECKUPS, {})]
    assert isinstance(agent.results[1], ReadMore)
    assert payload(agent.results[1]) == [{"ckupRcdSn": 7, "hsptlNm": "메이"}]
    # 결과 뒤 이동을 고르지 않았으면 안내서 화면 바로가기
    assert evs[-1][1]["shortcut"]["scrId"] == "SCR-MYP-010"
    # 검진 기록은 고지 READ가 아니고 사용법 안내도 고지 없음
    assert deltas(evs) == ANSWER
    assert [m["cnvrsCn"] for m in java.ai_messages(room)] == [ANSWER]


def test_사용법_뒤_고지_READ를_읽으면_고지가_붙어야_한다(client, java):
    agent = FakeToolAgent(
        "search_guide", {"chunk_id": "6-1"}, follow_tool="list_inspection_values", follow_raw={}
    )
    reader = FakeToolReader([{"inspArtclCd": "ALT"}])

    _, evs = _send(client, java, agent, "캐릭터는 어디서 만들어? 피검사 결과도", reader)

    assert len(reader.calls) == 1
    assert deltas(evs) == ANSWER + DISCLAIMER


def test_사용법_뒤에도_READ는_3번까지만_실행해야_한다(client, java):
    agent = FakeToolAgent(
        "search_guide",
        {"chunk_id": "6-1"},
        follows=(("list_checkups", {}), ("list_expenses", {}), ("list_care_items", {})),
    )
    reader = FakeToolReader([{"ckupRcdSn": 7}])

    _, evs = _send(client, java, agent, "캐릭터 어디서 만들어? 검진·지출·케어도", reader)

    # 첫 고르기가 사용법이라 READ 3번 모두 결과 뒤 도구
    assert len(reader.calls) == 3
    assert evs[-1][0] == "done"


def test_사용법_뒤_이동을_고르면_이동_화면이_바로가기여야_한다(client, java):
    row = row_of("SCR-MYP-030")
    agent = FakeToolAgent(
        "search_guide",
        {"chunk_id": "6-1"},
        follow_tool="navigate",
        follow_raw={"screen_num": row.no},
    )
    reader = FakeToolReader([])

    _, evs = _send(client, java, agent, "캐릭터 어디서 만들어? 가계부도 열어 줘", reader)

    assert reader.calls == []
    assert evs[0][1]["kind"] == "SEARCH"
    assert evs[-1][1]["shortcut"]["scrId"] == "SCR-MYP-030"


def test_사용법_뒤_쓰기_도구를_고르면_확인_카드를_줘야_한다(client, java):
    agent = FakeToolAgent(
        "search_guide",
        {"chunk_id": "6-1"},
        follows=(
            ("list_care_items", {}),
            ("draft_care_completion", {"care_artcl_sn": 7}),
        ),
    )
    reader = FakeToolReader([{"careArtclSn": 7, "careArtclNm": "산책"}])

    _, evs = _send(client, java, agent, "캐릭터 어디서 만들어? 산책 완료도 체크해 줘", reader)

    done = evs[-1][1]
    assert done["action"]["tool"] == "draft_care_completion"
    assert done["action"]["input"] == {"petSn": CHOCO, "careArtclSn": 7}
    assert done["shortcut"] is None
