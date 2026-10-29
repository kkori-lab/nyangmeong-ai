import json
from datetime import datetime, timedelta

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.chat import clients
from app.core.backend import get_backend_client
from app.core.config import get_settings
from app.main import create_app
from tests.chat.fakes import (
    FakeAnswerGenerator,
    FakeIntentClassifier,
    FakeRegisterExtractor,
    FakeTitleGenerator,
)

AJAX = {"X-Requested-With": "XMLHttpRequest"}
CONVERSATIONS = "/internal/ai/conversations"
REGISTER_CONTEXT = "/internal/ai/register-context"
ROLE_USER = "AIMC0024"


UNAUTHORIZED = {"status": "error", "httpCode": 401, "code": "UNAUTHORIZED"}


def member_of(request: httpx2.Request) -> int | None:
    """쿠키 access_token=member-<번호>면 그 회원 번호 (Java의 쿠키 판정 흉내)"""
    cookie = request.headers.get("cookie", "")
    token = dict(p.strip().split("=", 1) for p in cookie.split(";") if "=" in p).get(
        "access_token", ""
    )
    return int(token[7:]) if token.startswith("member-") else None


def fake_auth_check(request: httpx2.Request) -> httpx2.Response:
    """Java /internal/auth/check 흉내"""
    mbr_sn = member_of(request)
    if mbr_sn is not None:
        return httpx2.Response(200, json={"data": {"mbrSn": mbr_sn, "mbrAuthrtCd": "U"}})
    return httpx2.Response(401, json=UNAUTHORIZED)


class FakeJava:
    """Java 대화 내부 API를 메모리로 흉내 낸다. 회원은 쿠키로 정한다

    대화 API로 온 요청은 requests에 남긴다
    """

    def __init__(self) -> None:
        self.rooms: dict[int, dict] = {}  # room_sn -> {mbrSn, petSn, cnvrsTtl, regDt, messages}
        self.requests: list[httpx2.Request] = []
        self._next_room = 1
        self._next_msg = 1
        self._clock = datetime(2026, 10, 25, 9, 0, 0)
        # GET /internal/ai/register-context 응답(회원과 관계없이 같은 목록)
        self.pets: list[dict] = [
            {"petSn": 1, "petNm": "초코", "careArtclNms": []},
            {"petSn": 2, "petNm": "뭉치", "careArtclNms": ["발톱 깎기"]},
        ]
        # register-context 실패 흉내 : 응답 상태 코드, 0이면 연결 실패
        self.context_status: int | None = None

    def _tick(self) -> str:
        self._clock += timedelta(minutes=1)
        return self._clock.isoformat()

    def add_room(self, mbr_sn: int, title: str, pet_sn: int | None = None, cn: str = "본문") -> int:
        room_sn = self._next_room
        self._next_room += 1
        reg_dt = self._tick()
        message = {
            "aiCnvrsMsgSn": self._next_msg,
            "roleCd": ROLE_USER,
            "cnvrsCn": cn,
            "msgSeq": 1,
            "regDt": reg_dt,
        }
        self._next_msg += 1
        self.rooms[room_sn] = {
            "mbrSn": mbr_sn,
            "petSn": pet_sn,
            "cnvrsTtl": title,
            "regDt": reg_dt,
            "messages": [message],
        }
        return room_sn

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path == "/internal/auth/check":
            return fake_auth_check(request)
        self.requests.append(request)
        mbr_sn = member_of(request)
        if mbr_sn is None:
            return httpx2.Response(401, json=UNAUTHORIZED)
        params = request.url.params
        if path == REGISTER_CONTEXT and request.method == "GET":
            if self.context_status == 0:
                raise httpx2.ConnectError("down")
            if self.context_status is not None:
                return httpx2.Response(self.context_status, json={"status": "error"})
            return _ok(self.pets)
        if path == CONVERSATIONS and request.method == "POST":
            body = json.loads(request.content)
            room_sn = self.add_room(mbr_sn, body["cnvrsTtl"], body.get("petSn"), body["cnvrsCn"])
            return _ok(self._summary(room_sn), 201)
        if path == CONVERSATIONS and request.method == "GET":
            pet_sn = int(params["petSn"]) if "petSn" in params else None
            mine = [
                sn
                for sn, r in self.rooms.items()
                if r["mbrSn"] == mbr_sn and (pet_sn is None or r["petSn"] == pet_sn)
            ]
            mine.sort(key=lambda sn: (self.rooms[sn]["regDt"], sn), reverse=True)
            return _ok([self._summary(sn) for sn in mine])
        if path.startswith(f"{CONVERSATIONS}/"):
            room_sn = int(path.rsplit("/", 1)[1])
            room = self.rooms.get(room_sn)
            if room is None or room["mbrSn"] != mbr_sn:
                return httpx2.Response(
                    404, json={"status": "error", "httpCode": 404, "code": "NOT_FOUND"}
                )
            if request.method == "GET":
                return _ok({**self._summary(room_sn), "messages": room["messages"]})
            if request.method == "DELETE":
                del self.rooms[room_sn]
                return _ok(None)
        return httpx2.Response(404)

    def _summary(self, room_sn: int) -> dict:
        r = self.rooms[room_sn]
        return {
            "aiCnvrsRoomSn": room_sn,
            "petSn": r["petSn"],
            "cnvrsTtl": r["cnvrsTtl"],
            "regDt": r["regDt"],
        }


def _ok(data, status: int = 200) -> httpx2.Response:
    body = {"status": "success", "httpCode": status, "message": "ok"}
    if data is not None:
        body["data"] = data
    return httpx2.Response(status, json=body)


@pytest.fixture
def java() -> FakeJava:
    return FakeJava()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, java: FakeJava) -> TestClient:
    # 외부 AI는 가짜를 끼운다. 테스트가 따로 바꿔 끼울 수 있다
    monkeypatch.setenv("BACKEND_BASE_URL", "http://backend.test")
    get_settings.cache_clear()
    app = create_app()
    backend = httpx2.AsyncClient(transport=httpx2.MockTransport(java))
    app.dependency_overrides[get_backend_client] = lambda: backend
    app.dependency_overrides[clients.get_title_generator] = FakeTitleGenerator
    app.dependency_overrides[clients.get_intent_classifier] = FakeIntentClassifier
    app.dependency_overrides[clients.get_answer_generator] = FakeAnswerGenerator
    app.dependency_overrides[clients.get_register_extractor] = FakeRegisterExtractor
    return TestClient(app)


def as_member(client: TestClient, mbr_sn: int) -> None:
    client.cookies.set("access_token", f"member-{mbr_sn}")
