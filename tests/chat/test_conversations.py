import asyncio
import json

import httpx2
import pytest

from app.chat.repository import JavaConversationRepository
from app.chat.schemas import ROLE_AI
from app.core.backend import BackendError, get_backend_client
from app.core.config import Settings
from app.core.response import AppError
from tests.chat.conftest import AJAX, as_member, fake_auth_check

URL = "/ai/conversations"


def test_생성_Java에_쿠키와_평문으로_저장_요청하고_201(client, java):
    # FN-AIM-011-07·11·14 : 암호화·회원 판정은 Java 몫, Python은 쿠키와 평문을 넘긴다
    as_member(client, 1)
    res = client.post(
        URL, json={"petSn": 5, "cnvrsCn": "강아지 예방접종 순서 알려줘"}, headers=AJAX
    )

    assert res.status_code == 201
    data = res.json()["data"]
    assert data["petSn"] == 5
    assert data["cnvrsTtl"] == "강아지 예방접종 순서 알려줘"
    assert set(data) == {"aiCnvrsRoomSn", "petSn", "cnvrsTtl", "regDt"}
    (sent,) = java.requests
    assert sent.method == "POST"
    assert sent.url.path == "/internal/ai/conversations"
    assert sent.headers["cookie"] == "access_token=member-1"
    assert sent.headers["x-requested-with"] == "XMLHttpRequest"  # 추가-2 : Java RequestedWithFilter
    assert json.loads(sent.content) == {
        "petSn": 5,
        "cnvrsTtl": "강아지 예방접종 순서 알려줘",
        "cnvrsCn": "강아지 예방접종 순서 알려줘",
    }


def test_생성_제목은_200자로_자른다(client, java):
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
    assert json.loads(java.requests[0].content)["petSn"] is None


@pytest.mark.parametrize(
    "body", [{"cnvrsCn": "   "}, {"cnvrsCn": ""}, {"cnvrsCn": "가" * 1001}, {}]
)
def test_생성_본문_검증_실패는_400(client, java, body):
    # 입력창 규칙 : 공백만 불가, 1~1,000자
    as_member(client, 1)
    res = client.post(URL, json=body, headers=AJAX)

    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"
    assert java.requests == []


def test_생성_1000자는_통과(client):
    as_member(client, 1)
    assert client.post(URL, json={"cnvrsCn": "가" * 1000}, headers=AJAX).status_code == 201


def test_생성_쿠키_없으면_401(client, java):
    res = client.post(URL, json={"cnvrsCn": "안녕"}, headers=AJAX)

    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHORIZED"
    assert java.requests == []


def test_목록_내_대화만_최신순_필터(client, java):
    # FN-AIM-011-08·09 : A 목록에 B 방 없음, petSn 필터, 최신순, "전체"(null) 대화는 필터에서 제외
    java.add_room(1, "초코 첫째", pet_sn=5)
    java.add_room(2, "남의 대화", pet_sn=5)
    java.add_room(1, "뭉치", pet_sn=6)
    java.add_room(1, "전체", pet_sn=None)
    java.add_room(1, "초코 둘째", pet_sn=5)
    as_member(client, 1)

    all_titles = [r["cnvrsTtl"] for r in client.get(URL).json()["data"]]
    assert all_titles == ["초코 둘째", "전체", "뭉치", "초코 첫째"]
    assert dict(java.requests[-1].url.params) == {}
    assert java.requests[-1].headers["cookie"] == "access_token=member-1"

    choco = [r["cnvrsTtl"] for r in client.get(URL, params={"petSn": 5}).json()["data"]]
    assert choco == ["초코 둘째", "초코 첫째"]
    assert dict(java.requests[-1].url.params) == {"petSn": "5"}


def test_목록_없으면_빈_배열(client):
    as_member(client, 1)
    res = client.get(URL)

    assert res.status_code == 200
    assert res.json()["data"] == []


def test_상세_본인_방_메시지(client, java):
    # FN-AIM-011-10
    room_sn = java.add_room(1, "제목", pet_sn=5, cn="질문입니다")
    as_member(client, 1)
    res = client.get(f"{URL}/{room_sn}")

    assert res.status_code == 200
    data = res.json()["data"]
    assert data["cnvrsTtl"] == "제목"
    assert [(m["msgSeq"], m["roleCd"], m["cnvrsCn"]) for m in data["messages"]] == [
        (1, "AIMC0024", "질문입니다")
    ]
    assert dict(java.requests[-1].url.params) == {}


@pytest.mark.parametrize("room_sn", [999, 2])
def test_상세_남의_방과_없는_방은_Java_404_그대로(client, java, room_sn):
    java.add_room(1, "내 대화")
    java.add_room(2, "남의 대화")
    as_member(client, 1)
    res = client.get(f"{URL}/{room_sn}")

    assert res.status_code == 404
    assert res.json()["code"] == "NOT_FOUND"


def test_삭제_Java에_삭제_요청(client, java):
    # FN-AIM-011-13
    room_sn = java.add_room(1, "지울 대화")
    as_member(client, 1)
    res = client.delete(f"{URL}/{room_sn}", headers=AJAX)

    assert res.status_code == 200
    assert java.rooms == {}
    assert java.requests[-1].method == "DELETE"
    assert java.requests[-1].headers["x-requested-with"] == "XMLHttpRequest"
    assert java.requests[-1].url.path == f"/internal/ai/conversations/{room_sn}"


def test_삭제_남의_방은_404이고_남아_있다(client, java):
    room_sn = java.add_room(2, "남의 대화")
    as_member(client, 1)
    res = client.delete(f"{URL}/{room_sn}", headers=AJAX)

    assert res.status_code == 404
    assert res.json()["code"] == "NOT_FOUND"
    assert room_sn in java.rooms


def test_삭제_헤더_없으면_403이고_남아_있다(client, java):
    room_sn = java.add_room(1, "내 대화")
    as_member(client, 1)
    res = client.delete(f"{URL}/{room_sn}")

    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"
    assert room_sn in java.rooms


def test_목록_쿠키_없으면_Java_401_그대로이고_인증_확인은_부르지_않는다(client, java):
    # 추가-1 : 대화 API는 Java 대화 내부 API가 쿠키로 회원을 판정한다
    paths: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        paths.append(request.url.path)
        return java(request)

    _backend(client, handler)
    res = client.get(URL)

    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHORIZED"
    assert paths == ["/internal/ai/conversations"]


def test_Java_403은_본문과_Set_Cookie를_그대로(client):
    body = b'{"status":"error","httpCode":403,"code":"MEMBER_INACTIVE"}'
    clear = "access_token=; Max-Age=0; Path=/; HttpOnly"
    _backend(
        client,
        lambda r: httpx2.Response(
            403, content=body, headers={"content-type": "application/json", "set-cookie": clear}
        ),
    )
    as_member(client, 1)
    res = client.get(f"{URL}/1")

    assert res.status_code == 403
    assert res.content == body
    assert res.headers.get_list("set-cookie") == [clear]


def test_Java_오류의_내부_경로는_ai_경로로_바꾼다(client):
    # 추가-3 : /internal/** 경로를 React에 드러내지 않는다. 나머지 필드·Set-Cookie는 그대로
    body = {
        "status": "error",
        "httpCode": 404,
        "message": "요청한 정보를 찾을 수 없습니다.",
        "path": "/internal/ai/conversations/7",
        "code": "NOT_FOUND",
    }
    clear = "access_token=; Max-Age=0; Path=/; HttpOnly"
    _backend(client, lambda r: httpx2.Response(404, json=body, headers={"set-cookie": clear}))
    as_member(client, 1)
    res = client.get(f"{URL}/7")

    assert res.status_code == 404
    assert res.json() == {**body, "path": "/ai/conversations/7"}
    assert res.headers.get_list("set-cookie") == [clear]


def _backend(client, handler) -> None:
    backend = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    client.app.dependency_overrides[get_backend_client] = lambda: backend


def _auth_then(fail):
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/internal/auth/check":
            return fake_auth_check(request)
        return fail(request)

    return handler


def _connect_error(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("refused", request=request)


@pytest.mark.parametrize(
    "fail",
    [
        _connect_error,
        lambda r: httpx2.Response(500, json={"code": "INTERNAL_SERVER_ERROR"}),
        lambda r: httpx2.Response(200, json={"data": {"모양": "다름"}}),
    ],
    ids=["연결 실패", "Java 5xx", "응답 모양 다름"],
)
def test_Java_대화_API_실패는_502(client, fail):
    _backend(client, _auth_then(fail))
    as_member(client, 1)

    for res in (
        client.get(URL),
        client.get(f"{URL}/1"),
        client.post(URL, json={"cnvrsCn": "안녕"}, headers=AJAX),
    ):
        assert res.status_code == 502
        assert res.json()["code"] == "EXTERNAL_API_ERROR"


def _add_message(handler, cookie: str | None = "access_token=member-1"):
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    settings = Settings(_env_file=None, backend_base_url="http://backend.test")
    repo = JavaConversationRepository(client, settings, cookie)
    return asyncio.run(repo.add_message(3, ROLE_AI, "안내"))


def test_메시지_추가_Java에_역할과_본문으로_저장_요청():
    # FN-AIM-005-02 : POST /internal/ai/conversations/{roomSn}/messages
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        data = {
            "aiCnvrsMsgSn": 21,
            "roleCd": ROLE_AI,
            "cnvrsCn": "안내",
            "msgSeq": 2,
            "cmptnYn": True,
            "regDt": "2026-10-28T10:00:00",
        }
        return httpx2.Response(201, json={"status": "success", "httpCode": 201, "data": data})

    saved = _add_message(handler)

    req = seen[0]
    assert req.method == "POST"
    assert req.url.path == "/internal/ai/conversations/3/messages"
    assert json.loads(req.content) == {"roleCd": ROLE_AI, "cnvrsCn": "안내"}
    assert req.headers["X-Requested-With"] == "XMLHttpRequest"
    assert req.headers["Cookie"] == "access_token=member-1"
    assert (saved.ai_cnvrs_msg_sn, saved.role_cd, saved.msg_seq) == (21, ROLE_AI, 2)


@pytest.mark.parametrize("status", [401, 404])
def test_메시지_추가_Java_4xx는_그대로(status):
    body = {"status": "error", "httpCode": status, "code": "X"}
    with pytest.raises(BackendError) as exc:
        _add_message(lambda r: httpx2.Response(status, json=body))

    assert exc.value.status_code == status
    assert json.loads(exc.value.body) == body


def test_메시지_추가_응답_모양이_다르면_502():
    with pytest.raises(AppError) as exc:
        _add_message(lambda r: httpx2.Response(201, json={"data": {"모양": "다름"}}))

    assert (exc.value.code, exc.value.http_code) == ("EXTERNAL_API_ERROR", 502)
