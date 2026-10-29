import logging
from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends

from app.character.schemas import PetSeCd
from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


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


def get_character_client(
    settings: Annotated[Settings, Depends(get_settings)],
) -> CharacterClient | None:
    # 생성기(사진 분석 포함)는 다른 곳에서 만든 것을 붙인다. 그 전에는 None : 업로드 검증 뒤 502
    return None
