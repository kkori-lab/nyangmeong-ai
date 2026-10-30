import asyncio

from app.checkup import rules
from app.checkup.clients import LabResultClient, PdfAnalyzeApiError
from app.checkup.schemas import LabResultAnalyzeResponse
from app.core.backend import external_error
from app.core.response import AppError


async def analyze_lab_result(
    client: LabResultClient | None, pdf: bytes, file_name: str, timeout_sec: float
) -> LabResultAnalyzeResponse:
    # FN-HLT-005-04 : 업로드 검증이 먼저. 검증 실패는 LLM을 부르지 않는다
    rules.validate_pdf(pdf, file_name)
    if client is None:
        raise external_error()
    # 시간 초과·API 오류 구분. 실패하면 React가 SCR-HLT-005에서 사유를 안내한다
    try:
        output = await asyncio.wait_for(client.read(pdf), timeout=timeout_sec)
    except TimeoutError:
        raise AppError("PDF_ANALYZE_TIMEOUT", 504, "PDF 분석 시간이 초과되었습니다.") from None
    except PdfAnalyzeApiError:
        raise AppError("PDF_ANALYZE_API_ERROR", 502, "PDF 분석 중 오류가 발생했습니다.") from None
    if not output.is_lab_result:
        raise AppError("NOT_LAB_RESULT", 422, "검사결과지로 읽을 수 없는 PDF입니다.")
    # FN-HLT-007-04 : 인식 0건은 오류가 아닌 빈 목록(사용자가 직접 입력)
    items = [
        item
        for row in output.rows
        if (
            item := rules.to_item(
                row.name, row.value, row.unit, row.ref_min, row.ref_max, row.blood
            )
        )
    ]
    return LabResultAnalyzeResponse(items=items)
