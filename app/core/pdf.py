from app.core.response import AppError

# 검사결과지 PDF 업로드 규칙 : 검진상세 [PDF 분석](checkup)과 대화창 첨부(chat)가 같이 쓴다
MAX_PDF_BYTES = 10 * 1024 * 1024
PDF_SIGNATURE = b"%PDF-"


def is_pdf_name(file_name: str | None) -> bool:
    """확장자가 .pdf인지 (대화창 첨부가 PDF 흐름인지 가름)"""
    _, dot, extension = (file_name or "").rpartition(".")
    return bool(dot) and extension.lower() == "pdf"


def validate_pdf(data: bytes, file_name: str | None) -> None:
    """FN-HLT-005-04 : 확장자 .pdf + 실제 형식(%PDF-) 검증, 10MB 이하 (REQ-NFR-003)"""
    if len(data) > MAX_PDF_BYTES:
        raise AppError("FILE_SIZE_EXCEEDED", 400, "파일 용량은 10MB 이하여야 합니다.")
    if not is_pdf_name(file_name) or not data.startswith(PDF_SIGNATURE):
        raise AppError("FILE_TYPE_NOT_ALLOWED", 400, "검사결과지 PDF만 분석할 수 있습니다.")
