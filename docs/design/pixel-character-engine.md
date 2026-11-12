# 픽셀 캐릭터 엔진 이식 · 계약 설계 (초안)

SCR-MYP-010(캐릭터 생성)과 SCR-MYP-011(아이템 상점·착용)에 pixel-dog-generator 치비 엔진을 이식할 때의
Python ↔ Java ↔ React 계약 초안이다. **코드 없음, 팀 확인 전.** `docs/api/internal.md`는 고치지 않았다 —
계약은 백엔드 PR과 같은 때 바꾼다(`AGENTS.md` 4번).

## 0. 확정한 것 (2026-11-01, LJS)

| 항목 | 결정 |
| --- | --- |
| 이식 방식 | 엔진 파이썬 코드를 이 저장소 `app/character/`로 옮겨 `CharacterClient`(`clients.py`) 구현으로 붙인다(HTTP 위임 아님) |
| 아이템 | 목록은 공용(`ITEM`), 그림은 캐릭터마다 굽는다 |
| 합성 | 서버가 한다. 프론트는 겹치지 않는다 |
| 굽는 시점 | 캐릭터 생성 직후 전 아이템을 미리 굽는다. 사자마자 바로 장착. 굽기는 항상 켜져 있다(2026-11-11 `CHARACTER_BAKE_ENABLED` 설정 삭제). 안 구운 아이템 미리보기는 409 뒤 구워 둔다 |
| 지원 부위 | 머리·얼굴·목·의상·가방 5부위, 아이템 26개. 신발은 넣지 않는다(2026-11-02) |
| 표시 컷 | 서기 정면 1컷, 512×512, 얼굴 영역 `(96, 32, 320, 320)` 규격 유지(2026-11-04 변경, 백엔드 `CharacterSpec.FACE`와 같음. 옛 값 `(128, 64, 256, 256)`) |
| 캔버스 배치 | 4번 "V4a56" |
| 착장 합성 방식 | 머리 착용 그림(없으면 맨몸)을 바탕으로 의상 → 가방 → 목 → 얼굴 레이어를 얹는다(5번) |

## 1. 흐름 (2026-10-27 결정 위에 올린다)

이미 있는 `/ai/characters`(`docs/api/character.md`) 흐름 — 업로드 검증 → Java 작업 생성 → 202·`charCrtJobSn` →
백그라운드 `CharacterClient.generate` → 512×512 검증(`rules.matches_spec`) → Java 보고 — 을
생성·굽기·합성 세 단계로 늘린다. Python은 저장하지 않는다. 그림은 전부 Java가 보관하고 필요할 때 Python에 준다.
작업 생성·결과 보고·시트 저장과 조회는 Java 캐릭터 내부 API(`internal.md` "Python → Java" `/internal/ai/characters/**` 행)로 연결했다.

```
① 생성  React ─POST /ai/characters─▶ Python ─작업 생성─▶ Java               (202·charCrtJobSn)
         Python 백그라운드: generate = 엔진 맨몸 시트 생성 → 512 정규화
         Python ─512 결과 보고(지금 있음) + 맨몸 시트·배치값 저장(새로 필요)─▶ Java   (알림은 Java)
② 굽기  ①이 끝나면 Python이 이어서 전 아이템을 굽는다(요청 우선 큐, 3번)
         아이템마다: 맨몸 시트 + 아이템 지시 → 착용 시트 → Java에 저장·상태 보고
③ 합성  React ─POST /ai/characters/{pixelCharSn}/preview (장비)─▶ Python
         Python ─시트 조회─▶ Java → 합성 → 512 PNG 응답(저장 안 함)
         확정은 기존 Java `PUT /pixel-characters/{pixelCharSn}/equipped-items` (대표 이미지 삭제 → 맨몸)
④ 저장  확정 성공 뒤 React ─POST /ai/characters/{pixelCharSn}/equipped-image (같은 장비)─▶ Python
         Python ─시트 조회─▶ Java → 합성 → PUT /internal/ai/characters/{pixelCharSn}/equipped-image
         Java: 지금 착용 목록과 같으면 대표 이미지로 저장 → GET /pets/{petSn}/character-image
```

## 2. API 초안

### React → Python

| 메서드 | 경로 | 하는 일 | 응답 |
| --- | --- | --- | --- |
| POST | `/ai/characters` (있음) | 사진·petSn 받아 생성 작업 시작. 바뀌는 것은 생성기 구현과 성공 보고 내용뿐 | 202, `charCrtJobSn` |
| POST | `/ai/characters/{pixelCharSn}/preview` (새로) | 아이템(`itemSns`, 상점에서는 안 산 아이템도 입혀 보므로 보유 번호가 아님)대로 합성한 512 PNG | `image/png`. 아직 안 구운 아이템이 있으면 그 아이템을 큐 맨 앞으로 올리고 409 `ITEM_BAKING` |
| POST | `/ai/characters/{pixelCharSn}/equipped-image` (새로) | [장착] 확정 뒤 같은 `itemSns`로 합성해 Java에 대표 이미지로 저장 | 200. 오류는 `/preview`와 같고 저장하지 않는다 |

### Python → Java (새로 필요, 백엔드 몫)

| 하는 일 | 비고 |
| --- | --- |
| 생성 작업 생성·결과 보고 | `internal.md` 미정 행 그대로(지금 `CharacterJobRepository`의 `create_job`·`report_success`·`report_failure`) |
| 맨몸 시트·배치값 저장 | `report_success`는 512 PNG 하나만 보낸다 → 시트·배치값(4번 `scale, originX, originY`)을 함께 보내도록 늘린다 |
| 아이템 착용 시트 저장·굽기 상태 보고 | 캐릭터 × 아이템 단위 |
| 굽기 대상 아이템 목록 조회 | `ITEM` 중 판매 중 + 엔진이 아는 아이템 |
| 합성용 시트 조회 | 맨몸 시트 + 요청 장비의 착용 시트 |
| 대표 이미지 저장 | `PUT /internal/ai/characters/{pixelCharSn}/equipped-image`, 지금 착용 목록과 같을 때만 |
| 굽기용 아이템 그림 내려받기 | `GET /internal/ai/items/{itemSn}/bake-image`(9절). `bake-items`의 `bakeImgRefYn`이 true인 아이템만 받는다 |
| 반려동물 정보 | 작업 생성이 이미 `petSeCd`·`vrtyNm`·`colrNm`·`chrcCn`을 돌려준다(`CharacterRequest`). 엔진이 쓰는 성별(`PET_GNDR_CD`)만 없다 — 추가 여부 결정 |
| 사진 원본 조회 | 굽기는 맨몸 시트로 하므로 생성 뒤에는 필요 없다(생성 때는 요청에 사진이 온다) |

## 3. 저장 · 스키마 영향 (팀 결정 필요)

Java가 새로 보관해야 하는 것:

| 대상 | 개수 | 지금 자리 |
| --- | --- | --- |
| 맨몸 2×2 시트 (1024 PNG) | 캐릭터당 1 | 없음 — `CHAR_PHOTO` 역할 코드는 원본(FILC0006)·결과(FILC0007)뿐 |
| 착용 시트 (1024 PNG) | 캐릭터 × 아이템 | 없음 |
| 굽기 상태 | 캐릭터 × 아이템 | 없음 |
| 512 배치값 | 캐릭터당 1 | 없음 |

후보: (가) `CHAR_PHOTO` 역할 코드 추가 + 굽기 상태 테이블 신설 / (나) `CHAR_ITEM_SHEET(PIXEL_CHAR_SN, ITEM_SN, ATCH_FILE_SN, 상태)` 신설.
굽기 지시는 `ITEM`의 굽기 지시 컬럼에 둔다 — 6번.

Python 큐는 메모리에 있으므로 재시작하면 사라진다. 끊긴 굽기는 Java의 굽기 상태로 다시 찾아 재요청한다
(생성 작업의 타임아웃 정리를 Java가 하는 것과 같은 방식).

## 4. 512 캔버스 배치 규칙 — V4a56

> 2026-11-02 변경(LJS): 샘플 10건에서 눈 사이 77px 고정은 눈 비율에 따라 크기가 약 2배 벌어졌다. 배율은 **서기 컷 높이를 341px로 맞추는 값**으로 바꾸고, 눈 중점 `(256, 207)`만 유지한다. 아래 `EYE_GAP`과 2번 배율 공식은 대체됐다. 눈이 그림 위쪽에 있는 캐릭터는 입이 얼굴 영역 아래로 잘려, 상단이 y=100 아래로 내려가면 100으로 올린다(이때 눈 y는 207보다 작다). 다른 저장소는 눈 좌표를 쓰지 않고 얼굴 영역만 고정 좌표로 자른다.

엔진 그림은 캐릭터에 딱 맞게 잘린 그림이라 크기·위치가 컷마다 다르다(예: 350×346, 399×420).
얼굴 영역이 고정이므로 **캐릭터마다 배치를 한 번만 정하고 모든 착장에 재사용**한다.

1. 그 캐릭터의 맨몸 서기 정면 컷에서 두 눈을 찾는다(모자 쓴 그림에서는 찾지 않는다 — 시제품에서 오검출).
2. 배율 `scale = EYE_GAP / 눈 사이 거리`, 위치는 두 눈 중점이 `(256, EYE_Y)`에 오도록.
3. 이 값을 저장하고(3번), 착장 합성 결과에 같은 값을 쓴다. 착장이 바뀌어도 얼굴 자리가 같다.
4. 확대는 NEAREST.

| 상수 | 값 | 뜻 |
| --- | --- | --- |
| `EYE_GAP` | 0.30 × 256 ≈ 77px | 눈 사이 거리 |
| `EYE_X`, `EYE_Y` | 256, 207.36 | 눈 기준점. 옛 얼굴 영역 `(128, 64, 256, 256)`의 가운데·56% 지점(64 + 0.56 × 256)을 숫자로 고정했다. 얼굴 영역을 넓혀도 지금까지 만든 캐릭터와 새 캐릭터의 눈 높이가 같다. 새 영역에서는 위에서 약 55% |

시제품 실측(늘어진 귀 강아지 1마리, 앉기·서기 정면 × 맨몸+3착장 = 8컷): 배율 ×0.816, 512 밖으로 잘림 0/8,
얼굴 원형 자르기에 모자 전체와 턱까지 들어옴(사람 판정 "딱 이 정도"). **상수는 한 마리 기준이다** — 7번.

## 5. 착장 합성 — 머리 착용 그림을 바탕으로

엔진의 원래 방식(맨몸 + 아이템 레이어 + 모자가 가린 귀를 규칙으로 지움)은 늘어진 귀에서 귀 조각이 모자 밖에 남고
(지우는 범위가 모자 높이 + 27행이라 긴 귀를 못 덮음), 옆모습 눈 하이라이트가 사라졌다. 머리 아이템이 있으면
AI가 그린 머리 착용 그림을 바탕으로 쓰고 몸 아이템 레이어만 얹으면 둘 다 사라진다
(시제품 2마리 × 머리 7 × 몸 8 × 4컷, 사람 판정 "대체로 괜찮음").
이 방식은 엔진에 아직 구현되지 않았다 — 이식할 때 함께 구현한다.

> 2026-11-02 추가(LJS): 어두운 털은 검은 아이템 외곽선과 색 차이가 없어 레이어에서 외곽선이 빠졌다. 머리를 뺀 부위는 털을 밝은 회색으로 바꾼 시트로 굽고, 그 시트와의 차이로 레이어를 뽑는다. 합성 바탕은 원본이라 털 색은 그대로다. 레이어에서 바깥과 이어진 밝힌 털을 지우고, 가장자리 8px 안의 어두운 화소를 되살린다. 시험: `dog_black_poodle` 안경·방울 목걸이 2장.

## 6. 아이템 · 부위 매핑

5부위만 지원한다(2026-11-02). 신발은 넣지 않는다. 시드 아이템 26개(`docs/design/item-bake-hints.json`).

| 냥멍 부위(MYPG01) | 합성 | 시드 아이템 |
| --- | --- | --- |
| 머리 MYPC0001 | 머리 착용 그림을 바탕으로 쓴다(5번) | 7 |
| 의상 MYPC0004 | 레이어(첫째) | 7 |
| 가방 MYPC0005 | 레이어(둘째) | 4 |
| 목 MYPC0003 | 레이어(셋째) | 4 |
| 얼굴 MYPC0002 | 레이어(맨 위) | 4 |

굽기 지시(아이템별 프롬프트 문장)는 Java `ITEM`의 굽기 지시 컬럼에 있고, Python은 `bake-items`(`itemSn`·`regnCd`·`bakeHint`)로 받는다.
관리자 아이템 등록 때 `/ai/items/bake-hints`가 그림으로 초안을 만든다(SCR-ADM-070).

## 7. 열린 질문

1. 운영 생성 경로: 엔진의 $0 경로(codex CLI)는 개인 ChatGPT 구독 로그인이라 서버에서 쓸 수 없다 → OpenAI API만 남는다.
2. 비용(아래 표)을 누가 내는가. 미리 굽기라 아이템 수에 비례한다.
3. V4a56 상수를 다른 체형(고양이, 주둥이 긴 견종)으로 재검증.
4. 배율이 정수가 아니라 도트 굵기가 고르지 않을 수 있다 — 사람 판정 전.
5. 머리 아이템이 늘어진 귀를 감싸며 옆으로 처지는 그림(AI 원본 문제) — 굽기 지시 문장으로 다룰지.
6. 엔진은 눈 모양·색을 사진에서 LLM으로 판별한다(유료, 단가 미측정). 종은 `PET_SE_CD`로 대체 가능.
7. 이 저장소 의존성 추가: numpy, scipy, Pillow, openai (`uv add`, 승인 필요).
8. 엔진은 2×2 시트(앉기·서기 × 정면·옆)를 한 번에 그린다. 서기 정면만 쓰면 나머지 3컷은 버려진다 —
   시트를 그대로 둘지(엔진 정렬·합성이 4컷을 쓴다) 1컷 생성으로 줄일지.
9. `CharacterClient.generate`는 512 PNG 바이트 하나를 돌려준다. 엔진은 맨몸 시트·배치값도 내야 하므로
   반환형(과 `report_success`)을 넓힐지, 시트 보고를 따로 둘지.

## 8. 비용 · 시간 실측 (pixel-dog-generator 원장·로그, 합성 시간만 2026-10-30 측정)

| 항목 | 값 |
| --- | --- |
| 이미지 1장 평균 (API) | $0.0636 (110회) |
| 캐릭터 1 + 착용 14 (API) | $0.9483 (1마리) |
| 캐릭터 생성 시간 | 128초 (codex) |
| 착용 14장 굽기 (API, 5장 병렬) | 약 67초 |
| 합성 1회 | 단일 0.6초, 머리+몸 1.03초 |

| 아이템 수 | 캐릭터당 굽기 비용 (× $0.063) |
| --- | --- |
| 14 | 약 $0.88 |
| 30 | 약 $1.89 |
| 50 | 약 $3.15 |

## 9. 그림 참고 굽기 (2026-11-11 실험·결정, LJS. Python은 가짜 Java 응답으로 구현, Java 연결 전)

지금 굽기는 맨몸 시트 한 장과 굽기 지시 문장만 모델에 보낸다. 아이템 그림은 보내지 않는다.
그래서 상점 그림과 착용 모습이 따로 만들어지고, 문장에 담기지 않은 모양은 사라진다
(사람 확인 2026-11-11: 거북이 인형 가방이 초록 크로스백으로 구워짐).

### 결정

1. 굽기에 픽셀 아이템 그림(`/ai/items/pixel-image`로 만든 상점 그림)을 둘째 그림으로 넣는다.
   아이템 생김새는 그림이 전하고, 문장의 `{hint}` 자리는 "마지막 그림의 아이템"으로 바꾼다.
2. 부위마다 "어떻게 입는지" 문장을 둔다. 그림은 생김새만 알려 주고 착용 방식은 알려 주지 않는다.
   머리·얼굴·의상은 지금 `_WEAR_SLOT` 문장을 쓰고, 가방·목은 아래 문장을 새로 둔다.
3. 가방 부위의 기본 착용 방식은 백팩이다(등에 엎드린 모습). 크로스백 등 다른 방식을 아이템마다 고르게 할지는 정하지 않았다.
4. 이미 등록된 아이템은 지금 방식(굽기 지시 문장)으로 둔다. 새 부위 문장은 그림 참고로 굽는 경우에만 쓴다.
   기존 가방·목 아이템은 굽기 지시 안에 착용 방식이 들어 있어, 부위 문장을 같이 붙이면 지시가 겹친다.
5. Python이 아이템 그림을 받는 Java 내부 API를 먼저 만든다(백엔드 몫, 2절 "Python → Java"에 추가).
   지금 `bake-items` 응답에는 그림 정보가 없고, 파일 내려받기는 캐릭터 시트용만 있다.
6. Python 구현(2026-11-12 Java 연결, 계약은 `docs/api/internal.md`, 백엔드 PR #232): `bake-items` 항목의 `bakeImgRefYn`이 true면
   `bake-image`로 그림을 받아 그림 참고로 굽고(`engine._REF_WEAR_SLOT`), false면 `bakeHint`로 굽는다. 둘 다 없는 행은 뺀다.
   그림 받기 실패는 굽기 실패와 같이 한 번 다시 해 보고 실패로 보고한다. 시험 굽기(`/ai/items/trial-preview`)는 굽기 지시만 받는다.

### 프롬프트 (실험에 쓴 원문)

그림 순서는 맨몸 시트가 첫째, 아이템 그림이 마지막이다. 아이템 그림은 `normalize_item_image`로 흰 바탕에 올려 보낸다.

머리말(`chibi_wear.txt` 앞에 붙임. 본문의 "The image"는 "The FIRST image"로 바꿈):

```
Two images are given. The FIRST image is the character sheet to edit. The LAST image is only a reference picture of the item to wear: copy how the item looks, never its background, its size on the canvas or its position.
```

`{hint}` 자리:

```
item exactly like the one shown in the LAST image (same colors, pattern, material and shape)
```

가방 MYPC0005:

```
ONE {hint} worn as a backpack in all four figures: two thin shoulder straps go over the shoulders and the bag lies face-down flat against the back, its underside pressed to the back and its top surface facing away from the body, at the same place and the same size in every figure; in the side views the bag is drawn in PROFILE, seen from its own side as a low dome hugging the line of the back - the viewer must NOT see the bag's top surface as a full round shape; in the front views the straps show on the chest and the bag only peeks out from behind the body; the bag stays below the head and never touches the head or the ears
```

목 MYPC0003:

```
ONE {hint} around its neck in all four figures: a snug band circling the neck just under the chin, at the same place and the same width in every figure; in the front views its front part (buckle, tag or charm) shows centered under the chin, in the side views it is seen from the side as a band across the neck; it sits on the neck only and never covers the face, the ears or the chest
```

### 실험 (2026-11-11, 사람 판정)

고양이 캐릭터 1마리(실사 사진으로 새로 생성), 운영과 같은 모델·1024·medium, 조건마다 2장. 스크립트는 저장소 밖에서 돌렸다.
이미지 28장(캐릭터 1, 픽셀 아이템 5, 굽기 22), 비전 4회. 굽기 한 장은 두 방식 모두 30~34초.

| 아이템(부위) | 문장만(자동 초안) | 그림만 | 그림 + 부위 문장 |
| --- | --- | --- | --- |
| 갈색 털모자(머리) | 매끈한 갈색 캡에 곰 귀 | 복슬한 질감, 얼굴을 감싸는 모양 | 머리는 `_WEAR_SLOT` 문장이 이미 있어 "그림만"과 같은 조건 |
| 흰 털모자(머리) | 주황 지그재그 한 줄 | 여러 색 무늬 밴드, 로고 패치 | 위와 같음 |
| 거북이 가방(가방) | 등껍질 무늬 둥근 가방, 머리·다리 없음 | 거북이 전체. 메는 위치가 컷마다·장마다 다름 | 크로스백 문장: 위치 일정하나 착용 방식이 틀림 / 백팩 문장: 일정 / 엎드린 백팩 문장: 일정, 옆모습이 등에 엎드린 옆면 |
| 빨간 목줄(목) | 굽지 않음 | 굽지 않음 | 네 컷 모두 턱 아래 빨간 띠와 은색 버클, 두 장이 거의 같음 |
| 과일 목걸이(목) | 굽지 않음 | 굽지 않음 | 네 컷 모두 구슬 줄과 딸기·별·방울 장식, 두 장이 거의 같음. 장식은 가슴 쪽으로 내려옴 |

- 판정: 그림을 넣은 쪽이 세 아이템 모두 픽셀 아이템에 더 가깝다. 캐릭터 본체는 눈으로 보기에 유지됐다(화소 비교는 안 함). 가방은 엎드린 백팩 문장, 목은 위 목 문장으로 정했다.
- 가방을 등에 엎드리게 하면 옆모습에서 윗면 무늬가 얇게 눌려, 두 장 중 한 장은 거북이로 알아보기 어려웠다.
- 백팩은 서기 정면 컷에서 어깨끈만 보이고 가방은 몸 뒤로 조금만 보인다.

### 확인하지 않은 것

- 강아지, 어두운 털(밝힌 시트로 굽는 경로, 5절), 얼굴·의상 부위.
- 512 합성 결과와 여러 부위 동시 착용(모자 + 백팩 등).
- `bake.validate`는 아이템 레이어가 비지 않았는지만 본다(머리는 2×2로 잘리는지만). 위치가 틀리거나 다른 부위 영역을 침범해도 통과한다 — 실험의 22장이 모두 통과했다.
- 그림을 한 장 더 넣을 때의 굽기 단가(8절 표는 그림 한 장 기준).
- 실사 사진이 상점 그림으로 등록된 기존 아이템에 이 방식을 쓰면 어떻게 나오는지.
