import asyncio
import logging
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

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
BAKE_CONCURRENCY = 13
BAKE_ATTEMPTS = 2
# 전체 굽기 한 번 호출의 캐릭터 수 : 한 번 굽는 시간 안에 끝나 쿠키(30분) 만료 밖
BAKE_BATCH = BAKE_CONCURRENCY

# 굽기 결과 : 시트 저장·실패 표시, None은 둘 다 못 함 (Java 목록에 남음)
BakeOutcome = Literal["baked", "failed"] | None


@dataclass(frozen=True)
class BakeTask:
    client: CharacterClient
    repo: CharacterJobRepository
    pixel_char_sn: int
    item_sn: int
    item: engine.BakeItem
    # 전체 굽기 : 없으면 꺼낼 때 Java에서 받음 (캐릭터 수만큼 메모리에 올리지 않음)
    sheet: bytes | None
    pet_se_cd: PetSeCd | None

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
        # 결과를 기다리는 호출 : 같은 키가 굽는 중이면 그 결과를 함께 받음
        self._waiters: dict[tuple[int, int], list[asyncio.Future[BakeOutcome]]] = {}
        self._drains: set[asyncio.Task[None]] = set()

    def add(self, task: BakeTask) -> None:
        if task.key not in self._running and all(t.key != task.key for t in self._tasks):
            self._tasks.append(task)

    def put_first(self, task: BakeTask) -> None:
        if task.key in self._running:
            return
        self._tasks = deque(t for t in self._tasks if t.key != task.key)
        self._tasks.appendleft(task)

    async def run(self, tasks: Sequence[BakeTask]) -> list[BakeOutcome]:
        """큐 뒤에 넣고 끝날 때까지 기다림 -> 작업별 결과"""
        loop = asyncio.get_running_loop()
        waits: list[asyncio.Future[BakeOutcome]] = []
        for task in tasks:
            self.add(task)
            future: asyncio.Future[BakeOutcome] = loop.create_future()
            self._waiters.setdefault(task.key, []).append(future)
            waits.append(future)
        drain = asyncio.create_task(self.drain())
        self._drains.add(drain)
        drain.add_done_callback(self._drains.discard)
        return list(await asyncio.gather(*waits))

    async def drain(self) -> None:
        idle = BAKE_CONCURRENCY - self._workers
        await asyncio.gather(*(self._work() for _ in range(idle)))

    async def _work(self) -> None:
        self._workers += 1
        try:
            while self._tasks:
                task = self._tasks.popleft()
                self._running.add(task.key)
                outcome: BakeOutcome = None
                try:
                    outcome = await _bake_one(task)
                except Exception:
                    logger.exception("굽기 실패: %d, itemSn=%d", task.pixel_char_sn, task.item_sn)
                finally:
                    self._running.discard(task.key)
                    self._notify(task.key, outcome)
        finally:
            self._workers -= 1

    def _notify(self, key: tuple[int, int], outcome: BakeOutcome) -> None:
        for future in self._waiters.pop(key, []):
            # 요청이 끊겨 취소된 대기는 건너뜀
            if not future.done():
                future.set_result(outcome)


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
            job.char_crt_job_sn, character.image, character.sheet, character.layout
        )
    except Exception:
        # 보고 실패로 멈춘 작업은 Java가 타임아웃으로 정리
        logger.exception("캐릭터 성공 보고 실패: charCrtJobSn=%d", job.char_crt_job_sn)
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
    targets = await repo.list_bake_items()
    return [
        BakeTask(client, repo, pixel_char_sn, item_sn, item, sheet, pet_se_cd)
        for item_sn, item in targets.items()
    ]


async def _bake_one(task: BakeTask) -> BakeOutcome:
    # 저장 실패는 다시 굽지 않음 : 이미 낸 비용
    if task.sheet is None or task.pet_se_cd is None:
        try:
            found = await task.repo.find_sheets(task.pixel_char_sn, [])
        except Exception:
            logger.exception("굽기용 맨몸 시트 조회 실패: %d", task.pixel_char_sn)
            return None
        task = replace(task, sheet=found.sheet, pet_se_cd=found.pet_se_cd)
    started = time.perf_counter()
    worn, attempts = await _draw(task)
    seconds = time.perf_counter() - started
    logger.info(
        "굽기 시간: pixelCharSn=%d, itemSn=%d, %.1f초, %d회 시도, %s",
        task.pixel_char_sn,
        task.item_sn,
        seconds,
        attempts,
        "실패" if worn is None else "성공",
    )
    try:
        if worn is None:
            await task.repo.report_bake_failure(task.pixel_char_sn, task.item_sn)
            return "failed"
        await task.repo.save_item_sheet(task.pixel_char_sn, task.item_sn, worn)
        return "baked"
    except Exception:
        logger.exception("굽기 결과 보고 실패: %d, itemSn=%d", task.pixel_char_sn, task.item_sn)
        return None


async def _draw(task: BakeTask) -> tuple[bytes | None, int]:
    sheet, pet_se_cd = task.sheet, task.pet_se_cd
    if sheet is None or pet_se_cd is None:
        return None, 0
    for attempt in range(1, BAKE_ATTEMPTS + 1):
        try:
            return await _bake_once(task.client, sheet, pet_se_cd, task.item), attempt
        except Exception as exc:
            # 큐 일꾼 유지 : 한 아이템 실패가 나머지 굽기를 막지 않게
            logger.warning("굽기 시도 실패: itemSn=%d, %s", task.item_sn, type(exc).__name__)
    return None, BAKE_ATTEMPTS


async def _bake_once(
    client: CharacterClient, sheet: bytes, pet_se_cd: PetSeCd, item: engine.BakeItem
) -> bytes:
    source = await asyncio.to_thread(bake.bake_source, sheet, item.regn_cd)
    worn = await client.bake(source, pet_se_cd, item)
    await asyncio.to_thread(bake.validate, sheet, worn, item.regn_cd)
    return worn


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
    chosen = _chosen_items(item_sns, targets)
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


async def save_equipped_image(
    client: CharacterClient | None,
    repo: CharacterJobRepository,
    queue: BakeQueue,
    pixel_char_sn: int,
    item_sns: Sequence[int],
    bake_enabled: bool,
) -> bool:
    """FN-MYP-010-16·13 : [장착] 확정 뒤 착용 모습을 Java에 저장, 안 구운 아이템이 있으면 False"""
    image = await preview(client, repo, queue, pixel_char_sn, item_sns, bake_enabled)
    if image is None:
        return False
    await repo.save_equipped_image(pixel_char_sn, item_sns, image)
    return True


def _chosen_items(
    item_sns: Sequence[int], targets: dict[int, engine.BakeItem]
) -> dict[int, engine.BakeItem]:
    invalid = AppError("INVALID_REQUEST", 400, "입혀 볼 수 없는 아이템입니다.")
    chosen: dict[int, engine.BakeItem] = {}
    for item_sn in item_sns:
        item = targets.get(item_sn)
        if item is None:
            raise invalid
        chosen[item_sn] = item
    # FN-MYP-010-13 : 한 부위에 하나
    regions = [item.regn_cd for item in chosen.values()]
    if len(chosen) != len(item_sns) or len(regions) != len(set(regions)):
        raise invalid
    return chosen


async def _render(
    found: CharacterSheets,
    chosen: dict[int, engine.BakeItem],
    sheets: dict[int, bytes] | None = None,
) -> bytes:
    sheets = found.sheets if sheets is None else sheets
    worn = {chosen[sn].regn_cd: sheets[sn] for sn in chosen}
    try:
        return await asyncio.to_thread(compose.render, found.sheet, found.layout, worn)
    except Exception as exc:
        logger.error("캐릭터 합성 실패: %s", type(exc).__name__)
        raise _preview_error() from exc


async def describe_item(
    client: CharacterClient | None, image: bytes, file_name: str, regn_cd: str, item_nm: str
) -> str:
    """FN-ADM-070-02 : 관리자 아이템 그림 -> 굽기 지시 초안 (저장 안 함)"""
    _check_region(regn_cd)
    validate_upload(image, file_name)
    if client is None:
        logger.error("굽기 지시 초안 불가: 생성기가 아직 연결되지 않았습니다")
        raise external_error()
    try:
        return await client.describe_item(image, regn_cd, item_nm)
    except CharacterApiError:
        raise external_error() from None


async def draw_item(
    client: CharacterClient | None, image: bytes, file_name: str, regn_cd: str, item_nm: str
) -> bytes:
    """FN-ADM-070-02 : 실사 아이템 사진 -> 투명 배경 픽셀 아이템 그림 (상점 이미지, 저장 안 함)"""
    _check_region(regn_cd)
    validate_upload(image, file_name)
    if client is None:
        logger.error("픽셀 아이템 그림 불가: 생성기가 아직 연결되지 않았습니다")
        raise external_error()
    try:
        drawn = await client.draw_item(image, regn_cd, item_nm)
    except CharacterApiError:
        raise _item_image_error() from None
    try:
        return engine.cut_item(drawn)
    except (engine.ItemImageError, OSError, ValueError) as error:
        # OSError : PIL이 그림으로 못 읽음 (UnidentifiedImageError 포함)
        logger.error("픽셀 아이템 그림 후처리 실패: %s", type(error).__name__)
        raise _item_image_error() from None


async def trial_preview(
    client: CharacterClient | None,
    repo: CharacterJobRepository,
    pixel_char_sn: int,
    regn_cd: str,
    bake_hint: str,
) -> bytes:
    """FN-ADM-070-02 : 굽기 지시 1회 시험 굽기·합성 (저장 안 함, 굽기 설정과 무관)"""
    _check_region(regn_cd)
    if client is None:
        logger.error("시험 굽기 불가: 생성기가 아직 연결되지 않았습니다")
        raise external_error()
    found = await repo.find_sheets(pixel_char_sn, [])
    item = engine.BakeItem(0, regn_cd, bake_hint)
    try:
        worn = await _bake_once(client, found.sheet, found.pet_se_cd, item)
    except Exception as exc:
        logger.error("시험 굽기 실패: %s", type(exc).__name__)
        raise _preview_error() from exc
    return await _render(found, {item.item_sn: item}, {item.item_sn: worn})


@dataclass(frozen=True)
class ItemBakeResult:
    baked_cnt: int
    failed_cnt: int
    last: bool


async def bake_item_batch(
    client: CharacterClient | None,
    repo: CharacterJobRepository,
    queue: BakeQueue,
    item_sn: int,
    bake_enabled: bool,
) -> ItemBakeResult:
    """FN-ADM-070-02 : 안 구운 캐릭터 한 묶음을 관리자 쿠키로 굽고 기다림 -> 결과 수

    - 구웠거나 실패 표시한 캐릭터는 Java 목록에서 빠짐 : 매번 첫 페이지만 읽음
    - 관리자 프론트가 last가 될 때까지 다시 부름 : 요청마다 새 쿠키
    """
    if not bake_enabled:
        raise AppError("BAKE_DISABLED", 409, "아이템 굽기가 꺼져 있습니다.")
    if client is None:
        logger.error("전체 굽기 불가: 생성기가 아직 연결되지 않았습니다")
        raise external_error()
    item = (await repo.list_bake_items()).get(item_sn)
    if item is None:
        raise AppError("INVALID_REQUEST", 400, "구울 수 없는 아이템입니다.")
    page = await repo.list_bake_targets(item_sn)
    candidates = list(dict.fromkeys(page.pixel_char_sns))
    targets = candidates[:BAKE_BATCH]
    # 회원 미리보기(put_first)가 앞서도록 뒤에 추가
    outcomes = await queue.run(
        [BakeTask(client, repo, sn, item_sn, item, None, None) for sn in targets]
    )
    baked, failed = outcomes.count("baked"), outcomes.count("failed")
    logger.info(
        "전체 굽기 묶음: itemSn=%d, 대상 %d개, 저장 %d, 실패 표시 %d",
        item_sn,
        len(targets),
        baked,
        failed,
    )
    if targets and baked + failed == 0:
        # 하나도 줄지 않음 : 다시 불러도 같은 대상이라 반복을 멈춤
        logger.error("전체 굽기 묶음이 하나도 처리되지 않았습니다: itemSn=%d", item_sn)
        raise external_error()
    done = baked + failed == len(targets)
    last = page.last and len(candidates) <= BAKE_BATCH and done
    return ItemBakeResult(baked, failed, last)


def _check_region(regn_cd: str) -> None:
    if regn_cd not in engine.BAKE_REGIONS:
        raise AppError("INVALID_REQUEST", 400, "구울 수 없는 부위입니다.")


def _item_image_error() -> AppError:
    return AppError("CHARACTER_API_ERROR", 502, "픽셀 아이템 그림을 만들지 못했습니다.")


def _preview_error() -> AppError:
    return AppError("CHARACTER_API_ERROR", 502, "캐릭터 미리보기를 만들지 못했습니다.")


async def _report_failure(
    repo: CharacterJobRepository, job: CharacterJob, reason: CharacterFailure
) -> None:
    try:
        await repo.report_failure(job.char_crt_job_sn, reason)
    except Exception:
        logger.exception("캐릭터 실패 보고 실패: charCrtJobSn=%d, %s", job.char_crt_job_sn, reason)
