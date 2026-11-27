"""사진 턴 닫힌 선택지 열기 (SCR-AIM-013, 2026-11-27 추가 요청)
- image-intent AGENT : 사용자 "[사진] <글>"만 저장, React가 /messages를 cnvrsCn 없이 불러 에이전트로
- 안내 글은 판단 LLM 글(reply), 빈 글·200자 초과·판단 실패면 고정 글
- 도구 고르기 규칙에 "[사진]" 뜻, 정규식 규칙에는 표시를 뗀 글"""

import asyncio
from datetime import datetime

import pytest

from app.chat import clients, service, tools
from app.chat.clients import IMAGE_INTENT_SYSTEM, ImageIntentOutput, judgement_of, tool_system
from app.chat.schemas import (
    ROLE_AI,
    ROLE_USER,
    ConversationDetail,
    ConversationMessage,
    ImageIntentJudgement,
    ImageIntentKind,
)
from app.chat.service import IMAGE_MESSAGES, IMAGE_REPLY_MAX, image_reply, question_text
from tests.chat.conftest import AJAX, as_member
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_image_intent import FakeImageIntentJudge, image_bytes
from tests.chat.test_messages import MessageJava, events
from tests.chat.test_tools import use_agent

URL = "/ai/image-intent"
PROFILE_TOOL = "draft_member_profile_update"


class ReplyJudge(FakeImageIntentJudge):
    def __init__(self, kind: ImageIntentKind, reply: str | None = None) -> None:
        super().__init__(kind)
        self.reply = reply

    async def judge(self, jpeg: bytes, text: str | None) -> ImageIntentJudgement:
        self.calls.append((jpeg, text))
        return ImageIntentJudgement(kind=self.kind, reply=self.reply)


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


def use_judge(client, judge: FakeImageIntentJudge) -> FakeImageIntentJudge:
    client.app.dependency_overrides[clients.get_image_intent_judge] = lambda: judge
    as_member(client, 1)
    return judge


def post(client, data: dict):
    files = {"file": ("pet.png", image_bytes(), "image/png")}
    return client.post(URL, data=data, files=files, headers=AJAX)


def pairs(data: dict) -> list[tuple[str, str]]:
    return [(m["roleCd"], m["cnvrsCn"]) for m in data["messages"]]


# 판단 프롬프트·출력


def test_판단_프롬프트에_AGENT_정의와_안내_글_규칙이_있다():
    assert "- AGENT:" in IMAGE_INTENT_SYSTEM
    assert "프로필 사진" in IMAGE_INTENT_SYSTEM
    assert "글이 없으면 AGENT를 고르지 않는다" in IMAGE_INTENT_SYSTEM
    assert "reply" in IMAGE_INTENT_SYSTEM
    assert "다른 일도 글로 말해 달라" in IMAGE_INTENT_SYSTEM


def test_판단_출력의_안내_글을_판단_결과로_옮긴다():
    output = ImageIntentOutput(kind=ImageIntentKind.SKIN, reply="피부 분석으로 볼게요.")
    assert judgement_of(output) == ImageIntentJudgement(
        kind=ImageIntentKind.SKIN, reply="피부 분석으로 볼게요."
    )


def test_도구_고르기_규칙에_사진_표시_뜻이_있다():
    assert "'[사진]'으로 시작하면 회원이 그 메시지에 사진을 붙였다" in tool_system()


# AGENT 사진 턴 저장


def test_AGENT면_사용자_사진_메시지만_저장하고_안내는_없다(client, java):
    use_judge(client, ReplyJudge(ImageIntentKind.AGENT, reply="이어 갈게요."))
    room = java.add_room(1, "제목", pet_sn=1, cn="안녕")

    res = post(client, {"cnvrsCn": "프로필 사진 이걸로 바꿔줘", "aiCnvrsRoomSn": str(room)})

    assert res.status_code == 200
    data = res.json()["data"]
    assert data["kind"] == "AGENT"
    assert pairs(data) == [(ROLE_USER, "[사진] 프로필 사진 이걸로 바꿔줘")]


def test_AGENT_새_방은_글로_제목을_만들고_사진_메시지_하나만(client, java):
    use_judge(client, ReplyJudge(ImageIntentKind.AGENT))

    res = post(client, {"cnvrsCn": "프로필 사진 이걸로 바꿔줘"})

    data = res.json()["data"]
    assert data["kind"] == "AGENT"
    assert pairs(data) == [(ROLE_USER, "[사진] 프로필 사진 이걸로 바꿔줘")]
    assert java.rooms[data["aiCnvrsRoomSn"]]["cnvrsTtl"] != service.IMAGE_TITLE


# 안내 글은 LLM 글


def test_안내_글은_판단_LLM_글을_쓴다(client, java):
    use_judge(client, ReplyJudge(ImageIntentKind.ASK, reply="  이 사진으로 무엇을 할까요?  "))

    data = post(client, {"cnvrsCn": "이거 봐"}).json()["data"]

    assert pairs(data)[-1] == (ROLE_AI, "이 사진으로 무엇을 할까요?")


@pytest.mark.parametrize("reply", [None, "", "   ", "가" * (IMAGE_REPLY_MAX + 1)])
def test_안내_글이_없거나_길면_고정_글(client, java, reply):
    use_judge(client, ReplyJudge(ImageIntentKind.CHARACTER, reply=reply))

    data = post(client, {"cnvrsCn": "캐릭터 만들어줘"}).json()["data"]

    assert pairs(data)[-1] == (ROLE_AI, IMAGE_MESSAGES[ImageIntentKind.CHARACTER])


def test_판단_실패면_ASK_고정_글(client, java):
    use_judge(client, FakeImageIntentJudge(ImageIntentKind.ASK, fail=True))

    data = post(client, {"cnvrsCn": "이거 봐"}).json()["data"]

    assert data["kind"] == "ASK"
    assert pairs(data)[-1] == (ROLE_AI, IMAGE_MESSAGES[ImageIntentKind.ASK])


def test_동물병원_영수증은_안내_글이_있어도_AI_메시지가_없다(client, java):
    use_judge(client, ReplyJudge(ImageIntentKind.MEDICAL_RECEIPT, reply="영수증을 볼게요."))

    data = post(client, {"cnvrsCn": "병원비야"}).json()["data"]

    assert pairs(data) == [(ROLE_USER, "[사진] 병원비야")]


def test_안내_글_길이_경계():
    assert image_reply("가" * IMAGE_REPLY_MAX) == "가" * IMAGE_REPLY_MAX
    assert image_reply("가" * (IMAGE_REPLY_MAX + 1)) is None
    assert image_reply(None) is None


# /messages 이어 가기 : 문맥은 표시 그대로, 규칙에는 뗀 글


def test_사진_표시는_규칙용_글에서만_뗀다():
    assert question_text("[사진] 프로필 사진 바꿔줘") == "프로필 사진 바꿔줘"
    assert question_text("[사진]") == "[사진]"
    assert question_text("프로필 사진 [사진] 바꿔줘") == "프로필 사진 [사진] 바꿔줘"


def test_AGENT_뒤_메시지_없이_부르면_사진_메시지에_답하고_파일_칸_카드를_준다(client, java):
    as_member(client, 1)
    room = java.add_room(1, "제목", pet_sn=1, cn="[사진] 프로필 사진 이걸로 바꿔줘")
    agent = use_agent(client, FakeToolAgent(tool=PROFILE_TOOL, raw={}))

    res = client.post(f"/ai/conversations/{room}/messages", json={}, headers=AJAX)

    assert res.status_code == 200
    got = events(res)
    # LLM 문맥에는 표시를 그대로 둔다(사진을 붙였다는 뜻)
    messages = agent.decides[0][0]
    assert messages[-1] == {"role": "user", "content": "[사진] 프로필 사진 이걸로 바꿔줘"}
    done = next(data for name, data in got if name == "done")
    action = done["action"]
    assert action["tool"] == PROFILE_TOOL
    assert action["params"]["profilePhoto"]["type"] == "file"
    # 사용자 메시지는 새로 저장하지 않는다
    users = [m for m in java.rooms[room]["messages"] if m["roleCd"] == ROLE_USER]
    assert len(users) == 1


def test_prepare_turn은_답할_메시지의_사진_표시를_뗀다():
    message = ConversationMessage(
        ai_cnvrs_msg_sn=1,
        role_cd=ROLE_USER,
        cnvrs_cn="[사진] 프로필 사진 바꿔줘",
        msg_seq=1,
        reg_dt=datetime(2026, 11, 27, 9, 0),
    )
    room = ConversationDetail.model_construct(ai_cnvrs_room_sn=1, pet_sn=None, messages=[message])

    class Repo:
        async def get_room(self, room_sn: int) -> ConversationDetail:
            return room

    turn = asyncio.run(service.prepare_turn(Repo(), 1, None))

    assert turn.question.cnvrs_cn == "프로필 사진 바꿔줘"
    assert turn.question.msg_seq == 1
    assert turn.messages[0].cnvrs_cn == "[사진] 프로필 사진 바꿔줘"


# 도구 설명 : 파일 칸 카드는 붙인 사진을 쓰고, 반려동물 사진은 대화로 못 바꾼다


@pytest.mark.parametrize(
    "name",
    [
        PROFILE_TOOL,
        "draft_observation_cycle",
        "draft_observation_cycle_update",
        "draft_observation_item",
    ],
)
def test_파일_칸_카드_설명은_붙인_사진을_말한다(name):
    description = {d["name"]: d for d in tools.tool_definitions()}[name]["description"]
    assert "[사진]으로 시작하면 붙인 사진이 카드에 들어가고" in description
    assert "사진은 다루지 않는다" not in description


def test_반려동물_정보_수정_설명은_사진을_못_바꾼다고_한다():
    description = {d["name"]: d for d in tools.tool_definitions()}["draft_pet_update"]
    assert (
        "반려동물 사진·프로필 이미지를 바꾸는 말은 이 도구로 못 한다" in description["description"]
    )
