# 검사결과지 PDF 분석 API (초안)

React(SCR-HLT-005 검진상세 첨부 자료 탭 [PDF 분석])가 부른다. 담당 LJS. 결과는 저장하지 않는다. 보호자가 SCR-HLT-007에서 확인·수정한 뒤 React가 Java에 저장한다(FN-HLT-007-04).

| 메서드 | 경로 | 설명 | 기능 ID | 담당 | 요청 DTO | 응답 DTO |
| --- | --- | --- | --- | --- | --- | --- |
| POST | /ai/checkups/lab-results | 검사결과지 PDF(multipart) 1건을 읽어 SCR-HLT-007 입력값 모양의 혈액검사 항목을 돌려준다(이름은 백엔드 InspectionAnalysisItem과 같다). React가 첨부 자료의 파일을 다시 올린다(2026-10-30 결정, Java 첨부 조회를 거치지 않음). 인식은 LLM(`LLM_MODEL`)에 PDF를 그대로 보낸다. 인식 항목 0건도 200(`items` 빈 배열). 다시 분석의 중복 요청 차단은 React 버튼 잠금으로 한다(FN-HLT-007-06). 오류: PDF 아님·확장자와 실제 형식 불일치 400 `FILE_TYPE_NOT_ALLOWED`, 10MB 초과 400 `FILE_SIZE_EXCEEDED`, 파일 없음 400 `INVALID_REQUEST`(검증 실패는 LLM을 부르지 않는다), 검사결과지가 아님 422 `NOT_LAB_RESULT`, 분석 시간 초과(`PDF_ANALYZE_TIMEOUT_SEC`, 기본 30초) 504 `PDF_ANALYZE_TIMEOUT`, 외부 API 오류 502 `PDF_ANALYZE_API_ERROR`, LLM 키가 없음 502 `EXTERNAL_API_ERROR`. 실패·시간 초과는 React가 SCR-HLT-005에서 사유를 안내한다 | HLT-005-04 | LJS | LabResultAnalyzeRequest | LabResultAnalyzeResponse |

### LabResultAnalyzeRequest
쓰는 API: POST /ai/checkups/lab-results (multipart/form-data)
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| file | 파일 | Y | PDF만, 10MB 이하. 확장자 `.pdf`와 실제 형식(시그니처 `%PDF-`)이 같아야 한다 | HLT-005-04, REQ-NFR-003 |

### LabResultAnalyzeResponse
쓰는 API: POST /ai/checkups/lab-results
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| items | LabResultItem[] | Y | 인식한 혈액검사 항목. 결과지 순서. 없으면 빈 배열 | HLT-007-04·05 |
| excludedArtclNms | String[] | Y | 혈액검사가 아니라서 뺀 항목 이름(결과지 표기 그대로, 안내용). 없으면 빈 배열. 백엔드 InspectionAnalysisResponse와 같은 이름 | HLT-007-05 |

### LabResultItem
필드 이름과 크기는 백엔드 `docs/api/health.md` InspectionAnalysisItem(`INSP_NVL` 컬럼, DDL v0.10)과 같다. 그 DTO의 `registered`(같은 검진기록에 이미 있는 항목)는 Python이 검진기록을 모르므로 주지 않는다. React가 검진상세의 혈액검사 목록으로 판정한다.
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| inspArtclCd | String | N | 검사항목 공통코드(HLTG12). 드롭다운 항목이면 이 값, 아니면 null. 별칭(예: `Creatinine`·`CRE`)도 같은 코드로 맞춘다(`data/lab_items.yaml`) | INSP_NVL.INSP_ARTCL_CD, HLT-007-02·04 |
| inspArtclDrctInptNm | String | N | `inspArtclCd`가 null일 때 항목명(결과지 표기, 최대 40자). HLTG12에 코드가 없는 SDMA는 `SDMA` | INSP_NVL.INSP_ARTCL_DRCT_INPT_NM, HLT-007-04 |
| rsltNvl | Number | N | 결과수치. 못 읽었거나 숫자가 아니면(`<0.5`·`음성`) 또는 decimal(15,4)에 안 들어가면 null(사용자가 직접 입력) | INSP_NVL.RSLT_NVL, HLT-007-04 |
| unitNm | String | N | 단위(최대 20자). 못 읽으면 null | INSP_NVL.UNIT_NM, HLT-007-02 |
| refLlmtNvl | Number | N | 참고하한. 하한·상한 중 한쪽만 읽히면 둘 다 null | INSP_NVL.REF_LLMT_NVL, HLT-007-02 |
| refUplmtNvl | Number | N | 참고상한. 규칙은 refLlmtNvl과 같다 | INSP_NVL.REF_UPLMT_NVL, HLT-007-02 |
