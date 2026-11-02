import asyncio
import logging
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass

from app.character import bake, compose, engine
from app.character.clients import CharacterApiError, CharacterClient, CharacterRequest
from app.character.repository import (
    CharacterFailure,
    CharacterJob,
    CharacterJobRepository,
    CharacterSheets,
)
from app.character.rules import matches_spec
from app.character.schemas import PetSeCd
from app.core.backend import external_error
from app.core.image import validate_upload
from app.core.response import AppError

logger = logging.getLogger(__name__)

# OpenAI 동시 호출 상한
BAKE_CONCURRENCY = 10
BAKE_ATTEMPTS = 2


@dataclass(frozen=True)
class BakeTask:
    client: CharacterClient
    repo: CharacterJobRepository
    pixel_char_sn: int
    item_sn: int
    item: engine.BakeItem
    sheet: bytes
    pet_se_cd: PetSeCd

    @property
    def key(self) -> tuple[int, int]:
        return self.pixel_char_sn, self.item_sn


class BakeQueue:
    """[굽기 큐]
    - 프로세스 메모리 : 재시작하면 사라지고 워커 1개 전제
    - 이미 굽는 아이템은 다시 넣지 않음 : 같은 아이템 이중 과금 방지
    """

    def __init__(self) -> None:
        self._tasks: deque[BakeTask] = deque()
        self._running: set[tuple[int, int]] = set()
        self._workers = 0

    def add(self, task: BakeTask) -> None:
        if task.key not in self._running and all(t.key != task.key for t in self._tasks):
            self._tasks.append(task)

    def put_first(self, task: BakeTask) -> None:
        if task.key in self._running:
            return
        self._tasks = deque(t for t in self._tasks if t.key != task.key)
        self._tasks.appendleft(task)

    async def drain(self) -> None:
        idle = BAKE_CONCURRENCY - self._workers
        await asyncio.gather(*(self._work() for _ in range(idle)))

    async def _work(self) -> None:
        self._workers += 1
        try:
            while self._tasks:
                task = self._tasks.popleft()
                self._running.add(task.key)
                try:
                    await _bake_one(task)
                finally:
                    self._running.discard(task.key)
        finally:
            self._workers -= 1


_queue = BakeQueue()


def get_bake_queue() -> BakeQueue:
    return _queue


async def create_job(
    client: CharacterClient | None,
    repo: CharacterJobRepository,
    photo: bytes,
    file_name: str,
    pet_sn: int,
) -> CharacterJob:
    """FN-MYP-010-08 : 검증 실패·생성기 없음이면 Java 작업 미생성"""
    validate_upload(photo, file_name)
    if client is None:
        logger.error("캐릭터 생성 불가: 생성기가 아직 연결되지 않았습니다")
        raise external_error()
    # 주양육자 여부·이미 캐릭터 있음·생성 중 판정은 Java (4xx 그대로 전달)
    return await repo.create_job(pet_sn)


async def generate_and_report(
    client: CharacterClient,
    repo: CharacterJobRepository,
    queue: BakeQueue,
    job: CharacterJob,
    photo: bytes,
    bake_enabled: bool,
) -> None:
    """FN-MYP-010-09 : 응답 뒤 백그라운드 생성, 결과·상태 Java 보고, 켜져 있으면 이어서 굽기"""
    request = CharacterRequest(photo, job.pet_se_cd, job.vrty_nm, job.colr_nm, job.chrc_cn)
    try:
        character = await client.generate(request)
    except CharacterApiError:
        await _report_failure(repo, job, CharacterFailure.API_ERROR)
        return
    # FN-MYP-010-17·18 : 규격 밖 결과 저장 제외
    if not matches_spec(character.image):
        await _report_failure(repo, job, CharacterFailure.SPEC_MISMATCH)
        return
    try:
        pixel_char_sn = await repo.report_success(
            job.chrc_job_sn, character.image, character.sheet, character.layout
        )
    except Exception:
        # 보고 실패로 멈춘 작업은 Java가 타임아웃으로 정리
        logger.exception("캐릭터 성공 보고 실패: chrcJobSn=%d", job.chrc_job_sn)
        return
    if not bake_enabled:
        return
    # FN-MYP-011-01 : 사자마자 입도록 전 아이템 미리 굽기
    try:
        for task in await _tasks(client, repo, pixel_char_sn, character.sheet, job.pet_se_cd):
            queue.add(task)
    except Exception:
        logger.exception("굽기 대상 조회 실패: pixelCharSn=%d", pixel_char_sn)
        return
    started = time.perf_counter()
    await queue.drain()
    seconds = time.perf_counter() - started
    logger.info("전체 굽기 시간: pixelCharSn=%d, %.1f초", pixel_char_sn, seconds)


async def _tasks(
    client: CharacterClient,
    repo: CharacterJobRepository,
    pixel_char_sn: int,
    sheet: bytes,
    pet_se_cd: PetSeCd,
) -> list[BakeTask]:
    items = engine.load_items()
    targets = await repo.list_bake_items()
    return [
        BakeTask(client, repo, pixel_char_sn, item_sn, items[item_id], sheet, pet_se_cd)
        for item_sn, item_id in targets.items()
        if item_id in items
    ]


async def _bake_one(task: BakeTask) -> None:
    # 저장 실패는 다시 굽지 않음 : 이미 낸 비용
    started = time.perf_counter()
    worn, attempts = await _draw(task)
    seconds = time.perf_counter() - started
    logger.info(
        "굽기 시간: %s, %.1f초, %d회 시도, %s",
        task.item.item_id,
        seconds,
        attempts,
        "실패" if worn is None else "성공",
    )
    try:
        if worn is None:
            await task.repo.report_bake_failure(task.pixel_char_sn, task.item_sn)
        else:
            await task.repo.save_item_sheet(task.pixel_char_sn, task.item_sn, worn)
    except Exception:
        logger.exception("굽기 결과 보고 실패: %d, itemSn=%d", task.pixel_char_sn, task.item_sn)


async def _draw(task: BakeTask) -> tuple[bytes | None, int]:
    for attempt in range(1, BAKE_ATTEMPTS + 1):
        try:
            source = await asyncio.to_thread(bake.bake_source, task.sheet, task.item.regn_cd)
            worn = await task.client.bake(source, task.pet_se_cd, task.item)
            await asyncio.to_thread(bake.validate, task.sheet, worn, task.item.regn_cd)
            return worn, attempt
        except Exception as exc:
            # 큐 일꾼 유지 : 한 아이템 실패가 나머지 굽기를 막지 않게
            logger.warning("굽기 시도 실패: %s, %s", task.item.item_id, type(exc).__name__)
    return None, BAKE_ATTEMPTS


async def preview(
    client: CharacterClient | None,
    repo: CharacterJobRepository,
    queue: BakeQueue,
    pixel_char_sn: int,
    item_sns: Sequence[int],
    bake_enabled: bool,
) -> bytes | None:
    """FN-MYP-011-01·FN-MYP-010-13 : 합성 PNG, 아직 안 구운 아이템이 있으면 None"""
    targets = await repo.list_bake_items()
    items = engine.load_items()
    chosen = _chosen_items(item_sns, targets, items)
    found = await repo.find_sheets(pixel_char_sn, item_sns)
    if found.failed:
        logger.warning("굽기 실패 아이템 미리보기: pixelCharSn=%d", pixel_char_sn)
        raise _preview_error()
    missing = [sn for sn in item_sns if sn not in found.sheets]
    if missing:
        if bake_enabled:
            if client is None:
                logger.error("미리보기 불가: 생성기가 아직 연결되지 않았습니다")
                raise external_error()
            for sn in reversed(missing):
                queue.put_first(
                    BakeTask(
                        client, repo, pixel_char_sn, sn, chosen[sn], found.sheet, found.pet_se_cd
                    )
                )
        return None
    return await _render(found, chosen)


def _chosen_items(
    item_sns: Sequence[int], targets: dict[int, str], items: dict[str, engine.BakeItem]
) -> dict[int, engine.BakeItem]:
    invalid = AppError("INVALID_REQUEST", 400, "입혀 볼 수 없는 아이템입니다.")
    chosen: dict[int, engine.BakeItem] = {}
    for item_sn in item_sns:
        item = items.get(targets.get(item_sn, ""))
        if item is None:
            raise invalid
        chosen[item_sn] = item
    # FN-MYP-010-13 : 한 부위에 하나
    regions = [item.regn_cd for item in chosen.values()]
    if len(chosen) != len(item_sns) or len(regions) != len(set(regions)):
        raise invalid
    return chosen


async def _render(found: CharacterSheets, chosen: dict[int, engine.BakeItem]) -> bytes:
    worn = {chosen[sn].regn_cd: found.sheets[sn] for sn in chosen}
    try:
        return await asyncio.to_thread(compose.render, found.sheet, found.layout, worn)
    except Exception as exc:
        logger.error("캐릭터 합성 실패: %s", type(exc).__name__)
        raise _preview_error() from exc


def _preview_error() -> AppError:
    return AppError("CHARACTER_API_ERROR", 502, "캐릭터 미리보기를 만들지 못했습니다.")


async def _report_failure(
    repo: CharacterJobRepository, job: CharacterJob, reason: CharacterFailure
) -> None:
    try:
        await repo.report_failure(job.chrc_job_sn, reason)
    except Exception:
        logger.exception("캐릭터 실패 보고 실패: chrcJobSn=%d, %s", job.chrc_job_sn, reason)
