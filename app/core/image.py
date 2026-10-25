def detect_image_type(data: bytes) -> str | None:
    """파일 시그니처 기준 jpg·png·webp 판별 (해당 없으면 None)"""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None
