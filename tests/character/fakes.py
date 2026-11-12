import base64
import io
import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from app.character.canvas import Layout
from app.character.engine import BakeItem
from app.character.repository import (
    BakeTargetPage,
    CharacterFailure,
    CharacterJob,
    CharacterSheets,
)
from app.core.backend import BackendError

logger = logging.getLogger(__name__)

# Java ITEM 굽기 지시 시드 원본 (docs/design/item-bake-hints.json)
SEED = Path(__file__).resolve().parents[2] / "docs" / "design" / "item-bake-hints.json"
_NOT_FOUND = b'{"code":"PIXEL_CHARACTER_NOT_FOUND"}'
# Java bake-targets 한 페이지 크기
BAKE_TARGET_PAGE_SIZE = 100
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


def seed_rows() -> list[dict]:
    return json.loads(SEED.read_text(encoding="utf-8"))


def fake_items() -> dict[int, BakeItem]:
    """가짜 Java bake-items 응답 : 시드 26개에 가짜 ITEM_SN"""
    rows = {row["id"]: row for row in seed_rows()}
    return {
        sn: BakeItem(sn, rows[key]["regn_cd"], rows[key]["bake_hint"])
        for sn, key in _FAKE_ITEM_SNS.items()
    }


def fake_item(key: str) -> BakeItem:
    """시드 id로 가짜 아이템 찾기"""
    sn = next(sn for sn, name in _FAKE_ITEM_SNS.items() if name == key)
    return fake_items()[sn]


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
    equipped_item_sns: list[int] | None = None
    equipped_image: bytes | None = None


class FakeCharacterJobRepository:
    """[캐릭터 작업 가짜 저장소]
    - 메모리 기록만 : 판정은 Java 몫
    - 캐릭터 번호는 작업 번호와 같음, petSn이 짝수면 고양이 : 고양이 경로 확인용
    """

    def __init__(self) -> None:
        self.jobs: dict[int, SavedJob] = {}
        self._next = 1
        # 대표 이미지 저장 때 Java 4xx 흉내 (예: 409 EQUIPPED_ITEMS_CHANGED)
        self.equip_error: BackendError | None = None
        # 가짜 Java item-files : bakeImageFileSn -> 아이템 그림
        self.item_images: dict[int, bytes] = {}

    async def create_job(self, pet_sn: int) -> CharacterJob:
        job = CharacterJob(self._next, "PETC0002" if pet_sn % 2 == 0 else "PETC0001")
        self._next += 1
        self.jobs[job.char_crt_job_sn] = SavedJob(job, pet_sn)
        logger.info("가짜 Java 캐릭터 작업 생성: charCrtJobSn=%d", job.char_crt_job_sn)
        return job

    async def report_success(
        self, char_crt_job_sn: int, image: bytes, sheet: bytes, layout: Layout | None
    ) -> int:
        saved = self.jobs[char_crt_job_sn]
        saved.image, saved.sheet, saved.layout = image, sheet, layout
        logger.info(
            "가짜 Java 캐릭터 성공 보고: charCrtJobSn=%d, %d바이트", char_crt_job_sn, len(image)
        )
        return char_crt_job_sn

    async def report_failure(self, char_crt_job_sn: int, reason: CharacterFailure) -> None:
        self.jobs[char_crt_job_sn].failure = reason
        logger.info("가짜 Java 캐릭터 실패 보고: charCrtJobSn=%d, %s", char_crt_job_sn, reason)

    async def list_bake_items(self) -> dict[int, BakeItem]:
        return fake_items()

    async def fetch_item_image(self, atch_file_sn: int) -> bytes:
        image = self.item_images.get(atch_file_sn)
        if image is None:
            raise BackendError(404, b'{"code":"FILE_NOT_FOUND"}', "application/json", [])
        return image

    async def list_bake_targets(self, item_sn: int) -> BakeTargetPage:
        # 맨몸 시트가 있고 그 아이템을 굽지도 실패하지도 않은 캐릭터의 첫 페이지
        found = [
            sn
            for sn, saved in sorted(self.jobs.items())
            if saved.layout is not None
            and item_sn not in saved.item_sheets
            and item_sn not in saved.failed_items
        ]
        return BakeTargetPage(
            pixelCharSns=found[:BAKE_TARGET_PAGE_SIZE],
            last=len(found) <= BAKE_TARGET_PAGE_SIZE,
        )

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

    async def save_equipped_image(
        self, pixel_char_sn: int, item_sns: Sequence[int], image: bytes
    ) -> None:
        if self.equip_error is not None:
            raise self.equip_error
        saved = self.jobs[pixel_char_sn]
        saved.equipped_item_sns, saved.equipped_image = list(item_sns), image
        logger.info("가짜 Java 대표 이미지 저장: %d, %d바이트", pixel_char_sn, len(image))


def magenta_drawing(size: int = 1024, item: bool = True) -> bytes:
    """가짜 이미지 생성 답 : 마젠타 바탕에 빨간 테(안쪽은 바탕색 구멍)와 작은 얼룩"""
    image = Image.new("RGB", (size, size), (255, 0, 255))
    if item:
        image.paste((200, 30, 30), (300, 400, 700, 600))
        image.paste((255, 0, 255), (350, 450, 650, 550))
        image.paste((10, 10, 10), (20, 20, 22, 22))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


class FakeImagesOpenAI:
    """OpenAI images.edit 가짜 : 호출 기록, 정해 둔 그림(b64) 또는 예외"""

    def __init__(self, answer: bytes | Exception) -> None:
        self.answer = answer
        self.calls: list[dict] = []
        self.images = SimpleNamespace(edit=self._edit)

    def _edit(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.answer, Exception):
            raise self.answer
        data = SimpleNamespace(b64_json=base64.b64encode(self.answer).decode())
        return SimpleNamespace(data=[data])
