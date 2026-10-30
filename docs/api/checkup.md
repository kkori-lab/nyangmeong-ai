# 검사결과지 PDF 분석 API (초안)

React(SCR-HLT-005 검진상세 첨부 자료 탭 [PDF 분석])가 부른다. 담당 LJS. 결과는 저장하지 않는다. 보호자가 SCR-HLT-007에서 확인·수정한 뒤 React가 Java에 저장한다(FN-HLT-007-04).

| 메서드 | 경로 | 설명 | 기능 ID | 담당 | 요청 DTO | 응답 DTO |
| --- | --- | --- | --- | --- | --- | --- |
| POST | /ai/checkups/lab-results | 검사결과지 PDF(multipart) 1건을 읽어 SCR-HLT-007 입력값 모양의 검사 항목을 돌려준다. React가 첨부 자료의 파일을 다시 올린다(2026-10-30 결정, Java 첨부 조회를 거치지 않음). 인식은 LLM(`LLM_MODEL`)에 PDF를 그대로 보낸다. 인식 항목 0건도 200(`items` 빈 배열). 다시 분석의 중복 요청 차단은 React 버튼 잠금으로 한다(FN-HLT-007-06). 오류: PDF 아님·확장자와 실제 형식 불일치 400 `FILE_TYPE_NOT_ALLOWED`, 10MB 초과 400 `FILE_SIZE_EXCEEDED`, 파일 없음 400 `INVALID_REQUEST`(검증 실패는 LLM을 부르지 않는다), 검사결과지가 아님 422 `NOT_LAB_RESULT`, 분석 시간 초과(`PDF_ANALYZE_TIMEOUT_SEC`, 기본 30초) 504 `PDF_ANALYZE_TIMEOUT`, 외부 API 오류 502 `PDF_ANALYZE_API_ERROR`, LLM 키가 없음 502 `EXTERNAL_API_ERROR`. 실패·시간 초과는 React가 SCR-HLT-005에서 사유를 안내한다 | HLT-005-04 | LJS | LabResultAnalyzeRequest | LabResultAnalyzeResponse |

### LabResultAnalyzeRequest
쓰는 API: POST /ai/checkups/lab-results (multipart/form-data)
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| file | 파일 | Y | PDF만, 10MB 이하. 확장자 `.pdf`와 실제 형식(시그니처 `%PDF-`)이 같아야 한다 | HLT-005-04, REQ-NFR-003 |

### LabResultAnalyzeResponse
쓰는 API: POST /ai/checkups/lab-results
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| items | LabResultItem[] | Y | 인식한 검사 항목. 결과지 순서. 없으면 빈 배열 | HLT-007-04 |

### LabResultItem
필드 이름은 ERD를 보지 못한 초안이다. 건강기록 백엔드의 검사 수치 저장 DTO와 맞춘 뒤 백엔드 PR과 함께 병합한다.
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| inspArtclNm | String | Y | 검사 항목. 드롭다운 12종(WBC·RBC·HGB·HCT·PLT·BUN·CREA·SDMA·ALT·AST·ALP·GLU)이면 표준 약어로 맞춘다(예: `Creatinine`·`CRE` → `CREA`, `data/lab_items.yaml`). 목록 밖은 결과지 표기 그대로(직접입력) | HLT-007-02 |
| rsltVl | String | N | 결과값. 숫자 문자열(예: `1.2`). 못 읽었거나 숫자가 아니면 null(사용자가 직접 입력) | HLT-007-04 |
| unitNm | String | N | 단위(예: `mg/dL`). 못 읽으면 null | HLT-007-02 |
| refMinVl | String | N | 참고범위 최소. 숫자 문자열. 최소·최대 중 한쪽만 읽히면 둘 다 null | HLT-007-02 |
| refMaxVl | String | N | 참고범위 최대. 규칙은 refMinVl과 같다 | HLT-007-02 |
| bloodYn | String | Y | 혈액검사 항목이면 `Y`, 아니면 `N`. `N`인 행은 React가 저장 대상에서 빼고 안내한다 | HLT-007-05 |
