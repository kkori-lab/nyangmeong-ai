import logging

from app.character.clients import CharacterApiError, CharacterClient, CharacterRequest
from app.character.repository import CharacterFailure, CharacterJob, CharacterJobRepository
from app.character.rules import matches_spec
from app.core.backend import external_error
from app.core.image import validate_upload

logger = logging.getLogger(__name__)


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
    client: CharacterClient, repo: CharacterJobRepository, job: CharacterJob, photo: bytes
) -> None:
    """FN-MYP-010-09 : 응답 뒤 백그라운드 생성, 결과·상태 Java 보고"""
    request = CharacterRequest(photo, job.pet_se_cd, job.vrty_nm, job.colr_nm, job.chrc_cn)
    try:
        image = await client.generate(request)
    except CharacterApiError:
        await _report_failure(repo, job, CharacterFailure.API_ERROR)
        return
    # FN-MYP-010-17·18 : 규격 밖 결과 저장 제외
    if not matches_spec(image):
        await _report_failure(repo, job, CharacterFailure.SPEC_MISMATCH)
        return
    try:
        await repo.report_success(job.chrc_job_sn, image)
    except Exception:
        # 보고 실패로 멈춘 작업은 Java가 타임아웃으로 정리
        logger.exception("캐릭터 성공 보고 실패: chrcJobSn=%d", job.chrc_job_sn)


async def _report_failure(
    repo: CharacterJobRepository, job: CharacterJob, reason: CharacterFailure
) -> None:
    try:
        await repo.report_failure(job.chrc_job_sn, reason)
    except Exception:
        logger.exception("캐릭터 실패 보고 실패: chrcJobSn=%d, %s", job.chrc_job_sn, reason)
