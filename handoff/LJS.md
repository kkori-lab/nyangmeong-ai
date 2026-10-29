# LJS 핸드오프

## 지금 하는 것
명세 갱신(DMS) · AI매니저 기능명세서 FN-AIM-004에 PR #13 결정 반영 — 끝 (검증 통과, 사람 확인 2026-10-29. DMS 버전 12 `AI매니저_기능명세서_v0.10_20261029.xlsx`, 추가-1로 v1.0 표기를 v0.10으로 정정)
기획 상태: 승인됨 (2026-10-29 11:18)
- 고른 이유: "다음에 할 것" 맨 위. 마일스톤 절이 아닌 문서 작업이라 `milestone-status.sh`는 돌리지 않는다. 이전 작업(SCR-AIM-002 연결 끊김 정정·추가 요청 3건, 끝, PR #13 병합) 기획은 git 이력(47225df)에 있다.
- 범위 밖: `app/`·`tests/`·`docs/api/` 코드·계약은 바꾸지 않는다(이미 PR #13에 반영). 화면설계서는 문구 예시만 다루므로 그대로.
- 대상 파일: DMS `AI매니저_기능명세서_v0.9_20261026.xlsx`(문서 id `cmtwkb4h9000104latsavkapc`, 최신 v10) → 새 버전 `AI매니저_기능명세서_v1.0_20261029.xlsx`로 `add_version`. 편집은 스크래치 폴더에서 `uv run --with openpyxl`(프로젝트 의존성 아님)로 셀 글자만 바꾸고 서식은 그대로 둔다. 변경 이력 시트가 있으면 한 줄 추가.
- FN-AIM-004-02(AI 의도 분류) 기능 설명 뒤에 덧붙임: "AI 분류 호출이 실패(외부 API 오류)하면 폴백(SCR-AIM-005)으로 넘기지 않고 일시 오류로 안내하며 [다시 시도]를 띄운다. 이 오류는 연속 실패로 세지 않는다. 룰 매칭(FN-AIM-004-01)은 AI 장애와 무관하게 동작한다." 비고에 "/ v1.0 분류 장애는 오류(2026-10-29 결정)". 코드 근거: `app/chat/service.py:216`.
- FN-AIM-004-03(이동 안내 표출) 기능 설명의 저장 문장을 구체화: "안내 문구('<화면명>(으)로 이동할게요')는 AI 역할 메시지로 대화 이력에 저장하여 대화를 다시 열어도 남는다(이어 보기·AI 컨텍스트에 포함)." 비고에 "/ v1.0 문구 확정(2026-10-29)". 코드 근거: `app/chat/service.py:122`.
- FN-AIM-004-12(매칭 실패 분기) 끝에 덧붙임: "AI 분류가 판단 불가로 답한 경우만 해당하며, AI 분류 호출 실패는 FN-AIM-004-02대로 오류로 처리한다."
- 완료 조건 `명령:` 새 버전 업로드 뒤 `sh scripts/dms-fetch.sh AI매니저_기능명세서_v1.0_20261029.xlsx SCR-AIM-004` 출력에 위 세 행 문구가 보이고, 다른 행(FN-AIM-004-01·04~11·13)은 v0.9와 같다(두 출력 diff).
- 완료 조건 `화면:` DMS에서 새 버전 엑셀을 열어 서식(열 너비·줄바꿈·병합)이 깨지지 않았는지 사람이 확인.
- 하지 않는 것: 추가-3(15자 이하 첫 메시지는 그대로 제목)은 FN-AIM-011 몫이고 "다음에 할 것"에 없어 이번 범위 밖. 필요하면 승인 때 말해 주면 같은 버전에 넣는다.
새 의존성: 없음(openpyxl은 `uv run --with`로 일회성 실행, `pyproject.toml` 변경 없음)

### 추가 요청
| 번호 | 바꿀 파일 | 완료 조건 | 요청 |
| --- | --- | --- | --- |
| 추가-1 | DMS `AI매니저_기능명세서_v0.10_20261029.xlsx`(문서 `cmtwkb4h9000104latsavkapc` 새 버전) | 명령: 새 버전 추출본(SCR-AIM-004)에 `v1.0` 글자가 없고 `v0.10`으로 바뀜, 그 밖의 셀은 버전 11과 같음. 화면: 표지·제.개정내역 맨 위 행이 v0.10 | 요청 2026-10-29 11:30 "문서 제목을 0.10으로 바꿨음. 올린 것(버전 11) 삭제하고 0.10으로 버전 수정해서 다시 올리자" |

## 다음에 할 것
- DMS AI매니저 기능명세서 버전 11(v1.0 표기, 버전 12로 대체)은 MCP에 삭제 도구가 없어 남아 있을 수 있다. 남아 있으면 DMS 화면에서 지운다(LJS)
- 명세 갱신 후보(LJS, DMS): FN-AIM-011에 15자 이하 첫 메시지는 그대로 제목(PR #13 추가-3)
- 프론트(LJS)가 맞출 것: ROUTE 뒤 `done.message`(저장된 이동 안내)와 화면 안내 겹침 정리, 분류 장애 `error`는 연속 실패로 세지 않고 [다시 시도]. 프론트 세션에 알림(2026-10-29)
- 백엔드에 요청(LJS 백엔드): 대화 제목 수정 내부 API. 마일스톤 "첫 답변 요약 제목"이 기다림
- 다음 `/start`는 대기 맨 위 SCR-AIM-012(등록 카드). 메시지 API의 REGISTER 판정 뒤 흐름을 잇는다
- 백엔드에 요청(LJS 백엔드): AI 설정값 조회 내부 API(SYS_STNG_AI_TKN_UPLMT_CNT·SYS_STNG_AI_CNVRS_TURN_CNT, 연결되면 가짜 `get_ai_settings` 교체), AI 역할 메시지 `cnvrsCn` 1,000자 상한 확대(상한 없이 저장 요청 중, 넘으면 저장 실패). `docs/api/internal.md` "미정" 행은 "설정값 조회"만 남긴다(최근 6턴은 GET 대화, 미완료 완료 처리는 불필요)
- 프론트(LJS)와 맞출 것: 메시지 API SSE 이벤트(`intent`·`delta`·`done`·`error`, `chat.md` MessageEvent), 화면 ID → 프론트 경로 변환, 칩 재노출·연속 실패 카운트·FAQ 버튼(FN-AIM-005-03~06)은 프론트 몫
- 백엔드에 요청(LJS 백엔드, 영수증·캐릭터 흐름 재설계): Python이 부를 원본 이미지·RECPT·영수증 상태(AIMG01) 저장, 캐릭터 작업 생성·결과·상태 보고, (PDF를 Java에서 받는 방법이면) 첨부 조회 내부 API. 계약은 이 저장소 `docs/api/internal.md`의 `/internal/v1/**` 삭제와 같은 때 병합
- SCR-HLT-005 기획 때 정할 것: Python이 PDF를 받는 방법(React가 다시 올림 / 첨부 번호로 Java에서 받음), 인식 결과 모양(SCR-HLT-007 입력값)
- 계약은 백엔드 PR과 함께 낸다(`AGENTS.md` 4번): 백엔드 LJS의 `ai` 도메인(대화 내부 API, 정본 백엔드 `docs/api/ai.md`, 10-27 PR 전)·서버 간 키 제거. 이 저장소 `docs/api/internal.md`와 같은 때 병합
- 각자 `.env.local` 정리: `BACKEND_INTERNAL_KEY`·`INTERNAL_API_KEY`·`APP_PROFILE`·`*_DB_*`·`CONVERSATION_ENC_KEY` 삭제, `BACKEND_BASE_URL` 필수(없으면 `/ai/**` 전부 502). 운영 Nginx가 `/internal`을 막는지 확인
- 연결 남음: SCR-MYP-010 real 이미지 생성 클라이언트와 얼굴 영역·샘플 10건 이상 검증 (OpenAI GPT 2026-10-28 결정, 키·모델 정한 뒤, LJS)
- 연결 남음: SCR-AIM-008 real 모드 Google Vision 클라이언트 (서비스 계정 키 수령 후, LJS)
- 하네스 수정 PR 후보(공용): `verify-collect.sh:18` `cut -c8-` 멀티바이트 문제, `start-check.sh` 수정분, macOS BSD `sed`(`milestone-status.sh`·`impl-check.sh`·`api-row.sh`. `sed -i`가 실패해도 두 스크립트 모두 종료 코드 0이고 `impl-check.sh`는 "바꿈:"까지 출력한다, 2026-10-28 실측), `verify-collect.sh:37-38` `case` 문법, `impl-check.sh:18`이 "질문" 글자가 든 줄(제목 "검색 질문/응답" 등)을 모두 질문으로 읽음
- `docs/api/internal.md` OCR mock은 고정 응답 1개(Java `FakeOcrClient` 시나리오 미구현). 필요해지면 구현
- 이 PC는 애플리케이션 제어 정책이 `.venv\Scripts\*.exe`(uvicorn 등)를 막는다. `uv run python -m uvicorn ...`으로 띄운다
