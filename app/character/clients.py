import struct
import zlib
from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends

from app.character.schemas import (
    CANVAS_SIZE,
    FACE_H,
    FACE_W,
    FACE_X,
    FACE_Y,
    PetSeCd,
)
from app.core.config import AiMode, Settings, get_settings


class CharacterApiError(Exception):
    """외부 이미지 생성 API 오류"""


@dataclass(frozen=True)
class CharacterRequest:
    photo: bytes
    pet_se_cd: PetSeCd
    vrty_nm: str | None = None
    colr_nm: str | None = None
    chrc_cn: str | None = None


class CharacterClient(Protocol):
    async def generate(self, request: CharacterRequest) -> bytes: ...


class MockCharacterClient:
    # AI_MODE=mock 전용 : 사진과 무관하게 규격(512×512) PNG
    async def generate(self, request: CharacterRequest) -> bytes:
        return _mock_png()


def _chunk(kind: bytes, body: bytes) -> bytes:
    crc = zlib.crc32(kind + body)
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)


def _mock_png() -> bytes:
    transparent = b"\x00" * (CANVAS_SIZE * 4)
    face_row = (
        b"\x00" * (FACE_X * 4)
        + b"\xf2\xa6\x5a\xff" * FACE_W
        + b"\x00" * ((CANVAS_SIZE - FACE_X - FACE_W) * 4)
    )
    rows = b"".join(
        b"\x00" + (face_row if FACE_Y <= y < FACE_Y + FACE_H else transparent)
        for y in range(CANVAS_SIZE)
    )
    # IHDR : 폭, 높이, 비트 깊이 8, 색상 타입 6(RGBA)
    ihdr = struct.pack(">IIBBBBB", CANVAS_SIZE, CANVAS_SIZE, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(rows))
        + _chunk(b"IEND", b"")
    )


def get_character_client(settings: Annotated[Settings, Depends(get_settings)]) -> CharacterClient:
    if settings.ai_mode is AiMode.MOCK:
        return MockCharacterClient()
    # 이미지 생성은 OpenAI GPT(2026-10-28 결정) : 키·모델 정한 뒤 연결
    raise NotImplementedError("캐릭터 real 모드는 아직 연결되지 않았습니다")
