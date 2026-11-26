"""동사형 명령은 확인 없이 바로 실행 (SCR-AIM-012, 2026-11-26 팀 합의)
- "…기록해 줘"·"…지워 줘" 같은 명령이면 빈 칸이 없을 때 첫 턴에 done.execute
- 빈 칸·같은 이름 반려동물·삭제 동사 없는 삭제 카드·동사 없는 말은 지금처럼 확인 안내
- 돌려받은 카드를 고치는 말은 바로 실행하지 않음"""

import pytest

from app.chat import rules
from app.chat.service import ACTION_RUN_SHOWN, ACTION_SHOWN
from tests.chat.fakes import FakeToolAgent
from tests.chat.test_action import WEIGHT, send
from tests.chat.test_action_delete import DELETE_RECORD, RECORDS
from tests.chat.test_action_multi import (
    HEALTH,
    HOSPITAL,
    SCHEDULE,
    WEIGHT_RAW,
    SequenceAgent,
    done_of,
)
from tests.chat.test_action_update_follow import ChainAgent
from tests.chat.test_messages import MessageJava
from tests.chat.test_read_tools import FakeToolReader, use_reader
from tests.chat.test_register import CHOCO, TODAY
from tests.chat.test_same_name_pets import pet
from tests.chat.test_tools import room_of, use_agent

PET_UPDATE = "draft_pet_update"


@pytest.fixture
def java() -> MessageJava:
    return MessageJava()


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rules, "today_kst", lambda: TODAY)


@pytest.mark.parametrize(
    "text",
    [
        "코코 체중 4.5kg 기록해 줘",
        "코코 체중 4.5kg 기록해줘!",
        "코코 체중 4kg 기록",
        "내일 3시 병원 일정 등록해 주세요",
        "토요일에 미용 잡아줘",
        "목표 체중 4kg로 바꿔 줘",
        "목표 체중 4kg로 수정해",
        "어제 사료 산 거 3만원으로 고쳐 줘",
        "오늘 산책 완료 체크해줘",
        "어제 체중 기록 지워 줘",
        "그 일정 삭제해 줘",
        "매주 산책 넣어줘",
        "체중 기록해 줄래?",
        "병원 일정 추가하자",
    ],
)
def test_쓰기_명령형_문장은_명령이다(text):
    assert rules.commands_now(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "코코 체중 4kg",
        "체중 기록할까?",
        "일정 등록할 수 있어?",
        "등록해?",
        "일정 등록 어떻게 해?",
        "체중 기록 알려줘",
        "기록 보여줘",
        "삭제하려면 어떻게 해야 돼?",
        "이번 달 지출 얼마야?",
    ],
)
def test_물음꼴과_동사_없는_말은_명령이_아니다(text):
    assert rules.commands_now(text) is False


def test_명령이고_빈_칸이_없으면_첫_턴에_실행_지시한다(client, java):
    use_agent(client, FakeToolAgent(HEALTH, WEIGHT_RAW))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "초코 오늘 8시 반 체중 4.2kg 기록해 줘"))

    assert done["execute"] is True
    assert [card["tool"] for card in done["actions"]] == [HEALTH]
    assert done["action"] == done["actions"][0]
    text = done["message"]["cnvrsCn"]
    lines = text.split("\n")
    assert lines[0].startswith("초코 건강 일지 기록 — 체중")
    assert lines[-1] == "등록할게요."
    assert "이렇게 할까요?" not in text
    assert "'등록해 줘'" not in text
    assert java.ai_messages(room)[-1]["cnvrsCn"] == text


def test_동사_없는_말은_지금처럼_확인을_안내한다(client, java):
    use_agent(client, FakeToolAgent(HEALTH, WEIGHT_RAW))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "초코 오늘 8시 반 체중 4.2kg"))

    assert done["execute"] is False
    assert done["message"]["cnvrsCn"].startswith("이렇게 할까요?")
    assert "'등록해 줘'" in done["message"]["cnvrsCn"]


def test_빈_칸이_있으면_명령이어도_되묻고_실행하지_않는다(client, java):
    raw = {"daily_rcd_idct_cd": WEIGHT, "rcd_ymd": TODAY.isoformat(), "rcd_tm": "08:30"}
    use_agent(client, FakeToolAgent(HEALTH, raw))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "초코 체중 기록해 줘"))

    assert done["execute"] is False
    assert done["action"]["missing"]
    assert "비어 있어요" in done["message"]["cnvrsCn"]


def test_여러_명령은_카드_모두_한_번에_실행_지시한다(client, java):
    use_agent(client, SequenceAgent((HEALTH, WEIGHT_RAW), (SCHEDULE, HOSPITAL)))
    room = room_of(client, java, pet_sn=CHOCO)

    text = "초코 오늘 8시 반 체중 4.2kg 기록하고 10월 6일 3시 병원 일정도 잡아줘"
    done = done_of(send(client, room, text))

    assert done["execute"] is True
    assert [card["tool"] for card in done["actions"]] == [HEALTH, SCHEDULE]
    lines = done["message"]["cnvrsCn"].split("\n")
    assert lines[0].startswith("1. 초코 건강 일지 기록")
    assert lines[1].startswith("2. 초코 일정 등록")
    assert lines[-1] == "등록할게요."


def test_여러_카드_중_하나라도_빈_칸이면_모두_실행하지_않는다(client, java):
    weight = {key: value for key, value in WEIGHT_RAW.items() if key != "rcd_nvl"}
    use_agent(client, SequenceAgent((HEALTH, weight), (SCHEDULE, HOSPITAL)))
    room = room_of(client, java, pet_sn=CHOCO)

    text = "초코 오늘 8시 반 체중 기록하고 10월 6일 3시 병원 일정도 잡아줘"
    done = done_of(send(client, room, text))

    assert done["execute"] is False
    assert len(done["actions"]) == 2
    assert "1번" in done["message"]["cnvrsCn"]


def test_두_아이_카드도_한_번에_실행_지시한다(client, java):
    java.pets = [
        pet(21, "봄이", "강아지", "푸들"),
        pet(22, "누리", "강아지", "말티즈"),
    ]
    raw = {"daily_rcd_idct_cd": WEIGHT, "rcd_ymd": TODAY.isoformat(), "rcd_tm": "08:00"}
    use_agent(client, FakeToolAgent(HEALTH, raw | {"rcd_nvl": 30}))
    room = room_of(client, java)

    done = done_of(send(client, room, "오늘 아침 8시 봄이랑 누리 체중 30 기록해줘"))

    assert done["execute"] is True
    assert [card["input"]["petSn"] for card in done["actions"]] == [21, 22]


def test_같은_이름_반려동물을_못_정하면_명령이어도_되묻는다(client, java):
    java.pets = [pet(11, "까미", "강아지", "말티즈"), pet(12, "까미", "고양이", "코숏")]
    raw = {"daily_rcd_idct_cd": WEIGHT, "rcd_ymd": TODAY.isoformat(), "rcd_nvl": 4.2}
    use_agent(client, FakeToolAgent(HEALTH, raw))
    room = room_of(client, java)

    done = done_of(send(client, room, "까미 오늘 체중 4.2kg 기록해줘"))

    assert done["execute"] is False
    assert done["action"]["missing"] == ["petSn"]
    assert done["message"]["cnvrsCn"].endswith("'강아지 까미'처럼 알려 주세요.")


def test_수정_명령은_수정할게요로_실행_지시한다(client, java):
    use_agent(client, FakeToolAgent(PET_UPDATE, {"goal_bdwg": 4}))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "초코 목표 체중 4kg로 바꿔 줘"))

    assert done["execute"] is True
    assert done["message"]["cnvrsCn"].split("\n")[-1] == "수정할게요."


def test_돌려받은_카드를_고치는_말은_바로_실행하지_않는다(client, java):
    use_agent(client, FakeToolAgent(HEALTH, WEIGHT_RAW | {"rcd_nvl": 4.5}))
    room = room_of(client, java, pet_sn=CHOCO)
    prior = {"tool": HEALTH, "input": {"petSn": CHOCO, "dailyRcdIdctCd": WEIGHT, "rcdNvl": 4.2}}

    done = done_of(send(client, room, "4.5로 바꿔줘", action=prior))

    assert done["execute"] is False
    assert done["action"]["input"]["rcdNvl"] == 4.5


# READ 뒤 카드 (목록 -> 완료 체크·삭제)


def test_READ_뒤_카드도_명령이면_이_턴에_실행_지시한다(client, java):
    agent = use_agent(
        client,
        FakeToolAgent(
            "list_care_items",
            {},
            follow_tool="draft_care_completion",
            follow_raw={"care_artcl_sn": 7},
        ),
    )
    use_reader(client, FakeToolReader([{"careArtclSn": 7, "careArtclNm": "산책"}]))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "오늘 산책 완료 체크해줘"))

    assert agent.results[1].startswith(ACTION_RUN_SHOWN.split("{summary}")[0])
    assert done["action"]["tool"] == "draft_care_completion"
    assert done["execute"] is True


def test_READ_뒤_카드도_물음꼴이면_실행하지_않는다(client, java):
    agent = use_agent(
        client,
        FakeToolAgent(
            "list_care_items",
            {},
            follow_tool="draft_care_completion",
            follow_raw={"care_artcl_sn": 7},
        ),
    )
    use_reader(client, FakeToolReader([{"careArtclSn": 7, "careArtclNm": "산책"}]))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "오늘 산책 완료 체크할까?"))

    assert agent.results[1].startswith(ACTION_SHOWN.split("{summary}")[0])
    assert done["execute"] is False


def test_READ_뒤_빈_칸이_있는_카드는_실행하지_않는다(client, java):
    use_agent(
        client,
        FakeToolAgent(
            "list_care_items",
            {},
            follow_tool="draft_care_completion",
            follow_raw={"care_artcl_sn": 99},
        ),
    )
    use_reader(client, FakeToolReader([{"careArtclSn": 7, "careArtclNm": "산책"}]))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "오늘 산책 완료 체크해줘"))

    assert done["action"]["missing"] == ["careArtclSn"]
    assert done["execute"] is False


def test_삭제_명령은_삭제_동사가_있으면_바로_실행_지시한다(client, java):
    use_agent(
        client,
        ChainAgent(
            "list_daily_health_records",
            [(DELETE_RECORD, {"daily_hlth_rcd_sn": 51})],
            ("지울게요.",),
        ),
    )
    use_reader(client, FakeToolReader(RECORDS))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "초코 어제 체중 기록 지워 줘"))

    assert done["action"]["tool"] == DELETE_RECORD
    assert done["execute"] is True


def test_삭제_카드는_삭제_동사가_없으면_실행하지_않는다(client, java):
    use_agent(
        client,
        ChainAgent(
            "list_daily_health_records",
            [(DELETE_RECORD, {"daily_hlth_rcd_sn": 51})],
            ("카드를 확인해 주세요.",),
        ),
    )
    use_reader(client, FakeToolReader(RECORDS))
    room = room_of(client, java, pet_sn=CHOCO)

    done = done_of(send(client, room, "초코 어제 체중 기록 정리해 줘"))

    assert done["action"]["tool"] == DELETE_RECORD
    assert done["execute"] is False
