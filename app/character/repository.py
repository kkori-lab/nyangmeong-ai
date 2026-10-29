import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.character.schemas import PetSeCd

logger = logging.getLogger(__name__)


class CharacterFailure(StrEnum):
    # 실패 사유. Java 내부 API가 생기면 그쪽 값으로 맞춘다
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


class CharacterJobRepository(Protocol):
    async def create_job(self, pet_sn: int) -> CharacterJob: ...

    async def report_success(self, chrc_job_sn: int, image: bytes) -> None: ...

    async def report_failure(self, chrc_job_sn: int, reason: CharacterFailure) -> None: ...


@dataclass
class SavedJob:
    job: CharacterJob
    pet_sn: int
    image: bytes | None = None
    failure: CharacterFailure | None = None


class FakeCharacterJobRepository:
    """Java 캐릭터 작업 내부 API가 생기기 전의 가짜. 메모리에 기록만 한다

    주양육자 여부·이미 캐릭터 있음·생성 중 판정은 Java가 작업 생성 때 한다.
    연결은 LJS 백엔드 캐릭터 흐름 재설계 뒤(docs/api/internal.md "Python → Java" 미정 행)
    """

    def __init__(self) -> None:
        self.jobs: dict[int, SavedJob] = {}
        self._next = 1

    async def create_job(self, pet_sn: int) -> CharacterJob:
        job = CharacterJob(self._next, "PETC0001")
        self._next += 1
        self.jobs[job.chrc_job_sn] = SavedJob(job, pet_sn)
        logger.info("가짜 Java 캐릭터 작업 생성: chrcJobSn=%d", job.chrc_job_sn)
        return job

    async def report_success(self, chrc_job_sn: int, image: bytes) -> None:
        self.jobs[chrc_job_sn].image = image
        logger.info("가짜 Java 캐릭터 성공 보고: chrcJobSn=%d, %d바이트", chrc_job_sn, len(image))

    async def report_failure(self, chrc_job_sn: int, reason: CharacterFailure) -> None:
        self.jobs[chrc_job_sn].failure = reason
        logger.info("가짜 Java 캐릭터 실패 보고: chrcJobSn=%d, %s", chrc_job_sn, reason)


_fake = FakeCharacterJobRepository()


def get_character_job_repository() -> CharacterJobRepository:
    return _fake
