# LJS 핸드오프

## 지금 하는 것
영수증·캐릭터 프론트 직접 호출 결정 반영(규칙 문서·마일스톤 재작성) — 끝 (검증 통과 1회차, 사람 확인 2026-10-27. 문서만, 코드 변경 없음. FN-AIM-013-02·09는 별도 SCR-AIM-013 마일스톤으로 넣음)
기획 상태: 승인됨
- 고른 이유: "다음에 할 것" 맨 위. 그 항목이 "다음 `/start`에서 마일스톤을 다시 만든다. 그 전에 규칙 문서를 고친다"고 순서를 정했다. 대기 맨 위 SCR-AIM-004는 이 뒤.
- 경로: 한 세션. 큰 변경 조건 중 "바꿀 파일 3개 이상"에 해당하지만 문서만 바꾼다(`.sap/config` 없음).
- 범위: 문서만. `app/ocr`·`app/character`의 경로를 `/ai/...`로 옮기는 코드, `docs/api/` 계약(`internal.md` OCR·캐릭터 행)은 바꾸지 않는다. 계약은 백엔드 PR과 함께 내야 하므로(`AGENTS.md` 4번) 새 마일스톤에서 기획한다.
- 바꿀 파일:
  - `AGENTS.md` 2번: "React는 AI 채팅만 `/ai/**`, 영수증·캐릭터는 Java 경유" → "React는 AI 채팅·영수증 OCR·캐릭터 생성을 `/ai/**`로 부른다(2026-10-27 결정). 원본·결과·상태 저장은 Python이 Java 내부 API로 요청한다". 패키지 구조의 `ocr/`·`character/` 줄도 같게.
  - `docs/convention/architecture.md`: 경계 그림 8·10·11행(React → Java 목록에서 영수증·캐릭터 빼기, Java → Python 줄 처리, Python → Java 줄에 원본·상태 저장 추가), 23행 "영수증·캐릭터" 항목.
  - `docs/convention/milestone.md`: "Python 몫" 표의 영수증·캐릭터 행, "먼저 나와야 하는 것"의 `PythonOcrClient`·`PythonCharacterGenerator` 행 → Java 원본·상태 저장 내부 API 행.
  - `README.md` 7~12행 표와 12행 문장, 62행 "사람 확인"의 `/internal/v1/**` 안내.
  - `milestones/LJS.md`: 통째로 다시 쓰지 않고 바뀌는 절만 고친다(사람 승인 2026-10-27, `— 끝` 절의 연결 남음 기록 보존). DMS 기능명세서(읽기만, 명세서는 고치지 않음) 기능 목록으로 대조한다. SCR-AIM-008을 새 마일스톤으로 다시 열고(FN-AIM-008-05·06·07 서버 부분, 010-01, 013-02·04·09, 원본 보관 008-09·010-06·013-08의 저장 요청), SCR-MYP-010도 결정 (2)에 따라 다시 연다.
- 확인한 현황(2026-10-27, 백엔드·프론트 origin/develop): Java는 `OcrClient`·`CharacterGenerator`를 가짜 구현(`FakeOcrClient`·`FakeCharacterGenerator`)으로 직접 쓰고 Python 클라이언트는 없다. Python `/internal/v1/**`를 부르는 곳 없음. Java 영수증 흐름(`/api/receipts` 업로드·OCR·재분석·취소·저장)과 캐릭터 생성(`/api/pets/{petSn}/pixel-characters`, `@Async` 작업)이 Java에 있다. 프론트의 영수증 인식 3곳·캐릭터 생성은 가짜 응답이고 어느 서버에도 연결되지 않았다.
- 결정(사람, 2026-10-27 재확인): 프론트 → Python 직접 호출 유지. 백엔드 영수증·캐릭터 흐름은 백엔드에서 재설계한다. 따라서 Java → Python `/internal/v1/**`는 문서에서 폐기 예정으로 적는다(코드·`docs/api/internal.md` 삭제는 백엔드 PR과 함께, 새 마일스톤에서).
- 백엔드 재설계는 이 저장소 범위 밖. 마일스톤의 "기다리는 것"과 milestone.md "먼저 나와야 하는 것"에 "Java 영수증·캐릭터 저장·상태 내부 API(재설계, LJS 백엔드)"로 적는다.
- 결정(사람, 2026-10-27): 캐릭터 생성은 A안 — Java가 작업 상태를 갖는다. 프론트 → Python 생성 요청 → Python이 Java에 작업 생성 요청 후 202·작업 번호 반환 → Python이 백그라운드에서 생성하고 결과·상태를 Java 내부 API로 보냄 → 프론트는 Java에서 상태 조회. 생성 중 Python이 죽어 멈춘 작업의 타임아웃 정리는 Java 몫.
- 결정(사람, 2026-10-27): 검사결과지 PDF 분석(SCR-HLT-005)도 Python 몫. 건강기록_기능명세서_v1.1_20261026(DMS)에서 Python 몫은 FN-HLT-005-04 PDF 분석의 인식 부분만(결과는 SCR-HLT-007 입력값). 버튼 노출·SCR-HLT-007 이동은 프론트, 첨부 파일 보관·검사 수치 저장은 Java. 현재 Java에는 오류 코드 `CHECKUP_ATTACHMENT_NOT_ANALYZABLE`만 있고 분석 API는 없다. 프론트 `api.js`에도 없다.
  - 새 마일스톤에서 정할 것: PDF 원본이 Java 첨부 자료에 있으므로 Python이 받는 방법(프론트가 파일을 다시 올림 / Python이 첨부 번호로 Java 내부 API에서 받음).
- 추가로 바꿀 곳: `docs/convention/milestone.md` "담당" 표의 읽을 기능명세서에 "건강기록(SCR-HLT-005만)", "Python 몫" 표에 검사결과지 PDF 행. 마일스톤 "대조"에 건강기록 명세 건수 줄.
- 완료 조건 `명령:` `grep -rn "internal/v1" AGENTS.md README.md docs/convention`의 결과가 "폐기 예정" 문장뿐.
- 완료 조건 `명령:` `milestones/LJS.md` "대조"에서 AI매니저 147 = 마일스톤 + 제외, 마이페이지 116 = 마일스톤 + 제외, 건강기록 명세 전체 = 마일스톤 + 제외.
- 공통: 코드 변경 없음(`sh scripts/check.sh` 생략 사유).
새 의존성: 없음

## 다음에 할 것
- 다음 `/start`는 대기 맨 위 SCR-AIM-004. 새 대기 마일스톤 4개(SCR-AIM-008 전환·SCR-AIM-013·SCR-MYP-010 전환·SCR-HLT-005)는 맨 뒤에 둠
- 백엔드에 요청(LJS 백엔드, 영수증·캐릭터 흐름 재설계): Python이 부를 원본 이미지·RECPT·영수증 상태(AIMG01) 저장, 캐릭터 작업 생성·결과·상태 보고, (PDF를 Java에서 받는 방법이면) 첨부 조회 내부 API. 계약은 이 저장소 `docs/api/internal.md`의 `/internal/v1/**` 삭제와 같은 때 병합
- SCR-HLT-005 기획 때 정할 것: Python이 PDF를 받는 방법(React가 다시 올림 / 첨부 번호로 Java에서 받음), 인식 결과 모양(SCR-HLT-007 입력값)
- 계약은 백엔드 PR과 함께 낸다(`AGENTS.md` 4번): 백엔드 LJS의 `ai` 도메인(대화 내부 API, 정본 백엔드 `docs/api/ai.md`, 10-27 PR 전)·서버 간 키 제거. 이 저장소 `docs/api/internal.md`와 같은 때 병합
- 각자 `.env.local` 정리: `BACKEND_INTERNAL_KEY`·`INTERNAL_API_KEY`·`APP_PROFILE`·`*_DB_*`·`CONVERSATION_ENC_KEY` 삭제, `BACKEND_BASE_URL` 필수(없으면 `/ai/**` 전부 502). 운영 Nginx가 `/internal`을 막는지 확인
- 연결 남음: SCR-AIM-011 FN-AIM-011-11 제목 생성 real 클라이언트 (LLM 제공자 Anthropic 2026-10-28 결정, 키·모델 정한 뒤, LJS)
- 연결 남음: SCR-MYP-010 real 이미지 생성 클라이언트와 얼굴 영역·샘플 10건 이상 검증 (OpenAI GPT 2026-10-28 결정, 키·모델 정한 뒤, LJS)
- 연결 남음: SCR-AIM-008 real 모드 Google Vision 클라이언트 (서비스 계정 키 수령 후, LJS)
- 하네스 수정 PR 후보(공용): `verify-collect.sh:18` `cut -c8-` 멀티바이트 문제, `start-check.sh` 수정분, macOS BSD `sed`(`milestone-status.sh`·`impl-check.sh`·`api-row.sh`), `verify-collect.sh:37-38` `case` 문법
- `docs/api/internal.md` OCR mock은 고정 응답 1개(Java `FakeOcrClient` 시나리오 미구현). 필요해지면 구현
- 이 PC는 애플리케이션 제어 정책이 `.venv\Scripts\*.exe`(uvicorn 등)를 막는다. `uv run python -m uvicorn ...`으로 띄운다
