# AI 대화창 API·DTO (초안)

React가 부르는 `/ai/**` API다. 공통 규칙은 `docs/api/README.md`에 있다. 이 문서는 대화 저장·조회·삭제(SCR-AIM-011)까지 다룬다. 질문 전송·AI 답변(SCR-AIM-001·002·004·005·012)은 해당 마일스톤에서 추가한다.

- 인증: 쿠키 `access_token`(JWT, HS256). 토큰이 없거나 틀리면 401 `UNAUTHORIZED`, 만료면 401 `TOKEN_EXPIRED`(백엔드 `ErrorCode`와 같은 이름). 서명과 만료만 본다(Python은 로그인 세션 테이블을 읽지 않는다).
- POST·DELETE는 `X-Requested-With: XMLHttpRequest`가 없으면 403 `FORBIDDEN`이다.
- 본인 대화만 다룬다. 토큰의 회원 번호와 대화방의 `MBR_SN`이 다르면 없는 것으로 보고 404 `NOT_FOUND`를 준다.
- 제목과 본문은 DB에 암호문(`CNVRS_TTL_ENC`·`CNVRS_CN_ENC`)으로 저장하고, 응답은 복호화한 값이다. 암호문 형식과 키는 백엔드 `FieldCryptoService`와 같다.
- `petSn`은 대화의 펫 태그(구분값)다. 소유권은 검사하지 않는다(Java 담당). null이면 "전체" 대화다.

## API 목록

| 메서드 | 경로 | 설명 | 기능 ID | 담당 | 요청 DTO | 응답 DTO |
| --- | --- | --- | --- | --- | --- | --- |
| POST | /ai/conversations | 새 대화를 만든다. 첫 메시지로 제목을 자동 생성(200자 이내, 1회)하고, 방과 첫 메시지(사용자 역할)를 함께 저장한다. 오류: 본문 비었거나 공백만·1,000자 초과 400 `INVALID_REQUEST`. 성공은 201 | AIM-011-07·11·14 | LJS | ConversationCreateRequest | ConversationSummary |
| GET | /ai/conversations | 내 대화 목록을 최신순으로 준다. 쿼리 `petSn`을 주면 그 태그의 대화만(태그가 null인 "전체" 대화는 나오지 않는다), 없으면 전부. 오늘·어제·지난 7일 그룹은 React가 `regDt`로 나눈다. 없으면 빈 배열 | AIM-011-08·09 | LJS | - | List<ConversationSummary> |
| GET | /ai/conversations/{aiCnvrsRoomSn} | 대화 하나와 메시지를 순서대로 준다. 남의 대화·없는 번호 404 `NOT_FOUND` | AIM-011-10 | LJS | - | ConversationDetail |
| DELETE | /ai/conversations/{aiCnvrsRoomSn} | 대화와 메시지를 물리 삭제한다(복구 불가). 남의 대화·없는 번호 404 `NOT_FOUND` | AIM-011-13 | LJS | - | - |

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
쓰는 API: GET /ai/conversations/{aiCnvrsRoomSn}
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| aiCnvrsMsgSn | Long | Y | 메시지 번호 | AI_CNVRS_MSG.AI_CNVRS_MSG_SN |
| roleCd | String | Y | `AIMC0024` 사용자, `AIMC0025` AI(공통코드 AIMG06) | AI_CNVRS_MSG.ROLE_CD |
| cnvrsCn | String | Y | 복호화한 내용 | AI_CNVRS_MSG.CNVRS_CN_ENC |
| msgSeq | Integer | Y | 대화 안 순서(1부터) | AI_CNVRS_MSG.MSG_SEQ |
| regDt | LocalDateTime | Y | 메시지 일시 | AI_CNVRS_MSG.REG_DT |
