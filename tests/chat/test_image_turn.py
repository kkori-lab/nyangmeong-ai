"""사진 턴 저장 (FN-AIM-013-02, 2026-11-13 추가 요청)
- POST /ai/image-intent 판단 뒤 사용자 "[사진] <글>" + 용도별 안내 AI 메시지를 방에 저장
- 방 번호가 없으면 Python이 방을 만든다(메인 첫 사진, 빈 방이 남지 않게)"""

import json

import pytest

from app.chat import clients
from app.chat.schemas import ROLE_AI, ROLE_USER, ImageIntentKind
from app.chat.service import IMAGE_MESSAGES, IMAGE_TITLE
from tests.chat.conftest import AJAX, as_member
from tests.chat.fakes import FakeTitleGenerator
from tests.chat.test_image_intent import FakeImageIntentJudge, image_bytes
from tests.chat.test_messages import MessageJava

URL = "/ai/image-intent"


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


class CountingTitles(FakeTitleGenerator):
    def __init__(self) -> None:
        super().__init__()
        self.generated: list[str] = []

    async def generate(self, first_message: str) -> str:
        self.generated.append(first_message)
        return await super().generate(first_message)


@pytest.fixture
def judge(client) -> FakeImageIntentJudge:
    fake = FakeImageIntentJudge(ImageIntentKind.ASK)
    client.app.dependency_overrides[clients.get_image_intent_judge] = lambda: fake
    as_member(client, 1)
    return fake


@pytest.fixture
def titles(client) -> CountingTitles:
    fake = CountingTitles()
    client.app.dependency_overrides[clients.get_title_generator] = lambda: fake
    return fake


def post(client, data: dict, file=None):
    files = {"file": file or ("pet.png", image_bytes(), "image/png")}
    return client.post(URL, data=data, files=files, headers=AJAX)


def saved(java: MessageJava, room: int) -> list[tuple[str, str]]:
    return [(m["roleCd"], m["cnvrsCn"]) for m in java.rooms[room]["messages"]]


def test_방_번호가_있으면_사진_메시지와_안내를_그_방에_저장한다(client, java, judge, titles):
    room = java.add_room(1, "제목", pet_sn=1, cn="안녕")

    res = post(client, {"cnvrsCn": "이거 뭐야", "aiCnvrsRoomSn": str(room)})

    assert res.status_code == 200
    data = res.json()["data"]
    assert data["kind"] == "ASK"
    assert data["aiCnvrsRoomSn"] == room
    assert [(m["roleCd"], m["cnvrsCn"]) for m in data["messages"]] == [
        (ROLE_USER, "[사진] 이거 뭐야"),
        (ROLE_AI, IMAGE_MESSAGES[ImageIntentKind.ASK]),
    ]
    assert saved(java, room)[-2:] == [
        (ROLE_USER, "[사진] 이거 뭐야"),
        (ROLE_AI, IMAGE_MESSAGES[ImageIntentKind.ASK]),
    ]
    assert titles.generated == []


def test_방_번호가_없으면_방을_만들고_번호를_준다(client, java, judge, titles):
    res = post(client, {"cnvrsCn": "이거 뭐야", "petSn": "3"})

    data = res.json()["data"]
    room = data["aiCnvrsRoomSn"]
    assert java.rooms[room]["petSn"] == 3
    assert java.rooms[room]["cnvrsTtl"] == "이거 뭐야"
    assert saved(java, room) == [
        (ROLE_USER, "[사진] 이거 뭐야"),
        (ROLE_AI, IMAGE_MESSAGES[ImageIntentKind.ASK]),
    ]
    assert [m["cnvrsCn"] for m in data["messages"]] == [
        "[사진] 이거 뭐야",
        IMAGE_MESSAGES[ImageIntentKind.ASK],
    ]
    assert titles.generated == ["이거 뭐야"]


def test_글이_없으면_자리_표시만_저장하고_제목_LLM을_부르지_않는다(client, java, judge, titles):
    res = post(client, {})

    room = res.json()["data"]["aiCnvrsRoomSn"]
    assert java.rooms[room]["cnvrsTtl"] == IMAGE_TITLE
    assert saved(java, room)[0] == (ROLE_USER, "[사진]")
    assert titles.generated == []


def test_동물병원_영수증은_사용자_메시지만_저장한다(client, java, judge, titles):
    judge.kind = ImageIntentKind.MEDICAL_RECEIPT
    room = java.add_room(1, "제목", cn="안녕")

    data = post(client, {"cnvrsCn": "영수증", "aiCnvrsRoomSn": str(room)}).json()["data"]

    assert [m["roleCd"] for m in data["messages"]] == [ROLE_USER]
    assert saved(java, room)[-1] == (ROLE_USER, "[사진] 영수증")


@pytest.mark.parametrize("kind", [ImageIntentKind.CHARACTER, ImageIntentKind.EXPENSE_RECEIPT])
def test_용도별_고정_안내를_저장한다(client, java, judge, titles, kind):
    judge.kind = kind
    room = java.add_room(1, "제목", cn="안녕")

    post(client, {"aiCnvrsRoomSn": str(room)})

    assert saved(java, room)[-1] == (ROLE_AI, IMAGE_MESSAGES[kind])


def test_판단_실패로_ASK여도_저장한다(client, java, judge, titles):
    judge.fail = True
    room = java.add_room(1, "제목", cn="안녕")

    data = post(client, {"aiCnvrsRoomSn": str(room)}).json()["data"]

    assert data["kind"] == "ASK"
    assert saved(java, room)[-1] == (ROLE_AI, IMAGE_MESSAGES[ImageIntentKind.ASK])


def test_형식_오류면_저장하지_않는다(client, java, judge, titles):
    res = post(client, {}, ("doc.pdf", b"%PDF-1.4", "application/pdf"))

    assert res.status_code == 400
    assert java.rooms == {}
    assert judge.calls == []


def test_남의_방이면_Java_404를_그대로_준다(client, java, judge, titles):
    other = java.add_room(2, "남의 방", cn="안녕")

    res = post(client, {"aiCnvrsRoomSn": str(other)})

    assert res.status_code == 404
    assert len(java.rooms[other]["messages"]) == 1


def test_저장한_사진_턴은_다음_턴_맥락에_들어간다(client, java, judge, titles):
    from tests.chat.fakes import FakeToolAgent
    from tests.chat.test_messages import events
    from tests.chat.test_tools import use_agent

    agent = FakeToolAgent(texts=("방금 사진을 보내셨어요.",))
    use_agent(client, agent)
    room = post(client, {"cnvrsCn": "이거 뭐야"}).json()["data"]["aiCnvrsRoomSn"]

    res = client.post(
        f"/ai/conversations/{room}/messages",
        json={"cnvrsCn": "방금 뭐 보냈지?"},
        headers=AJAX,
    )
    events(res)

    context = agent.decides[0][0]
    assert {"role": "user", "content": "[사진] 이거 뭐야"} in context
    assert json.dumps(context, ensure_ascii=False).count("[사진]") == 1
