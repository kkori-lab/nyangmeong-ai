import base64
import binascii
import os
from typing import Annotated

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import Depends

from app.core.config import Settings, get_settings
from app.core.response import AppError

VERSION = "v1"
KEY_BYTES = 32
NONCE_BYTES = 12


class CryptoError(Exception):
    """키 형식 오류 또는 복호화 실패"""


class FieldCrypto:
    """백엔드 FieldCryptoService와 같은 형식 : v1.{nonce}.{암호문+태그} (Base64URL, 패딩 없음)"""

    def __init__(self, key_base64: str) -> None:
        self._aes = AESGCM(parse_key(key_base64))

    def encrypt(self, plaintext: str) -> str:
        nonce = os.urandom(NONCE_BYTES)
        sealed = self._aes.encrypt(nonce, plaintext.encode("utf-8"), None)
        return f"{VERSION}.{_b64url(nonce)}.{_b64url(sealed)}"

    def decrypt(self, envelope: str) -> str:
        parts = envelope.split(".")
        if len(parts) != 3 or parts[0] != VERSION:
            raise CryptoError("지원하지 않는 암호문 형식")
        try:
            nonce = _b64url_decode(parts[1])
            sealed = _b64url_decode(parts[2])
            if len(nonce) != NONCE_BYTES:
                raise CryptoError("암호문 길이 불일치")
            return self._aes.decrypt(nonce, sealed, None).decode("utf-8")
        except (binascii.Error, InvalidTag, UnicodeDecodeError, ValueError) as e:
            raise CryptoError("복호화 실패") from e


def parse_key(key_base64: str) -> bytes:
    try:
        key = base64.b64decode(key_base64.strip(), validate=True)
    except (binascii.Error, ValueError) as e:
        # 비ASCII 문자는 binascii.Error가 아니라 ValueError로 나온다
        raise CryptoError("CONVERSATION_ENC_KEY가 Base64가 아닙니다.") from e
    if len(key) != KEY_BYTES:
        raise CryptoError("CONVERSATION_ENC_KEY는 Base64로 풀었을 때 32바이트여야 합니다.")
    return key


def check_key(settings: Settings) -> None:
    """서버 시작 때 호출 : 값이 있는데 형식이 틀리면 바로 실패. 빈 값은 요청 때 500"""
    key = settings.conversation_enc_key.get_secret_value()
    if key.strip():
        parse_key(key)


def get_crypto(settings: Annotated[Settings, Depends(get_settings)]) -> FieldCrypto:
    key = settings.conversation_enc_key.get_secret_value()
    if not key.strip():
        raise AppError("INTERNAL_SERVER_ERROR", 500, "서버 설정 오류가 발생했습니다.")
    try:
        return FieldCrypto(key)
    except CryptoError:
        raise AppError("INTERNAL_SERVER_ERROR", 500, "서버 설정 오류가 발생했습니다.") from None


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
