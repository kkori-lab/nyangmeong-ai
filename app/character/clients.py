import logging
from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends

from app.character.schemas import PetSeCd
from app.core.backend import external_error
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


def get_character_client(settings: Annotated[Settings, Depends(get_settings)]) -> CharacterClient:
    # 이미지 생성은 OpenAI GPT(2026-10-28 결정) : 키·모델 정한 뒤 연결. 그 전에는 502
    logger.error("캐릭터 생성 불가: 이미지 생성 클라이언트가 아직 연결되지 않았습니다")
    raise external_error()
