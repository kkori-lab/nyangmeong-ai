from http.cookiejar import CookieJar, DefaultCookiePolicy
from typing import Any

import httpx2
from fastapi import Request

from app.core.config import Settings
from app.core.response import AppError

# Java 내부 API 제한 시간(초)
TIMEOUT_SEC = 3.0


class BackendError(Exception):
    """Java 4xx 오류 : 본문·Set-Cookie 그대로 전달"""

    def __init__(
        self, status_code: int, body: bytes, content_type: str | None, set_cookies: list[str]
    ) -> None:
        super().__init__(status_code)
        self.status_code = status_code
        self.body = body
        self.content_type = content_type
        self.set_cookies = set_cookies

    @classmethod
    def of(cls, res: httpx2.Response) -> "BackendError":
        return cls(
            res.status_code,
            res.content,
            res.headers.get("content-type"),
            res.headers.get_list("set-cookie"),
        )


class _FailureCause(Exception):
    """502로 바꾼 Java 호출 실패의 원인(로그용, 응답에는 나가지 않음)"""


def failure_reason(error: Exception) -> str:
    """Java 호출 실패 이유 한 줄 : 제한 시간·연결·상태 코드·주소·본문 구분"""
    if isinstance(error, BackendError):
        return f"Java {error.status_code}"
    cause = error.__cause__
    if isinstance(cause, _FailureCause):
        return str(cause)
    if isinstance(cause, httpx2.TimeoutException):
        return f"제한 시간 초과 {type(cause).__name__}"
    if isinstance(cause, httpx2.ConnectError):
        return f"연결 실패 {type(cause).__name__}"
    if isinstance(cause, httpx2.HTTPError):
        return f"통신 실패 {type(cause).__name__}"
    return type(error).__name__


def create_backend_client() -> httpx2.AsyncClient:
    # 요청끼리 공유하므로 Java의 Set-Cookie를 저장하지 않는다 : 다른 회원 요청에 섞임 방지
    jar = CookieJar(policy=DefaultCookiePolicy(allowed_domains=[]))
    return httpx2.AsyncClient(timeout=TIMEOUT_SEC, cookies=jar)


def get_backend_client(request: Request) -> httpx2.AsyncClient:
    return request.app.state.backend_client


async def _send(
    client: httpx2.AsyncClient, settings: Settings, method: str, path: str, **kwargs: Any
) -> httpx2.Response:
    base_url = settings.backend_base_url.rstrip("/")
    if not base_url:
        raise external_error() from _FailureCause("주소 비어 있음")
    try:
        res = await client.request(method, f"{base_url}{path}", **kwargs)
    except httpx2.HTTPError as error:
        raise external_error() from error
    except (httpx2.InvalidURL, OverflowError) as error:
        # 주소 꼴이 틀림(포트 문자·괄호 깨짐, Linux 포트 범위 밖) : 주소 값은 로그에 넣지 않는다
        raise external_error() from _FailureCause(f"주소 꼴 틀림 {type(error).__name__}")
    if 400 <= res.status_code < 500:
        raise BackendError.of(res)
    if not res.is_success:
        raise external_error() from _FailureCause(f"Java {res.status_code}")
    return res


async def fetch_backend_bytes(
    client: httpx2.AsyncClient, settings: Settings, path: str, **kwargs: Any
) -> bytes:
    """Java 내부 API에서 파일 내려받기 (4xx 그대로 전달, 그 외 실패·빈 본문 502)"""
    res = await _send(client, settings, "GET", path, **kwargs)
    if not res.content:
        raise external_error()
    return res.content


async def call_backend(
    client: httpx2.AsyncClient, settings: Settings, method: str, path: str, **kwargs: Any
) -> Any:
    """Java 내부 API 호출 -> ApiResponse의 data (4xx 그대로 전달, 그 외 실패 502)"""
    res = await _send(client, settings, method, path, **kwargs)
    if not res.content:
        return None
    try:
        return res.json().get("data")
    except (ValueError, AttributeError):
        raise external_error() from _FailureCause("응답 JSON 아님")


def external_error() -> AppError:
    return AppError(
        "EXTERNAL_API_ERROR", 502, "외부 서비스 호출에 실패했습니다. 잠시 후 다시 시도해 주세요."
    )
