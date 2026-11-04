import logging
import time
from typing import Annotated, Protocol

import anthropic
from anthropic import AsyncAnthropic
from fastapi import Depends
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.core.llm import get_anthropic_client
from app.healthreport.schemas import HealthReportInput

logger = logging.getLogger(__name__)

LLM_MAX_TOKENS = 1024


class HealthReportApiError(Exception):
    """외부 LLM API 오류 (시간 초과는 TimeoutError로 따로)"""


class ReportOutput(BaseModel):
    # 구조화 출력 : 필드를 늘리면 실제 API로 한 번 확인 (스키마 복잡도 거절 사례, handoff 참고)
    title: str
    tips: list[str] = []


class ReportGenerator(Protocol):
    async def generate(self, data: HealthReportInput) -> ReportOutput: ...


GENERATE_SYSTEM = (
    "너는 반려동물 케어 서비스의 건강 기록 코멘트 작성자다. 보호자가 남긴 최근 14일 기록을 보고 "
    "메인 화면 카드에 들어갈 짧은 코멘트를 쓴다. 입력은 JSON이다(weights 체중 kg, meals 식사량, "
    "waters 음수량, walks 산책 분, stools 배변상태, inspOutOfRange 최근 혈액검사 중 참고 범위 밖 "
    "항목, goalBdwg 목표체중).\n"
    'title: "{이름}는 지금 ___" 문장의 빈칸만 쓴다. 20자 이내 해요체. 예: "건강해요", '
    '"물을 조금 더 마시면 좋아요". 이름·따옴표는 넣지 않는다.\n'
    "tips: 1~3개, 각 40자 이내 해요체. 기록에서 보이는 변화와 보호자가 할 수 있는 일을 쓴다. "
    "혈액검사 범위 밖 항목이나 큰 체중 변화가 있으면 수의사 상담을 권하는 팁을 하나 넣는다.\n"
    "병명을 단정하거나 진단·처방하지 않는다. 입력에 없는 사실을 지어내지 않는다. "
    "기록이 적은 지표는 언급하지 않는다."
)


class ClaudeReportGenerator:
    # 로그에는 건수·소요 시간만 (기록 값 제외)
    def __init__(self, llm: AsyncAnthropic, model: str, timeout_sec: float) -> None:
        self._llm = llm
        self._model = model
        self._timeout_sec = timeout_sec

    async def generate(self, data: HealthReportInput) -> ReportOutput:
        started = time.monotonic()
        body = data.model_dump_json(by_alias=True, exclude_none=True)
        try:
            llm = self._llm.with_options(timeout=self._timeout_sec, max_retries=0)
            response = await llm.messages.parse(
                model=self._model,
                max_tokens=LLM_MAX_TOKENS,
                system=GENERATE_SYSTEM,
                messages=[{"role": "user", "content": body}],
                output_format=ReportOutput,
            )
        except anthropic.APITimeoutError:
            logger.warning("LLM 건강분석 리포트 시간 초과 (%.0fms)", _elapsed(started))
            raise TimeoutError from None
        except anthropic.APIError:
            logger.warning("LLM 건강분석 리포트 실패 (%.0fms)", _elapsed(started))
            raise HealthReportApiError("llm") from None
        except ValidationError:
            logger.warning("LLM 건강분석 리포트 모양 오류 (%.0fms)", _elapsed(started))
            raise HealthReportApiError("llm") from None
        output = response.parsed_output
        if response.stop_reason == "refusal" or output is None or not output.title.strip():
            logger.warning("LLM 건강분석 리포트 결과 없음: %s", response.stop_reason or "no_output")
            raise HealthReportApiError("llm")
        logger.info("LLM 건강분석 리포트: 팁 %d개 (%.0fms)", len(output.tips), _elapsed(started))
        return output


def _elapsed(started: float) -> float:
    return (time.monotonic() - started) * 1000


def get_report_generator(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReportGenerator | None:
    # 키 없으면 None : 저장본·데이터 부족 응답은 LLM 없이 되므로 502는 생성이 필요할 때 service에서
    if not settings.llm_api_key.get_secret_value():
        logger.error("건강분석 리포트 생성 불가: .env.local의 LLM_API_KEY가 비어 있습니다")
        return None
    return ClaudeReportGenerator(
        get_anthropic_client(settings), settings.llm_model, settings.health_report_timeout_sec
    )
