import json
from datetime import datetime, timedelta

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.core.backend import get_backend_client
from app.core.config import get_settings
from app.main import create_app

AJAX = {"X-Requested-With": "XMLHttpRequest"}
CONVERSATIONS = "/internal/ai/conversations"
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
    # 각자 PC의 .env.local 값과 무관하게 mock 모드로 기동. DB 설정은 없다
    monkeypatch.setenv("AI_MODE", "mock")
    monkeypatch.setenv("BACKEND_BASE_URL", "http://backend.test")
    get_settings.cache_clear()
    app = create_app()
    backend = httpx2.AsyncClient(transport=httpx2.MockTransport(java))
    app.dependency_overrides[get_backend_client] = lambda: backend
    return TestClient(app)


def as_member(client: TestClient, mbr_sn: int) -> None:
    client.cookies.set("access_token", f"member-{mbr_sn}")
