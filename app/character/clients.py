import asyncio
import base64
import io
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Protocol, TypeVar

from fastapi import Depends
from openai import OpenAI

from app.character import canvas, engine
from app.character.schemas import PetSeCd
from app.core.config import Settings, get_settings
from app.core.usage import (
    NO_USAGE,
    ExternalApi,
    ExternalCall,
    UsageReporter,
    errored,
    failed,
    get_usage_reporter,
    succeeded,
)

logger = logging.getLogger(__name__)

IMAGE_SIZE = "1024x1024"
IMAGE_QUALITY = "medium"
# 눈을 못 찾은 결과 : service의 규격 판정에서 CHARACTER_SPEC_MISMATCH
NOT_PLACED = b""
# 사용량 통지 종류 : 캐릭터 패키지의 OpenAI 호출 전부 (FN-ADM-112-01)
USAGE_API = ExternalApi.CHARACTER

T = TypeVar("T")


class CharacterApiError(Exception):
    """외부 이미지 생성 API 오류"""


@dataclass(frozen=True)
class CharacterRequest:
    photo: bytes
    pet_se_cd: PetSeCd
    vrty_nm: str | None = None
    colr_nm: str | None = None
    chrc_cn: str | None = None


@dataclass(frozen=True)
class GeneratedCharacter:
    """512 결과와 굽기·합성에 다시 쓸 맨몸 시트·배치값"""

    image: bytes
    sheet: bytes = b""
    layout: canvas.Layout | None = None


class CharacterClient(Protocol):
    async def generate(self, request: CharacterRequest) -> GeneratedCharacter: ...

    async def bake(
        self,
        sheet: bytes,
        pet_se_cd: PetSeCd,
        item: engine.BakeItem,
        item_image: bytes | None = None,
    ) -> bytes: ...

    async def describe_item(self, image: bytes, regn_cd: str, item_nm: str) -> str: ...

    async def draw_item(self, image: bytes, regn_cd: str, item_nm: str) -> bytes: ...


@dataclass(frozen=True)
class Rendered:
    """맨몸 시트·서기 정면 컷과 512 배치 결과 (눈을 못 찾으면 placement 없음)"""

    sheet: bytes
    front: bytes
    placement: canvas.Placement | None


class OpenAICharacterClient:
    """FN-MYP-010-08·17 : 눈 판별 -> 2×2 시트 1회 생성 -> 서기 정면 512 배치"""

    def __init__(
        self,
        client: Any,
        image_model: str,
        vision_model: str,
        usage: UsageReporter = NO_USAGE,
    ) -> None:
        self._client = client
        self._image_model = image_model
        self._vision_model = vision_model
        self._usage = usage

    async def _in_thread(self, fn: Callable[..., T], *args: Any) -> T:
        """동기 SDK를 스레드에서 실행 -> 돌아온 뒤 모은 호출 통지 (스레드엔 이벤트 루프 없음)"""
        calls: list[ExternalCall] = []
        try:
            return await asyncio.to_thread(fn, *args, calls)
        finally:
            for call in calls:
                self._usage.record(call)

    def _edit_image(self, calls: list[ExternalCall], prompt: str, images: list) -> bytes:
        """images.edit 한 번 = 통지 한 건, 그림 없는 응답은 실패"""
        started = time.monotonic()
        try:
            response = self._client.images.edit(
                model=self._image_model,
                prompt=prompt,
                image=images,
                size=IMAGE_SIZE,
                quality=IMAGE_QUALITY,
                n=1,
            )
        except Exception as exc:
            calls.append(errored(USAGE_API, started, exc))
            raise
        usage = getattr(response, "usage", None)
        data = getattr(response, "data", None) or []
        encoded = getattr(data[0], "b64_json", None) if data else None
        if not encoded:
            calls.append(failed(USAGE_API, started, "invalid_output", usage))
            raise CharacterApiError("그림 없는 응답")
        calls.append(succeeded(USAGE_API, started, usage))
        return base64.b64decode(encoded)

    def _ask_vision(
        self,
        calls: list[ExternalCall],
        question: str,
        png: bytes,
        usable: Callable[[str], bool] = lambda _: True,
    ) -> str:
        """그림 한 장 + 질문 채팅 한 번 = 통지 한 건, 못 쓰는 답은 실패"""
        uri = "data:image/png;base64," + base64.b64encode(png).decode()
        started = time.monotonic()
        try:
            response = self._client.chat.completions.create(
                model=self._vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": question},
                            {"type": "image_url", "image_url": {"url": uri}},
                        ],
                    }
                ],
            )
            answer = response.choices[0].message.content or ""
        except Exception as exc:
            calls.append(errored(USAGE_API, started, exc))
            raise
        usage = getattr(response, "usage", None)
        if not usable(answer):
            calls.append(failed(USAGE_API, started, "invalid_output", usage))
        else:
            calls.append(succeeded(USAGE_API, started, usage))
        return answer

    async def generate(self, request: CharacterRequest) -> GeneratedCharacter:
        rendered = await self._in_thread(self.render, request)
        if rendered.placement is None:
            logger.warning("캐릭터 눈을 찾지 못함: 규격 실패로 보고")
            return GeneratedCharacter(NOT_PLACED)
        if rendered.placement.clipped:
            logger.warning("캐릭터가 512 캔버스 밖으로 잘림: 배율 %.3f", rendered.placement.scale)
        return GeneratedCharacter(rendered.placement.png, rendered.sheet, rendered.placement.layout)

    async def bake(
        self,
        sheet: bytes,
        pet_se_cd: PetSeCd,
        item: engine.BakeItem,
        item_image: bytes | None = None,
    ) -> bytes:
        return await self._in_thread(self._bake, sheet, pet_se_cd, item, item_image)

    def _bake(
        self,
        sheet: bytes,
        pet_se_cd: PetSeCd,
        item: engine.BakeItem,
        item_image: bytes | None,
        calls: list[ExternalCall],
    ) -> bytes:
        try:
            species = engine.species_of(pet_se_cd)
            prompt = engine.build_wear_prompt(species, item, by_image=item_image is not None)
            images = [("character.png", io.BytesIO(sheet), "image/png")]
            if item_image is not None:
                # 그림 순서 : 맨몸 시트가 첫째, 아이템 그림이 마지막 (프롬프트 머리말과 짝)
                reference = engine.normalize_item_image(item_image)
                images.append(("item.png", io.BytesIO(reference), "image/png"))
            return self._edit_image(calls, prompt, images)
        except Exception as exc:
            logger.error("아이템 굽기 실패: itemSn=%d, %s", item.item_sn, type(exc).__name__)
            raise CharacterApiError from exc

    async def describe_item(self, image: bytes, regn_cd: str, item_nm: str) -> str:
        return await self._in_thread(self._describe_item, image, regn_cd, item_nm)

    def _describe_item(
        self, image: bytes, regn_cd: str, item_nm: str, calls: list[ExternalCall]
    ) -> str:
        """FN-ADM-070-02 : 아이템 그림 -> 굽기 지시 한 문장"""
        try:
            png = engine.normalize_item_image(image)
            answer = self._ask_vision(
                calls,
                engine.item_hint_question(regn_cd, item_nm),
                png,
                lambda text: engine.parse_bake_hint(text) is not None,
            )
            hint = engine.parse_bake_hint(answer)
        except Exception as exc:
            logger.error("굽기 지시 초안 실패: %s", type(exc).__name__)
            raise CharacterApiError from exc
        if hint is None:
            logger.error("굽기 지시 초안 실패: 빈 답 또는 길이 초과")
            raise CharacterApiError
        return hint

    async def draw_item(self, image: bytes, regn_cd: str, item_nm: str) -> bytes:
        return await self._in_thread(self._draw_item, image, regn_cd, item_nm)

    def _draw_item(
        self, image: bytes, regn_cd: str, item_nm: str, calls: list[ExternalCall]
    ) -> bytes:
        """FN-ADM-070-02 : 실사 아이템 사진 -> 단색 배경 픽셀 아이템 그림 (배경 떼기는 service)"""
        try:
            # 순서 고정 : 프롬프트가 첫 그림을 화풍 기준, 마지막 그림을 사진으로 지칭
            refs = [
                ("style_ref.png", io.BytesIO(engine.STYLE_REF.read_bytes()), "image/png"),
                ("item.png", io.BytesIO(engine.normalize_item_image(image)), "image/png"),
            ]
            return self._edit_image(calls, engine.item_pixel_prompt(regn_cd, item_nm), refs)
        except Exception as exc:
            logger.error("픽셀 아이템 그림 생성 실패: %s", type(exc).__name__)
            raise CharacterApiError from exc

    def render(
        self, request: CharacterRequest, calls: list[ExternalCall] | None = None
    ) -> Rendered:
        """동기 SDK·이미지 처리 전체 (샘플 검증 스크립트도 사용)
        calls : 외부 호출 통지를 모을 목록, 없으면 버림"""
        calls = [] if calls is None else calls
        try:
            species = engine.species_of(request.pet_se_cd)
            photo = engine.normalize_photo(request.photo)
            prompt = engine.build_prompt(
                species,
                self._detect_eyes(photo, species, calls),
                request.vrty_nm,
                request.colr_nm,
                request.chrc_cn,
            )
            sheet = self._draw_sheet(prompt, photo, calls)
            front = engine.stand_front(sheet)
            buffer = io.BytesIO()
            front.save(buffer, "PNG")
            return Rendered(sheet, buffer.getvalue(), canvas.place(front))
        except Exception as exc:
            # 예외 본문 제외 : 요청 번호·내부 경로 포함 가능
            logger.error("캐릭터 생성 실패: %s", type(exc).__name__)
            raise CharacterApiError from exc

    def _detect_eyes(self, photo: bytes, species: str, calls: list[ExternalCall]) -> engine.Eyes:
        try:
            answer = self._ask_vision(calls, engine.eye_question(species), photo)
            return engine.parse_eyes(answer)
        except Exception as exc:
            # 눈 판별 때문에 생성을 실패시키지 않음
            logger.warning("눈 판별 실패, 기본값 사용: %s", type(exc).__name__)
            return engine.Eyes()

    def _draw_sheet(self, prompt: str, photo: bytes, calls: list[ExternalCall]) -> bytes:
        # 순서 고정 : 프롬프트가 첫 그림을 화풍 기준, 마지막 그림을 사진으로 지칭
        refs = [
            ("style_ref.png", io.BytesIO(engine.STYLE_REF.read_bytes()), "image/png"),
            ("photo.png", io.BytesIO(photo), "image/png"),
        ]
        return self._edit_image(calls, prompt, refs)


def get_character_client(
    settings: Annotated[Settings, Depends(get_settings)],
    usage: Annotated[UsageReporter, Depends(get_usage_reporter)] = NO_USAGE,
) -> CharacterClient | None:
    # 키 없음 : None이면 업로드 검증 뒤 502
    key = settings.openai_api_key.get_secret_value()
    if not key:
        return None
    client = OpenAI(api_key=key, timeout=settings.character_timeout_sec, max_retries=1)
    return OpenAICharacterClient(
        client, settings.character_image_model, settings.character_vision_model, usage
    )
