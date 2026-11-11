# 캐릭터 생성 API·DTO (초안)

React가 부르는 `/ai/**` API다. 공통 규칙은 `docs/api/README.md`에 있다. 이 문서는 픽셀 캐릭터 만들기(SCR-MYP-010 10-3)의 서버 부분을 다룬다.

- 인증: `chat.md`와 같다. 쿠키 `access_token`을 Java `/internal/auth/check`로 확인하고, 인증 오류는 본문·`Set-Cookie` 그대로, Java에 닿지 못하면 502 `EXTERNAL_API_ERROR`. `X-Requested-With: XMLHttpRequest`가 없으면 403 `FORBIDDEN`.
- 흐름: 업로드 검증 → 생성기 준비 확인 → Java에 작업 생성(주양육자 여부·이미 캐릭터 있음·생성 중 판정, 등록된 품종·털색·특징을 돌려받음) → 202·작업 번호 → 응답 뒤 백그라운드 생성 → 512×512 규격 검증 → Java에 결과·상태 보고. Java 호출은 `app/character/repository.py` `JavaCharacterJobRepository`가 한다(계약은 `internal.md` "Python → Java").
- 품종·털색·특징은 React가 보내지 않는다(FN-MYP-010-08 등록된 값 읽기 전용). 보내도 쓰지 않는다.
- 상태 조회·결과 자동 저장·완료 알림·실패 시 종별 기본 캐릭터 표시·멈춘 작업 정리는 Java가 한다. React는 상태를 Java에서 조회한다.
- 생성기(사진 분석 포함)는 다른 곳에서 만드는 것을 붙인다. 붙이기 전에는 502 `EXTERNAL_API_ERROR`다.

## API 목록

| 메서드 | 경로 | 설명 | 기능 ID | 담당 | 요청 DTO | 응답 DTO |
| --- | --- | --- | --- | --- | --- | --- |
| POST | /ai/characters | 사진과 반려동물로 픽셀 캐릭터 생성을 시작한다. 202와 작업 번호를 바로 주고, 생성은 응답 뒤에 한다. 결과(성공이면 512×512 PNG, 실패면 `CHARACTER_API_ERROR`·`CHARACTER_SPEC_MISMATCH`)는 Java에 보고한다. 오류: 형식(확장자·실제 형식 불일치, PDF 포함) 400 `FILE_TYPE_NOT_ALLOWED`, 10MB 초과 400 `FILE_SIZE_EXCEEDED`, `petSn`·`photo` 없음 400 `INVALID_REQUEST`(검증 실패는 Java 작업을 만들지 않는다), 생성기가 없음 502 `EXTERNAL_API_ERROR`(Java 작업을 만들기 전에 판정), 주양육자 아님·이미 캐릭터 있음·생성 중 등 Java 4xx 그대로, Java 연결 실패 502 `EXTERNAL_API_ERROR` | MYP-010-08·09·17·18 | LJS | CharacterCreateRequest | CharacterCreateResponse |
| POST | /ai/characters/{pixelCharSn}/preview | 아이템을 입힌 512×512 PNG를 돌려준다. 저장하지 않는다. 합성 순서는 머리 착용 그림(없으면 맨몸) → 의상 → 가방 → 목 → 얼굴. 착용 확정은 Java `PUT /pixel-characters/{pixelCharSn}/equipped-items`, 확정 뒤 대표 이미지 저장은 `POST /ai/characters/{pixelCharSn}/equipped-image`. 오류: 아이템 번호가 굽기 대상이 아님(신발 포함)·같은 부위 2개 400 `INVALID_REQUEST`, 캐릭터 없음 404 `PIXEL_CHARACTER_NOT_FOUND`(Java 4xx 그대로), 아직 안 구움 409 `ITEM_BAKING`(굽기가 켜져 있으면 그 아이템을 큐 맨 앞으로 올린다. 다시 요청한다), 굽기 실패·합성 실패 502 `CHARACTER_API_ERROR`, 생성기 없음 502 `EXTERNAL_API_ERROR` | MYP-011-01, MYP-010-13 | LJS | CharacterPreviewRequest | `image/png` |
| POST | /ai/characters/{pixelCharSn}/equipped-image | 꾸미기 [장착]으로 착용을 확정한 뒤 그 모습을 대표 이미지로 저장한다. React가 Java `PUT /pixel-characters/{pixelCharSn}/equipped-items` 성공 뒤 같은 `itemSns`로 부른다(결과를 기다리지 않아도 된다). Java가 착용 확정 때 대표 이미지를 지우므로 이 호출이 실패해도 꾸미기 밖 화면(`GET /pets/{petSn}/character-image`)은 맨몸이다. 합성은 `/preview`와 같고, 결과 PNG를 Java `PUT /internal/ai/characters/{pixelCharSn}/equipped-image`로 저장한다(브라우저가 올린 그림은 받지 않는다). 응답 200 `data` 없음. 오류: `/preview`와 같은 400 `INVALID_REQUEST`·404·409 `ITEM_BAKING`·502 `CHARACTER_API_ERROR`·502 `EXTERNAL_API_ERROR`(모두 저장하지 않는다), 저장 때 Java 4xx 그대로(지금 착용 목록과 다르면 409 `EQUIPPED_ITEMS_CHANGED`, 공동양육자 403 `PET_PRIMARY_ONLY`, 없는 캐릭터 404 `PIXEL_CHARACTER_NOT_FOUND`) | MYP-010-16, MYP-010-13 | LJS | CharacterPreviewRequest | - |
| POST | /ai/items/bake-hints | 관리자가 올린 아이템 그림을 비전 모델이 보고 굽기 지시(영어 한 문장)를 만든다. 관리자는 문장을 고쳐 Java 아이템 등록에 함께 보낸다. 그림을 저장하지 않는다. 관리자(`mbrAuthrtCd` `USRC0005`)만. 오류: 관리자 아님 403 `FORBIDDEN`, 부위가 MYPC0001~0005 밖(신발 포함)·이름 길이·그림 없음 400 `INVALID_REQUEST`, 그림 형식 400 `FILE_TYPE_NOT_ALLOWED`, 10MB 초과 400 `FILE_SIZE_EXCEEDED`, 생성기 없음·비전 호출 실패·빈 답 502 `EXTERNAL_API_ERROR` | ADM-070-02 | LJS | ItemBakeHintRequest | ItemBakeHintResponse |
| POST | /ai/items/pixel-image | 관리자가 올린 실사 아이템 사진으로 픽셀 아이템 그림(상점·관리자 목록 이미지)을 만든다. 256×256 투명 배경 PNG, 아이템 하나가 가운데. 관리자 프론트가 미리 보여 주고 고르면 Java 아이템 등록의 이미지로 올린다. 착용 그림은 이 그림이 아니라 굽기 지시로 캐릭터마다 굽는다. 그림을 저장하지 않는다. 요청마다 이미지 1장 과금, 30~40초. 관리자만. 오류: 관리자 아님 403 `FORBIDDEN`, 부위가 MYPC0001~0005 밖(신발 포함)·이름 길이·그림 없음 400 `INVALID_REQUEST`, 그림 형식 400 `FILE_TYPE_NOT_ALLOWED`, 10MB 초과 400 `FILE_SIZE_EXCEEDED`, 생성기 없음 502 `EXTERNAL_API_ERROR`, 생성 실패·배경을 떼고 남은 그림 없음 502 `CHARACTER_API_ERROR` | ADM-070-02 | LJS | ItemBakeHintRequest | `image/png` |
| POST | /ai/items/trial-preview | 관리자 본인 캐릭터에 굽기 지시를 한 번 구워 입힌 512×512 PNG를 돌려준다. 저장하지 않는다. 요청마다 이미지 1장 과금. 관리자만. 오류: 관리자 아님 403 `FORBIDDEN`, 형식 400 `INVALID_REQUEST`, 캐릭터 없음·남의 캐릭터 Java 4xx 그대로, 생성기 없음 502 `EXTERNAL_API_ERROR`, 굽기·검증·합성 실패 502 `CHARACTER_API_ERROR` | ADM-070-02 | LJS | ItemTrialRequest | `image/png` |
| POST | /ai/items/{itemSn}/bake | 새 아이템을 아직 안 구운 기존 캐릭터에 한 묶음(최대 13개)씩 굽는다. 관리자 프론트가 Java 아이템 등록 성공 뒤 부르고, 응답 `lastYn`이 true가 될 때까지 다시 부른다(요청마다 새 쿠키라 access_token 30분 만료에 걸리지 않는다. 한 번은 굽기 한 번 시간, 약 31~37초). Java 대상 목록 첫 페이지를 관리자 쿠키로 읽어 큐 뒤에 넣고 끝날 때까지 기다린 뒤 200으로 답한다(회원 미리보기가 먼저, 같은 캐릭터×아이템을 굽는 중이면 그 결과를 함께 받는다). 구웠거나 실패 표시한 캐릭터는 Java 목록에서 빠지므로 다시 불러도 된다(재시작으로 끊긴 굽기 재개). 관리자만. 오류: 관리자 아님 403 `FORBIDDEN`, 굽기 대상 아이템이 아님 400 `INVALID_REQUEST`, 대상 목록 Java 4xx 그대로, 생성기 없음·묶음을 하나도 저장·실패 표시하지 못함(다시 불러도 같은 대상이라 반복을 멈춘다) 502 `EXTERNAL_API_ERROR` | ADM-070-02, MYP-011-01 | LJS | - | ItemBakeResponse |

## DTO

### CharacterCreateRequest
쓰는 API: POST /ai/characters (multipart/form-data)
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| photo | 파일 | Y | jpg·jpeg·png·webp, 10MB 이하. 확장자와 실제 형식(파일 시그니처)이 같아야 한다. PDF 불가 | MYP-010-08 |
| petSn | Long | Y | 캐릭터를 만들 반려동물. 주양육자 여부 검사는 Java가 작업 생성 때 한다 | MYP-010-08 |

### CharacterCreateResponse
쓰는 API: POST /ai/characters (202)
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| charCrtJobSn | Long | Y | Java가 만든 생성 작업 번호. 상태 조회에 쓴다. | MYP-010-09 |

### CharacterPreviewRequest
쓰는 API: POST /ai/characters/{pixelCharSn}/preview, POST /ai/characters/{pixelCharSn}/equipped-image
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| itemSns | List\<Long\> | Y | 입혀 볼 아이템 번호(`ITEM_SN`). 상점에서는 아직 안 산 아이템도 입혀 보므로 보유 번호가 아니다. 부위당 1개. 빈 목록이면 맨몸 | MYP-011-01, MYP-010-13 |

### ItemBakeHintRequest
쓰는 API: POST /ai/items/bake-hints, POST /ai/items/pixel-image (multipart/form-data)
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| regnCd | String | Y | 부위 공통코드 MYPG01: MYPC0001 머리·MYPC0002 얼굴·MYPC0003 목·MYPC0004 의상·MYPC0005 가방. 신발(MYPC0006)은 굽지 않아 400 | ADM-070-02 |
| itemNm | String | Y | 아이템 이름 1~50자. 그림 설명의 참고로만 쓴다 | ADM-070-02 |
| image | 파일 | Y | 아이템 그림(상점 이미지와 같은 파일). jpg·jpeg·png·webp, 10MB 이하 | ADM-070-02 |

### ItemBakeHintResponse
쓰는 API: POST /ai/items/bake-hints
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| bakeHint | String | Y | 영어 한 문장(150자 이내). 종은 `dog`로 쓰고 굽기 때 고양이면 `cat`으로 바꾼다. Java `ITEM` 굽기 지시로 저장한다 | ADM-070-02 |

### ItemTrialRequest
쓰는 API: POST /ai/items/trial-preview
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| pixelCharSn | Long | Y | 시험할 캐릭터. 소유 판정은 Java(관리자 본인 캐릭터) | ADM-070-02 |
| regnCd | String | Y | ItemBakeHintRequest와 같다 | ADM-070-02 |
| bakeHint | String | Y | 1~300자. 시험할 굽기 지시 | ADM-070-02 |

### ItemBakeResponse
쓰는 API: POST /ai/items/{itemSn}/bake (200)
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| itemSn | Long | Y | 굽는 아이템 | ADM-070-02 |
| bakedCnt | Integer | Y | 이번 묶음에서 착용 시트를 저장한 캐릭터 수 | ADM-070-02 |
| failedCnt | Integer | Y | 이번 묶음에서 굽기 실패로 표시한 캐릭터 수 | ADM-070-02 |
| lastYn | Boolean | Y | 남은 대상 없음. false면 관리자 프론트가 다시 부른다. 맨몸 시트를 못 받는 등 처리하지 못한 캐릭터가 있으면 false | ADM-070-02 |
