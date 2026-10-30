import logging
from functools import lru_cache

from anthropic import AsyncAnthropic

from app.core.backend import external_error
from app.core.config import Settings

logger = logging.getLogger(__name__)


@lru_cache
def _anthropic_client(api_key: str, timeout_sec: float) -> AsyncAnthropic:
    return AsyncAnthropic(api_key=api_key, timeout=timeout_sec, max_retries=1)


def get_anthropic_client(settings: Settings) -> AsyncAnthropic:
    """대화창·영수증 정리가 같이 쓰는 Anthropic 클라이언트"""
    api_key = settings.llm_api_key.get_secret_value()
    if not api_key:
        # 키 없는 PC·CI : 실제 API 미호출, 502 (키 값은 로그 제외)
        logger.error("LLM 호출 불가: .env.local의 LLM_API_KEY가 비어 있습니다")
        raise external_error()
    return _anthropic_client(api_key, settings.llm_timeout_sec)
