import asyncio

from app.checkup import rules
from app.checkup.clients import LabResultClient, PdfAnalyzeApiError
from app.checkup.schemas import LabResultAnalyzeResponse, LabResultItem
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
    # FN-HLT-007-05 : 혈액검사가 아닌 항목은 items에서 빼고 이름만 안내용으로
    items: list[LabResultItem] = []
    excluded: list[str] = []
    for row in output.rows:
        if not row.name or not row.name.strip():
            continue
        if not rules.is_blood(row.name, row.blood):
            excluded.append(row.name.strip())
            continue
        item = rules.to_item(row.name, row.value, row.unit, row.ref_min, row.ref_max)
        if item:
            items.append(item)
    return LabResultAnalyzeResponse(items=items, excluded_artcl_nms=excluded)
