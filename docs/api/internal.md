# 내부 API·DTO (초안)

Java ↔ Python 서버 간 API다. 공통 규칙은 `docs/api/README.md`에 있다. 2026-10-26 결정(DB는 Java만)으로 OCR은 Java가 부르는 이 내부 API로 유지한다(10-25 A안의 `/ai/receipts` 이전은 폐기). 캐릭터 생성은 2026-10-27 결정으로 React가 `/ai/characters`(`character.md`)를 직접 부르고, 작업 생성·결과 보고는 아래 "Python → Java" `/internal/ai/characters` 행이다(이전 `/internal/v1/character/generate`는 삭제, 백엔드 `PythonCharacterGenerator` 삭제와 같은 때 병합). Java 쪽 계약은 백엔드 `global/external`(`OcrClient`·`ReceiptOcrResponse`, 캐릭터 규격 `CharacterSpec`)이고, 이 문서의 필드는 그 record와 같아야 한다. 한쪽을 바꾸면 다른 쪽도 같은 때 바꾼다.

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
| POST | `/internal/ai/characters/jobs` | 생성 작업을 만들고 반려동물 등록 정보를 돌려준다. 주양육자 여부·이미 캐릭터 있음·생성 중 판정은 Java(쿠키로 회원 판정, 4xx는 Python이 React에 그대로 전달). 요청 `{petSn: Long}`, 응답 `data {charCrtJobSn: Long, petSeCd, vrtyNm, colrNm, chrcCn}` | MYP-010-08·09 | 백엔드 | - | - |
| POST | `/internal/ai/characters/jobs/{charCrtJobSn}/success` | 생성 성공 보고. 응답 뒤 호출이라 요청에서 복사해 둔 쿠키를 보낸다. 작업을 만든 회원 본인만, 아니면 403. 생성 중인 작업만 받고, 이미 완료면 같은 `pixelCharSn`, 실패로 끝난 작업이면 409 `ALREADY_PROCESSED`. multipart `image`(512×512 PNG)·`sheet`(맨몸 2×2 시트 1024 PNG), 폼 `scale`·`originX`·`originY`. 응답 `data {pixelCharSn: Long}`. 자동 저장·알림·실패 시 기본 캐릭터 표시는 Java. 보고가 실패해 멈춘 작업은 Java가 타임아웃으로 정리한다 | MYP-010-09·17·18, MYP-011-01 | 백엔드 | - | - |
| POST | `/internal/ai/characters/jobs/{charCrtJobSn}/failure` | 생성 실패 보고. 쿠키로 작업을 만든 회원 본인만, 아니면 403. 끝난 작업이면 그대로 200. 요청 `{failRsn}`: `CHARACTER_API_ERROR`(생성기 오류)·`CHARACTER_SPEC_MISMATCH`(규격 밖) | MYP-010-09 | 백엔드 | - | - |
| GET | `/internal/ai/characters/bake-items` | 굽기 대상(판매 중이고 굽기 지시나 굽기용 그림이 있는 아이템). 쿠키로 로그인만 확인한다. 응답 `data [{itemSn: Long, regnCd: String, bakeHint: String?, bakeImageFileSn: Long?}]`. `ITEM`에 굽기 지시 컬럼이 필요하다(시드 원본 `docs/design/item-bake-hints.json` 26개, 관리자 등록 때 `/ai/items/bake-hints` 초안). **초안(2026-11-11, 백엔드 확정 전. Python은 가짜 응답으로 구현)**: `bakeImageFileSn`이 있으면 그 픽셀 아이템 그림을 참고로 굽고(`item-files`로 받는다), 없으면 `bakeHint` 문장으로 굽는다. 둘 다 없는 행은 Python이 뺀다. 그림 참고로 구울 아이템은 Java가 이 값을 채워 정한다(상점 그림이 실사 사진인 옛 아이템은 null). 설계 `docs/design/pixel-character-engine.md` 9절 | MYP-011-01, MYP-010-13, ADM-070-02 | 백엔드 | - | - |
| GET | `/internal/ai/characters/item-files/{atchFileSn}` | **초안(2026-11-11, 백엔드 확정 전. Python은 가짜 응답으로 구현)** 굽기용 아이템 그림 내려받기, 응답 `image/png`(ApiResponse 아님). 쿠키로 로그인만 확인한다(회원 굽기는 주양육자 쿠키, 전체 굽기는 관리자 쿠키). `bake-items`의 `bakeImageFileSn`이 아니면 404 | MYP-011-01, MYP-010-13, ADM-070-02 | 백엔드 | - | - |
| GET | `/internal/ai/items/{itemSn}/bake-targets?page=` | 그 아이템을 아직 안 구운 캐릭터(맨몸 시트가 있고 착용 시트·굽기 실패 표시가 없음). 쿠키로 관리자만(아니면 403 `ADMIN_ONLY`), 굽기 대상 아이템이 아니면 404 `ITEM_NOT_FOUND`. `page`는 0부터, 한 페이지 100개, 캐릭터 번호순. 응답 `data {pixelCharSns: [Long], last: Boolean}`. 구웠거나 실패 표시한 캐릭터는 빠지므로 Python은 묶음마다 `page=0`만 읽는다 | ADM-070-02 | 백엔드 | - | - |
| PUT | `/internal/ai/characters/{pixelCharSn}/item-sheets/{itemSn}` | 캐릭터 × 아이템 착용 시트 저장. 쿠키로 주양육자만. multipart `sheet`(1024 PNG). 관리자 쿠키면 남의 캐릭터도 허용한다(전체 굽기 `/ai/items/{itemSn}/bake`, 백엔드 PR #149). 쿠키 없는 호출은 401 | MYP-011-01, MYP-010-13 | 백엔드 | - | - |
| POST | `/internal/ai/characters/{pixelCharSn}/item-sheets/{itemSn}/failure` | 캐릭터 × 아이템 굽기 실패 표시. 쿠키로 주양육자만. 본문 없음. 관리자 쿠키면 남의 캐릭터도 허용한다(전체 굽기 `/ai/items/{itemSn}/bake`, 백엔드 PR #149). 쿠키 없는 호출은 401 | MYP-011-01, MYP-010-13 | 백엔드 | - | - |
| GET | `/internal/ai/characters/{pixelCharSn}/sheets?itemSns=` | 합성용 시트 정보. 안 산 아이템도 조회한다. 응답 `data {petSeCd, sheetFileSn: Long, scale, originX, originY, items: [{itemSn, atchFileSn: Long?, bakeFailed: Boolean}]}`. 안 구운 아이템은 `atchFileSn` null. 주양육자·소유 판정은 Java(쿠키, 4xx는 Python이 React에 그대로 전달). 없으면 404 `PIXEL_CHARACTER_NOT_FOUND`. 관리자 쿠키면 남의 캐릭터도 허용한다(전체 굽기 `/ai/items/{itemSn}/bake`, 백엔드 PR #149). 쿠키 없는 호출은 401 | MYP-011-01·06, MYP-010-13 | 백엔드 | - | - |
| GET | `/internal/ai/characters/{pixelCharSn}/sheet-files/{atchFileSn}` | 시트 파일 내려받기, 응답 `image/png`(ApiResponse 아님). 쿠키로 소유 판정. 그 캐릭터의 시트가 아니면 404. 관리자 쿠키면 남의 캐릭터도 허용한다(전체 굽기 `/ai/items/{itemSn}/bake`, 백엔드 PR #149). 쿠키 없는 호출은 401 | MYP-011-01, MYP-010-13 | 백엔드 | - | - |
| PUT | `/internal/ai/characters/{pixelCharSn}/equipped-image` | 착용 모습 대표 이미지 저장(백엔드 PR #149). React가 Java `PUT /pixel-characters/{pixelCharSn}/equipped-items` 성공 뒤 Python `/ai/characters/{pixelCharSn}/equipped-image`를 부르면 Python이 합성해 보낸다. 쿠키로 주양육자만. multipart `image`(512×512 PNG), 폼 `itemSns`(여러 번, 맨몸이면 없음). `itemSns`가 지금 확정 착용 목록과 같을 때만 저장하고, 다르면 409 `EQUIPPED_ITEMS_CHANGED`(늦게 끝난 옛 합성이 덮어쓰지 않게). 512×512 PNG가 아니면 400 `FILE_TYPE_NOT_ALLOWED`, 공동양육자 403 `PET_PRIMARY_ONLY`, 없는 캐릭터 404 `PIXEL_CHARACTER_NOT_FOUND`. Java는 `PUT equipped-items`(착용 확정)와 캐릭터 생성 성공 보고 때 대표 이미지를 지우고, `GET /pets/{petSn}/character-image`는 대표 이미지 → 맨몸 → 기본 캐릭터 순으로 준다. 응답 200 본문 없음 | MYP-010-16, MYP-010-13 | 백엔드 | - | - |
| GET | `/internal/ai/pets/{petSn}/health-report-input?baseYmd=` | **구현(2026-11-04 초안, 백엔드 `AiHealthReportController`, LJS 백엔드)** 메인 AI 건강분석 리포트의 분석 입력과 저장된 최근 리포트를 한 번에 준다. 쿠키로 그 반려동물을 양육하는 회원만(아니면 4xx, Python이 그대로 전달). `baseYmd`(KST 오늘) 포함 14일 기록을 자른다. 응답 `data {input, report, rfrshPsblYn: Boolean, autoRgnrPsblYn: Boolean}`. `input {petNm, petSeCd, vrtyNm, ageMm: Integer, nutrYn, goalBdwg, weights·meals·waters·walks [{ymd, rcdNvl}](DAILY_HLTH_RCD HLTC0014·0015·0016·0018), stools [{ymd, crsdSttsCdNm}](HLTC0017), latestCkupYmd, inspOutOfRange [{inspArtclNm, rsltNvl, unitNm, refLlmtNvl, refUplmtNvl}](가장 최근 검진 1회의 INSP_NVL 중 참고 범위 밖)}`. `report {rptTtl, tips: [String], inputHash: String(64), crtDt}`는 그 반려동물의 가장 최근 저장본, 없으면 null. `rfrshPsblYn`은 `baseYmd`에 새로고침(`rfrshYn: true` 저장)을 아직 안 했으면 true. `autoRgnrPsblYn`은 `baseYmd`에 자동 재생성(그날 첫 생성 뒤 `rfrshYn: false` 저장)이 5회 미만이면 true | MAN-006 | 백엔드 | - | - |
| PUT | `/internal/ai/pets/{petSn}/health-report` | **구현(2026-11-04 초안, 백엔드 `AiHealthReportController`, LJS 백엔드)** 리포트 저장(반려동물·기준일당 최신 1건을 덮어써도 된다). 요청 `{baseYmd, rptTtl(≤20), tips: [String](≤3, 각 ≤40), inputHash: String(64), rfrshYn: Boolean}`. Java는 `rfrshYn`으로 새로고침 횟수를, 그날 이미 저장본이 있는데 `rfrshYn: false`면 자동 재생성 횟수를 센다. 200. 새 테이블(ERD 변경) | MAN-006 | 백엔드 | - | - |
| GET | `/internal/ai/tools` | **확정(2026-11-06, 백엔드 PR #174 병합. 설계 `docs/design/tool-catalog.md` 3-2절)** AI 매니저 도구 목록. `@AiTool`을 붙인 컨트롤러 메서드와 요청 DTO의 검증 어노테이션(`@NotNull`·`@NotBlank`·`@Size` 등)·`@AiCode`·`@AiRequiredIf`를 읽어 만든다. 회원과 관계없는 목록이라 쿠키·키 없이 부른다. 응답 `data` AiToolCatalogResponse. Python은 기동 때 1회 부르고(2026-11-09부터 항상), 실패(연결 실패·5xx·4xx·모양 다름)하면 `data/tools.snapshot.json`으로 뜨고 코드 칸이 있는 도구는 싣지 않는다(`app/chat/catalog.py`). 400 응답은 지금 모양 그대로 `data: [{field, message}]`(Bean Validation 오류만 칸 이름이 있고, 서비스 검사 `INVALID_INPUT_VALUE`의 칸 이름은 다음 백엔드 마일스톤. 2026-11-05 백엔드 결정) | AIM-004-02, AIM-012-03(도구 목록 기능 ID는 기능명세서 추가 전) | 백엔드 | - | AiToolCatalogResponse |
| GET | `/internal/ai/routes` | **확정(정본은 백엔드 `docs/api/ai.md`, 백엔드 `c0bf1f2` develop·main 병합)** 라우팅 매핑표(관리자 SCR-ADM-080, DB `AI_ROUT_MPNG`). 사용 중(`USE_YN='Y'`) 행만 `prrtSeq`·`aiRoutMpngSn` 순, 이동 방식이 라우팅 대상 아님·제외·보류(AIMC0034~0036)인 행도 준다. 쿠키로 로그인 회원이면 같은 표. Python은 대화 메시지 요청 때 받은 지 10초가 지났으면 그 요청의 쿠키로 다시 받는다(2026-11-10 결정, `app/chat/service.py` `RouteCache`). 실패(연결 실패·5xx·4xx·모양 다름)나 이동할 행이 없으면 마지막 성공본, 처음부터 실패면 `data/routes.snapshot.json`. `aiRoutMpngSn`이 LLM의 화면 번호(`screen_num`), `scrnParamCn` `cat=hospital`은 React에 `?cat=hospital`로, `…`가 든 자리표시 값은 파라미터 없음 | AIM-004-09, ADM-080-04 | 백엔드 | - | List<AiRouteResponse> |
| (미정) | 미완료 메시지 완료 처리·최근 6턴·AI 설정값 조회 | 백엔드 `docs/api/ai.md`에 PATCH 설계만 있음. SCR-AIM-002에서 필요해지면 요청 | AIM-002 | 백엔드 | 미정 | 미정 |

## DTO

### AiToolCatalogResponse
쓰는 API: GET /internal/ai/tools (확정, 백엔드 PR #174). `data/tools.snapshot.json`은 백엔드 로컬 응답(2026-11-06)에서 `codes`만 뺀 것, 가짜 응답은 `tests/chat/fakes.py` `fake_catalog_json()`(스냅샷 + 같은 응답의 공통코드 값)

| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| version | String | Y | 응답 본문(구조 + 코드 값)의 해시 | tool-catalog 3-2 |
| structureVersion | String | Y | 코드 값을 뺀 구조의 해시. Python 스냅샷과 다르면 경고 로그(배포 순서 어긋남) | tool-catalog 3-2·4-2 |
| tools[].name | String | Y | `@AiTool(name)`. `data/tool_prompts.yaml`과 짝짓는 키(예: `draft_schedule`) | tool-catalog 3-1 |
| tools[].domain | String | Y | `health` 등 | tool-catalog 3-1 |
| tools[].kind | String | Y | `READ`·`CARD` | tool-catalog 3-1 |
| tools[].call | `{method, path, contentType?}` | Y | 컨트롤러 매핑(예: `POST /api/pets/{petSn}/care-schedules`). 파일 칸이 있는 API는 `contentType: multipart/form-data`(관찰 기록 추가) | tool-catalog 3-2 |
| tools[].params.<Java 칸> | `{in, type, required?, group?, codes?, maxLength?, min?, max?, positive?, pattern?, items?, minItems?, generated?}` | Y | `in`: `path`·`query`·`body`. `type`: `string`·`long`·`int`·`decimal`·`boolean`·`date`·`time`·`datetime`·`code`·`array`·`file`(`datetime`은 `LocalDateTime` 칸 때문에 3-2절에 더함). `code`면 `group`(공통코드 그룹)과 `codes: [{cd, nm}]`(사용 중인 값). `min`·`max`는 `@Min`·`@Max`(예: `cycleDrctInptDayCnt` 1~9999, 백엔드 결정 2026-11-05). `array`면 `items`(항목 칸 이름 → 같은 모양의 규칙, `in` 없음, 중첩 배열 가능: `pets[].drugs[]`)와 `minItems`. `generated: "uuid"`는 클라이언트가 만드는 칸(`idmptDmndId`). Python은 항목 칸 코드 값까지 없으면 그 도구를 싣지 않는다(SCR-AIM-012 2단계 ③, `app/chat/catalog.py`) | tool-catalog 3-2 |
| tools[].rules[] | `{requiredIf: {field, when, equals}}` | N | 조건부 필수. "병원이 아니면 일정명"처럼 같지 않음 조건은 값마다 한 줄(가짜 응답은 HLTC0058·0059·0060 세 줄) | tool-catalog 3-1 |

### AiRouteResponse
쓰는 API: GET /internal/ai/routes (정본 백엔드 `docs/api/ai.md`)
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| aiRoutMpngSn | Long | Y | | AI_ROUT_MPNG.AI_ROUT_MPNG_SN |
| trgtScrnNm | String | Y | | AI_ROUT_MPNG.TRGT_SCRN_NM |
| scrnId | String | N | | AI_ROUT_MPNG.SCRN_ID |
| scrnParamCn | String | N | 예 `cat=hospital` | AI_ROUT_MPNG.SCRN_PARAM_CN |
| instKwrds | List<String> | Y | 지시어를 쉼표로 나눠 앞뒤 공백을 뺀 배열, 빈 값 제외. 지시어가 없으면 빈 배열 | AI_ROUT_MPNG.INST_KWRD_CN |
| mvmnMthdCd | String | Y | AIMG09: AIMC0032 화면 이동, AIMC0033 모달 열기, AIMC0034 라우팅 대상 아님, AIMC0035 제외, AIMC0036 보류 | AI_ROUT_MPNG.MVMN_MTHD_CD |
| rprsChipYn | boolean | Y | 대표 칩 | AI_ROUT_MPNG.RPRS_CHIP_YN |
| prrtSeq | Integer | Y | 작을수록 먼저 | AI_ROUT_MPNG.PRRT_SEQ |

### ReceiptOcrRequest
쓰는 API: POST /internal/v1/ocr/receipt (multipart/form-data)
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| file | 파일 | Y | jpg·jpeg·png·webp. 형식·용량 검증은 Java가 업로드 때 끝냈다(여기서는 이미지로 읽히는지만 본다) | AIM-008-05 |

### ReceiptOcrResponse
쓰는 API: POST /internal/v1/ocr/receipt
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| hsptlNm | String | N | 병원명. 병원이 아닌 영수증은 null | AIM-009-02 |
| expndPlcusNm | String | N | 사용처. 영수증에 찍힌 가게 이름(상호), 앞 80자. 모든 출처에서 채운다(2026-11-03 추가, 백엔드 PR과 함께) | MYP-031-03, EXPND.EXPND_PLCUS_NM |
| expndClsfCd | String | N | 상호·품목에서 추정한 지출 카테고리(MYPG05 7종). 불확실하면 null. 모든 출처에서 채운다(2026-11-03 추가, 백엔드 PR과 함께) | MYP-031-03, EXPND.EXPND_CLSF_CD |
| ckupYmd | LocalDate | N | 검진일(건강 일지)·결제일(가계부) `YYYY-MM-DD`. 연도가 없으면 null(연도 보정은 Java) | AIM-009-02, MYP-031-04 |
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
