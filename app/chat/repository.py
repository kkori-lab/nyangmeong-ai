from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from app.core.db import create_engine

ROLE_USER = "AIMC0024"


@dataclass(frozen=True)
class RoomRow:
    room_sn: int
    pet_sn: int | None
    ttl_enc: str
    reg_dt: datetime


@dataclass(frozen=True)
class MessageRow:
    msg_sn: int
    role_cd: str
    cn_enc: str
    msg_seq: int
    reg_dt: datetime


class ConversationRepository(Protocol):
    async def create_room(
        self, mbr_sn: int, pet_sn: int | None, ttl_enc: str, first_cn_enc: str
    ) -> RoomRow: ...

    async def list_rooms(self, mbr_sn: int, pet_sn: int | None) -> list[RoomRow]: ...

    async def get_room(self, mbr_sn: int, room_sn: int) -> RoomRow | None: ...

    async def list_messages(self, room_sn: int) -> list[MessageRow]: ...

    async def delete_room(self, mbr_sn: int, room_sn: int) -> bool: ...

    async def delete_member(self, mbr_sn: int) -> int: ...


class SqlConversationRepository:
    # DDL에 FK·CASCADE가 없어 메시지를 먼저 지우고 방을 지운다. 모두 한 트랜잭션
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create_room(
        self, mbr_sn: int, pet_sn: int | None, ttl_enc: str, first_cn_enc: str
    ) -> RoomRow:
        async with self._engine.begin() as conn:
            inserted = await conn.execute(
                text(
                    "INSERT INTO AI_CNVRS_ROOM (MBR_SN, PET_SN, CNVRS_TTL_ENC) "
                    "VALUES (:mbr_sn, :pet_sn, :ttl_enc)"
                ),
                {"mbr_sn": mbr_sn, "pet_sn": pet_sn, "ttl_enc": ttl_enc},
            )
            room_sn = inserted.lastrowid
            await conn.execute(
                text(
                    "INSERT INTO AI_CNVRS_MSG (AI_CNVRS_ROOM_SN, ROLE_CD, CNVRS_CN_ENC, MSG_SEQ) "
                    "VALUES (:room_sn, :role_cd, :cn_enc, 1)"
                ),
                {"room_sn": room_sn, "role_cd": ROLE_USER, "cn_enc": first_cn_enc},
            )
            row = (
                await conn.execute(
                    text(
                        "SELECT AI_CNVRS_ROOM_SN, PET_SN, CNVRS_TTL_ENC, REG_DT "
                        "FROM AI_CNVRS_ROOM WHERE AI_CNVRS_ROOM_SN = :room_sn"
                    ),
                    {"room_sn": room_sn},
                )
            ).one()
        return _room(row)

    async def list_rooms(self, mbr_sn: int, pet_sn: int | None) -> list[RoomRow]:
        sql = (
            "SELECT AI_CNVRS_ROOM_SN, PET_SN, CNVRS_TTL_ENC, REG_DT "
            "FROM AI_CNVRS_ROOM WHERE MBR_SN = :mbr_sn"
        )
        params: dict[str, int] = {"mbr_sn": mbr_sn}
        if pet_sn is not None:
            sql += " AND PET_SN = :pet_sn"
            params["pet_sn"] = pet_sn
        sql += " ORDER BY REG_DT DESC, AI_CNVRS_ROOM_SN DESC"
        async with self._engine.connect() as conn:
            rows = (await conn.execute(text(sql), params)).all()
        return [_room(r) for r in rows]

    async def get_room(self, mbr_sn: int, room_sn: int) -> RoomRow | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT AI_CNVRS_ROOM_SN, PET_SN, CNVRS_TTL_ENC, REG_DT "
                        "FROM AI_CNVRS_ROOM "
                        "WHERE AI_CNVRS_ROOM_SN = :room_sn AND MBR_SN = :mbr_sn"
                    ),
                    {"room_sn": room_sn, "mbr_sn": mbr_sn},
                )
            ).first()
        return _room(row) if row else None

    async def list_messages(self, room_sn: int) -> list[MessageRow]:
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT AI_CNVRS_MSG_SN, ROLE_CD, CNVRS_CN_ENC, MSG_SEQ, REG_DT "
                        "FROM AI_CNVRS_MSG WHERE AI_CNVRS_ROOM_SN = :room_sn ORDER BY MSG_SEQ"
                    ),
                    {"room_sn": room_sn},
                )
            ).all()
        return [MessageRow(r[0], r[1], r[2], int(r[3]), r[4]) for r in rows]

    async def delete_room(self, mbr_sn: int, room_sn: int) -> bool:
        async with self._engine.begin() as conn:
            params = {"room_sn": room_sn, "mbr_sn": mbr_sn}
            await conn.execute(
                text(
                    "DELETE FROM AI_CNVRS_MSG WHERE AI_CNVRS_ROOM_SN = :room_sn AND EXISTS "
                    "(SELECT 1 FROM AI_CNVRS_ROOM "
                    "WHERE AI_CNVRS_ROOM_SN = :room_sn AND MBR_SN = :mbr_sn)"
                ),
                params,
            )
            deleted = await conn.execute(
                text(
                    "DELETE FROM AI_CNVRS_ROOM "
                    "WHERE AI_CNVRS_ROOM_SN = :room_sn AND MBR_SN = :mbr_sn"
                ),
                params,
            )
        return deleted.rowcount > 0

    async def delete_member(self, mbr_sn: int) -> int:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM AI_CNVRS_MSG WHERE AI_CNVRS_ROOM_SN IN "
                    "(SELECT AI_CNVRS_ROOM_SN FROM AI_CNVRS_ROOM WHERE MBR_SN = :mbr_sn)"
                ),
                {"mbr_sn": mbr_sn},
            )
            deleted = await conn.execute(
                text("DELETE FROM AI_CNVRS_ROOM WHERE MBR_SN = :mbr_sn"), {"mbr_sn": mbr_sn}
            )
        return deleted.rowcount


def _room(row) -> RoomRow:
    return RoomRow(int(row[0]), row[1], row[2], row[3])


@lru_cache
def _engine() -> AsyncEngine:
    # Settings는 해시할 수 없어 캐시 키로 못 쓴다. 엔진은 프로세스당 하나
    return create_engine(get_settings())


def get_conversation_repository() -> ConversationRepository:
    return SqlConversationRepository(_engine())
