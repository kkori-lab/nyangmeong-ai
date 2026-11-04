import asyncio
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Any, Protocol

import httpx2
from fastapi import Depends, Request
from pydantic import BaseModel, Field, ValidationError

from app.character import engine
from app.character.canvas import Layout
from app.character.schemas import PetSeCd
from app.core.auth import REQUESTED_WITH
from app.core.backend import (
    call_backend,
    external_error,
    fetch_backend_bytes,
    get_backend_client,
)
from app.core.config import Settings, get_settings

# Java 캐릭터 내부 API (docs/api/internal.md "Python → Java")
CHARACTERS_PATH = "/internal/ai/characters"
JOBS_PATH = f"{CHARACTERS_PATH}/jobs"
ITEMS_PATH = "/internal/ai/items"
REQUESTED_WITH_HEADER = "X-Requested-With"
# 시트는 1024 PNG : 기본 3초로는 전송이 끊길 수 있음
SHEET_TIMEOUT_SEC = 15.0


class CharacterFailure(StrEnum):
    # 실패 사유 : Java CHAR_CRT_JOB 실패 사유로 저장
    API_ERROR = "CHARACTER_API_ERROR"  # 생성기 오류
    SPEC_MISMATCH = "CHARACTER_SPEC_MISMATCH"  # 512×512 규격 밖


@dataclass(frozen=True)
class CharacterJob:
    """Java가 만든 생성 작업과 반려동물 등록 정보(FN-MYP-010-08 읽기 전용 값)"""

    char_crt_job_sn: int
    pet_se_cd: PetSeCd
    vrty_nm: str | None = None
    colr_nm: str | None = None
    chrc_cn: str | None = None


@dataclass(frozen=True)
class CharacterSheets:
    """합성용 시트 : sheets는 구운 아이템, failed는 굽기 실패 아이템"""

    pet_se_cd: PetSeCd
    sheet: bytes
    layout: Layout
    sheets: dict[int, bytes] = field(default_factory=dict)
    failed: frozenset[int] = frozenset()


class CharacterJobRepository(Protocol):
    async def create_job(self, pet_sn: int) -> CharacterJob: ...

    async def report_success(
        self, char_crt_job_sn: int, image: bytes, sheet: bytes, layout: Layout | None
    ) -> int: ...

    async def report_failure(self, char_crt_job_sn: int, reason: CharacterFailure) -> None: ...

    async def list_bake_items(self) -> dict[int, engine.BakeItem]: ...

    async def list_bake_targets(self, item_sn: int) -> "BakeTargetPage": ...

    async def save_item_sheet(self, pixel_char_sn: int, item_sn: int, sheet: bytes) -> None: ...

    async def report_bake_failure(self, pixel_char_sn: int, item_sn: int) -> None: ...

    async def find_sheets(self, pixel_char_sn: int, item_sns: Iterable[int]) -> CharacterSheets: ...

    async def save_equipped_image(
        self, pixel_char_sn: int, item_sns: Sequence[int], image: bytes
    ) -> None: ...


class _JobResponse(BaseModel):
    char_crt_job_sn: int = Field(alias="charCrtJobSn")
    pet_se_cd: PetSeCd = Field(alias="petSeCd")
    vrty_nm: str | None = Field(default=None, alias="vrtyNm")
    colr_nm: str | None = Field(default=None, alias="colrNm")
    chrc_cn: str | None = Field(default=None, alias="chrcCn")


class _SuccessResponse(BaseModel):
    pixel_char_sn: int = Field(alias="pixelCharSn")


class _BakeItem(BaseModel):
    item_sn: int = Field(alias="itemSn")
    regn_cd: str = Field(alias="regnCd")
    bake_hint: str = Field(alias="bakeHint", min_length=1)


class BakeTargetPage(BaseModel):
    """FN-ADM-070-02 : 안 구운 캐릭터 첫 페이지 (Java 100개씩)"""

    pixel_char_sns: list[int] = Field(alias="pixelCharSns")
    last: bool


class _SheetItem(BaseModel):
    item_sn: int = Field(alias="itemSn")
    atch_file_sn: int | None = Field(default=None, alias="atchFileSn")
    bake_failed: bool = Field(default=False, alias="bakeFailed")


class _SheetsResponse(BaseModel):
    pet_se_cd: PetSeCd = Field(alias="petSeCd")
    sheet_file_sn: int = Field(alias="sheetFileSn")
    scale: float
    origin_x: float = Field(alias="originX")
    origin_y: float = Field(alias="originY")
    items: list[_SheetItem] = []


def _png(name: str, content: bytes) -> tuple[str, bytes, str]:
    return name, content, "image/png"


class JavaCharacterJobRepository:
    # 회원 판정은 Java(브라우저 Cookie) : 4xx 그대로 전달, 연결 실패·5xx·응답 모양 불일치는 502
    # 응답 뒤 호출도 요청에서 복사해 둔 쿠키를 쓴다 : 쿠키가 만료되면 Java가 401 (보고 실패로 남음)
    def __init__(self, client: httpx2.AsyncClient, settings: Settings, cookie: str | None) -> None:
        self._client = client
        self._settings = settings
        # Java RequestedWithFilter가 /internal/**의 POST에도 적용
        self._headers = {REQUESTED_WITH_HEADER: REQUESTED_WITH}
        if cookie:
            self._headers["Cookie"] = cookie

    async def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        kwargs.setdefault("headers", self._headers)
        return await call_backend(self._client, self._settings, method, path, **kwargs)

    async def create_job(self, pet_sn: int) -> CharacterJob:
        # FN-MYP-010-08 : 주양육자·이미 캐릭터 있음·생성 중 판정은 Java
        data = await self._call("POST", JOBS_PATH, json={"petSn": pet_sn})
        try:
            job = _JobResponse.model_validate(data)
        except ValidationError:
            raise external_error() from None
        return CharacterJob(
            job.char_crt_job_sn, job.pet_se_cd, job.vrty_nm, job.colr_nm, job.chrc_cn
        )

    async def report_success(
        self, char_crt_job_sn: int, image: bytes, sheet: bytes, layout: Layout | None
    ) -> int:
        # FN-MYP-010-09·17 : 결과와 합성에 쓸 맨몸 시트·배치값을 함께 저장 요청
        placement = {}
        if layout is not None:
            placement = {
                "scale": str(layout.scale),
                "originX": str(layout.origin_x),
                "originY": str(layout.origin_y),
            }
        data = await self._call(
            "POST",
            f"{JOBS_PATH}/{char_crt_job_sn}/success",
            files={"image": _png("image.png", image), "sheet": _png("sheet.png", sheet)},
            data=placement,
            timeout=SHEET_TIMEOUT_SEC,
        )
        try:
            return _SuccessResponse.model_validate(data).pixel_char_sn
        except ValidationError:
            raise external_error() from None

    async def report_failure(self, char_crt_job_sn: int, reason: CharacterFailure) -> None:
        await self._call(
            "POST", f"{JOBS_PATH}/{char_crt_job_sn}/failure", json={"failRsn": reason.value}
        )

    async def list_bake_items(self) -> dict[int, engine.BakeItem]:
        data = await self._call("GET", f"{CHARACTERS_PATH}/bake-items")
        try:
            items = [_BakeItem.model_validate(item) for item in data]
        except (TypeError, ValidationError):
            raise external_error() from None
        return {
            item.item_sn: engine.BakeItem(item.item_sn, item.regn_cd, item.bake_hint)
            for item in items
        }

    async def list_bake_targets(self, item_sn: int) -> BakeTargetPage:
        # FN-ADM-070-02 : 아직 안 구운 캐릭터 첫 페이지 (관리자 판정은 Java)
        # 구운·실패 표시한 캐릭터는 빠지므로 다음 묶음도 첫 페이지
        data = await self._call("GET", f"{ITEMS_PATH}/{item_sn}/bake-targets", params={"page": 0})
        try:
            return BakeTargetPage.model_validate(data)
        except ValidationError:
            raise external_error() from None

    async def save_item_sheet(self, pixel_char_sn: int, item_sn: int, sheet: bytes) -> None:
        await self._call(
            "PUT",
            f"{CHARACTERS_PATH}/{pixel_char_sn}/item-sheets/{item_sn}",
            files={"sheet": _png("sheet.png", sheet)},
            timeout=SHEET_TIMEOUT_SEC,
        )

    async def report_bake_failure(self, pixel_char_sn: int, item_sn: int) -> None:
        await self._call("POST", f"{CHARACTERS_PATH}/{pixel_char_sn}/item-sheets/{item_sn}/failure")

    async def find_sheets(self, pixel_char_sn: int, item_sns: Iterable[int]) -> CharacterSheets:
        # FN-MYP-011-06 : 주양육자·소유 판정은 Java, 시트는 커서 파일 번호로 따로 받음
        wanted = set(item_sns)
        data = await self._call(
            "GET",
            f"{CHARACTERS_PATH}/{pixel_char_sn}/sheets",
            params={"itemSns": sorted(wanted)},
        )
        try:
            found = _SheetsResponse.model_validate(data)
        except ValidationError:
            raise external_error() from None
        items = [item for item in found.items if item.item_sn in wanted]
        baked = [item for item in items if item.atch_file_sn is not None]
        files = await asyncio.gather(
            self._fetch_sheet(pixel_char_sn, found.sheet_file_sn),
            *(self._fetch_sheet(pixel_char_sn, item.atch_file_sn) for item in baked),
        )
        return CharacterSheets(
            found.pet_se_cd,
            files[0],
            Layout(found.scale, found.origin_x, found.origin_y),
            {item.item_sn: sheet for item, sheet in zip(baked, files[1:], strict=True)},
            frozenset(item.item_sn for item in items if item.bake_failed),
        )

    async def save_equipped_image(
        self, pixel_char_sn: int, item_sns: Sequence[int], image: bytes
    ) -> None:
        # FN-MYP-010-16 : Java 대표 이미지로 저장
        # 지금 확정 착용 목록과 다르면 409 EQUIPPED_ITEMS_CHANGED (옛 합성 덮어쓰기 방지)
        await self._call(
            "PUT",
            f"{CHARACTERS_PATH}/{pixel_char_sn}/equipped-image",
            files={"image": _png("image.png", image)},
            data={"itemSns": [str(sn) for sn in item_sns]},
            timeout=SHEET_TIMEOUT_SEC,
        )

    async def _fetch_sheet(self, pixel_char_sn: int, atch_file_sn: int | None) -> bytes:
        return await fetch_backend_bytes(
            self._client,
            self._settings,
            f"{CHARACTERS_PATH}/{pixel_char_sn}/sheet-files/{atch_file_sn}",
            headers=self._headers,
            timeout=SHEET_TIMEOUT_SEC,
        )


def get_character_job_repository(
    request: Request,
    client: Annotated[httpx2.AsyncClient, Depends(get_backend_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CharacterJobRepository:
    return JavaCharacterJobRepository(client, settings, request.headers.get("cookie"))
