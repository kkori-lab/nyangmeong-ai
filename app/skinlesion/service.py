import asyncio

from app.core.backend import external_error
from app.core.image import to_jpeg, validate_upload
from app.core.response import AppError
from app.skinlesion import rules
from app.skinlesion.clients import SkinJudge, SkinJudgeApiError
from app.skinlesion.schemas import SkinAnalysisResponse, SkinFinding


async def analyze_skin(
    judge: SkinJudge | None, image: bytes, file_name: str, timeout_sec: float
) -> SkinAnalysisResponse:
    # 업로드 검증 먼저 (검증 실패 시 LLM 미호출)
    validate_upload(image, file_name)
    jpeg = to_jpeg(image, rules.IMAGE_LONG_EDGE)
    if judge is None:
        raise external_error()
    table = rules.load_table()
    try:
        judgement = await asyncio.wait_for(judge.judge(jpeg, table.choices()), timeout=timeout_sec)
    except TimeoutError:
        raise AppError("SKIN_ANALYZE_TIMEOUT", 504, "피부 분석 시간이 초과되었습니다.") from None
    except SkinJudgeApiError:
        raise AppError("SKIN_ANALYZE_API_ERROR", 502, "피부 분석 중 오류가 발생했습니다.") from None
    if judgement is None:
        result = rules.evaluate(None, [], table)
    else:
        findings = [(f.lesion, f.cnfdnc) for f in judgement.findings]
        result = rules.evaluate(judgement.pet_skin, findings, table)
    return SkinAnalysisResponse(
        rslt=result.rslt,
        grade=result.grade,
        findings=[
            SkinFinding(lesion_cd=lesion.key, lesion_nm=lesion.name, cnfdnc=cnfdnc)
            for lesion, cnfdnc in result.findings
        ],
        guide=list(result.guide),
        notice=table.notice,
        rule_version=table.rule_version,
    )
