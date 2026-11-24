# 피부 병변 분석 API (초안)

React(화면 ID 미정, 기능명세서 FN 행 작성 전)가 부른다. 대화창·메인 검색창에서는 사진 용도 판단(`/ai/image-intent`, `chat.md`)이 `SKIN`이면 React가 같은 사진으로 이 API를 부른다(2026-11-24). 담당 LJS. 반려동물 피부 사진 1장을 LLM(`LLM_MODEL`)이 정해진 병변 목록(`data/skin_lesions.yaml`) 안에서 판정하고, 등급은 규칙(`app/skinlesion/rules.py`, `ruleVersion`)이 정한다(2026-11-24 결정: YOLO는 그다음 검토). 결과는 저장하지 않는다(Java 저장·`petSn`은 다음 마일스톤). 참고용 분석이며 진단이 아니다.

| 메서드 | 경로 | 설명 | 기능 ID | 담당 | 요청 DTO | 응답 DTO |
| --- | --- | --- | --- | --- | --- | --- |
| POST | /ai/skin-analyses | 사진(multipart) 1장을 긴 변 1024px JPEG로 줄여 LLM에 보내고, 반려동물 피부 사진인지와 목록 중 해당하는 병변(최대 3개, 확신도 HIGH·MEDIUM·LOW)을 한 번에 받는다. LLM은 목록 밖 값을 말할 수 없다(출력 스키마 enum). 등급: 확신도 LOW를 뺀 병변이 없으면 `UNCLEAR`, 있으면 그중 위험군이 가장 높은 것(이상 없음만이면 `OBSERVE`). 안내문·`notice`는 목록 파일의 고정 문장이다(LLM이 쓰지 않음). 반려동물 정보는 LLM에 보내지 않는다(POL-006). LLM 거절·깨진 출력은 오류 대신 200 `UNCLEAR`. 성공 200. 오류: 형식(확장자·실제 형식 불일치, 열 수 없는 이미지) 400 `FILE_TYPE_NOT_ALLOWED`, 10MB 초과 400 `FILE_SIZE_EXCEEDED`, 파일 없음 400 `INVALID_REQUEST`(검증 실패는 LLM을 부르지 않는다), 분석 시간 초과(`SKIN_ANALYZE_TIMEOUT_SEC`, 기본 20초) 504 `SKIN_ANALYZE_TIMEOUT`, 외부 API 오류 502 `SKIN_ANALYZE_API_ERROR`, LLM 키 없음 502 `EXTERNAL_API_ERROR` | 없음(명세 전) | LJS | SkinAnalysisRequest | SkinAnalysisResponse |

### SkinAnalysisRequest
쓰는 API: POST /ai/skin-analyses (multipart/form-data)
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| file | 파일 | Y | jpg·jpeg·png·webp, 10MB 이하. 확장자와 실제 형식(시그니처)이 같아야 한다 | REQ-NFR-003 |

### SkinAnalysisResponse
쓰는 API: POST /ai/skin-analyses
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| rslt | String | Y | `ANALYZED`(판정함), `NOT_PET_SKIN`(반려동물 피부 사진이 아님), `UNCLEAR`(사진으로 판단하기 어려움) | 2026-11-24 결정 |
| grade | String | N | `OBSERVE`(지켜보기), `VISIT`(진료 권장), `URGENT`(빨리 진료). `ANALYZED`일 때만 값, 그 밖에는 null | 2026-11-24 결정 |
| findings | SkinFinding[] | Y | 등급에 쓴 병변(확신도 HIGH·MEDIUM). 위험군 높은 순, 최대 3개. 다른 병변이 있으면 "이상 없음"은 빼고, `ANALYZED`가 아니면 빈 배열 | 2026-11-24 결정 |
| guide | String[] | Y | 보호자 안내 문장(목록 파일의 고정 문장, `rslt`·`grade`별) | 2026-11-24 결정 |
| notice | String | Y | 참고용 분석·수의사 상담 문구. 화면에 항상 보인다 | 2026-11-24 결정 |
| ruleVersion | String | Y | 목록·등급 규칙 판(`data/skin_lesions.yaml` `rule_version`). 저장 때 함께 남긴다 | 2026-11-24 결정 |

### SkinFinding
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| lesionCd | String | Y | 병변 키(`data/skin_lesions.yaml`의 `key`, 예: `hair_loss`). DB 공통코드가 아니다. Java 저장을 붙일 때 맞춘다 | 2026-11-24 결정 |
| lesionNm | String | Y | 병변 이름(목록 파일의 `name`) | 2026-11-24 결정 |
| cnfdnc | String | Y | 확신도 `HIGH`·`MEDIUM` | 2026-11-24 결정 |
