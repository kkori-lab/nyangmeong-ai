import base64
import logging
import time
from typing import Annotated, Protocol

import anthropic
from anthropic import AsyncAnthropic
from fastapi import Depends
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.core.llm import get_anthropic_client

logger = logging.getLogger(__name__)

# 항목 많은 결과지 수용 : thinking 토큰 포함
LLM_MAX_TOKENS = 8192
LLM_EFFORT = "low"


class PdfAnalyzeApiError(Exception):
    """외부 LLM API 오류 (시간 초과는 TimeoutError로 따로)"""


class LabRow(BaseModel):
    # 구조화 출력의 한 행 : 결과지 표기 그대로, 못 읽은 값은 null
    name: str | None = None
    value: str | None = None
    unit: str | None = None
    ref_min: str | None = None
    ref_max: str | None = None
    blood: bool = True


class LabResultOutput(BaseModel):
    is_lab_result: bool = False
    rows: list[LabRow] = []


class LabResultClient(Protocol):
    async def read(self, pdf: bytes) -> LabResultOutput: ...


READ_SYSTEM = (
    "반려동물 동물병원 검사결과지 PDF를 읽어 검사 항목을 행으로 정리한다. "
    "PDF에 없는 값은 지어내지 않고 null로 둔다.\n"
    "is_lab_result: 동물병원 검사결과지(혈액검사 등 검사 수치표)이면 true, "
    "영수증·안내문·그 밖의 문서이면 false.\n"
    "rows: 결과지 순서대로 한 행씩. name: 항목명(결과지 표기 그대로, 약어가 있으면 약어). "
    "value: 측정값(숫자만, 단위·H/L 표시 제외. 읽을 수 없거나 숫자가 아니면 null). "
    "unit: 단위. ref_min·ref_max: 참고범위 최소·최대(숫자만, 한쪽만 찍혔으면 찍힌 쪽만). "
    "blood: 혈액검사(혈구·생화학·전해질 등 혈액으로 하는 검사) 항목이면 true, "
    "소변·분변·영상 등 그 밖의 검사이면 false.\n"
    "판정·해석·설명은 넣지 않는다. 검사결과지가 아니면 rows를 빈 배열로 둔다."
)


class ClaudePdfClient:
    # FN-HLT-005-04 : PDF를 document 블록으로 그대로 전송 (텍스트·스캔 PDF 모두)
    # 로그에는 건수·크기·소요 시간만
    def __init__(self, llm: AsyncAnthropic, model: str, timeout_sec: float) -> None:
        self._llm = llm
        self._model = model
        self._timeout_sec = timeout_sec

    async def read(self, pdf: bytes) -> LabResultOutput:
        started = time.monotonic()
        document = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.b64encode(pdf).decode("ascii"),
            },
        }
        try:
            # 대화창용 제한(10초·재시도 1번) 대신 분석 제한 시간 하나만 적용
            llm = self._llm.with_options(timeout=self._timeout_sec, max_retries=0)
            response = await llm.messages.parse(
                model=self._model,
                max_tokens=LLM_MAX_TOKENS,
                system=READ_SYSTEM,
                messages=[
                    {
                        "role": "user",
                        "content": [document, {"type": "text", "text": "검사 항목을 정리해 줘."}],
                    }
                ],
                output_config={"effort": LLM_EFFORT},
                output_format=LabResultOutput,
            )
        except anthropic.APITimeoutError:
            logger.warning("LLM 검사결과지 분석 시간 초과 (%.0fms)", _elapsed(started))
            raise TimeoutError from None
        except anthropic.APIError:
            logger.warning("LLM 검사결과지 분석 실패 (%.0fms)", _elapsed(started))
            raise PdfAnalyzeApiError("llm") from None
        except ValidationError:
            logger.warning("LLM 검사결과지 분석 모양 오류 (%.0fms)", _elapsed(started))
            raise PdfAnalyzeApiError("llm") from None
        output = response.parsed_output
        if response.stop_reason == "refusal" or output is None:
            logger.warning("LLM 검사결과지 분석 결과 없음: %s", response.stop_reason or "no_output")
            raise PdfAnalyzeApiError("llm")
        logger.info(
            "LLM 검사결과지 분석: PDF %d바이트 → %d행 (%.0fms)",
            len(pdf),
            len(output.rows),
            _elapsed(started),
        )
        return output


def _elapsed(started: float) -> float:
    return (time.monotonic() - started) * 1000


def get_lab_result_client(
    settings: Annotated[Settings, Depends(get_settings)],
) -> LabResultClient | None:
    # 키 없으면 None : 업로드 검증 먼저, 502는 service에서
    if not settings.llm_api_key.get_secret_value():
        logger.error("PDF 분석 불가: .env.local의 LLM_API_KEY가 비어 있습니다")
        return None
    return ClaudePdfClient(
        get_anthropic_client(settings), settings.llm_model, settings.pdf_analyze_timeout_sec
    )
