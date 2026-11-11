import pytest

from app.chat import catalog, rules
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_messages import MessageJava, events, send
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import CHOCO
from tests.chat.test_tools import room_of, use_agent

# FN-AIM-002-04 : 도구 흐름 글 답변의 연관 바로가기


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


def shortcut_of(client, java, agent: FakeToolAgent, text: str, data: object = None) -> dict | None:
    use_agent(client, agent)
    use_reader(client, FakeToolReader(data))
    room = room_of(client, java, pet_sn=CHOCO)
    evs = events(send(client, room, text))
    assert evs[0][1]["kind"] == "SEARCH"
    return evs[-1][1]["shortcut"]


# READ 답변


@pytest.mark.parametrize(
    ("tool", "scr_id"),
    [
        ("list_daily_health_records", "SCR-HLT-002"),
        ("list_my_care_schedules", "SCR-HLT-003"),
        ("list_prescriptions", "SCR-HLT-011"),
        ("get_expense_total", "SCR-MYP-030"),
        ("list_expenses", "SCR-MYP-031"),
    ],
)
def test_READ_답변에는_도구의_화면이_바로가기여야_한다(client, java, tool, scr_id):
    shortcut = shortcut_of(client, java, FakeToolAgent(tool, {}), "코코 기록 알려줘")

    assert shortcut is not None
    assert shortcut["kind"] == "ROUTE"
    assert shortcut["scrId"] == scr_id


def without_daily_log(java: MessageJava) -> None:
    # 관리자가 건강 일지 행을 지운 매핑표(Java GET /internal/ai/routes)
    java.routes = [r for r in java.routes if r["scrnId"] != "SCR-HLT-002"]


def test_도구_화면이_매핑표에_없으면_질문_글_키워드로_바로가기여야_한다(client, java):
    without_daily_log(java)
    agent = FakeToolAgent("list_daily_health_records", {})

    shortcut = shortcut_of(client, java, agent, "코코 가계부랑 일지 알려줘")

    assert shortcut["scrId"] == "SCR-MYP-030"


def test_도구_화면도_키워드도_없으면_바로가기가_없어야_한다(client, java):
    without_daily_log(java)
    agent = FakeToolAgent("list_daily_health_records", {})

    assert shortcut_of(client, java, agent, "코코 요즘 어때?") is None


def test_확인_카드가_같이_나가는_READ_턴은_바로가기가_없어야_한다(client, java):
    agent = FakeToolAgent(
        "list_care_items",
        {},
        follow_tool="draft_care_completion",
        follow_raw={"care_artcl_sn": 7},
    )
    use_agent(client, agent)
    use_reader(client, FakeToolReader([{"careArtclSn": 7, "careArtclNm": "산책"}]))
    room = room_of(client, java, pet_sn=CHOCO)

    done = events(send(client, room, "오늘 산책 완료 체크해줘"))[-1][1]

    assert done["action"] is not None
    assert done["shortcut"] is None


# 바로 답


def test_바로_답은_질문_글이_키워드에_걸리면_그_행이_바로가기여야_한다(client, java):
    agent = FakeToolAgent(texts=("4~5kg이 ", "적당해요."))

    shortcut = shortcut_of(client, java, agent, "강아지 체중은 얼마가 적당해?")

    assert shortcut["scrId"] == "SCR-HLT-002"


@pytest.mark.parametrize("text", ["강아지 포도 먹어도 돼?", "고마워"])
def test_키워드가_없거나_인사면_바로_답에_바로가기가_없어야_한다(client, java, text):
    agent = FakeToolAgent(texts=("네, ", "알겠어요."))

    assert shortcut_of(client, java, agent, text) is None


# yaml 점검


def test_READ_도구의_화면은_모두_스냅샷_매핑표의_라우팅_가능_행이어야_한다():
    entries = catalog.build(catalog.read_snapshot(), "snapshot").entries
    reads = {name: e for name, e in entries.items() if e.kind == "READ"}
    prompts = catalog.tool_prompts()
    opened = {name for name in reads if name in prompts}

    assert opened
    for name in opened:
        screen = prompts[name].screen
        assert screen is not None, name
        assert rules.find_route(screen, None) is not None, name
