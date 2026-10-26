from datetime import datetime, timedelta

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.chat.repository import MessageRow, RoomRow, get_conversation_repository
from app.core.backend import get_backend_client
from app.core.config import get_settings
from app.main import create_app

# 0~31 바이트 : 테스트 전용 키(운영 값 아님)
ENC_KEY_B64 = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
AJAX = {"X-Requested-With": "XMLHttpRequest"}
INTERNAL = {"X-Internal-Key": "test-key"}


def fake_auth_check(request: httpx2.Request) -> httpx2.Response:
    """Java /internal/auth/check 흉내 : 쿠키 access_token=member-<번호>면 통과"""
    cookie = request.headers.get("cookie", "")
    token = dict(p.strip().split("=", 1) for p in cookie.split(";") if "=" in p).get(
        "access_token", ""
    )
    if token.startswith("member-"):
        return httpx2.Response(200, json={"data": {"mbrSn": int(token[7:]), "mbrAuthrtCd": "U"}})
    return httpx2.Response(401, json={"status": "error", "httpCode": 401, "code": "UNAUTHORIZED"})


class FakeRepo:
    """ConversationRepository를 메모리로 흉내 낸다 (공용 DB에 붙지 않음)"""

    def __init__(self) -> None:
        self.rooms: dict[int, tuple[int, RoomRow]] = {}  # room_sn -> (mbr_sn, row)
        self.messages: dict[int, list[MessageRow]] = {}
        self._next_room = 1
        self._next_msg = 1
        self._clock = datetime(2026, 10, 25, 9, 0, 0)

    def _tick(self) -> datetime:
        self._clock += timedelta(minutes=1)
        return self._clock

    def add_room(
        self, mbr_sn: int, pet_sn: int | None, ttl_enc: str, cn_enc: str, role: str = "AIMC0024"
    ) -> RoomRow:
        room = RoomRow(self._next_room, pet_sn, ttl_enc, self._tick())
        self._next_room += 1
        self.rooms[room.room_sn] = (mbr_sn, room)
        self.messages[room.room_sn] = [MessageRow(self._next_msg, role, cn_enc, 1, self._tick())]
        self._next_msg += 1
        return room

    async def create_room(self, mbr_sn, pet_sn, ttl_enc, first_cn_enc) -> RoomRow:
        return self.add_room(mbr_sn, pet_sn, ttl_enc, first_cn_enc)

    async def list_rooms(self, mbr_sn, pet_sn) -> list[RoomRow]:
        rows = [
            r
            for m, r in self.rooms.values()
            if m == mbr_sn and (pet_sn is None or r.pet_sn == pet_sn)
        ]
        return sorted(rows, key=lambda r: (r.reg_dt, r.room_sn), reverse=True)

    async def get_room(self, mbr_sn, room_sn) -> RoomRow | None:
        found = self.rooms.get(room_sn)
        return found[1] if found and found[0] == mbr_sn else None

    async def list_messages(self, room_sn) -> list[MessageRow]:
        return sorted(self.messages.get(room_sn, []), key=lambda m: m.msg_seq)

    async def delete_room(self, mbr_sn, room_sn) -> bool:
        found = self.rooms.get(room_sn)
        if not found or found[0] != mbr_sn:
            return False
        del self.rooms[room_sn]
        self.messages.pop(room_sn, None)
        return True

    async def delete_member(self, mbr_sn) -> int:
        mine = [sn for sn, (m, _) in self.rooms.items() if m == mbr_sn]
        for sn in mine:
            del self.rooms[sn]
            self.messages.pop(sn, None)
        return len(mine)


@pytest.fixture
def repo() -> FakeRepo:
    return FakeRepo()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, repo: FakeRepo) -> TestClient:
    # 각자 PC의 .env.local 값과 무관하게 mock 모드·고정 키로 기동
    monkeypatch.setenv("AI_MODE", "mock")
    monkeypatch.setenv("INTERNAL_API_KEY", "test-key")
    monkeypatch.setenv("BACKEND_BASE_URL", "http://backend.test")
    monkeypatch.setenv("CONVERSATION_ENC_KEY", ENC_KEY_B64)
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_conversation_repository] = lambda: repo
    backend = httpx2.AsyncClient(transport=httpx2.MockTransport(fake_auth_check))
    app.dependency_overrides[get_backend_client] = lambda: backend
    return TestClient(app)


def as_member(client: TestClient, mbr_sn: int) -> None:
    client.cookies.set("access_token", f"member-{mbr_sn}")
