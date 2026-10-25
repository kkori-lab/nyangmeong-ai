import pytest

from app.core.auth import require_member
from app.core.config import Settings
from app.core.response import AppError
from tests.chat.conftest import JWT_SECRET_B64, make_token


def _settings(secret: str = JWT_SECRET_B64) -> Settings:
    return Settings(_env_file=None, jwt_secret_base64=secret)


def test_정상_토큰은_회원_번호를_돌려준다() -> None:
    # FN-AIM-011-03
    assert require_member(_settings(), make_token(42)) == 42


@pytest.mark.parametrize(
    "token",
    [
        None,
        "",
        "not-a-jwt",
        make_token(1, key=b"x" * 32),  # 서명 틀림
        make_token(1, typ="refresh"),  # refresh를 access 자리에
    ],
)
def test_쿠키_없음_서명_틀림_refresh는_UNAUTHORIZED(token) -> None:
    with pytest.raises(AppError) as e:
        require_member(_settings(), token)

    assert (e.value.http_code, e.value.code) == (401, "UNAUTHORIZED")


def test_만료는_TOKEN_EXPIRED() -> None:
    with pytest.raises(AppError) as e:
        require_member(_settings(), make_token(1, exp_in=-60))

    assert (e.value.http_code, e.value.code) == (401, "TOKEN_EXPIRED")


def test_서버에_비밀키가_없으면_정상_토큰도_거절() -> None:
    with pytest.raises(AppError) as e:
        require_member(_settings(secret=""), make_token(1))

    assert e.value.code == "UNAUTHORIZED"
