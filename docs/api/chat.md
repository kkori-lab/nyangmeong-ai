# AI 대화창 API·DTO (초안)

React가 부르는 `/ai/**` API다. 공통 규칙은 `docs/api/README.md`에 있다. 이 문서는 대화 저장·조회·삭제(SCR-AIM-011)와 메시지 전송·AI 답변(SCR-AIM-002, 판정은 SCR-AIM-004·005)을 다룬다. 등록 카드(SCR-AIM-012)와 2단계 쓰기 확인 카드(`intent.kind=ACTION`, 초안 2026-11-09)도 다룬다. 대화창 영수증 분석(SCR-AIM-013)의 대화 이력 저장도 다룬다(분석 자체는 `ocr.md` `POST /ai/receipts`).

- 인증: 요청마다 쿠키 `access_token`을 Java `/internal/auth/check`로 확인한다(`docs/api/README.md`). 토큰이 없거나 틀리면 401 `UNAUTHORIZED`, 만료면 401 `TOKEN_EXPIRED`, 정지·탈퇴면 403 `MEMBER_INACTIVE`(쿠키 삭제 `Set-Cookie` 포함), Java에 닿지 못하면 502 `EXTERNAL_API_ERROR`.
- POST·DELETE는 `X-Requested-With: XMLHttpRequest`가 없으면 403 `FORBIDDEN`이다.
- 본인 대화만 다룬다. 남의 대화·없는 번호는 없는 것으로 보고 404 `NOT_FOUND`를 준다. 전환 후에는 Java 대화 API가 판정한다(오류 코드 이름은 Java 설계 확정 후 맞춘다).
- 제목과 본문은 DB에 암호문(`CNVRS_TTL_ENC`·`CNVRS_CN_ENC`)으로 저장하고, 응답은 복호화한 값이다. 전환 후 암호화는 Java `FieldCryptoService`가 한다. 아래 경로·DTO(React와의 계약)는 전환 후에도 그대로 둔다.
- `petSn`은 대화의 펫 태그(구분값)다. 소유권은 검사하지 않는다(Java 담당). null이면 "전체" 대화다.

## API 목록

| 메서드 | 경로 | 설명 | 기능 ID | 담당 | 요청 DTO | 응답 DTO |
| --- | --- | --- | --- | --- | --- | --- |
| GET | /ai/me | 인증 확인용. Java `/internal/auth/check` 결과의 회원 번호만 준다. 오류: Java 인증 오류(401·403) 본문·`Set-Cookie` 그대로, Java에 닿지 못하면 502 `EXTERNAL_API_ERROR` | AIM-011-03 | LJS | - | `{mbrSn: Long}` |
| POST | /ai/conversations | 새 대화를 만든다. 첫 메시지로 제목을 자동 생성(30자 이내, 1회. Java 저장 상한은 200)하고, 방과 첫 메시지(사용자 역할)를 함께 저장한다. 오류: 본문 비었거나 공백만·1,000자 초과 400 `INVALID_REQUEST`. 성공은 201 | AIM-011-07·11·14 | LJS | ConversationCreateRequest | ConversationSummary |
| GET | /ai/conversations | 내 대화 목록을 최신순으로 준다. 쿼리 `petSn`을 주면 그 태그의 대화만(태그가 null인 "전체" 대화는 나오지 않는다), 없으면 전부. 오늘·어제·지난 7일 그룹은 React가 `regDt`로 나눈다. 없으면 빈 배열 | AIM-011-08·09 | LJS | - | List<ConversationSummary> |
| GET | /ai/conversations/{aiCnvrsRoomSn} | 대화 하나와 메시지를 순서대로 준다. 남의 대화·없는 번호 404 `NOT_FOUND` | AIM-011-10 | LJS | - | ConversationDetail |
| DELETE | /ai/conversations/{aiCnvrsRoomSn} | 대화와 메시지를 물리 삭제한다(복구 불가). 남의 대화·없는 번호 404 `NOT_FOUND` | AIM-011-13 | LJS | - | - |
| POST | /ai/conversations/{aiCnvrsRoomSn}/messages | 메시지를 보내고 판정·답변을 SSE(`text/event-stream`)로 받는다. `cnvrsCn`이 있으면 사용자 메시지로 저장하고 답한다. 없으면 저장 없이 방의 마지막 사용자 메시지에 답한다(첫 메시지 직후·[다시 시도]·[다시 생성]). 판정이 SEARCH면 LLM 답변을 흘리고 끝에 의료 고지를 붙여 저장, FALLBACK이면 안내 문구를 저장, ROUTE면 이동 안내("<화면명>(으)로 이동할게요")를 저장, REGISTER면 `done.card`로 미리보기 카드나 되물음을 준다(되물음 문구만 저장, 카드는 저장 안 함. 2026-11-09 ④부터 옛 등록 카드의 `draft` 이어 쓰기에서만 나온다, 프론트 전환 뒤 삭제), ACTION이면 `done.action`으로 확인 카드를 주고 카드 요약 글("이렇게 할까요?
<반려동물> <label> — <값> · …" + 빈 칸이 있으면 "아직 <칸>이(가) 비어 있어요. 말로 알려 주세요.", 없으면 "맞으면 '등록해 줘'라고 말해 주세요. …". 요약 줄 뒤에 회원이 말한 수를 Java 소수 자리로 반올림했으면 "소수 둘째 자리까지라 4.57kg로 적을게요.", 사진 칸이 빈 카드면 "사진은 카드에서 올려 주세요."(카드 여럿이면 "N번 사진은…", 2026-11-25)(2026-11-20: 카드가 모두 수정 PATCH면 '수정해 줘', 등록·수정이 섞이면 '진행해 줘'. 아래 실행·취소·0자 안내 글도 같은 동사))을 AI 메시지로 저장해 `done.message`로 준다(2026-11-13: 모달 대신 채팅으로 확인, 카드 자체는 저장 안 함, 결과는 `action-result`. 일정·케어 항목 등록 `draft_schedule`·`draft_care_item`도 ④부터 ACTION, 빈 칸은 카드 `missing`). `action`(돌려받은 카드)이 있고 메시지가 확인 말("등록해 줘"·"응"·"네 저장해" 등 짧은 문장 전체)이면 LLM 없이: 빈 칸이 없으면 `done.execute: true`·`done.action`(돌려받은 `input`을 다시 검증한 카드)·저장 글 "등록할게요."(수정 "수정할게요."·섞임 "진행할게요.". 사진(`file`) 칸만 빈 카드가 있으면 "사진과 함께 등록할게요.", 2026-11-25. 2026-11-26 "사진이 없으면 카드에서 올려 주세요."는 뺌) → React가 [확인]과 같이 `call`을 실행하고 `action-result`를 부른다. 동사형 명령(2026-11-26 팀 합의): 돌려받은 카드가 없는 턴에 문장이 쓰기 명령형("…기록해 줘"·"…등록해 주세요"·"…바꿔 줘"·"…지워 줘"·끝이 "기록", 물음꼴 "할까?" 제외, `rules.commands_now`)이고 말로 물을 빈 칸(같은 이름 반려동물 포함)이 없으면 확인 말을 기다리지 않고 그 턴에 `done.execute: true`·`action`·`actions` 전부(여러 명령·두 아이 카드도 한 번에)를 주고 저장 글은 요약(여럿이면 번호 줄) + 반올림 안내 + "등록할게요."(동사·사진 규칙은 확인 말과 같음). 삭제 카드는 삭제 동사가 든 말일 때만. READ 뒤 고른 카드(SEARCH 답변의 `done`)도 같다. 빈 칸이 있으면 지금처럼 되묻는다. 빈 칸이 남았으면 `execute` 없이 그 카드와 빈 칸 되물음 글. 취소 말("아니"·"취소해"·"하지 마" 등)이면 카드 없이 "등록하지 않았어요."(수정 "수정하지 않았어요."·섞임 "진행하지 않았어요.")를 저장한다. 그 밖의 말은 아래처럼 칸을 고친다. 수정 도구가 경로의 번호 칸(`schdlSn`·`careArtclSn`·`expndSn`)을 정하지 못하면 카드 없이 SEARCH로 "바꿀 <대상>을 찾지 못했어요. 이름이나 날짜를 넣어 다시 말해 주세요."(고지 없음)를 저장한다. 관찰 기록 추가가 본문의 관찰 항목 번호(`obsrvArtclSn`)를 정하지 못하면 같은 방식으로 "기록할 관찰 항목을 찾지 못했어요. 이름을 넣어 다시 말해 주세요."를 저장한다. 한 메시지 여러 명령 ②(2026-11-19): 쓰기 도구를 고른 메시지에 이어 주는 말("하고·그리고·~도·랑" 등)이 있으면 남은 쓰기 도구를 이어 골라 확인 카드를 최대 3장 `done.actions`로 준다(같은 도구는 한 장, `done.action`은 첫 카드. 2026-11-23: 반려동물 칸이 있고 번호 칸(`…Sn`, petSn 제외)이 없는 새 등록 카드(POST: 일정·케어 항목·건강 일지)에 다른 반려동물 이름이 둘 이상이면 이름마다 같은 값의 카드를 한 장씩 — 같은 `tool`이 `actions`에 둘 이상 올 수 있다. 모두 합쳐 3장을 넘으면 나누지 않고 한 장 + 말한 아이들 칩). 카드가 둘 이상이면 저장 글은 "이렇게 할까요?\n1. <요약>\n2. <요약>" + 빈 칸이 있는 카드마다 "아직 <N>번의 <칸>이(가) 비어 있어요. 말로 알려 주세요.", 없으면 확인 말 안내. 돌려받은 `actions`에 확인 말이면 모두 빈 칸이 없을 때만 `execute: true`·`actions` 전부(React가 순서대로 실행, 실패해도 나머지를 이어 실행, 카드마다 `action-result`, 묶음 저장 없음), 빈 칸이 남았으면 `execute` 없이 그 카드 번호로 되묻고, 취소 말은 모두 버린다. 칸을 고치는 말에서 고른 쓰기 도구가 모두 돌려받은 목록 안이면 그 카드만 바뀌고 나머지 카드는 그대로 목록으로(같은 도구 카드가 여럿이면 문장에 이름이 나온 아이의 카드만, 이름이 없으면 그 도구 카드 모두, 2026-11-23), 목록 밖 쓰기 도구면 새 목록이다. 읽기 도구를 세 번 부른 뒤에도 확인 카드 도구는 한 번 고를 수 있고, 읽기 답변이 0자로 끝나면 오류 대신 안내 글(카드가 있으면 "카드 내용이 맞으면 '등록해 줘'라고 말해 주세요.")을 저장한다. 읽기 결과를 본 뒤 고른 카드의 답변 글은 LLM이 카드 요약과 확인 말 안내로 쓴다, RECEIPT는 판정만 준다. `action`(가장 최근 확인 카드)이 있고 도구 흐름이 같은 도구를 고르면 그 `input`을 바탕으로 이 메시지 칸을 덮어쓴 새 카드를 준다. `draft`(가장 최근 카드)가 있고 이 메시지에서 칸이 하나라도 뽑히면 판정 없이 REGISTER로 초안을 채우거나 고친 새 카드를 준다(뽑힌 칸이 없으면 일반 판정). 도구 고르기 LLM이 서비스 범위 밖이라고 고르면(`decline`) FALLBACK이고 안내 문구는 범위 안내 "반려동물 케어와 관련된 질문만 도와드릴 수 있어요. 반려동물이나 서비스 이용에 관해 물어봐 주세요."(뜻을 알 수 없는 입력이면 일반 폴백 문구). 키워드 행이 없는 문장에서 도구 고르기가 실패(오류·시간 초과)하면 폴백이 아니라 `error` 이벤트(저장 없음). 도구 흐름(2026-11-09부터 항상, 끄는 설정 없음)에서는 키워드에 걸린 문장이 질문꼴이 아니어도 키워드 힌트와 함께 도구 고르기 LLM으로 보내고, 도구 고르기가 실패(오류·시간 초과)하면 그 행으로 ROUTE(2026-11-06). 컨텍스트는 현재 대화의 미완료를 뺀 "방 요약 + 요약 경계선 뒤 최근 15턴"(턴은 사용자 메시지 수, 요약은 첫 사용자 메시지 앞 "이전 대화 요약:"). 경계선 뒤 사용자 메시지가 15개가 된 답변을 저장한 뒤 이전 요약 + 경계선 뒤 전부를 새 요약으로 Java에 저장한다(`internal.md` PUT summary, 2026-11-24). 요약은 응답에 나오지 않는다. 첫 글자 10초 초과·오류는 `error` 이벤트(저장 없음), 첫 글자 뒤 60초 초과·오류는 부분 답변을 미완료(`cmptnYn=false`)로 저장. 연결이 끊겨도 생성·저장은 끝까지 한다(완료로 저장). 스트림 시작 전 오류는 JSON: 본문 공백만·1,000자 초과·답할 사용자 메시지 없음 400 `INVALID_REQUEST`, 남의 대화·없는 번호 404 `NOT_FOUND` | AIM-002-02·03·04·07·08·09·10·11, AIM-011-15·16, AIM-012-02~08·10, AIM-012(2단계 쓰기) | LJS | MessageSendRequest | SSE 이벤트(아래 MessageEvent) |
| POST | /ai/conversations/{aiCnvrsRoomSn}/register-result | 옛 등록 카드의 결과(등록됨·취소됨)를 텍스트 요약으로 AI 메시지에 저장한다. 옛 카드 호환용: 2026-11-09 ④부터 일정·케어 항목 등록은 확인 카드(`action-result`)라 프론트 범용 카드 전환 뒤 삭제한다. 등록 자체는 React가 Java 일정·케어 항목 등록 API로 한다(출처 HLTC0067 AI 생성). 등록됨: `✔ 등록됨 — 초코 예방접종 · 10-06(화) 15:00`(시간 없으면 날짜만), 케어 항목은 `✔ 등록됨 — 뭉치 발톱 깎기 · 2주마다 · 다음 예정일 10-10(토)`. 취소됨: `취소됨 — 등록하지 않았어요.` 무응답이면 부르지 않는다(저장 없음). 성공 201. 오류: `cardType`이 ASK·필수 칸 빔·`petNm` 없음·허용값 밖 400 `INVALID_REQUEST`, 남의 대화·없는 번호 404 `NOT_FOUND` | AIM-012-11·16 | LJS | RegisterResultRequest | ConversationMessage |
| POST | /ai/conversations/{aiCnvrsRoomSn}/action-result | 확인 카드(2단계 쓰기)의 결과를 텍스트 요약으로 AI 메시지에 저장한다. 실행은 React가 카드의 `call`(메서드·경로)과 `input`(경로 칸은 경로에, 나머지는 본문)으로 Java 공개 API를 부른다. 요약 글은 Python이 도구 표시 이름(`label`)과 `input`으로 만든다(React가 보내지 않음): `DONE` `✔ 건강 일지 기록 — 체중 · 09-29(화) 08:30 · 4.2kg`(수치 칸에는 같은 카드의 항목 이름으로 단위: 체중 kg·식사량 g·음수량 ml·산책 분, 항목 코드 칸이 없으면 도구 칸 설명의 단위(등록 몸무게 `4kg`·관찰 크기 `1.2cm`), 2026-11-25. 번호 칸·`petSn`·참거짓 칸은 빼고, 코드는 이름으로, `hrInptYn`이 false면 datetime 칸은 날짜만, 남는 값이 없으면 `✔ 케어 완료 체크`). 일정 등록 `✔ 일정 등록 — 병원 · 10-06(화) 15:00 · 정기검진 · 메이 동물병원`, 케어 항목 등록 `✔ 케어 항목 등록 — 발톱 깎기 · 정기관리 · 2주`, 배열 칸은 1줄이면 항목 값을 펼치고 2줄 이상이면 `N건`(2026-11-24). 검사 수치 저장 `draft_inspection_values`는 Python이 Java register-context·`GET /api/pets/{petSn}/checkups`(READ `list_checkups`)로 반려동물 이름과 검진기록(검진일 병원)을 읽어 `✔ 검사 수치 저장 — 탄이 · 12-14(월) 검증병원D · 혈액검사 52항목`(`values`는 줄 수와 상관없이 `혈액검사 N항목`, 읽기 실패·못 찾음이면 그 부분만 빼고 저장). `CANCELED` `취소됨 — <label> · 저장하지 않았어요.`, `FAILED` `실패 — <label> · 저장하지 못했어요.`(`errors`가 있으면 끝에 `<칸 표시 이름>을 다시 확인해 주세요.`, 표시 이름이 없으면 `입력값을 다시 확인해 주세요.` — Java 칸 이름·Java 문구는 보이지 않음, 2026-11-25)(2026-11-24: `input`에 요약할 값이 있으면 `취소됨 — <label> · <요약> · 저장하지 않았어요.`처럼 label 뒤에 같은 요약). 무응답이면 부르지 않는다. Java 실행이 400이면 `data: [{field, message}]`의 칸만 카드에서 다시 고치게 하고, `data`가 비면(가계부 서비스 검사 등) 카드 전체 오류로 보여 준다. 성공 201. 오류: 도구 목록에 없는 도구·목록에 없는 칸·Java 규칙(코드 값·min·max·maxLength) 밖 값·`status` 허용값 밖·`DONE`인데 필수 칸(required·requiredIf) 빔 400 `INVALID_REQUEST`, 남의 대화·없는 번호 404 `NOT_FOUND` | AIM-012(2단계 쓰기) | LJS | ActionResultRequest | ConversationMessage |
| POST | /ai/conversations/{aiCnvrsRoomSn}/receipt-result | 대화창 영수증 분석(`POST /ai/receipts`, 출처 `AIMC0031`)이 끝나면(인식·인식 실패·일시 오류·분석 취소) 함께 보낸 텍스트를 사용자 메시지로, 결과를 요약 한 줄 AI 메시지로 저장한다. 이미지가 붙은 전송은 `/messages`(의도 판정)를 부르지 않는다. 사진 경로(`/ai/image-intent` → `MEDICAL_RECEIPT`)에서는 사진 메시지를 `image-intent`가 이미 저장했으므로 `cnvrsCn`을 보내지 않는다(2026-11-13). 텍스트는 이후 대화의 AI 컨텍스트에 들어가고 분석에는 쓰지 않는다. 대화 이력에 이미지는 저장하지 않는다. 요약: `RECOGNIZED` `영수증 분석 — 메이 동물병원, 10월 20일, 145,000원`(없는 값은 빼고, 셋 다 없으면 `영수증 분석 — 결과를 확인해 주세요`), `FAILED` `영수증 분석 — 영수증을 읽지 못했어요`, `ERROR` `영수증 분석 — 일시적인 오류로 분석하지 못했어요`, `CANCELED` `영수증 분석 — 취소했어요`. 결과 카드의 [취소]는 이 API를 다시 부르지 않는다. 성공 201, 응답은 저장한 순서(사용자 메시지(있으면) → AI 요약). 오류: `result` 허용값 밖·`cnvrsCn` 길이 위반·공백만 400 `INVALID_REQUEST`, 남의 대화·없는 번호 404 `NOT_FOUND` | AIM-013-02·09 | LJS | ReceiptResultRequest | ConversationMessage[] |
| POST | /ai/conversations/{aiCnvrsRoomSn}/checkup-card | 대화창 검사결과지 PDF 분석(`image-intent` `CHECKUP_PDF` → `POST /ai/checkups/lab-results`)이 끝나면 React가 결과를 보내고, Python이 결과 요약 AI 메시지를 저장하고 검사 수치 저장 확인 카드(ACTION, 도구 `draft_inspection_values` = Java `POST /api/pets/{petSn}/inspection-values`)를 준다(초안 2026-11-23, 프론트와 맞춤). 카드는 저장하지 않고, 이후 흐름은 `/messages`의 확인 카드와 같다(카드를 `action`으로 돌려보내고, "등록해 줘"면 `done.execute`, 결과는 `action-result`). 처리: `RECOGNIZED`면 `items` 중 결과수치·단위·항목(코드 또는 직접입력명)이 있고 Java 칸 규칙에 맞는 줄만 카드 `values`에 넣고(뺀 줄 수는 글로), Python이 Java `GET /api/pets/{petSn}/checkups`(READ `list_checkups`)로 그 아이 검진기록을 읽어 1건이면 `ckupRcdSn`을 채우고, 여럿이면 빈 칸(`missing`)으로 두고 최근 3건(검진일·병원·검진유형, 검진일이 없으면 "날짜 없음")을 글로 보인다 → 회원이 "9월 1일 튼튼 병원"처럼 말하면 도구 고르기가 `list_checkups`를 읽고 같은 카드의 `ckupRcdSn`만 채운다(돌려받은 카드의 `values`는 그대로). 0건이면 카드 없이 "검진기록이 없어요. 검진기록을 먼저 등록할까요? 등록하면 <반려동물>의 검사 수치를 바로 저장할 수 있어요."(이름을 모르면 "등록하면 검사 수치를…", 프론트는 이 글 아래에 [검진기록 등록하기]·[나중에] 버튼만 붙인다)와 `noCardReason` `NO_CHECKUP`(2026-11-24, 프론트가 검진기록 추가 뒤 같은 `items`로 다시 부른다). 뺀 줄·저장할 수 없는 수치 안내는 "검진상세에서 직접 입력해 주세요." 저장 글: `검사결과지 분석 — 혈액검사 N항목` + "<반려동물>의 검사 수치를 이렇게 저장할까요?" + 항목 줄(`- WBC 12.3 10^3/uL (참고 6~17)`, 최대 12줄 + "외 N항목") + 검진기록 줄과 확인 말 안내(1건) 또는 고르기 목록(여럿). 인식 0건 `검사결과지 분석 — 읽은 혈액검사 항목이 없어요`, `NOT_LAB_RESULT` `검사결과지 분석 — 검사결과지로 읽을 수 없는 PDF예요`, `ERROR` `… — 일시적인 오류로 분석하지 못했어요`, `CANCELED` `… — 취소했어요`(모두 카드 없음). 도구 목록에 `draft_inspection_values`가 없으면(백엔드 병합 전·스냅샷) 카드 없이 "검진상세의 [PDF 분석]에서 저장할 수 있어요.". 항목 줄에 `inspArtclCd`가 있으면 `inspArtclDrctInptNm`은 뺀다(둘 다 보내면 Java 400, 2026-11-24). 성공 201. 오류: `result` 허용값 밖·`petSn` 없음 400 `INVALID_REQUEST`, 남의 대화·없는 번호 404 `NOT_FOUND`(Java 그대로), 검진기록 읽기 실패 502 `EXTERNAL_API_ERROR`(저장 없음) | AIM-013, HLT-005-04 | LJS | CheckupCardRequest | CheckupCardResult |
| POST | /ai/conversations/{aiCnvrsRoomSn}/lesion-card | 대화창 피부·눈 분석(`image-intent` `SKIN` → `POST /ai/skin-analyses`, `EYE` → `POST /ai/eye-analyses`)이 끝나면 React가 분석 응답에 `kind`·`petSn`을 더해 보내고, Python이 결과 요약 AI 메시지를 저장하고 지속 관찰 항목 확인 카드(ACTION, 도구 `draft_observation_item` = Java `POST /api/pets/{petSn}/observation-items`, multipart)를 준다(초안 2026-11-24). 카드는 저장하지 않고, 이후 흐름은 `/messages`의 확인 카드와 같다(카드를 `action`으로 돌려보내고, "등록해 줘"면 `done.execute`, 결과는 `action-result`). 사진 `file`은 React가 분석한 같은 사진을 카드에 붙인다(카드 `missing`에는 `file`이 들어 있지만 글로 묻지 않고 확인 말 판정에서도 세지 않음 — 사진 칸만 비었으면 "등록해 줘"에 `done.execute`, 2026-11-24. 대화로 만든 `draft_observation_cycle` 등 파일 칸이 있는 모든 카드에 같음). 저장 글: `피부 분석 — 진료 권장`(등급 `OBSERVE` 지켜보기·`VISIT` 진료 권장·`URGENT` 빨리 진료, 눈은 `눈 분석 — …`) + 병변 줄(`- 탈모 (확신도 높음)`) + `guide` 줄 + `notice` + "<반려동물>의 지속 관찰 항목으로 남길까요? 카드에 분석한 사진을 붙여 저장해요." + 빈 칸 안내 또는 확인 말 안내. 카드 `input`: `petSn`, `obsrvArtclNm` 첫 병변 이름(40자), `obsrvDt` 지금(KST, 초 버림), `memoCn` "피부 분석 참고: 탈모(높음)·비듬(보통), 진료 권장"(200자, `ruleVersion`은 넣지 않고 서버 로그에만, 2026-11-24). `obsrvRegnCd`는 피부면 비움(`missing`, 회원이 고름), 눈이면 Java 도구 목록의 "얼굴" 코드(2026-11-24 사람 결정, 눈 코드 추가 없음)로 채우고 "부위는 얼굴로 골라 두었어요. 왼쪽 눈인지 오른쪽 눈인지 말해 주시면 적을게요."(`obsrvRegnDtlNm`은 비움). 카드 없음: 병변이 "이상 없음"(`normal`)만이면 요약만, `NOT_PET_SKIN`·`NOT_PET_EYE` `… — 반려동물 피부(눈) 사진이 아니에요`·`UNCLEAR` `… — 사진으로 판단하기 어려워요`(+ `guide`·`notice`), `ERROR` `… — 일시적인 오류로 분석하지 못했어요`, `CANCELED` `… — 취소했어요`. 도구 목록에 `draft_observation_item`이 없으면 카드 없이 "건강기록의 지속 관찰에서 직접 남길 수 있어요.". 이미 관찰 중인 항목(2026-11-26): 카드가 있으면 Python이 READ `list_observation_items`(그 아이, 상태 "관찰중")를 읽어 글에 "이미 관찰 중인 항목이 있어요." + 최대 3줄(`- 흰자 충혈 (얼굴·11월 24일)`, 부위·최근 관찰일) + "이미 관찰 중인 항목에 기록을 더하려면 '흰자 충혈에 추가해 줘'처럼 말해 주세요."를 확인 말 안내 앞에 넣는다(도구 없음·읽기 실패·0건이면 줄 없이 그대로 201). 카드는 자동으로 바꾸지 않는다(이름·부위 자동 맞춤 없음, 회원이 이름으로 고른다). 카드를 `action`으로 돌려보내며 "흰자 충혈에 추가해 줘"라고 하면 `/messages`가 관찰 기록 추가 카드(`draft_observation_cycle`, Java `POST /api/pets/{petSn}/observation-cycles`)로 바꾸고, 회원이 말하지 않은 `memoCn`(분석 메모)·`obsrvDt`는 돌려받은 카드 값을 옮긴다. 카드가 `draft_observation_cycle`로 바뀌어도 React는 분석한 같은 사진을 `file`로 붙인다. 성공 201. 오류: `kind`·`rslt`·`cnfdnc` 허용값 밖, `petSn` 없음, `ANALYZED`인데 `grade` 없음, `findings` 4개 이상 400 `INVALID_REQUEST`, 남의 대화·없는 번호 404 `NOT_FOUND`(Java 그대로) | AIM-013(피부·안구 FN 행 작성 전) | LJS | LesionCardRequest | LesionCardResult |
| POST | /ai/image-intent | 대화창·메인 검색창에 사진을 붙여 보내면 사진과 함께 보낸 글로 사진의 용도를 판단한다(2026-11-09 추가, 기능 ID는 메인 개편 뒤). 판단 뒤 사진 턴을 대화방에 저장한다(2026-11-13): 사용자 메시지 `[사진] <cnvrsCn>`(글이 없으면 `[사진]`) + 용도별 고정 AI 메시지(`ASK` "이 사진으로 무엇을 할까요? 캐릭터 만들기, 영수증 분석, 피부 분석, 눈 분석 중에 골라 주세요.", `CHARACTER` "캐릭터 만들기로 이어 갈게요.", `EXPENSE_RECEIPT` "가계부 영수증은 본창 가계부에서 등록할 수 있어요.", `SKIN` "피부 분석으로 이어 갈게요."(2026-11-24, 결과 요약은 `lesion-card`), `EYE` "눈 분석으로 이어 갈게요."(2026-11-24, 결과 요약은 `lesion-card`). 글이 캐릭터를 원하지만 사진에 반려동물 얼굴·몸이 안 보여 `ASK`면 안내만 "캐릭터는 반려동물 얼굴이나 몸 전체가 보이는 사진으로 만들 수 있어요. 다른 사진을 올려 주시거나, 이 사진으로 할 일을 골라 주세요."(`kind`는 그대로 `ASK`, 2026-11-24), `MEDICAL_RECEIPT`은 AI 메시지 없음 — 결과 요약은 `receipt-result`). `aiCnvrsRoomSn`이 없으면 방을 만든다(첫 메시지가 사진 메시지, 펫 태그 `petSn`, 제목은 글이 있으면 생성·없으면 "사진 대화"). 사진 파일은 저장하지 않아 다시 열면 `[사진]` 글만 보이고, 다음 턴 LLM도 사진 내용은 모른다. 형식·크기 400은 저장하지 않는다. React가 `kind`로 흐름을 나눈다: `CHECKUP_PDF` → `POST /ai/checkups/lab-results`·`checkup-card`(2026-11-23), `MEDICAL_RECEIPT` → `POST /ai/receipts`(출처 `AIMC0031`)·`receipt-result`, `CHARACTER` → `POST /ai/characters`, `EXPENSE_RECEIPT` → 본창 가계부 안내(바로 등록은 다음 차수), `SKIN` → `POST /ai/skin-analyses`(`skinlesion.md`, 2026-11-24)·`lesion-card`, `EYE` → `POST /ai/eye-analyses`(`eyelesion.md`, 2026-11-24)·`lesion-card`, `ASK` → React가 칩으로 되묻는다. 판단은 LLM(이미지는 긴 변 1024px JPEG로 줄여 보냄)이 한다. 글이 사진과 다른 용도를 말하면 글을 따른다. 단 캐릭터는 사진에 반려동물 얼굴이나 몸 전체가 보일 때만이고, 영수증·피부·눈을 가까이 찍은 사진에 "캐릭터 만들어줘"면 `ASK`(2026-11-24). LLM 오류·시간 초과·거절·깨진 출력은 오류 대신 200 `ASK`. PDF(확장자 `.pdf`·실제 형식 `%PDF-`, 10MB 이하)는 판단 LLM 없이 `CHECKUP_PDF`다(2026-11-23 사람 결정, 글과 무관. 검사결과지가 아닌 PDF는 `lab-results`가 422 `NOT_LAB_RESULT`로 가린다). PDF 턴은 사용자 메시지 `[PDF] <cnvrsCn>`(글이 없으면 `[PDF]`, 새 방 제목은 글이 없으면 "PDF 대화")만 저장하고 AI 메시지는 없다(결과 요약은 `checkup-card`). 성공 200. 오류: 형식(확장자·실제 형식 불일치, 열 수 없는 이미지, `.pdf`인데 PDF가 아님) 400 `FILE_TYPE_NOT_ALLOWED`, 10MB 초과 400 `FILE_SIZE_EXCEEDED`, `file` 없음·`cnvrsCn` 1,000자 초과·`petSn`·`aiCnvrsRoomSn` 형식 오류 400 `INVALID_REQUEST`(검증 실패는 LLM을 부르지 않는다), 남의 대화·없는 번호 404 `NOT_FOUND`(Java 그대로), LLM 키 없음 502 `EXTERNAL_API_ERROR` | AIM-013, MAN-002 | LJS | ImageIntentRequest | ImageIntentResponse |

## DTO

### ConversationCreateRequest
쓰는 API: POST /ai/conversations
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| petSn | Long | N | 펫 태그. 생략·null이면 "전체" | AIM-011-08 |
| cnvrsCn | String | Y | 첫 메시지. 공백만 불가, 1~1,000자 | AIM-011-07, AIM-011 입력창 |

### ConversationSummary
쓰는 API: POST /ai/conversations, GET /ai/conversations
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| aiCnvrsRoomSn | Long | Y | 대화방 번호 | AI_CNVRS_ROOM.AI_CNVRS_ROOM_SN |
| petSn | Long | N | 펫 태그. null이면 "전체" | AI_CNVRS_ROOM.PET_SN |
| cnvrsTtl | String | Y | 복호화한 제목 | AI_CNVRS_ROOM.CNVRS_TTL_ENC, AIM-011-11 |
| regDt | LocalDateTime | Y | 생성 일시 | AI_CNVRS_ROOM.REG_DT |

### ConversationDetail
쓰는 API: GET /ai/conversations/{aiCnvrsRoomSn}
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| aiCnvrsRoomSn | Long | Y | ConversationSummary와 같음 | |
| petSn | Long | N | ConversationSummary와 같음 | |
| cnvrsTtl | String | Y | ConversationSummary와 같음 | |
| regDt | LocalDateTime | Y | ConversationSummary와 같음 | |
| messages | List<ConversationMessage> | Y | `msgSeq` 오름차순 | AIM-011-10 |

### ConversationMessage
쓰는 API: GET /ai/conversations/{aiCnvrsRoomSn}, POST /ai/conversations/{aiCnvrsRoomSn}/messages(`done` 이벤트), POST /ai/conversations/{aiCnvrsRoomSn}/receipt-result(목록)
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| aiCnvrsMsgSn | Long | Y | 메시지 번호 | AI_CNVRS_MSG.AI_CNVRS_MSG_SN |
| roleCd | String | Y | `AIMC0024` 사용자, `AIMC0025` AI(공통코드 AIMG06) | AI_CNVRS_MSG.ROLE_CD |
| cnvrsCn | String | Y | 복호화한 내용. AI 메시지(`AIMC0025`)는 Markdown(GFM)이다. 프론트는 `react-markdown`+`remark-gfm`으로 그리고 HTML·이미지는 그리지 않는다. 의료 고지는 맨 끝 빈 줄 뒤 `※` 문단으로 떼어 표시한다(마지막 문단 유지, 프론트 PR #288) | AI_CNVRS_MSG.CNVRS_CN_ENC |
| msgSeq | Integer | Y | 대화 안 순서(1부터) | AI_CNVRS_MSG.MSG_SEQ |
| regDt | LocalDateTime | Y | 메시지 일시 | AI_CNVRS_MSG.REG_DT |
| cmptnYn | Boolean | Y | false면 미완료 답변("답변이 완료되지 않았어요" 표시, AI 컨텍스트에서 제외). Java가 주지 않으면 true | AI_CNVRS_MSG.AI_CNVRS_MSG_CMPTN_YN, AIM-002-07 |

### MessageSendRequest
쓰는 API: POST /ai/conversations/{aiCnvrsRoomSn}/messages
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| cnvrsCn | String | N | 보낼 메시지. 공백만 불가, 1~1,000자. 생략·null이면 저장 없이 방의 마지막 사용자 메시지에 답한다 | AIM-011 입력창, AIM-002-07 |
| draft | RegisterDraft | N | 가장 최근 등록 카드(되물음 포함). React가 `done.card`를 그대로 돌려보낸다(출력 전용 필드는 무시). Python은 초안을 저장하지 않는다 | AIM-012-05·10 |
| action | `{tool: String, input: Object, targetText?: String}` | N | 삭제 카드는 `targetText`도 그대로 돌려보낸다(2026-11-25). 가장 최근 확인 카드(ACTION)의 `tool`과 `input`(회원이 카드에서 고친 값 포함). `draft`와 따로 둔다(등록 카드 계약 그대로). Python은 카드를 저장하지 않는다. 같은 도구를 다시 고르면 이 `input`이 바탕(Java 규칙 밖 값·목록 밖 칸은 버림) | AIM-012(2단계 쓰기) |
| actions | `[{tool: String, input: Object, targetText?: String}]` | N | 가장 최근 확인 카드 목록(`done.actions` 그대로, 최대 3개, 넘으면 400 `INVALID_REQUEST`). 있으면 `action` 대신 쓴다. 프론트가 옮긴 뒤 `action`은 지운다(2026-11-19 한 메시지 여러 명령 ②) | AIM-012(2단계 쓰기) |

### MessageEvent
쓰는 API: POST /ai/conversations/{aiCnvrsRoomSn}/messages (응답 본문)

`ApiResponse` 껍데기 없이 SSE 이벤트가 차례로 온다. 각 이벤트는 `event: <이름>`과 `data: <JSON>` 두 줄이다. 순서는 `intent` → (`delta`…) → `done` 또는 `error`이고, `done`·`error`가 오면 스트림이 끝난다.
| 이벤트 | data | 설명 | 근거 |
| --- | --- | --- | --- |
| intent | Intent `{kind, scrId, scrNm, param, moveType}` | 판정. `kind`: SEARCH·ROUTE·FALLBACK·REGISTER·RECEIPT·ACTION(2단계 쓰기 확인 카드). 화면 필드는 ROUTE일 때만 값이 있다(화면 ID → 프론트 경로 변환은 React) | AIM-001-05, AIM-004 |
| delta | `{text: String}` | SEARCH 답변 조각. 이어 붙여 표시한다. 조각을 이어 붙인 글은 Markdown(GFM)이다(ConversationMessage `cnvrsCn`과 같음). 마지막 조각은 의료 고지(`\n\n※ 참고 정보이며 의료 진단이 아닙니다. …`), 미완료 답변에는 없다. 도구 없이 바로 쓴 답은 회원 글에 건강 말(증상·먹이·접종·산책 등, `app/chat/rules.py` `is_health_topic`)이 있을 때만 고지(2026-11-25: "오늘 날씨 어때?" 같은 답에는 없음), 인사·잡담·사용법 답에도 없다 | AIM-002-02·03 |
| done | `{message: ConversationMessage?, shortcut: Intent?, card: RegisterCard?, action: ActionCard?, actions: ActionCard[]?, execute: Boolean}` | 끝. `message`는 저장된 AI 메시지(SEARCH 답변·FALLBACK 안내·ROUTE 이동 안내·ACTION 카드 요약·확인 말 응답). 저장하지 않았거나 저장에 실패하면 null. `message.cmptnYn=false`면 미완료(60초 초과·도중 오류): "답변이 완료되지 않았어요" + [다시 생성]. `shortcut`은 연관 바로가기(Intent ROUTE 모양, 저장 안 함), 없으면 null | AIM-002-04·07 | `card`는 REGISTER일 때만 값이 있다(미리보기 카드나 되물음, AIM-012-05~08, ④부터 옛 카드 `draft` 이어 쓰기에서만). `action`은 ACTION일 때(`message`는 카드 요약 글, 2026-11-13), 그리고 SEARCH에서 읽기 도구 결과를 본 LLM이 쓰기 도구를 고른 경우(예: 케어 목록 → 완료 체크, 답변 글은 카드 요약과 확인 말 안내) 값이 있다. React는 카드를 모달로 띄우지 않고 글만 보이며, 카드는 다음 메시지의 `action`으로 돌려보낸다. `execute`(기본 false)가 true면 돌려받은 카드에 확인 말이 온 것이다: React가 `action`의 `call`을 바로 실행하고 `action-result`를 부른다(2026-11-13). 2026-11-26부터 동사형 명령이면 카드를 처음 주는 턴에도 `execute: true`가 온다(ACTION·SEARCH 둘 다, React는 같은 방식으로 실행). `actions`(2026-11-19 한 메시지 여러 명령 ②)는 `action`이 있을 때 늘 함께 오는 카드 목록(최대 3장, 첫 카드가 `action`)이다. React는 `actions`를 다음 메시지의 `actions`로 돌려보내고, `execute`면 순서대로 각 `call`을 실행하며(하나가 실패해도 나머지 실행) 카드마다 `action-result`를 부른다. `action`은 프론트가 `actions`로 옮긴 뒤 지운다.
| error | `{code: "EXTERNAL_API_ERROR", message: "일시적으로 답변할 수 없어요"}` | 첫 글자 전 실패(10초 초과·오류)와 키워드 행이 없는 문장의 도구 고르기 LLM 실패. AI 메시지는 저장하지 않는다. [다시 시도]는 `cnvrsCn` 없이 다시 보낸다 | AIM-002-07 |

### RegisterDraft
쓰는 API: POST /ai/conversations/{aiCnvrsRoomSn}/messages(`draft`)

필드 이름은 SCHDL·CARE_ARTCL 컬럼, 코드는 공통코드(백엔드 `db/20261029_insert_base_data_v0.10.sql`) 그대로다. 일정 칸과 케어 항목 칸 중 `careZoneCd`가 있으면 케어 항목이다.
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| petSn | Long | N | 반려동물 | SCHDL.PET_SN, CARE_ARTCL.PET_SN |
| schdlKndCd | String | N | 일정종류 HLTG19: `HLTC0057` 병원·`HLTC0058` 미용·목욕·`HLTC0059` 케어·투약·`HLTC0060` 기타 | SCHDL.SCHDL_KND_CD |
| schdlYmd | LocalDate | N | 일정 날짜 | SCHDL.SCHDL_DT |
| schdlTm | String | N | `HH:MM`. 없으면 시간 미입력 | SCHDL.SCHDL_DT, SCHDL.HR_INPT_YN |
| ckupTypeCd | String | N | 병원일 때 검진유형 HLTG01: `HLTC0001` 정기검진·`HLTC0002` 예방접종·`HLTC0003` 질병진료·`HLTC0004` 검사·`HLTC0005` 기타 진료 | SCHDL.CKUP_TYPE_CD |
| hsptlNm | String | N | 병원명, 80자 이하 | SCHDL.HSPTL_NM |
| schdlNm | String | N | 병원이 아닌 일정의 일정명, 40자 이하 | SCHDL.SCHDL_NM |
| memoCn | String | N | 메모, 500자 이하 | SCHDL.MEMO_CN |
| careArtclNm | String | N | 케어 항목명, 40자 이하 | CARE_ARTCL.CARE_ARTCL_NM |
| careZoneCd | String | N | 반복 유형 HLTG13: `HLTC0036` 일상관리(매일)·`HLTC0037` 정기관리(주기) | CARE_ARTCL.CARE_ZONE_CD |
| careCycleCd | String | N | 케어주기 HLTG15: `HLTC0038` 1주·`HLTC0039` 2주·`HLTC0040` 한달·`HLTC0041` 1년·`HLTC0042` 직접입력 | CARE_ARTCL.CARE_CYCLE_CD |
| cycleDays | Integer | N | 직접입력일 때 n일마다(1~3650) | CARE_ARTCL.CYCLE_DRCT_INPT_DAY_CNT |
| lastCmptnYmd | LocalDate | N | 마지막으로 한 날. 없으면 등록일 | CARE_ARTCL.LAST_CMPTN_YMD |

### RegisterCard
쓰는 API: POST /ai/conversations/{aiCnvrsRoomSn}/messages(`done.card`), POST /ai/conversations/{aiCnvrsRoomSn}/register-result(`card`)

RegisterDraft의 필드에 아래가 더해진다. 필수 칸이 모두 찬 경우에만 SCHEDULE·CARE_ITEM이다(빈 카드 없음).
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| cardType | String | Y | `SCHEDULE` 일정 카드·`CARE_ITEM` 케어 항목 카드·`ASK` 되물음 | AIM-012-05·06·07 |
| petNm | String | N | 정한 반려동물 이름 | AIM-012-04 |
| petChoices | List<`{petSn, petNm, petSeNm?, vrtyNm?}`> | Y | 반려동물을 정하지 못했을 때 이름 칩(양육 반려동물 전부, 문장 속 이름이 여러 마리에 걸렸으면 그 아이들만(같은 이름이면 문장의 품종 이름·종 말 "강아지"·"댕댕이"·"멍멍이"·"고양이"·"냥이"로 먼저 좁힘). `petSeNm`(종 이름)·`vrtyNm`(품종 이름)은 Java가 줄 때만 실림 — 같은 이름 칩을 "까미 (강아지·말티즈)"처럼 구별해 보여 줄 때 쓴다. 같은 이름이라 못 정하면 저장 글은 "까미가 둘이에요. 칩에서 고르거나 '강아지 까미'처럼 알려 주세요.", 카드가 여럿이면 "2번: 까미가 둘이에요. …" 뒤 그 카드의 남은 빈 칸은 "아직 2번의 <칸>이(가) 비어 있어요."(2026-11-23)). 정했으면 빈 배열 | AIM-012-04 |
| missing | List<String> | Y | ASK일 때 빈 필수 칸 필드 이름(`petSn`·`schdlKndCd`·`schdlYmd`·`ckupTypeCd`·`hsptlNm`·`schdlNm`·`careArtclNm`·`careCycleCd`·`cycleDays`). 필수: 일정 = 종류·날짜 + 병원이면 검진유형·병원명, 그 외 일정명 / 케어 항목 = 항목명 + 정기관리면 주기 | AIM-012-05·12 |
| nxtmPrnmntYmd | LocalDate | N | CARE_ITEM의 다음 예정일 = 마지막으로 한 날(없으면 오늘) + 주기, 매일은 다음 날, 한달은 같은 날짜(말일 넘으면 말일) | AIM-012-07 |
| duplicateName | Boolean | Y | 같은 반려동물에 같은 이름(띄어쓰기 무시) 케어 항목이 있음 | AIM-012-08 |
| notice | String | N | duplicateName일 때 안내 문구 `{반려동물명}에게 '{항목명}' 항목이 이미 있어요. 그래도 새로 등록할까요?` | AIM-012-08 |

### RegisterResultRequest
쓰는 API: POST /ai/conversations/{aiCnvrsRoomSn}/register-result
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| result | String | Y | `REGISTERED` 등록됨·`CANCELED` 취소됨 | AIM-012-11·16 |
| card | RegisterCard | Y | 결과를 낸 카드(SCHEDULE·CARE_ITEM) | AIM-012-16 |

### ActionCard
쓰는 API: POST /ai/conversations/{aiCnvrsRoomSn}/messages(`done.action`)

범용 확인 카드(`docs/design/tool-catalog.md` 5절). 2026-11-13부터 모달 대신 채팅으로 확인한다: 카드 내용은 `done.message`의 요약 글로 보이고, 회원이 "등록해 줘"(수정 카드는 "수정해 줘", 2026-11-20)라고 하면 `done.execute`로 실행 지시가 온다(실행 버튼을 말풍선에 같이 둘지는 React가 정한다). `params`는 폼·칸 검사용으로 그대로 준다. `missing`이 비지 않으면 실행하지 않는다. 칸 이름은 Java 요청 DTO 그대로다. 삭제 카드(2026-11-25, `call.method` DELETE: 일정·케어 항목·케어 완료 취소·건강 일지·검진기록·처방약·기타검사·관찰 기록·반복 예방·지출·즐겨찾기 11개)는 확인 안내가 "맞으면 '삭제해 줘'라고 말해 주세요."이고, "응"·"네"만으로는 실행하지 않고 "지우려면 '삭제해 줘'라고 말해 주세요."를 저장한다(`execute` 없음). "삭제해·지워·없애"가 든 확인 말이면 `execute: true`·"삭제할게요.", 취소 말이면 "삭제하지 않았어요.". 등록·삭제가 섞이면 삭제 동사나 "진행해 줘"로 실행한다. 삭제 카드가 없을 때 "삭제해 줘"는 확인 말이 아니다. 대상 번호를 못 정하면 카드 없이 "지울 <대상>을 찾지 못했어요. 이름이나 날짜를 넣어 다시 말해 주세요.". React는 DELETE를 본문 없이 보낸다.
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| tool | String | Y | 도구 이름(2026-11-25 수정 `draft_daily_health_record_update`·`draft_checkup_update`·`draft_prescription_update`·`draft_etc_inspection_update`·`draft_inspection_value_update`·`draft_observation_cycle_update`, 삭제 `delete_schedule`·`delete_care_item`·`cancel_care_completion`·`delete_daily_health_record`·`delete_checkup`·`delete_prescription`·`delete_etc_inspection`·`delete_observation_cycle`·`delete_repeat_prevention`·`delete_expense`·`delete_place_bookmark` 추가; 등록: `draft_schedule` 일정 등록(출처 코드 `schdlSrcCd`는 넣지 않음, Java 기본값)·`draft_care_item` 케어 항목 등록(④부터), `draft_care_completion` 케어 완료 체크·`draft_daily_health_record` 건강 일지 기록·`draft_expense_limit` 월 지출 한도 설정, 수정(PATCH, 바꿀 칸만 `input`에): `draft_schedule_update` 일정 수정·`draft_care_item_update` 케어 항목 수정·`draft_expense_update` 지출 수정·`draft_pet_update` 반려동물 정보 수정, 배열·파일 칸: `draft_expense` 지출 등록(`lines` 줄 하나, `expndInptMthCd`는 직접입력 고정, 문장 속 반려동물 이름이 하나면 `lines[0].petSn`, 아니면 비움)·`draft_observation_cycle` 관찰 기록 추가(사진 `file`은 카드에서 첨부). 2단계 진행에 따라 늘어난다) | Java 도구 목록 `name` |
| domain | String | Y | `health`·`expense` 등. 본창 새로고침 대상 | Java 도구 목록 `domain` |
| label | String | N | 도구 표시 이름(카드 제목) | `data/tool_prompts.yaml` `label` |
| call | `{method, path, contentType?}` | Y | 실행할 Java 공개 API. `path`의 `{칸}`은 `input`의 같은 칸 값으로 바꾼다. `contentType`은 파일 칸이 있을 때만(`multipart/form-data`, 없으면 키 없음) | Java 도구 목록 `call` |
| params | Map<String, `{in, type, required, group, codes, maxLength, min, max, positive, pattern, items, minItems, generated}`> | Y | 칸별 규칙. `in`: path·query·body, `type`: string·long·int·decimal·boolean·date·time·datetime·code·array·file, `codes`: `[{cd, nm}]`(code 칸). `array`면 `items`(항목 칸 → 같은 모양 규칙, `in` 없음, 중첩 가능)와 `minItems`. `file`은 React가 첨부(Python은 채우지 않음). `generated: "uuid"`는 React가 [확인] 때 카드 하나에 한 번 만든다(필수로 세지 않음). 값이 없는 규칙도 키가 빠지지 않고 null로 온다(`items` 안 칸도 같음) | Java 도구 목록 `params` |
| rules | List<`{field, when, equals}`> | Y | 조건부 필수(`when` 칸이 `equals`면 `field` 필수). 폼에서 값이 바뀌면 React가 다시 판정 | Java 도구 목록 `rules[].requiredIf` |
| input | Object | Y | Python이 검증한 값(Java 칸 이름). 틀린 값은 비운다. 번호 칸(`…Sn`, petSn 제외)은 같은 턴 읽기 결과에 나온 값만(돌려받은 `action.input`의 값은 그대로). 경로의 번호 칸(수정 도구의 `schdlSn`·`careArtclSn`·`expndSn`)을 정하지 못하면 카드를 주지 않는다: 바로 고른 경우 SEARCH로 "바꿀 <대상>을 찾지 못했어요. 이름이나 날짜를 넣어 다시 말해 주세요."(고지 없음, 저장), 읽기 결과를 본 뒤면 LLM이 글로 다시 물어본다. datetime 칸에 날짜만 오면 오늘은 지금 시각, 다른 날은 빈 칸. LLM이 date hook 날짜를 비우면 문장의 날짜 말이 하나일 때 그 날짜, 날짜 말이 없으면 새 등록 기록 도구(시간 입력 칸·경로 번호 칸 없음: 건강 일지·관찰 기록)만 오늘로 채운다(2026-11-23). 일정 카드는 빈 칸 그대로. 단 수정 카드(경로 번호 칸·date hook·`hrInptYn`이 있는 도구)는 날짜만 오면 원래 시간을 쓴다(원래 시간이 미입력이면 그대로 미입력). 원래 값은 같은 턴 읽기 결과의 그 번호 행, 없으면 돌려받은 카드 `input` | |
| missing | List<String> | Y | 빈 필수·조건부 필수 칸(Java 칸 이름, `petSn` 포함). 빈 필수 배열·`minItems` 미만은 `lines`, 항목 안 빈 필수 칸은 `lines[0].expndAmt`(중첩은 `pets[0].drugs[1].mdcnNm`). 필수 파일 칸은 늘 들어 있다(첨부하면 React가 다시 판정) | |
| petChoices | List<`{petSn, petNm, petSeNm?, vrtyNm?}`> | Y | 반려동물을 정하지 못했을 때 이름 칩(양육 반려동물 전부, 문장 속 이름이 여러 마리에 걸렸으면 그 아이들만(같은 이름이면 문장의 품종 이름·종 말 "강아지"·"댕댕이"·"멍멍이"·"고양이"·"냥이"로 먼저 좁힘). `petSeNm`(종 이름)·`vrtyNm`(품종 이름)은 Java가 줄 때만 실림 — 같은 이름 칩을 "까미 (강아지·말티즈)"처럼 구별해 보여 줄 때 쓴다. 같은 이름이라 못 정하면 저장 글은 "까미가 둘이에요. 칩에서 고르거나 '강아지 까미'처럼 알려 주세요.", 카드가 여럿이면 "2번: 까미가 둘이에요. …" 뒤 그 카드의 남은 빈 칸은 "아직 2번의 <칸>이(가) 비어 있어요."(2026-11-23)). 정했거나 반려동물 칸이 없는 도구면 빈 배열 | AIM-012-04 |
| petNm | String | N | 정한 반려동물 이름 | AIM-012-04 |
| notice | String | N | 카드 위에 보여 줄 안내 문구. 지금은 케어 항목 등록에서 같은 반려동물에 같은 이름(띄어쓰기 무시)의 케어 항목이 있을 때만 `{petNm}에게 '{이름}' 항목이 이미 있어요. 그래도 새로 등록할까요?`, 없으면 null | AIM-012-08 |
| targetText | String | N | 삭제 카드(`call.method` DELETE, 2026-11-25)의 대상 글. Python이 같은 턴 읽기 결과의 그 번호 행으로 만든다(예: `09-28(월) 08:30 · 체중 · 4.2kg`, 코드는 이름·날짜는 `MM-DD(요일)`·시간 미입력 일정은 날짜만). 삭제 카드는 고칠 칸이 없어(`params`는 경로 번호뿐) React는 입력 칸 대신 이 글을 보여 주고, 다음 메시지의 `action(s)`와 `action-result`에 그대로 돌려보낸다. 행을 못 찾았거나 삭제 카드가 아니면 null | `data/tool_prompts.yaml` `target_fields` |

### ActionResultRequest
쓰는 API: POST /ai/conversations/{aiCnvrsRoomSn}/action-result
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| tool | String | Y | 결과를 낸 카드의 `tool`(④부터 `draft_schedule`·`draft_care_item` 포함) | |
| status | String | Y | `DONE` 실행 성공·`CANCELED` 취소·`FAILED` 실행 실패 | |
| input | Object | N | 실행한(또는 카드에 있던) 값. Java 칸 이름, 목록에 있는 칸만. 배열은 항목 칸까지 같은 규칙으로 검사(목록 밖 항목 칸·규칙 밖 값 400). 파일 칸은 보내지 않는다(와도 버림). `DONE`이면 필수 칸(항목 안 필수 칸 포함, 파일 칸 제외)이 차 있어야 한다. 요약 글은 배열 항목 값(번호·uuid·petSn 빼고)을 넣고 고정 칸·파일 칸은 뺀다: `✔ 지출 등록 — 09-29(화) · 사료 · 32,000`. 배열이 2줄 이상이면 펼치지 않고 `N건`(검사 수치 `values`는 늘 `혈액검사 N항목`) | |
| errors | Array | N | `FAILED`일 때 Java 400 응답 `data`의 `[{field, message}]`를 그대로(2026-11-25). Python은 `field`만 써서 저장 글 끝에 칸 표시 이름으로 다시 확인을 안내하고 `message`(Java 문구)는 쓰지 않는다. 프론트는 빨간 Java 오류 글 대신 이 저장 글(응답 ConversationMessage)을 보여 준다. `DONE`·`CANCELED`면 무시. 최대 50개 | |
| targetText | String | N | 삭제 카드의 `targetText` 그대로(2026-11-25, 200자까지). 저장 글: `DONE` `✔ 건강 일지 삭제 — <targetText>`, `CANCELED` `취소됨 — 건강 일지 삭제 · <targetText> · 삭제하지 않았어요.`, `FAILED` `실패 — 건강 일지 삭제 · 삭제하지 못했어요.`(`errors`가 있으면 끝에 다시 확인 안내). 없으면 label만. 삭제 카드가 아니면 쓰지 않는다 | |

### ReceiptResultRequest
쓰는 API: POST /ai/conversations/{aiCnvrsRoomSn}/receipt-result
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| result | String | Y | `RECOGNIZED` 인식·부분 인식, `FAILED` 인식 실패(추출 0건), `ERROR` 일시 오류(API 오류·15초 초과), `CANCELED` 분석 중 취소 | AIM-013-09 |
| cnvrsCn | String | N | 이미지와 함께 보낸 텍스트. 1~1,000자, 공백만 불가. 있으면 사용자 메시지로 먼저 저장 | AIM-013-02 |
| hsptlNm | String | N | 병원명. `ReceiptOcrResponse.hsptlNm` 그대로. `RECOGNIZED`일 때만 쓴다 | AIM-013-09 |
| ckupYmd | LocalDate | N | 검진일. `ReceiptOcrResponse.ckupYmd` 그대로. `RECOGNIZED`일 때만 쓴다 | AIM-013-09 |
| recptAmt | Integer | N | 영수증 금액. `ReceiptOcrResponse.recptAmt` 그대로. `RECOGNIZED`일 때만 쓴다 | AIM-013-09 |

### CheckupCardRequest
쓰는 API: POST /ai/conversations/{aiCnvrsRoomSn}/checkup-card
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| result | String | Y | `RECOGNIZED` 분석 성공(인식 0건 포함), `NOT_LAB_RESULT` 검사결과지 아님(lab-results 422), `ERROR` 일시 오류(504·502), `CANCELED` 분석 중 취소 | AIM-013 |
| petSn | Long | Y | 대상 반려동물. 영수증처럼 React가 정한다(펫 태그, [전체]면 이름 칩, FN-AIM-013-03) | AIM-013-03 |
| items | LabResultItem[] | N | `POST /ai/checkups/lab-results` 응답 `items` 그대로(`docs/api/checkup.md` LabResultItem). `RECOGNIZED`일 때만 쓴다. 최대 100 | HLT-007-04 |
| excludedArtclNms | String[] | N | lab-results 응답 그대로. 저장 글에 "혈액검사가 아닌 항목(…)은 저장하지 않아요." | HLT-007-05 |

### CheckupCardResult
쓰는 API: POST /ai/conversations/{aiCnvrsRoomSn}/checkup-card
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| messages | List<ConversationMessage> | Y | 저장한 AI 메시지(1개) | AIM-013-09 |
| action | ActionCard | N | 검사 수치 저장 확인 카드(`done.action`과 같은 모양, `input`의 `petSn`·`ckupRcdSn`·`values`). 카드가 없으면 null | AIM-013 |
| noCardReason | String | N | 카드가 없는 이유. `NO_CHECKUP` 그 아이 검진기록 0건(프론트가 검진기록 추가로 잇는다). 그 밖(카드 있음·도구 없음·수치 없음·분석 실패)은 null (2026-11-24) | AIM-013 |

### LesionCardRequest
쓰는 API: POST /ai/conversations/{aiCnvrsRoomSn}/lesion-card
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| kind | String | Y | `SKIN` 피부 분석(`skin-analyses`), `EYE` 눈 분석(`eye-analyses`) | 2026-11-24 결정 |
| petSn | Long | Y | 대상 반려동물. 영수증·검사결과지처럼 React가 정한다(FN-AIM-013-03) | AIM-013-03 |
| rslt | String | Y | 분석 응답 `rslt` 그대로(`ANALYZED`·`NOT_PET_SKIN`·`NOT_PET_EYE`·`UNCLEAR`) 또는 `ERROR` 일시 오류(504·502)·`CANCELED` 분석 중 취소 | 2026-11-24 결정 |
| grade | String | N | 분석 응답 그대로(`OBSERVE`·`VISIT`·`URGENT`). `ANALYZED`면 필수 | 2026-11-24 결정 |
| findings | LesionFinding[] | N | 분석 응답 그대로(`lesionCd`·`lesionNm` 각 40자, `cnfdnc` `HIGH`·`MEDIUM`). 최대 3 | 2026-11-24 결정 |
| guide | String[] | N | 분석 응답 그대로. 최대 10 | 2026-11-24 결정 |
| notice | String | N | 분석 응답 그대로. 500자 | 2026-11-24 결정 |
| ruleVersion | String | N | 분석 응답 그대로. 40자. 서버 로그에만 남긴다(카드 `memoCn`에 넣지 않음, 2026-11-24 frontend-66 요청) | 2026-11-24 결정 |

### LesionCardResult
쓰는 API: POST /ai/conversations/{aiCnvrsRoomSn}/lesion-card
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| messages | List<ConversationMessage> | Y | 저장한 AI 메시지(1개) | AIM-013 |
| action | ActionCard | N | 지속 관찰 항목 확인 카드(`done.action`과 같은 모양, `input`의 `petSn`·`obsrvArtclNm`·`obsrvDt`·`memoCn`, 눈이면 `obsrvRegnCd`). 카드가 없으면 null | AIM-013 |

### ImageIntentRequest
쓰는 API: POST /ai/image-intent (multipart/form-data)
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| file | 파일 | Y | jpg·jpeg·png·webp 또는 pdf(2026-11-23), 10MB 이하. 확장자와 실제 형식(파일 시그니처, PDF는 `%PDF-`)이 같아야 한다 | AIM-008-05, HLT-005-04 |
| cnvrsCn | String | N | 사진과 함께 보낸 글. 1,000자 이하. 빈 값·공백만은 글 없음으로 본다. 판단에 쓰고 사용자 메시지 `[사진] <글>`로 저장한다 | AIM-013 |
| petSn | Long | N | 선택한 반려동물. 판단에 쓰지 않는다. 방을 새로 만들 때 펫 태그로 쓰고, React가 다음 요청에도 쓴다 | AIM-013 |
| aiCnvrsRoomSn | Long | N | 사진 턴을 저장할 대화방. 없으면 Python이 방을 만든다(2026-11-13) | AIM-013-02 |

### ImageIntentResponse
쓰는 API: POST /ai/image-intent
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| kind | String | Y | `CHARACTER` 반려동물 사진(캐릭터 만들기), `MEDICAL_RECEIPT` 동물병원 영수증·진료비 내역, `EXPENSE_RECEIPT` 그 밖의 영수증(사료·용품·미용 등, 가계부), `ASK` 모름(사람·풍경·애매함·판단 실패), `SKIN` 반려동물 피부·털 문제가 보이는 사진(피부 병변 분석, 2026-11-24), `EYE` 반려동물 눈 문제가 보이는 사진 또는 글이 눈을 말함(안구 질환 분석, 2026-11-24), `CHECKUP_PDF` PDF 첨부(검사결과지 분석, 판단 LLM 미호출, 2026-11-23) | AIM-013 |
| aiCnvrsRoomSn | Long | Y | 사진 턴을 저장한 방(보낸 번호 또는 새로 만든 방). React는 이 번호로 이어 간다 | AIM-013-02 |
| messages | List<ConversationMessage> | Y | 저장한 메시지(저장 순서: 사용자 사진 메시지 → 안내 AI 메시지(있으면)). React는 화면에만 둔 사진 말풍선 대신 이것을 그린다 | AIM-013-02 |
