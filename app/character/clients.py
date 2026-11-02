import asyncio
import base64
import io
import logging
from dataclasses import dataclass
from typing import Annotated, Any, Protocol

from fastapi import Depends
from openai import OpenAI

from app.character import canvas, engine
from app.character.schemas import PetSeCd
from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

IMAGE_SIZE = "1024x1024"
IMAGE_QUALITY = "medium"
# 눈을 못 찾은 결과 : service의 규격 판정에서 CHARACTER_SPEC_MISMATCH
NOT_PLACED = b""


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


@dataclass(frozen=True)
class Rendered:
    """서기 정면 컷과 512 배치 결과 (눈을 못 찾으면 placement 없음)"""

    front: bytes
    placement: canvas.Placement | None


class OpenAICharacterClient:
    """FN-MYP-010-08·17 : 눈 판별 -> 2×2 시트 1회 생성 -> 서기 정면 512 배치

    - 맨몸 시트·배치값은 Java 저장 자리가 정해질 때까지 버림
    """

    def __init__(self, client: Any, image_model: str, vision_model: str) -> None:
        self._client = client
        self._image_model = image_model
        self._vision_model = vision_model

    async def generate(self, request: CharacterRequest) -> bytes:
        rendered = await asyncio.to_thread(self.render, request)
        if rendered.placement is None:
            logger.warning("캐릭터 눈을 찾지 못함: 규격 실패로 보고")
            return NOT_PLACED
        if rendered.placement.clipped:
            logger.warning("캐릭터가 512 캔버스 밖으로 잘림: 배율 %.3f", rendered.placement.scale)
        return rendered.placement.png

    def render(self, request: CharacterRequest) -> Rendered:
        """동기 SDK·이미지 처리 전체 (샘플 검증 스크립트도 사용)"""
        try:
            species = engine.species_of(request.pet_se_cd)
            photo = engine.normalize_photo(request.photo)
            prompt = engine.build_prompt(
                species,
                self._detect_eyes(photo, species),
                request.vrty_nm,
                request.colr_nm,
                request.chrc_cn,
            )
            front = engine.stand_front(self._draw_sheet(prompt, photo))
            buffer = io.BytesIO()
            front.save(buffer, "PNG")
            return Rendered(buffer.getvalue(), canvas.place(front))
        except Exception as exc:
            # 예외 본문 제외 : 요청 번호·내부 경로 포함 가능
            logger.error("캐릭터 생성 실패: %s", type(exc).__name__)
            raise CharacterApiError from exc

    def _detect_eyes(self, photo: bytes, species: str) -> engine.Eyes:
        uri = "data:image/png;base64," + base64.b64encode(photo).decode()
        try:
            response = self._client.chat.completions.create(
                model=self._vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": engine.eye_question(species)},
                            {"type": "image_url", "image_url": {"url": uri}},
                        ],
                    }
                ],
            )
            return engine.parse_eyes(response.choices[0].message.content or "")
        except Exception as exc:
            # 눈 판별 때문에 생성을 실패시키지 않음
            logger.warning("눈 판별 실패, 기본값 사용: %s", type(exc).__name__)
            return engine.Eyes()

    def _draw_sheet(self, prompt: str, photo: bytes) -> bytes:
        # 순서 고정 : 프롬프트가 첫 그림을 화풍 기준, 마지막 그림을 사진으로 지칭
        refs = [
            ("style_ref.png", io.BytesIO(engine.STYLE_REF.read_bytes()), "image/png"),
            ("photo.png", io.BytesIO(photo), "image/png"),
        ]
        response = self._client.images.edit(
            model=self._image_model,
            prompt=prompt,
            image=refs,
            size=IMAGE_SIZE,
            quality=IMAGE_QUALITY,
            n=1,
        )
        return base64.b64decode(response.data[0].b64_json)


def get_character_client(
    settings: Annotated[Settings, Depends(get_settings)],
) -> CharacterClient | None:
    # 키 없음 : None이면 업로드 검증 뒤 502
    key = settings.openai_api_key.get_secret_value()
    if not key:
        return None
    client = OpenAI(api_key=key, timeout=settings.character_timeout_sec, max_retries=1)
    return OpenAICharacterClient(
        client, settings.character_image_model, settings.character_vision_model
    )
