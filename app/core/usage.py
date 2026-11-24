"""[외부 API 사용량 통지]
- Java POST /internal/ai/external-api-calls (FN-ADM-112-01·02, FN-ADM-082-03)
- 정본 백엔드 docs/api/global.md ExternalApiCallRequest
- 통지 실패는 사용자 응답과 무관 : 기다리지 않고 경고 로그만
- 요청마다 그 요청의 쿠키로 만든 통지기를 주입 : 요청을 넘는 작업에서 회원이 섞이지 않게
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Protocol

import anthropic
import httpx2
import openai
from fastapi import Depends, Request

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

PATH = "/internal/ai/external-api-calls"
# 통지 한 건의 제한 시간 : 사용자 응답과 따로 돌아 길게 잡지 않음
TIMEOUT_SEC = 5.0
# EXTL_API_CALL_LOG.FAIL_RSN 길이
FAIL_REASON_MAX = 1000


class ExternalApi(StrEnum):
    """외부API구분 SYSG05"""

    CHAT = "SYSC0015"
    CLASSIFY = "SYSC0024"
    OCR = "SYSC0016"
    CHARACTER = "SYSC0017"
    PDF = "SYSC0025"


class CallResult(StrEnum):
    """호출결과 SYSG06"""

    SUCCESS = "SYSC0021"
    FAIL = "SYSC0022"
    TIMEOUT = "SYSC0023"


@dataclass(frozen=True)
class ExternalCall:
    api: ExternalApi
    result: CallResult
    rspns_ms: int
    http_status: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    fail_reason: str | None = None

    def body(self) -> dict[str, Any]:
        # 값 없는 칸은 보내지 않음 : callDt는 Java 저장 시각
        body: dict[str, Any] = {
            "extlApiSeCd": self.api.value,
            "callRsltCd": self.result.value,
            "rspnsMs": self.rspns_ms,
            "httpSttsVl": self.http_status,
            "inptTknCnt": self.input_tokens,
            "otptTknCnt": self.output_tokens,
            "failRsn": self.fail_reason[:FAIL_REASON_MAX] if self.fail_reason else None,
        }
        return {key: value for key, value in body.items() if value is not None}


class UsageReporter(Protocol):
    def record(self, call: ExternalCall) -> None: ...


class NoUsageReporter:
    """통지 안 함 : 평가 스크립트·직접 만든 클라이언트의 기본값"""

    def record(self, call: ExternalCall) -> None:
        return None


NO_USAGE = NoUsageReporter()

# 보내는 중인 통지 : 끝나기 전에 작업이 버려지지 않게 참조 보관
_pending: set[asyncio.Task] = set()


class JavaUsageReporter:
    def __init__(self, client: httpx2.AsyncClient, settings: Settings, cookie: str | None) -> None:
        self._client = client
        self._base_url = settings.backend_base_url.rstrip("/")
        self._cookie = cookie

    def record(self, call: ExternalCall) -> None:
        # 쿠키 없는 호출(Java -> Python 등)은 Java가 회원을 못 정해 보내지 않음
        if not self._cookie or not self._base_url:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._send(call))
        _pending.add(task)
        task.add_done_callback(_pending.discard)

    async def _send(self, call: ExternalCall) -> None:
        headers = {"Cookie": self._cookie or "", "X-Requested-With": "XMLHttpRequest"}
        try:
            res = await self._client.post(
                f"{self._base_url}{PATH}", json=call.body(), headers=headers, timeout=TIMEOUT_SEC
            )
        except (httpx2.HTTPError, httpx2.InvalidURL, OverflowError) as error:
            logger.warning(
                "외부 API 사용량 통지 실패(%s): %s", type(error).__name__, call.api.value
            )
            return
        if not res.is_success:
            logger.warning(
                "외부 API 사용량 통지 실패(Java %d): %s", res.status_code, call.api.value
            )


async def flush() -> None:
    """보내는 중인 통지 끝까지 기다리기"""
    while _pending:
        await asyncio.gather(*list(_pending), return_exceptions=True)


def get_usage_reporter(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> UsageReporter:
    # 기동 전(lifespan 없는 앱)에는 Java 클라이언트가 없어 통지 안 함
    client = getattr(request.app.state, "backend_client", None)
    if client is None:
        return NO_USAGE
    return JavaUsageReporter(client, settings, request.headers.get("cookie"))


def elapsed_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))


def token_counts(usage: Any) -> tuple[int | None, int | None]:
    # 2026-11-24 사람 결정 : 입력 = input + 캐시 읽기 + 캐시 쓰기, 출력 = output
    # OpenAI 채팅은 prompt_tokens(캐시 포함)·completion_tokens, 이미지는 input·output_tokens
    if usage is None:
        return None, None
    total = (
        (getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", 0) or 0)
        + (getattr(usage, "cache_read_input_tokens", 0) or 0)
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
    )
    output = getattr(usage, "output_tokens", None)
    if output is None:
        output = getattr(usage, "completion_tokens", None)
    return total, output


def succeeded(
    api: ExternalApi, started: float, usage: Any = None, http_status: int = 200
) -> ExternalCall:
    input_tokens, output_tokens = token_counts(usage)
    return ExternalCall(
        api, CallResult.SUCCESS, elapsed_ms(started), http_status, input_tokens, output_tokens
    )


def failed(
    api: ExternalApi,
    started: float,
    reason: str,
    usage: Any = None,
    http_status: int | None = None,
) -> ExternalCall:
    """응답은 왔지만 쓸 수 없는 호출(거절·모양 오류·오류 응답)"""
    input_tokens, output_tokens = token_counts(usage)
    return ExternalCall(
        api,
        CallResult.FAIL,
        elapsed_ms(started),
        http_status,
        input_tokens,
        output_tokens,
        reason,
    )


def errored(api: ExternalApi, started: float, error: BaseException) -> ExternalCall:
    """예외로 끝난 호출 -> 시간초과·실패 구분"""
    ms = elapsed_ms(started)
    timeouts = (anthropic.APITimeoutError, openai.APITimeoutError)
    if isinstance(error, (*timeouts, httpx2.TimeoutException, TimeoutError)):
        return ExternalCall(api, CallResult.TIMEOUT, ms, fail_reason="timeout")
    if isinstance(error, (anthropic.APIStatusError, openai.APIStatusError)):
        status = error.status_code
        return ExternalCall(api, CallResult.FAIL, ms, status, fail_reason=f"api_error {status}")
    if isinstance(error, (anthropic.APIError, openai.APIError)):
        return ExternalCall(api, CallResult.FAIL, ms, fail_reason="api_error")
    return ExternalCall(api, CallResult.FAIL, ms, fail_reason=f"network {type(error).__name__}")
