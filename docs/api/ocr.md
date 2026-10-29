# 영수증 분석 API·DTO (초안)

React가 부르는 `/ai/**` API다. 공통 규칙은 `docs/api/README.md`에 있다. 이 문서는 건강 일지의 영수증 촬영·업로드(SCR-AIM-008)와 실패 판정(SCR-AIM-010)을 다룬다. AI 대화창 영수증 분석(SCR-AIM-013)도 같은 API를 출처 `AIMC0031`로 부르고, 대화 이력 저장은 `chat.md` `receipt-result`로 한다.

- 인증: `chat.md`와 같다. 쿠키 `access_token`을 Java `/internal/auth/check`로 확인하고, 인증 오류는 본문·`Set-Cookie` 그대로, Java에 닿지 못하면 502 `EXTERNAL_API_ERROR`. `X-Requested-With: XMLHttpRequest`가 없으면 403 `FORBIDDEN`.
- 흐름: 업로드 검증 → Java에 원본 저장(영수증 생성) → Google Vision 글자 인식 → LLM이 항목으로 정리 → Java에 결과·상태 보고 → 응답. Java 영수증 저장·상태 내부 API는 아직 없어 가짜(`app/ocr/repository.py` `FakeReceiptRepository`)로 돈다(`internal.md` "Python → Java" 미정 행).
- 확인 모달 뒤 검진기록 저장, 직접 입력 저장 시 영수증 상태 변경(FN-AIM-010-06)은 Java가 한다.

## API 목록

| 메서드 | 경로 | 설명 | 기능 ID | 담당 | 요청 DTO | 응답 DTO |
| --- | --- | --- | --- | --- | --- | --- |
| POST | /ai/receipts | 영수증 이미지(multipart)를 분석한다. 원본은 분석 전에 Java에 저장한다(실패해도 유지). 추출 0건도 200(`ocr` 값이 모두 null, `sections` 빈 배열, 상태 인식실패). 같은 회원의 분석이 진행 중이면 409 `OCR_IN_PROGRESS`. 분석 제한 15초(Vision·LLM 합계). [취소]는 React가 요청을 끊는 것이다(Python이 끊김을 감지해 분석을 멈추고 상태 취소를 보고, 응답 없음). 오류: 형식(확장자·실제 형식 불일치, PDF 포함) 400 `FILE_TYPE_NOT_ALLOWED`, 10MB 초과 400 `FILE_SIZE_EXCEEDED`, 폼 값 없음·`ocrRqstSrcCd` 허용값 밖 400 `INVALID_REQUEST`(검증 실패는 Java·OCR을 부르지 않는다), 분석 시간 초과 504 `OCR_TIMEOUT`, 외부 API 오류 502 `OCR_API_ERROR`, OCR 키가 없음 502 `EXTERNAL_API_ERROR`, Java 원본 저장 실패는 Java 4xx 그대로·연결 실패 502 `EXTERNAL_API_ERROR` | AIM-008-05·06·07·09, AIM-010-01·06, AIM-013-04 | LJS | ReceiptAnalyzeRequest | ReceiptAnalyzeResponse |

## DTO

### ReceiptAnalyzeRequest
쓰는 API: POST /ai/receipts (multipart/form-data)
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| file | 파일 | Y | jpg·jpeg·png·webp, 10MB 이하. 확장자와 실제 형식(파일 시그니처)이 같아야 한다. PDF 불가 | AIM-008-05 |
| petSn | Long | Y | 기록이 귀속될 반려동물. 소유 검사는 Java가 원본 저장 때 한다 | AIM-008-03 |
| ocrRqstSrcCd | String | Y | 요청 출처(AIMG07). 건강 일지 `AIMC0026`, AI 대화창 `AIMC0031`(2026-10-29 신설, 백엔드 공통코드 변경과 같은 때 병합). 가계부 `AIMC0027`은 받지 않는다 | AIM-013-04 |

### ReceiptAnalyzeResponse
쓰는 API: POST /ai/receipts
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| recptSn | Long | Y | Java가 만든 영수증 번호(RECPT). 확인 모달 뒤 저장할 때 Java에 넘긴다 | AIM-008-09 |
| ocr | ReceiptOcrResponse | Y | 인식 결과. 모양은 `internal.md` ReceiptOcrResponse와 같다(백엔드와 맞춘 DTO를 바꾸지 않고 감쌌다) | AIM-009-02 |
