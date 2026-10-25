import pytest

from app.core.crypto import FieldCrypto
from tests.chat.conftest import AJAX, ENC_KEY_B64, INTERNAL, FakeRepo, as_member

URL = "/ai/conversations"
CRYPTO = FieldCrypto(ENC_KEY_B64)


def _seed(repo: FakeRepo, mbr_sn: int, title: str, pet_sn: int | None = None, cn: str = "본문"):
    return repo.add_room(mbr_sn, pet_sn, CRYPTO.encrypt(title), CRYPTO.encrypt(cn))


def test_생성_암호화해서_저장하고_201(client, repo):
    # FN-AIM-011-07·11·14
    as_member(client, 1)
    res = client.post(
        URL, json={"petSn": 5, "cnvrsCn": "강아지 예방접종 순서 알려줘"}, headers=AJAX
    )

    assert res.status_code == 201
    data = res.json()["data"]
    assert data["petSn"] == 5
    assert data["cnvrsTtl"] == "강아지 예방접종 순서 알려줘"
    assert len(repo.rooms) == 1
    mbr_sn, room = repo.rooms[data["aiCnvrsRoomSn"]]
    assert mbr_sn == 1
    assert "예방접종" not in room.ttl_enc
    assert CRYPTO.decrypt(room.ttl_enc) == "강아지 예방접종 순서 알려줘"
    (msg,) = repo.messages[room.room_sn]
    assert msg.role_cd == "AIMC0024"
    assert msg.msg_seq == 1
    assert "예방접종" not in msg.cn_enc
    assert CRYPTO.decrypt(msg.cn_enc) == "강아지 예방접종 순서 알려줘"


def test_생성_제목은_200자로_자른다(client):
    # FN-AIM-011-11
    from app.chat import clients

    class Long:
        async def generate(self, first_message: str) -> str:
            return "가" * 500

    client.app.dependency_overrides[clients.get_title_generator] = lambda: Long()
    as_member(client, 1)
    res = client.post(URL, json={"cnvrsCn": "안녕"}, headers=AJAX)

    assert res.status_code == 201
    assert len(res.json()["data"]["cnvrsTtl"]) == 200
    assert res.json()["data"]["petSn"] is None  # 전체 태그


@pytest.mark.parametrize(
    "body", [{"cnvrsCn": "   "}, {"cnvrsCn": ""}, {"cnvrsCn": "가" * 1001}, {}]
)
def test_생성_본문_검증_실패는_400(client, repo, body):
    # 입력창 규칙 : 공백만 불가, 1~1,000자
    as_member(client, 1)
    res = client.post(URL, json=body, headers=AJAX)

    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"
    assert repo.rooms == {}


def test_생성_1000자는_통과(client):
    as_member(client, 1)
    assert client.post(URL, json={"cnvrsCn": "가" * 1000}, headers=AJAX).status_code == 201


def test_생성_쿠키_없으면_401(client):
    res = client.post(URL, json={"cnvrsCn": "안녕"}, headers=AJAX)

    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHORIZED"


def test_목록_내_대화만_최신순_필터(client, repo):
    # FN-AIM-011-08·09 : A 목록에 B 방 없음, petSn 필터, 최신순, "전체"(null) 대화는 필터에서 제외
    _seed(repo, 1, "초코 첫째", pet_sn=5)
    _seed(repo, 2, "남의 대화", pet_sn=5)
    _seed(repo, 1, "뭉치", pet_sn=6)
    _seed(repo, 1, "전체", pet_sn=None)
    _seed(repo, 1, "초코 둘째", pet_sn=5)
    as_member(client, 1)

    all_titles = [r["cnvrsTtl"] for r in client.get(URL).json()["data"]]
    assert all_titles == ["초코 둘째", "전체", "뭉치", "초코 첫째"]

    choco = [r["cnvrsTtl"] for r in client.get(URL, params={"petSn": 5}).json()["data"]]
    assert choco == ["초코 둘째", "초코 첫째"]


def test_목록_없으면_빈_배열(client):
    as_member(client, 1)
    res = client.get(URL)

    assert res.status_code == 200
    assert res.json()["data"] == []


def test_상세_본인_방_메시지_복호화(client, repo):
    # FN-AIM-011-10
    room = _seed(repo, 1, "제목", pet_sn=5, cn="질문입니다")
    as_member(client, 1)
    res = client.get(f"{URL}/{room.room_sn}")

    assert res.status_code == 200
    data = res.json()["data"]
    assert data["cnvrsTtl"] == "제목"
    assert [(m["msgSeq"], m["roleCd"], m["cnvrsCn"]) for m in data["messages"]] == [
        (1, "AIMC0024", "질문입니다")
    ]


@pytest.mark.parametrize("room_sn", [999, 2])
def test_상세_남의_방과_없는_방은_404(client, repo, room_sn):
    _seed(repo, 1, "내 대화")
    _seed(repo, 2, "남의 대화")
    as_member(client, 1)
    res = client.get(f"{URL}/{room_sn}")

    assert res.status_code == 404
    assert res.json()["code"] == "NOT_FOUND"


def test_삭제_방과_메시지_모두_없어진다(client, repo):
    # FN-AIM-011-13
    room = _seed(repo, 1, "지울 대화")
    as_member(client, 1)
    res = client.delete(f"{URL}/{room.room_sn}", headers=AJAX)

    assert res.status_code == 200
    assert repo.rooms == {}
    assert repo.messages == {}


def test_삭제_남의_방은_404이고_남아_있다(client, repo):
    room = _seed(repo, 2, "남의 대화")
    as_member(client, 1)
    res = client.delete(f"{URL}/{room.room_sn}", headers=AJAX)

    assert res.status_code == 404
    assert room.room_sn in repo.rooms


def test_삭제_헤더_없으면_403이고_남아_있다(client, repo):
    room = _seed(repo, 1, "내 대화")
    as_member(client, 1)
    res = client.delete(f"{URL}/{room.room_sn}")

    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"
    assert room.room_sn in repo.rooms


PURGE = "/internal/v1/members/{}/conversations"


def test_파기_대상_회원만_지운다(client, repo):
    # FN-AIM-011-19
    _seed(repo, 1, "A1")
    _seed(repo, 1, "A2")
    b = _seed(repo, 2, "B1")
    res = client.delete(PURGE.format(1), headers=INTERNAL)

    assert res.status_code == 200
    assert list(repo.rooms) == [b.room_sn]
    assert list(repo.messages) == [b.room_sn]


def test_파기_대화_없는_회원도_200(client):
    assert client.delete(PURGE.format(77), headers=INTERNAL).status_code == 200


@pytest.mark.parametrize("headers", [{}, {"X-Internal-Key": "wrong"}])
def test_파기_내부_키_없거나_틀리면_401(client, repo, headers):
    _seed(repo, 1, "A1")
    res = client.delete(PURGE.format(1), headers=headers)

    assert res.status_code == 401
    assert len(repo.rooms) == 1
