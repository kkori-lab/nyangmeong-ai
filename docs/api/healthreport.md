# AI 건강분석 리포트 API (초안)

React(SCR-MAN-001 메인페이지 건강 지표 위젯 'AI 건강분석 리포트', MANC0007)가 부른다. 담당 LJS. 명세 밖 추가 요청(2026-11-04). 리포트 저장·새로고침 횟수·자동 재생성 횟수 판정은 Java(LJS 백엔드)가 하고, Python은 Java 내부 API(`internal.md` "Python → Java")로 입력을 받고 결과를 저장한다.

다시 만드는 기준은 "분석 입력이 바뀌었는가"다. Python이 기준일(`baseYmd`, KST 오늘)과 분석 입력으로 SHA-256 `inputHash`를 계산해 리포트와 함께 저장하고, 조회 때 저장본의 해시와 비교한다. 같으면 저장본, 다르면 새로 만든다. 날이 바뀌면 해시가 달라지므로 자정 갱신도 같은 규칙으로 된다(스케줄러 없음).

| 메서드 | 경로 | 설명 | 기능 ID | 담당 | 요청 DTO | 응답 DTO |
| --- | --- | --- | --- | --- | --- | --- |
| GET | /ai/pets/{petSn}/health-report | 오늘의 리포트. 저장본의 `inputHash`가 지금 입력과 같으면 저장본을 돌려준다(LLM 미호출). 다르거나 저장본이 없으면 LLM(`LLM_MODEL`)으로 만들고 Java에 저장한 뒤 돌려준다(저장이 실패해도 200, 다음 조회에서 다시 만든다). 입력이 바뀌었어도 Java의 자동 재생성 하루 상한(5회)을 넘었으면 LLM 없이 저장본을 `staleYn: true`로 돌려준다. 14일 기록이 하나도 없으면 LLM·저장 없이 `dataLackYn: true`와 고정 문구. 오류: Java 4xx(반려동물 접근 거부 등) 본문 그대로, 생성 시간 초과(`HEALTH_REPORT_TIMEOUT_SEC`, 기본 20초) 504 `HEALTH_REPORT_TIMEOUT`, 외부 API 오류 502 `HEALTH_REPORT_API_ERROR`, 생성이 필요한데 LLM 키 없음 502 `EXTERNAL_API_ERROR` | MAN-006 | LJS | - | HealthReportResponse |
| POST | /ai/pets/{petSn}/health-report/refresh | 새로고침(하루 1회, Java가 판정). 입력이 같아도 다시 만들고 `rfrshYn: true`로 저장한다. 입력이 바뀌어 자동으로 다시 만든 것은 횟수에 세지 않는다. 이미 새로고침했으면 LLM 없이 409 `HEALTH_REPORT_REFRESH_LIMIT`. 그 밖의 응답·오류는 GET과 같다. `X-Requested-With` 필요 | MAN-006 | LJS | - | HealthReportResponse |

### HealthReportResponse
쓰는 API: GET /ai/pets/{petSn}/health-report, POST /ai/pets/{petSn}/health-report/refresh
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| petSn | Long | Y | 경로의 반려동물 | MAN-006 |
| baseYmd | LocalDate | Y | 기준일(KST 오늘) | 건강기록 화면설계서 v0.4 "자정 자동 갱신" |
| rptTtl | String | Y | "{petNm}는 지금 ___"의 빈칸(20자 이내). 프론트가 이름과 이어 붙인다 | 메인 화면설계서 3번 |
| tips | String[] | Y | 1~3개, 각 40자 이내. 데이터 부족이면 고정 안내 1개 | 메인 화면설계서 3번 |
| notice | String | Y | 고정 문구 "AI 코멘트는 진단이 아니에요. 걱정되는 변화가 있으면 수의사와 상담해 주세요." | MANC0007 |
| dataLackYn | Boolean | Y | 14일 기록이 하나도 없어 분석하지 않음 | MAN-006 |
| staleYn | Boolean | Y | 최근 기록이 아직 반영되지 않은 저장본(자동 재생성 상한 초과). 프론트는 "최근 기록이 아직 반영되지 않았어요"를 보인다 | 2026-11-04 LJS 결정 |
| rfrshPsblYn | Boolean | Y | 오늘 새로고침할 수 있는가 | 건강기록 화면설계서 v0.4 "새로고침(1일 1회)" |
| crtDt | LocalDateTime | N | 리포트를 만든 시각. 데이터 부족이면 없음 | MAN-005 |
