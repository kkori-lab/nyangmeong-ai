import io

import pytest
from PIL import Image

from app.core.image import to_jpeg
from app.core.response import AppError


def image_bytes(size: tuple[int, int], fmt: str = "PNG", exif_rotate: bool = False) -> bytes:
    img = Image.new("RGB", size, (10, 20, 30))
    out = io.BytesIO()
    if exif_rotate:
        exif = Image.Exif()
        exif[0x0112] = 6  # 90도 돌려 보기
        img.save(out, fmt, exif=exif)
    else:
        img.save(out, fmt)
    return out.getvalue()


def size_of(jpeg: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(jpeg)) as opened:
        assert opened.format == "JPEG"
        return opened.size


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ((2048, 1024), (1024, 512)),
        ((600, 3000), (205, 1024)),
        ((800, 600), (800, 600)),  # 작으면 그대로
    ],
)
def test_to_jpeg_긴_변을_줄인다(size, expected):
    assert size_of(to_jpeg(image_bytes(size), 1024)) == expected


def test_to_jpeg_EXIF_회전을_반영한다():
    assert size_of(to_jpeg(image_bytes((400, 200), "JPEG", exif_rotate=True), 1024)) == (200, 400)


def test_to_jpeg_열_수_없으면_400():
    with pytest.raises(AppError) as caught:
        to_jpeg(b"\x89PNG\r\n\x1a\n" + b"0" * 16, 1024)
    assert (caught.value.code, caught.value.http_code) == ("FILE_TYPE_NOT_ALLOWED", 400)
