import io

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.response import AppError

# 업로드 제약(REQ-NFR-003) : 영수증(FN-AIM-008-05)·캐릭터 사진(FN-MYP-010-08)
MAX_IMAGE_BYTES = 10 * 1024 * 1024
EXTENSION_TYPES = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}


def detect_image_type(data: bytes) -> str | None:
    """파일 시그니처 기준 jpg·png·webp 판별 (해당 없으면 None)"""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def validate_upload(image: bytes, file_name: str | None) -> None:
    """확장자 + 실제 형식 검증, 10MB 이하 (PDF 불가)"""
    if len(image) > MAX_IMAGE_BYTES:
        raise AppError("FILE_SIZE_EXCEEDED", 400, "파일 용량은 10MB 이하여야 합니다.")
    _, dot, extension = (file_name or "").rpartition(".")
    expected = EXTENSION_TYPES.get(extension.lower()) if dot else None
    if expected is None or detect_image_type(image) != expected:
        raise AppError("FILE_TYPE_NOT_ALLOWED", 400, "jpg·jpeg·png·webp 이미지만 올릴 수 있습니다.")


def to_jpeg(image: bytes, long_edge: int, quality: int = 85) -> bytes:
    """EXIF 회전 반영 후 긴 변 long_edge 이하 RGB JPEG (열 수 없으면 400)"""
    try:
        with Image.open(io.BytesIO(image)) as opened:
            flat = ImageOps.exif_transpose(opened).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as error:
        # 시그니처만 맞고 열 수 없는 파일
        raise AppError(
            "FILE_TYPE_NOT_ALLOWED", 400, "jpg·jpeg·png·webp 이미지만 올릴 수 있습니다."
        ) from error
    flat.thumbnail((long_edge, long_edge), Image.LANCZOS)
    out = io.BytesIO()
    flat.save(out, "JPEG", quality=quality)
    return out.getvalue()
