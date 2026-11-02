import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from app.character.canvas import Layout
from app.character.schemas import PetSeCd
from app.core.backend import BackendError

logger = logging.getLogger(__name__)

_NOT_FOUND = b'{"code":"PIXEL_CHARACTER_NOT_FOUND"}'
# 가짜 번호 : ITEM에 엔진 키 컬럼이 생기기 전 임시. 시드의 얼굴·목·가방 ITEM_SN은 그대로
_FAKE_ITEM_SNS = {
    5: "round-glasses",
    6: "sunglasses",
    7: "heart-glasses",
    8: "monocle",
    9: "bell-necklace",
    10: "check-scarf",
    11: "bow-tie",
    12: "pearl-necklace",
    17: "small-backpack",
    18: "crossbody-bag",
    19: "lunch-bag",
    20: "flower-basket",
    101: "red-beanie",
    102: "straw-hat",
    103: "baseball-cap",
    104: "bucket-hat",
    105: "winter-earflap-hat",
    106: "pink-bucket-hat",
    107: "green-earflap-hat",
    108: "green-sweater",
    109: "yellow-raincoat",
    110: "denim-jacket",
    111: "hoodie",
    112: "puffer-vest",
    113: "purple-denim-jacket",
    114: "teal-puffer-vest",
}


class CharacterFailure(StrEnum):
    # 실패 사유 : Java 내부 API 확정 시 그쪽 값으로 맞춤
    API_ERROR = "CHARACTER_API_ERROR"  # 생성기 오류
    SPEC_MISMATCH = "CHARACTER_SPEC_MISMATCH"  # 512×512 규격 밖


@dataclass(frozen=True)
class CharacterJob:
    """Java가 만든 생성 작업과 반려동물 등록 정보(FN-MYP-010-08 읽기 전용 값)"""

    chrc_job_sn: int
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
        self, chrc_job_sn: int, image: bytes, sheet: bytes, layout: Layout | None
    ) -> int: ...

    async def report_failure(self, chrc_job_sn: int, reason: CharacterFailure) -> None: ...

    async def list_bake_items(self) -> dict[int, str]: ...

    async def save_item_sheet(self, pixel_char_sn: int, item_sn: int, sheet: bytes) -> None: ...

    async def report_bake_failure(self, pixel_char_sn: int, item_sn: int) -> None: ...

    async def find_sheets(self, pixel_char_sn: int, item_sns: Iterable[int]) -> CharacterSheets: ...


@dataclass
class SavedJob:
    job: CharacterJob
    pet_sn: int
    image: bytes | None = None
    sheet: bytes = b""
    layout: Layout | None = None
    failure: CharacterFailure | None = None
    item_sheets: dict[int, bytes] = field(default_factory=dict)
    failed_items: set[int] = field(default_factory=set)


class FakeCharacterJobRepository:
    """[캐릭터 작업 가짜 저장소]
    - Java 캐릭터 작업·시트 내부 API 연결 전까지 메모리 기록만 : 판정은 Java 몫
    - 캐릭터 번호는 작업 번호와 같음, petSn이 짝수면 고양이 : 고양이 경로 확인용
    - 연결 시점 : LJS 백엔드 캐릭터 흐름 재설계 뒤 (docs/api/internal.md "Python → Java" 미정 행)
    """

    def __init__(self) -> None:
        self.jobs: dict[int, SavedJob] = {}
        self._next = 1

    async def create_job(self, pet_sn: int) -> CharacterJob:
        job = CharacterJob(self._next, "PETC0002" if pet_sn % 2 == 0 else "PETC0001")
        self._next += 1
        self.jobs[job.chrc_job_sn] = SavedJob(job, pet_sn)
        logger.info("가짜 Java 캐릭터 작업 생성: chrcJobSn=%d", job.chrc_job_sn)
        return job

    async def report_success(
        self, chrc_job_sn: int, image: bytes, sheet: bytes, layout: Layout | None
    ) -> int:
        saved = self.jobs[chrc_job_sn]
        saved.image, saved.sheet, saved.layout = image, sheet, layout
        logger.info("가짜 Java 캐릭터 성공 보고: chrcJobSn=%d, %d바이트", chrc_job_sn, len(image))
        return chrc_job_sn

    async def report_failure(self, chrc_job_sn: int, reason: CharacterFailure) -> None:
        self.jobs[chrc_job_sn].failure = reason
        logger.info("가짜 Java 캐릭터 실패 보고: chrcJobSn=%d, %s", chrc_job_sn, reason)

    async def list_bake_items(self) -> dict[int, str]:
        return dict(_FAKE_ITEM_SNS)

    async def save_item_sheet(self, pixel_char_sn: int, item_sn: int, sheet: bytes) -> None:
        self.jobs[pixel_char_sn].item_sheets[item_sn] = sheet
        logger.info("가짜 Java 착용 시트 저장: %d, itemSn=%d", pixel_char_sn, item_sn)

    async def report_bake_failure(self, pixel_char_sn: int, item_sn: int) -> None:
        self.jobs[pixel_char_sn].failed_items.add(item_sn)
        logger.info("가짜 Java 굽기 실패 보고: %d, itemSn=%d", pixel_char_sn, item_sn)

    async def find_sheets(self, pixel_char_sn: int, item_sns: Iterable[int]) -> CharacterSheets:
        saved = self.jobs.get(pixel_char_sn)
        if saved is None or saved.layout is None:
            raise BackendError(404, _NOT_FOUND, "application/json", [])
        wanted = set(item_sns)
        return CharacterSheets(
            saved.job.pet_se_cd,
            saved.sheet,
            saved.layout,
            {sn: sheet for sn, sheet in saved.item_sheets.items() if sn in wanted},
            frozenset(saved.failed_items & wanted),
        )


_fake = FakeCharacterJobRepository()


def get_character_job_repository() -> CharacterJobRepository:
    return _fake
