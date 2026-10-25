import pytest

from app.core.crypto import CryptoError, FieldCrypto
from tests.chat.conftest import ENC_KEY_B64

# 백엔드 FieldCryptoService와 같은 JDK 호출(AES/GCM/NoPadding, 12바이트 nonce, 128비트 태그)로
# 만든 고정값. 키 = ENC_KEY_B64, 평문 = "예방접종 순서 문의"
JAVA_ENVELOPE = "v1.ZGVmZ2hpamtsbW5v.pINWjclAuj6vjv1t-oniYa5GmipgwEueOkntROweGWXtbLj6cdCfoRQ3"


def test_Java가_만든_암호문을_복호화한다() -> None:
    assert FieldCrypto(ENC_KEY_B64).decrypt(JAVA_ENVELOPE) == "예방접종 순서 문의"


def test_암호화_결과는_Java_형식이고_왕복된다() -> None:
    crypto = FieldCrypto(ENC_KEY_B64)
    envelope = crypto.encrypt("안녕 🐶")

    version, nonce, sealed = envelope.split(".")
    assert version == "v1"
    assert "=" not in nonce + sealed
    assert crypto.decrypt(envelope) == "안녕 🐶"
    assert crypto.encrypt("안녕 🐶") != envelope  # nonce가 매번 다르다


@pytest.mark.parametrize("bad", ["", "v2.a.b", "v1.a", "v1.AAAA.AAAA", "평문"])
def test_깨진_암호문은_CryptoError(bad) -> None:
    with pytest.raises(CryptoError):
        FieldCrypto(ENC_KEY_B64).decrypt(bad)


def test_키_변조_암호문은_복호화_실패() -> None:
    envelope = FieldCrypto(ENC_KEY_B64).encrypt("원문")
    other = FieldCrypto("AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA=")

    with pytest.raises(CryptoError):
        other.decrypt(envelope)


@pytest.mark.parametrize("key", ["", "짧음", "QUJD"])  # 빈 값, Base64 아님, 3바이트
def test_키_형식이_틀리면_생성_실패(key) -> None:
    with pytest.raises(CryptoError):
        FieldCrypto(key)
