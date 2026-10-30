# AI 대화창 API·DTO (초안)

React가 부르는 `/ai/**` API다. 공통 규칙은 `docs/api/README.md`에 있다. 이 문서는 대화 저장·조회·삭제(SCR-AIM-011)와 메시지 전송·AI 답변(SCR-AIM-002, 판정은 SCR-AIM-004·005)을 다룬다. 등록 카드(SCR-AIM-012)도 다룬다. 대화창 영수증 분석(SCR-AIM-013)의 대화 이력 저장도 다룬다(분석 자체는 `ocr.md` `POST /ai/receipts`).

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
| POST | /ai/conversations/{aiCnvrsRoomSn}/messages | 메시지를 보내고 판정·답변을 SSE(`text/event-stream`)로 받는다. `cnvrsCn`이 있으면 사용자 메시지로 저장하고 답한다. 없으면 저장 없이 방의 마지막 사용자 메시지에 답한다(첫 메시지 직후·[다시 시도]·[다시 생성]). 판정이 SEARCH면 LLM 답변을 흘리고 끝에 의료 고지를 붙여 저장, FALLBACK이면 안내 문구를 저장, ROUTE면 이동 안내("<화면명>(으)로 이동할게요")를 저장, REGISTER면 `done.card`로 미리보기 카드나 되물음을 준다(되물음 문구만 저장, 카드는 저장 안 함), RECEIPT는 판정만 준다. `draft`(가장 최근 카드)가 있고 이 메시지에서 칸이 하나라도 뽑히면 판정 없이 REGISTER로 초안을 채우거나 고친 새 카드를 준다(뽑힌 칸이 없으면 일반 판정). 룰에 걸리지 않은 문장에서 분류 LLM이 실패(오류·시간 초과)하면 폴백이 아니라 `error` 이벤트(저장 없음). 룰 키워드에 걸려도 질문꼴(`data/routing.yaml` `question_markers`)이면 분류 LLM으로 서비스 범위를 확인해 범위 밖은 FALLBACK(안내 문구는 범위 안내 "반려동물 케어와 관련된 질문만 도와드릴 수 있어요. 반려동물이나 서비스 이용에 관해 물어봐 주세요.", 룰에 안 걸린 범위 밖 질문도 같음), 이때 LLM이 실패하면 룰대로 ROUTE(2026-10-30). 컨텍스트는 현재 대화의 미완료를 뺀 최근 6턴. 첫 글자 10초 초과·오류는 `error` 이벤트(저장 없음), 첫 글자 뒤 60초 초과·오류는 부분 답변을 미완료(`cmptnYn=false`)로 저장. 연결이 끊겨도 생성·저장은 끝까지 한다(완료로 저장). 스트림 시작 전 오류는 JSON: 본문 공백만·1,000자 초과·답할 사용자 메시지 없음 400 `INVALID_REQUEST`, 남의 대화·없는 번호 404 `NOT_FOUND` | AIM-002-02·03·04·07·08·09·10·11, AIM-011-15·16, AIM-012-02~08·10 | LJS | MessageSendRequest | SSE 이벤트(아래 MessageEvent) |
| POST | /ai/conversations/{aiCnvrsRoomSn}/register-result | 등록 카드의 결과(등록됨·취소됨)를 텍스트 요약으로 AI 메시지에 저장한다. 등록 자체는 React가 Java 일정·케어 항목 등록 API로 한다(출처 HLTC0067 AI 생성). 등록됨: `✔ 등록됨 — 초코 예방접종 · 10-06(화) 15:00`(시간 없으면 날짜만), 케어 항목은 `✔ 등록됨 — 뭉치 발톱 깎기 · 2주마다 · 다음 예정일 10-10(토)`. 취소됨: `취소됨 — 등록하지 않았어요.` 무응답이면 부르지 않는다(저장 없음). 성공 201. 오류: `cardType`이 ASK·필수 칸 빔·`petNm` 없음·허용값 밖 400 `INVALID_REQUEST`, 남의 대화·없는 번호 404 `NOT_FOUND` | AIM-012-11·16 | LJS | RegisterResultRequest | ConversationMessage |
| POST | /ai/conversations/{aiCnvrsRoomSn}/receipt-result | 대화창 영수증 분석(`POST /ai/receipts`, 출처 `AIMC0031`)이 끝나면(인식·인식 실패·일시 오류·분석 취소) 함께 보낸 텍스트를 사용자 메시지로, 결과를 요약 한 줄 AI 메시지로 저장한다. 이미지가 붙은 전송은 `/messages`(의도 판정)를 부르지 않는다. 텍스트는 이후 대화의 AI 컨텍스트에 들어가고 분석에는 쓰지 않는다. 대화 이력에 이미지는 저장하지 않는다. 요약: `RECOGNIZED` `영수증 분석 — 메이 동물병원, 10월 20일, 145,000원`(없는 값은 빼고, 셋 다 없으면 `영수증 분석 — 결과를 확인해 주세요`), `FAILED` `영수증 분석 — 영수증을 읽지 못했어요`, `ERROR` `영수증 분석 — 일시적인 오류로 분석하지 못했어요`, `CANCELED` `영수증 분석 — 취소했어요`. 결과 카드의 [취소]는 이 API를 다시 부르지 않는다. 성공 201, 응답은 저장한 순서(사용자 메시지(있으면) → AI 요약). 오류: `result` 허용값 밖·`cnvrsCn` 길이 위반·공백만 400 `INVALID_REQUEST`, 남의 대화·없는 번호 404 `NOT_FOUND` | AIM-013-02·09 | LJS | ReceiptResultRequest | ConversationMessage[] |

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
| cnvrsCn | String | Y | 복호화한 내용 | AI_CNVRS_MSG.CNVRS_CN_ENC |
| msgSeq | Integer | Y | 대화 안 순서(1부터) | AI_CNVRS_MSG.MSG_SEQ |
| regDt | LocalDateTime | Y | 메시지 일시 | AI_CNVRS_MSG.REG_DT |
| cmptnYn | Boolean | Y | false면 미완료 답변("답변이 완료되지 않았어요" 표시, AI 컨텍스트에서 제외). Java가 주지 않으면 true | AI_CNVRS_MSG.AI_CNVRS_MSG_CMPTN_YN, AIM-002-07 |

### MessageSendRequest
쓰는 API: POST /ai/conversations/{aiCnvrsRoomSn}/messages
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| cnvrsCn | String | N | 보낼 메시지. 공백만 불가, 1~1,000자. 생략·null이면 저장 없이 방의 마지막 사용자 메시지에 답한다 | AIM-011 입력창, AIM-002-07 |
| draft | RegisterDraft | N | 가장 최근 등록 카드(되물음 포함). React가 `done.card`를 그대로 돌려보낸다(출력 전용 필드는 무시). Python은 초안을 저장하지 않는다 | AIM-012-05·10 |

### MessageEvent
쓰는 API: POST /ai/conversations/{aiCnvrsRoomSn}/messages (응답 본문)

`ApiResponse` 껍데기 없이 SSE 이벤트가 차례로 온다. 각 이벤트는 `event: <이름>`과 `data: <JSON>` 두 줄이다. 순서는 `intent` → (`delta`…) → `done` 또는 `error`이고, `done`·`error`가 오면 스트림이 끝난다.
| 이벤트 | data | 설명 | 근거 |
| --- | --- | --- | --- |
| intent | Intent `{kind, scrId, scrNm, param, moveType}` | 판정. `kind`: SEARCH·ROUTE·FALLBACK·REGISTER·RECEIPT. 화면 필드는 ROUTE일 때만 값이 있다(화면 ID → 프론트 경로 변환은 React) | AIM-001-05, AIM-004 |
| delta | `{text: String}` | SEARCH 답변 조각. 이어 붙여 표시한다. 마지막 조각은 의료 고지(`\n\n※ 참고 정보이며 의료 진단이 아닙니다. …`), 미완료 답변에는 없다 | AIM-002-02·03 |
| done | `{message: ConversationMessage?, shortcut: Intent?, card: RegisterCard?}` | 끝. `message`는 저장된 AI 메시지(SEARCH 답변·FALLBACK 안내·ROUTE 이동 안내). 저장하지 않았거나 저장에 실패하면 null. `message.cmptnYn=false`면 미완료(60초 초과·도중 오류): "답변이 완료되지 않았어요" + [다시 생성]. `shortcut`은 연관 바로가기(Intent ROUTE 모양, 저장 안 함), 없으면 null | AIM-002-04·07 | `card`는 REGISTER일 때만 값이 있다(미리보기 카드나 되물음, AIM-012-05~08).
| error | `{code: "EXTERNAL_API_ERROR", message: "일시적으로 답변할 수 없어요"}` | 첫 글자 전 실패(10초 초과·오류)와 의도 분류 LLM 실패. AI 메시지는 저장하지 않는다. [다시 시도]는 `cnvrsCn` 없이 다시 보낸다 | AIM-002-07 |

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
| petChoices | List<`{petSn, petNm}`> | Y | 반려동물을 정하지 못했을 때 이름 칩(양육 반려동물 전부). 정했으면 빈 배열 | AIM-012-04 |
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

### ReceiptResultRequest
쓰는 API: POST /ai/conversations/{aiCnvrsRoomSn}/receipt-result
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| result | String | Y | `RECOGNIZED` 인식·부분 인식, `FAILED` 인식 실패(추출 0건), `ERROR` 일시 오류(API 오류·15초 초과), `CANCELED` 분석 중 취소 | AIM-013-09 |
| cnvrsCn | String | N | 이미지와 함께 보낸 텍스트. 1~1,000자, 공백만 불가. 있으면 사용자 메시지로 먼저 저장 | AIM-013-02 |
| hsptlNm | String | N | 병원명. `ReceiptOcrResponse.hsptlNm` 그대로. `RECOGNIZED`일 때만 쓴다 | AIM-013-09 |
| ckupYmd | LocalDate | N | 검진일. `ReceiptOcrResponse.ckupYmd` 그대로. `RECOGNIZED`일 때만 쓴다 | AIM-013-09 |
| recptAmt | Integer | N | 영수증 금액. `ReceiptOcrResponse.recptAmt` 그대로. `RECOGNIZED`일 때만 쓴다 | AIM-013-09 |
