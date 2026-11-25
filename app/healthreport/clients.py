import logging
import time
from typing import Annotated, Protocol

import anthropic
from anthropic import AsyncAnthropic
from anthropic.types import Message
from fastapi import Depends
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.core.llm import get_anthropic_client
from app.healthreport.schemas import HealthReportInput

logger = logging.getLogger(__name__)

# effort low : thinking 토큰도 max_tokens에 포함 (1024에서 JSON이 잘린 사례, handoff 참고)
LLM_EFFORT = "low"
LLM_MAX_TOKENS = 2048
LOG_TEXT_CHARS = 80  # 실패 로그의 응답 앞부분 : 잘린 곳은 보이고 기록 값은 거의 안 섞이는 길이


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
    '"물을 조금 더 마시면 좋아요", "평소처럼 잘 지내요". 이름·따옴표는 넣지 않는다. '
    '앞에 이미 "지금"이 있으므로 "지금"으로 시작하지 않는다.\n'
    "tips: 1~3개, 각 15자 이내(공백 포함) 짧은 요약. 해요체나 명사형으로 끝낸다. "
    '예: "산책 꾸준해요", "음수량 기록 필요". 기록에서 보이는 변화와 보호자가 할 일을 담는다. '
    "이상 신호(혈액검사 범위 밖 항목, 14일 동안 체중 5% 이상 변화, 식사량·음수량이 계속 줄어듦, "
    "묽은 변이 이어짐)가 하나라도 있으면: 첫 팁은 수의사 상담 안내로 쓴다"
    '(예: "수의사 상담 권해요"). 산책·운동·식사량·사료를 늘리거나 바꾸라고 권하지 않는다'
    "(원인을 모르는 상태라서). 나머지 팁은 보호자가 "
    "지켜볼 변화(예: 음수량·식욕 기록 계속하기)만 쓴다. title도 걱정되는 변화를 담담하게 쓴다.\n"
    "이상 신호가 없으면 지금 관리를 이어 가는 일상 팁을 쓴다.\n"
    "기록이 적으면(모든 지표가 각 3건 미만) 건강하다고 판단하지 않는다. title은 "
    '"기록이 더 필요해요"처럼 쓰고 tips는 기록을 권하는 내용만 쓴다(예: "매일 기록해 주세요").\n'
    "병명을 단정하거나 진단·처방하지 않는다. 입력에 없는 사실을 지어내지 않는다. "
    "기록이 적은 지표는 언급하지 않는다."
)


class _BadOutput(Exception):
    """잘림·모양 오류 : 한 번만 다시 요청한다"""


class ClaudeReportGenerator:
    # 로그에는 건수·소요 시간, 실패 때만 응답 앞 LOG_TEXT_CHARS자
    def __init__(self, llm: AsyncAnthropic, model: str, timeout_sec: float) -> None:
        self._llm = llm
        self._model = model
        self._timeout_sec = timeout_sec

    async def generate(self, data: HealthReportInput) -> ReportOutput:
        started = time.monotonic()
        body = data.model_dump_json(by_alias=True, exclude_none=True)
        try:
            output = await self._request(body, started)
        except _BadOutput:
            # 시간 제한은 service의 wait_for 하나가 두 번을 함께 감싼다
            logger.warning("LLM 건강분석 리포트 다시 요청 (%.0fms)", _elapsed(started))
            try:
                output = await self._request(body, started)
            except _BadOutput:
                raise HealthReportApiError("llm") from None
        logger.info("LLM 건강분석 리포트: 팁 %d개 (%.0fms)", len(output.tips), _elapsed(started))
        return output

    async def _request(self, body: str, started: float) -> ReportOutput:
        try:
            llm = self._llm.with_options(timeout=self._timeout_sec, max_retries=0)
            response = await llm.messages.create(
                model=self._model,
                max_tokens=LLM_MAX_TOKENS,
                system=GENERATE_SYSTEM,
                messages=[{"role": "user", "content": body}],
                output_config={
                    "effort": LLM_EFFORT,
                    "format": {"type": "json_schema", "schema": REPORT_SCHEMA},
                },
            )
        except anthropic.APITimeoutError:
            logger.warning("LLM 건강분석 리포트 시간 초과 (%.0fms)", _elapsed(started))
            raise TimeoutError from None
        except anthropic.APIError:
            logger.warning("LLM 건강분석 리포트 실패 (%.0fms)", _elapsed(started))
            raise HealthReportApiError("llm") from None
        text = "".join(block.text for block in response.content if block.type == "text")
        reason = response.stop_reason or "no_output"
        if response.stop_reason == "refusal":
            _log_failure("결과 없음", reason, response, text)
            raise HealthReportApiError("llm")
        if response.stop_reason == "max_tokens":
            _log_failure("결과 없음", reason, response, text)
            raise _BadOutput
        try:
            output = ReportOutput.model_validate_json(text)
        except ValidationError:
            _log_failure("모양 오류", reason, response, text)
            raise _BadOutput from None
        if not output.title.strip():
            _log_failure("결과 없음", reason, response, text)
            raise _BadOutput
        return output


REPORT_SCHEMA = anthropic.transform_schema(ReportOutput)


def _log_failure(kind: str, reason: str, response: Message, text: str) -> None:
    logger.warning(
        "LLM 건강분석 리포트 %s: stop_reason=%s output_tokens=%s 글 %d자 앞부분=%r",
        kind,
        reason,
        response.usage.output_tokens if response.usage else None,
        len(text),
        text[:LOG_TEXT_CHARS],
    )


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
