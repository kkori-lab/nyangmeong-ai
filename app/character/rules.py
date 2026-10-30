import struct

from app.character.schemas import CANVAS_SIZE

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_size(data: bytes) -> tuple[int, int] | None:
    """PNG IHDR(첫 청크)의 폭·높이 (PNG가 아니면 None)"""
    if len(data) < 24 or not data.startswith(_PNG_SIGNATURE) or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def matches_spec(data: bytes) -> bool:
    """FN-MYP-010-18 : 512×512 PNG 여부 (백엔드 CharacterSpec.matches와 같은 기준)"""
    return png_size(data) == (CANVAS_SIZE, CANVAS_SIZE)
