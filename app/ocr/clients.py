import base64
import logging
import time
from datetime import date
from typing import Annotated, Protocol

import anthropic
import httpx2
from anthropic import AsyncAnthropic
from fastapi import Depends
from pydantic import BaseModel, ValidationError

from app.core.backend import external_error
from app.core.config import Settings, get_settings
from app.core.llm import get_anthropic_client
from app.ocr.rules import layout_text
from app.ocr.schemas import ReceiptOcrResponse, Section

logger = logging.getLogger(__name__)

VISION_URL = "https://vision.googleapis.com/v1/images:annotate"
# 품목이 많은 영수증도 담기게. thinking 토큰도 이 안에서 쓴다
LLM_MAX_TOKENS = 8192
LLM_EFFORT = "low"


class OcrApiError(Exception):
    """외부 OCR API 오류 (시간 초과는 서비스에서 별도 구분)"""


class OcrClient(Protocol):
    async def recognize(self, image: bytes) -> ReceiptOcrResponse: ...


class ReceiptOutput(BaseModel):
    # 구조화 출력 모양 : 못 읽은 값은 null, 날짜는 YYYY-MM-DD 문자열
    hsptl_nm: str | None = None
    ckup_ymd: str | None = None
    recpt_amt: int | None = None
    btm_dscnt_amt: int | None = None
    sections: list[Section] = []


STRUCTURE_SYSTEM = (
    "동물병원 영수증·약봉투를 OCR로 읽은 글자를 받아 항목으로 정리한다. "
    "글자에 없는 값은 지어내지 않고 null로 둔다. 금액은 원 단위 정수(쉼표·'원' 제거).\n"
    "hsptl_nm: 병원명. ckup_ymd: 진료일 YYYY-MM-DD, 연도가 없으면 null. "
    "recpt_amt: 최종 결제 금액(할인 후). btm_dscnt_amt: 영수증 하단에만 찍힌 할인 합계.\n"
    "같은 할인을 btm_dscnt_amt와 dscntAmt에 겹쳐 넣지 않는다. 하단 합계 부분의 할인은 "
    "btm_dscnt_amt에만, 반려동물 구역 안에 찍힌 할인만 dscntAmt에 둔다.\n"
    "sections: 반려동물 구역. 영수증이 반려동물 이름별로 나뉘면 구역마다 하나(sectionNm=이름), "
    "나뉘지 않으면 sectionNm=null인 구역 하나. sbttlAmt: 구역 소계, dscntAmt: 구역 안 할인. "
    "items: 진료 품목(itemNm, itemAmt). 줄 끝의 '수량 금액'(예: 1 60,000)은 금액만 쓴다. "
    "품목명 앞의 비과세 표시 '*'는 뺀다. drugs: 처방 약품(mdcnNm, mdcnDays 일수, "
    "mdcnUsage 용법 원문 예: 1일 2회, mdcnAmt 금액). 약품은 items에 겹쳐 넣지 않는다.\n"
    "글자가 영수증이 아니거나 읽을 것이 없으면 모든 값을 null, sections를 빈 배열로 둔다."
)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


class GoogleVisionOcrClient:
    # FN-AIM-008-06 : Vision 글자 읽기(DOCUMENT_TEXT_DETECTION) -> LLM 항목 정리
    # 로그에는 길이·소요 시간만
    def __init__(
        self,
        api_key: str,
        llm: AsyncAnthropic,
        model: str,
        timeout_sec: float,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._llm = llm
        self._model = model
        self._timeout_sec = timeout_sec
        self._transport = transport

    async def recognize(self, image: bytes) -> ReceiptOcrResponse:
        text = await self._read_text(image)
        if not text.strip():
            return ReceiptOcrResponse()
        return await self._structure(text)

    async def _read_text(self, image: bytes) -> str:
        started = time.monotonic()
        body = {
            "requests": [
                {
                    "image": {"content": base64.b64encode(image).decode("ascii")},
                    "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                    "imageContext": {"languageHints": ["ko"]},
                }
            ]
        }
        try:
            async with httpx2.AsyncClient(
                timeout=self._timeout_sec, transport=self._transport
            ) as http:
                res = await http.post(VISION_URL, params={"key": self._api_key}, json=body)
        except httpx2.TimeoutException:
            logger.warning("Vision 시간 초과 (%.0fms)", _elapsed(started))
            raise TimeoutError from None
        except httpx2.HTTPError:
            logger.warning("Vision 연결 실패 (%.0fms)", _elapsed(started))
            raise OcrApiError("vision") from None
        if not res.is_success:
            logger.warning("Vision 오류 %d (%.0fms)", res.status_code, _elapsed(started))
            raise OcrApiError("vision")
        try:
            response = res.json()["responses"][0]
        except (ValueError, KeyError, IndexError, TypeError):
            raise OcrApiError("vision") from None
        if "error" in response:
            logger.warning("Vision 오류 응답 (%.0fms)", _elapsed(started))
            raise OcrApiError("vision")
        # 줄 순서를 낱말 위치로 재구성 (품목과 금액을 같은 줄에)
        text = layout_text(response.get("fullTextAnnotation") or {})
        logger.info("Vision 글자 %d자 (%.0fms)", len(text), _elapsed(started))
        return text

    async def _structure(self, text: str) -> ReceiptOcrResponse:
        started = time.monotonic()
        try:
            # 대화창용 제한(10초·재시도 1번) 대신 분석 제한 시간 하나만 적용
            llm = self._llm.with_options(timeout=self._timeout_sec, max_retries=0)
            response = await llm.messages.parse(
                model=self._model,
                max_tokens=LLM_MAX_TOKENS,
                system=STRUCTURE_SYSTEM,
                messages=[{"role": "user", "content": text}],
                output_config={"effort": LLM_EFFORT},
                output_format=ReceiptOutput,
            )
        except anthropic.APITimeoutError:
            logger.warning("LLM 영수증 정리 시간 초과 (%.0fms)", _elapsed(started))
            raise TimeoutError from None
        except anthropic.APIError:
            logger.warning("LLM 영수증 정리 실패 (%.0fms)", _elapsed(started))
            raise OcrApiError("llm") from None
        except ValidationError:
            logger.warning("LLM 영수증 정리 모양 오류 (%.0fms)", _elapsed(started))
            raise OcrApiError("llm") from None
        output = response.parsed_output
        if response.stop_reason == "refusal" or output is None:
            logger.warning("LLM 영수증 정리 결과 없음: %s", response.stop_reason or "no_output")
            raise OcrApiError("llm")
        logger.info(
            "LLM 영수증 정리: 글자 %d자 → 구역 %d개 (%.0fms)",
            len(text),
            len(output.sections),
            _elapsed(started),
        )
        return ReceiptOcrResponse(
            hsptl_nm=output.hsptl_nm,
            ckup_ymd=_parse_date(output.ckup_ymd),
            recpt_amt=output.recpt_amt,
            btm_dscnt_amt=output.btm_dscnt_amt,
            sections=output.sections,
        )


def _elapsed(started: float) -> float:
    return (time.monotonic() - started) * 1000


def get_ocr_client(settings: Annotated[Settings, Depends(get_settings)]) -> OcrClient:
    api_key = settings.google_vision_api_key.get_secret_value()
    if not api_key:
        # 키 없는 PC·CI : 실제 API 미호출, 502 (키 값은 로그 제외)
        logger.error("OCR 호출 불가: .env.local의 GOOGLE_VISION_API_KEY가 비어 있습니다")
        raise external_error()
    return GoogleVisionOcrClient(
        api_key, get_anthropic_client(settings), settings.llm_model, settings.ocr_timeout_sec
    )
