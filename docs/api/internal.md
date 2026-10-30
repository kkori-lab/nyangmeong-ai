# 내부 API·DTO (초안)

Java ↔ Python 서버 간 API다. 공통 규칙은 `docs/api/README.md`에 있다. 2026-10-26 결정(DB는 Java만)으로 OCR은 Java가 부르는 이 내부 API로 유지한다(10-25 A안의 `/ai/receipts` 이전은 폐기). 캐릭터 생성은 2026-10-27 결정으로 React가 `/ai/characters`(`character.md`)를 직접 부르고, 작업 생성·결과 보고는 아래 "Python → Java" 미정 행이다(이전 `/internal/v1/character/generate`는 삭제, 백엔드 `PythonCharacterGenerator` 삭제와 같은 때 병합). Java 쪽 계약은 백엔드 `global/external`(`OcrClient`·`ReceiptOcrResponse`, 캐릭터 규격 `CharacterSpec`)이고, 이 문서의 필드는 그 record와 같아야 한다. 한쪽을 바꾸면 다른 쪽도 같은 때 바꾼다.

## API 목록

| 메서드 | 경로 | 설명 | 기능 ID | 담당 | 요청 DTO | 응답 DTO |
| --- | --- | --- | --- | --- | --- | --- |
| POST | /internal/v1/ocr/receipt | 영수증 이미지(multipart `file`)에서 항목을 뽑는다. 저장하지 않는다. 추출 0건도 200(값이 모두 null, `sections` 빈 배열). 오류: 이미지로 읽히지 않음 400 `FILE_TYPE_NOT_ALLOWED`(백엔드 `ErrorCode`와 같은 이름), 분석 시간 초과 504 `OCR_TIMEOUT`, 외부 API 오류 502 `OCR_API_ERROR`. 시간 제한은 Java 제한(15초)보다 짧게 둔다 | AIM-008-06, AIM-010-01 | LJS | ReceiptOcrRequest | ReceiptOcrResponse |

## Python → Java

Java가 만드는 API다(백엔드 저장소 기준). 키 헤더는 없다. 인증 확인과 대화 API 모두 브라우저에서 받은 `Cookie` 헤더를 그대로 보내고, 회원은 Java가 쿠키로 판정한다(`mbrSn`을 넘기지 않는다, 10-27 결정). Java `RequestedWithFilter`가 `/internal/**`에도 걸리므로 대화 API 요청에는 `X-Requested-With: XMLHttpRequest`를 붙인다. 대화 API의 인증 실패는 `/internal/auth/check`와 같은 401·403(`Set-Cookie` 포함)이다. Python은 대화 생성만 제목 생성(LLM) 전에 `/internal/auth/check`를 부르고, 나머지 대화 API 앞에서는 부르지 않는다. 대화 API의 암호화·본인 대화 판정·탈퇴 회원 파기(AIM-011-19)는 Java가 한다. Java 4xx 오류는 Python이 본문 그대로 React에 전달하고, 연결 실패·5xx·응답 모양이 다르면 Python이 502 `EXTERNAL_API_ERROR`로 답한다.

| 메서드 | 경로 | 설명 | 기능 ID | 담당 | 요청 DTO | 응답 DTO |
| --- | --- | --- | --- | --- | --- | --- |
| GET | /internal/auth/check | 쿠키의 `access_token`으로 세션·정지·탈퇴·권한을 판정한다. 통과하면 200 `data { mbrSn: Long, mbrAuthrtCd: String }`. 실패하면 Java 인증 오류(401·403, `Set-Cookie` 포함)를 그대로 돌려준다 | AIM-011-03 | 백엔드 | - | `{mbrSn, mbrAuthrtCd}` |
| POST | /internal/ai/conversations | **확정(10-27, 정본은 백엔드 `docs/api/ai.md`)** 방과 첫 메시지(사용자 역할)를 한 트랜잭션으로 저장한다. 요청 `{petSn: Long?, cnvrsTtl: String(≤200), cnvrsCn: String(1~1,000)}`. 성공 201 | AIM-011-07·11·14 | 백엔드 | `{petSn, cnvrsTtl, cnvrsCn}` | ConversationSummary(`chat.md`) |
| GET | /internal/ai/conversations?petSn= | 쿠키 회원의 대화 목록 최신순. `petSn`을 주면 그 태그만(태그 null인 "전체" 대화는 제외), 없으면 전부. 없거나 양육하지 않는 `petSn`은 404 `NOT_FOUND`(생성도 같음) | AIM-011-08·09 | 백엔드 | - | List<ConversationSummary> |
| GET | /internal/ai/conversations/{aiCnvrsRoomSn} | 대화 하나와 메시지(`msgSeq` 오름차순). 남의 대화·없는 번호 404 `NOT_FOUND` | AIM-011-10 | 백엔드 | - | ConversationResponse(Java 이름, 필드는 `chat.md` ConversationDetail + 메시지별 `cmptnYn: boolean`) |
| PATCH | /internal/ai/conversations/{aiCnvrsRoomSn} | **확정(10-30, 정본은 백엔드 `docs/api/ai.md`)** 대화 제목을 바꾼다. 요청 `{cnvrsTtl: String(1~200)}`, Java가 암호화해 저장한다. 200 ConversationSummary. 남의 대화·없는 번호 404 `NOT_FOUND`. 명세 밖 추가 요청(SCR-AIM-011): 방의 첫 AI 답변이 SEARCH로 끝나면 Python이 질문·답변 요약으로 한 번 부른다. 실패해도 답변은 그대로(로그만). 사용자 제목 변경 기능은 아니다. | AIM-011-11 | 백엔드 | `{cnvrsTtl}` | ConversationSummary(`chat.md`) |
| DELETE | /internal/ai/conversations/{aiCnvrsRoomSn} | 대화와 메시지 물리 삭제. 200. 남의 대화·없는 번호 404 `NOT_FOUND` | AIM-011-13 | 백엔드 | - | - |
| POST | /internal/ai/conversations/{aiCnvrsRoomSn}/messages | 메시지 추가. 요청 `{roleCd(AIMG06: AIMC0024 사용자·AIMC0025 AI), cnvrsCn(1~1,000), cmptnYn: Boolean?(기본 true)}`, 201 ConversationMessageResponse. `msgSeq`는 Java가 매긴다. SCR-AIM-005 폴백 문구 저장에서 사용(SCR-AIM-002·012도 사용 예정) | AIM-002·012 | 백엔드 | `{roleCd, cnvrsCn, cmptnYn}` | ConversationMessageResponse |
| GET | /internal/ai/register-context | **확정(백엔드 #54)** 쿠키 회원이 양육하는 반려동물과 각자의 케어 항목 이름. 응답 `data [{petSn: Long, petNm: String, careArtclNms: [String]}]`, `careArtclNms`는 케어 항목 API가 생길 때까지 빈 배열. SCR-AIM-012 반려동물 결정·같은 이름 케어 항목 안내에서 사용(`app/chat/repository.py` JavaRegisterContextRepository). `X-Requested-With`를 붙인다. 실패하면 메시지 스트림의 `error` `EXTERNAL_API_ERROR` | AIM-012-04·08 | 백엔드 | - | `[{petSn, petNm, careArtclNms}]` |
| POST | /internal/ai/receipts | **확정(10-30, 정본은 백엔드 `docs/api/receipt.md`, 백엔드 PR #64)** 분석 전에 원본 이미지를 저장한다. Java가 원본 파일과 RECPT(상태 분석중, 출처)를 만든다. multipart `file`(파일명·이미지 content-type)·`petSn`·`ocrDmndSrcCd`(Python 요청의 `ocrRqstSrcCd` 값). 회원은 쿠키로 판정, `X-Requested-With`를 붙인다. 201 `data { recptSn }`. 오류: `FILE_TYPE_NOT_ALLOWED`·`FILE_TOO_LARGE`·`INVALID_INPUT_VALUE`(400), `PET_ACCESS_DENIED`. Python은 형식·용량을 먼저 검증하므로 보통 Python 오류(`FILE_SIZE_EXCEEDED` 등)가 먼저 난다. `app/ocr/repository.py` `JavaReceiptRepository` | AIM-008-09, AIM-010-06, AIM-013-08 | 백엔드 | ReceiptOriginalRequest(백엔드) | ReceiptOriginalResponse(백엔드) |
| POST | /internal/ai/receipts/{recptSn}/result | **확정(10-30, 정본은 백엔드 `docs/api/receipt.md`)** 분석 결과·상태를 보고한다. 요청 JSON `{ocrRslt, ocr}`, `ocrRslt`는 `RECOGNIZED`·`UNRECOGNIZED`·`TIMEOUT`·`API_ERROR`·`CANCELED`(Java가 AIMG01로 바꾼다), `ocr`(ReceiptOcrResponse)는 `RECOGNIZED`·`UNRECOGNIZED`만 보내고 나머지는 null. React 응답 전에 보고한다. 200. 오류: `INVALID_INPUT_VALUE`·`BAD_REQUEST`(400), `RECEIPT_NOT_FOUND`(404), `RECEIPT_ALREADY_CANCELED`·`RECEIPT_ALREADY_SAVED`·`ALREADY_PROCESSED`(409). 보고 실패 처리는 `ocr.md` `/ai/receipts` | AIM-008-07, AIM-010-01, AIM-013-04 | 백엔드 | ReceiptReportRequest(백엔드) | ReceiptReportResponse(백엔드) |
| (미정) | 캐릭터 작업 생성 | 생성 작업을 만들고 반려동물 등록 정보를 돌려준다. 주양육자 여부·이미 캐릭터 있음·생성 중 판정은 Java(4xx는 Python이 React에 그대로 전달). Python이 보내는 값: `petSn`, 돌려받는 값: 작업 번호(`chrcJobSn`, 이름은 Java 작업 테이블에 맞춤)·`petSeCd`·`vrtyNm`·`colrNm`·`chrcCn`. 회원은 쿠키로 판정. 그때까지 `app/character/repository.py` `FakeCharacterJobRepository` | MYP-010-08·09 | 백엔드 | 미정 | 미정 |
| (미정) | 캐릭터 결과·상태 보고 | 작업 번호의 결과를 보고한다. 성공이면 512×512 PNG, 실패면 사유 `CHARACTER_API_ERROR`(생성기 오류)·`CHARACTER_SPEC_MISMATCH`(규격 밖). 보고가 실패해 멈춘 작업은 Java가 타임아웃으로 정리한다. 자동 저장·알림·실패 시 기본 캐릭터 표시는 Java | MYP-010-09·17·18 | 백엔드 | 미정 | 미정 |
| (미정) | 미완료 메시지 완료 처리·최근 6턴·AI 설정값 조회 | 백엔드 `docs/api/ai.md`에 PATCH 설계만 있음. SCR-AIM-002에서 필요해지면 요청 | AIM-002 | 백엔드 | 미정 | 미정 |

## DTO

### ReceiptOcrRequest
쓰는 API: POST /internal/v1/ocr/receipt (multipart/form-data)
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| file | 파일 | Y | jpg·jpeg·png·webp. 형식·용량 검증은 Java가 업로드 때 끝냈다(여기서는 이미지로 읽히는지만 본다) | AIM-008-05 |

### ReceiptOcrResponse
쓰는 API: POST /internal/v1/ocr/receipt
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| hsptlNm | String | N | 병원명 | AIM-009-02 |
| ckupYmd | LocalDate | N | 검진일 `YYYY-MM-DD`. 연도가 없으면 null(연도 보정은 Java) | AIM-009-02 |
| recptAmt | Long | N | 최종 결제 금액(할인 후) | AIM-009-02 |
| btmDscntAmt | Long | N | 영수증 하단에만 찍힌 할인 합계. 배분은 Java | AIM-009-20 |
| sections | List<Section> | Y | 반려동물 구역. 구역 없는 영수증은 `sectionNm` null인 구역 1개 | AIM-009-16 |

#### Section (ReceiptOcrResponse.sections)
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| sectionNm | String | N | 구역의 반려동물 이름(예: 미르) | AIM-009-16·17 |
| sbttlAmt | Long | N | 구역 소계 | AIM-009-20 |
| dscntAmt | Long | N | 구역 안에 찍힌 할인 | AIM-009-20 |
| items | List<Line> | Y | 진료 품목 | AIM-009-21 |
| drugs | List<Drug> | Y | 처방 약품 | AIM-009-03·04 |

#### Line (Section.items)
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| itemNm | String | N | 품목명 | AIM-009-21 |
| itemAmt | Long | N | 품목 금액 | AIM-009-19 |

#### Drug (Section.drugs)
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| mdcnNm | String | N | 약품명 | AIM-009-03 |
| mdcnDays | Integer | N | 일수 | AIM-009-04 |
| mdcnUsage | String | N | 용법 원문(예: 1일 2회) | AIM-009-04 |
| mdcnAmt | Long | N | 약품 금액(대조용) | AIM-009-13 |

## 외부 AI 키가 없을 때

mock 모드는 없다(2026-10-29). 키가 없거나 클라이언트가 연결되기 전이면 OCR·캐릭터 API는 502 `EXTERNAL_API_ERROR`다. 테스트는 가짜 클라이언트를 끼운다.
