import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.chat import clients
from app.chat.clients import ImageIntentError
from app.chat.schemas import ImageIntentJudgement, ImageIntentKind
from tests.chat.conftest import AJAX, as_member
from tests.chat.test_messages import MessageJava

URL = "/ai/image-intent"


def image_bytes(fmt: str = "PNG", size: tuple[int, int] = (64, 48)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 120, 40)).save(out, fmt)
    return out.getvalue()


class FakeImageIntentJudge:
    def __init__(self, kind: ImageIntentKind = ImageIntentKind.CHARACTER, fail: bool = False):
        self.kind = kind
        self.fail = fail
        self.character_photo_unfit = False
        self.calls: list[tuple[bytes, str | None]] = []

    async def judge(self, jpeg: bytes, text: str | None) -> ImageIntentJudgement:
        self.calls.append((jpeg, text))
        if self.fail:
            raise ImageIntentError("timeout")
        return ImageIntentJudgement(
            kind=self.kind, character_photo_unfit=self.character_photo_unfit
        )


@pytest.fixture
def java() -> MessageJava:
    # 2026-11-13 : 판단 뒤 사진 턴을 대화방에 저장(방 생성·메시지 추가)
    return MessageJava()


@pytest.fixture
def judge(client: TestClient) -> FakeImageIntentJudge:
    fake = FakeImageIntentJudge()
    client.app.dependency_overrides[clients.get_image_intent_judge] = lambda: fake
    as_member(client, 7)
    return fake


def post(client: TestClient, data: dict | None = None, file=None, headers=AJAX):
    files = {"file": file or ("pet.png", image_bytes(), "image/png")}
    return client.post(URL, data=data or {}, files=files, headers=headers)


# 성공·응답 모양
@pytest.mark.parametrize("kind", list(ImageIntentKind))
def test_image_intent_판단_결과를_그대로_돌려줌(client, judge, kind):
    judge.kind = kind
    res = post(client, {"cnvrsCn": "이거 봐줘", "petSn": "3"})
    assert res.status_code == 200
    assert res.json()["data"]["kind"] == kind.value


def test_image_intent_글과_축소한_jpeg를_넘김(client, judge):
    big = image_bytes("PNG", (3000, 1500))
    res = post(client, {"cnvrsCn": " 가계부에 넣어줘 "}, ("r.png", big, "image/png"))
    assert res.status_code == 200
    jpeg, text = judge.calls[0]
    assert text == "가계부에 넣어줘"
    with Image.open(io.BytesIO(jpeg)) as opened:
        assert opened.format == "JPEG"
        assert opened.size == (1024, 512)


def test_image_intent_작은_사진은_키우지_않음(client, judge):
    post(client, file=("p.webp", image_bytes("WEBP", (300, 200)), "image/webp"))
    with Image.open(io.BytesIO(judge.calls[0][0])) as opened:
        assert opened.size == (300, 200)


@pytest.mark.parametrize("data", [{}, {"cnvrsCn": ""}, {"cnvrsCn": "   "}])
def test_image_intent_글이_없거나_공백이면_None(client, judge, data):
    res = post(client, data)
    assert res.status_code == 200
    assert judge.calls[0][1] is None


def test_image_intent_판단_실패는_ASK(client, judge):
    judge.fail = True
    res = post(client, {"cnvrsCn": "이거 뭐야"})
    assert res.status_code == 200
    assert res.json()["data"]["kind"] == "ASK"


# 인증·검증 실패는 판단기 미호출
def test_image_intent_쿠키_없음_401(client, judge):
    client.cookies.clear()
    res = post(client)
    assert res.status_code == 401
    assert judge.calls == []


def test_image_intent_X_Requested_With_없음_403(client, judge):
    res = post(client, headers={})
    assert res.status_code == 403
    assert res.json()["code"] == "FORBIDDEN"
    assert judge.calls == []


@pytest.mark.parametrize(
    ("file", "code"),
    [
        # PDF는 받지만(2026-11-23) 확장자와 실제 형식이 같아야 한다
        (("r.jpg", b"%PDF-1.7 0000", "image/jpeg"), "FILE_TYPE_NOT_ALLOWED"),
        (("r.pdf", image_bytes("PNG"), "application/pdf"), "FILE_TYPE_NOT_ALLOWED"),
        (
            ("r.pdf", b"%PDF-1.7" + b"0" * (10 * 1024 * 1024), "application/pdf"),
            "FILE_SIZE_EXCEEDED",
        ),
        (("r.jpg", image_bytes("PNG"), "image/jpeg"), "FILE_TYPE_NOT_ALLOWED"),
        (("r.png", b"\x89PNG\r\n\x1a\n" + b"0" * 16, "image/png"), "FILE_TYPE_NOT_ALLOWED"),
        (
            ("r.png", b"\x89PNG\r\n\x1a\n" + b"0" * (10 * 1024 * 1024), "image/png"),
            "FILE_SIZE_EXCEEDED",
        ),
    ],
)
def test_image_intent_파일_검증_400(client, judge, file, code):
    res = post(client, file=file)
    assert res.status_code == 400
    assert res.json()["code"] == code
    assert judge.calls == []


@pytest.mark.parametrize("name", ["result.pdf", "RESULT.PDF"])
def test_image_intent_PDF는_판단_LLM_없이_CHECKUP_PDF(client, judge, name):
    # 대화창 PDF 첨부 (2026-11-23) : 검사결과지 분석으로. 글과 무관
    res = post(client, {"cnvrsCn": "캐릭터 만들어줘"}, (name, b"%PDF-1.7 0000", "application/pdf"))
    assert res.status_code == 200
    assert res.json()["data"]["kind"] == "CHECKUP_PDF"
    assert judge.calls == []


@pytest.mark.parametrize("data", [{"cnvrsCn": "가" * 1001}, {"petSn": "abc"}, {"petSn": "0"}])
def test_image_intent_폼_값_검증_400(client, judge, data):
    res = post(client, data)
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"
    assert judge.calls == []


def test_image_intent_file_없음_400(client, judge):
    res = client.post(URL, data={"cnvrsCn": "사진"}, headers=AJAX)
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"
    assert judge.calls == []


def test_image_intent_LLM_키_없음_502(client):
    as_member(client, 7)
    res = post(client)
    assert res.status_code == 502
    assert res.json()["code"] == "EXTERNAL_API_ERROR"


def test_image_intent_판단_지시문에_SKIN_용도가_있다():
    from app.chat.clients import IMAGE_INTENT_SYSTEM

    assert "- SKIN:" in IMAGE_INTENT_SYSTEM
    assert "'피부 봐줘' -> SKIN" in IMAGE_INTENT_SYSTEM


def test_image_intent_글이_피부를_말하면_SKIN_지시가_있다():
    from app.chat.clients import IMAGE_INTENT_SYSTEM

    assert "글이 피부·털·상처를 말하고 사진이 반려동물이면" in IMAGE_INTENT_SYSTEM


def test_image_intent_판단_지시문에_EYE_용도가_있다():
    from app.chat.clients import IMAGE_INTENT_SYSTEM

    assert "- EYE:" in IMAGE_INTENT_SYSTEM
    assert "'눈 봐줘' -> EYE" in IMAGE_INTENT_SYSTEM
    assert "눈과 눈 주변이 사진의 중심이면 SKIN이 아니라 EYE" in IMAGE_INTENT_SYSTEM


def test_image_intent_글이_눈을_말하면_EYE_지시가_있다():
    from app.chat.clients import IMAGE_INTENT_SYSTEM

    assert "글이 눈을 말하고 사진이 반려동물이면" in IMAGE_INTENT_SYSTEM


def test_image_intent_눈만_찍은_사진에_캐릭터_글이면_ASK_지시가_있다():
    from app.chat.clients import IMAGE_INTENT_SYSTEM

    assert "눈만 가까이 찍은 사진 + '캐릭터 만들어줘' -> ASK" in IMAGE_INTENT_SYSTEM


def test_image_intent_얼굴이나_몸이_안_보이면_캐릭터_글이어도_ASK_지시가_있다():
    from app.chat.clients import IMAGE_INTENT_SYSTEM

    assert "사진에 반려동물 얼굴이나 몸 전체가 안 보이면 ASK" in IMAGE_INTENT_SYSTEM
    assert "영수증 사진 + '캐릭터 만들어줘' -> ASK" in IMAGE_INTENT_SYSTEM
    assert "'캐릭터 만들어줘' -> CHARACTER" not in IMAGE_INTENT_SYSTEM


@pytest.mark.parametrize(
    ("kind", "unfit", "expected"),
    [
        (ImageIntentKind.ASK, True, True),
        (ImageIntentKind.ASK, False, False),
        # ASK가 아니면 표시를 버린다
        (ImageIntentKind.CHARACTER, True, False),
    ],
)
def test_image_intent_캐릭터_사진_부적합은_ASK일_때만(kind, unfit, expected):
    output = clients.ImageIntentOutput(kind=kind, character_photo_unfit=unfit)

    judgement = clients.judgement_of(output)

    assert judgement.kind is kind
    assert judgement.character_photo_unfit is expected


def test_image_intent_지시문에_캐릭터_사진_부적합_표시가_있다():
    assert "character_photo_unfit을 true" in clients.IMAGE_INTENT_SYSTEM
