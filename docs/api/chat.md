# AI 대화창 API·DTO (초안)

React가 부르는 `/ai/**` API다. 공통 규칙은 `docs/api/README.md`에 있다. 이 문서는 대화 저장·조회·삭제(SCR-AIM-011)와 메시지 전송·AI 답변(SCR-AIM-002, 판정은 SCR-AIM-004·005)을 다룬다. 등록(SCR-AIM-012)·영수증(SCR-AIM-013) 이어 가기는 해당 마일스톤에서 추가한다.

- 인증: 요청마다 쿠키 `access_token`을 Java `/internal/auth/check`로 확인한다(`docs/api/README.md`). 토큰이 없거나 틀리면 401 `UNAUTHORIZED`, 만료면 401 `TOKEN_EXPIRED`, 정지·탈퇴면 403 `MEMBER_INACTIVE`(쿠키 삭제 `Set-Cookie` 포함), Java에 닿지 못하면 502 `EXTERNAL_API_ERROR`.
- POST·DELETE는 `X-Requested-With: XMLHttpRequest`가 없으면 403 `FORBIDDEN`이다.
- 본인 대화만 다룬다. 남의 대화·없는 번호는 없는 것으로 보고 404 `NOT_FOUND`를 준다. 전환 후에는 Java 대화 API가 판정한다(오류 코드 이름은 Java 설계 확정 후 맞춘다).
- 제목과 본문은 DB에 암호문(`CNVRS_TTL_ENC`·`CNVRS_CN_ENC`)으로 저장하고, 응답은 복호화한 값이다. 전환 후 암호화는 Java `FieldCryptoService`가 한다. 아래 경로·DTO(React와의 계약)는 전환 후에도 그대로 둔다.
- `petSn`은 대화의 펫 태그(구분값)다. 소유권은 검사하지 않는다(Java 담당). null이면 "전체" 대화다.

## API 목록

| 메서드 | 경로 | 설명 | 기능 ID | 담당 | 요청 DTO | 응답 DTO |
| --- | --- | --- | --- | --- | --- | --- |
| GET | /ai/me | 인증 확인용. Java `/internal/auth/check` 결과의 회원 번호만 준다. 오류: Java 인증 오류(401·403) 본문·`Set-Cookie` 그대로, Java에 닿지 못하면 502 `EXTERNAL_API_ERROR` | AIM-011-03 | LJS | - | `{mbrSn: Long}` |
| POST | /ai/conversations | 새 대화를 만든다. 첫 메시지로 제목을 자동 생성(200자 이내, 1회)하고, 방과 첫 메시지(사용자 역할)를 함께 저장한다. 오류: 본문 비었거나 공백만·1,000자 초과 400 `INVALID_REQUEST`. 성공은 201 | AIM-011-07·11·14 | LJS | ConversationCreateRequest | ConversationSummary |
| GET | /ai/conversations | 내 대화 목록을 최신순으로 준다. 쿼리 `petSn`을 주면 그 태그의 대화만(태그가 null인 "전체" 대화는 나오지 않는다), 없으면 전부. 오늘·어제·지난 7일 그룹은 React가 `regDt`로 나눈다. 없으면 빈 배열 | AIM-011-08·09 | LJS | - | List<ConversationSummary> |
| GET | /ai/conversations/{aiCnvrsRoomSn} | 대화 하나와 메시지를 순서대로 준다. 남의 대화·없는 번호 404 `NOT_FOUND` | AIM-011-10 | LJS | - | ConversationDetail |
| DELETE | /ai/conversations/{aiCnvrsRoomSn} | 대화와 메시지를 물리 삭제한다(복구 불가). 남의 대화·없는 번호 404 `NOT_FOUND` | AIM-011-13 | LJS | - | - |
| POST | /ai/conversations/{aiCnvrsRoomSn}/messages | 메시지를 보내고 판정·답변을 SSE(`text/event-stream`)로 받는다. `cnvrsCn`이 있으면 사용자 메시지로 저장하고 답한다. 없으면 저장 없이 방의 마지막 사용자 메시지에 답한다(첫 메시지 직후·[다시 시도]·[다시 생성]). 판정이 SEARCH면 LLM 답변을 흘리고 끝에 의료 고지를 붙여 저장, FALLBACK이면 안내 문구를 저장, ROUTE·REGISTER·RECEIPT는 판정만 준다. 컨텍스트는 현재 대화의 미완료를 뺀 최근 6턴. 첫 글자 10초 초과·오류는 `error` 이벤트(저장 없음), 첫 글자 뒤 60초 초과·오류는 부분 답변을 미완료(`cmptnYn=false`)로 저장. 연결이 끊겨도 생성·저장은 끝까지 한다(완료로 저장). 스트림 시작 전 오류는 JSON: 본문 공백만·1,000자 초과·답할 사용자 메시지 없음 400 `INVALID_REQUEST`, 남의 대화·없는 번호 404 `NOT_FOUND` | AIM-002-02·03·04·07·08·09·10·11, AIM-011-15·16 | LJS | MessageSendRequest | SSE 이벤트(아래 MessageEvent) |

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
쓰는 API: GET /ai/conversations/{aiCnvrsRoomSn}, POST /ai/conversations/{aiCnvrsRoomSn}/messages(`done` 이벤트)
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

### MessageEvent
쓰는 API: POST /ai/conversations/{aiCnvrsRoomSn}/messages (응답 본문)

`ApiResponse` 껍데기 없이 SSE 이벤트가 차례로 온다. 각 이벤트는 `event: <이름>`과 `data: <JSON>` 두 줄이다. 순서는 `intent` → (`delta`…) → `done` 또는 `error`이고, `done`·`error`가 오면 스트림이 끝난다.
| 이벤트 | data | 설명 | 근거 |
| --- | --- | --- | --- |
| intent | Intent `{kind, scrId, scrNm, param, moveType}` | 판정. `kind`: SEARCH·ROUTE·FALLBACK·REGISTER·RECEIPT. 화면 필드는 ROUTE일 때만 값이 있다(화면 ID → 프론트 경로 변환은 React) | AIM-001-05, AIM-004 |
| delta | `{text: String}` | SEARCH 답변 조각. 이어 붙여 표시한다. 마지막 조각은 의료 고지(`\n\n※ 참고 정보이며 의료 진단이 아닙니다. …`), 미완료 답변에는 없다 | AIM-002-02·03 |
| done | `{message: ConversationMessage?, shortcut: Intent?}` | 끝. `message`는 저장된 AI 메시지(SEARCH 답변·FALLBACK 안내). 저장하지 않았거나 저장에 실패하면 null. `message.cmptnYn=false`면 미완료(60초 초과·도중 오류): "답변이 완료되지 않았어요" + [다시 생성]. `shortcut`은 연관 바로가기(Intent ROUTE 모양, 저장 안 함), 없으면 null | AIM-002-04·07 |
| error | `{code: "EXTERNAL_API_ERROR", message: "일시적으로 답변할 수 없어요"}` | 첫 글자 전 실패(10초 초과·오류). AI 메시지는 저장하지 않는다. [다시 시도]는 `cnvrsCn` 없이 다시 보낸다 | AIM-002-07 |
