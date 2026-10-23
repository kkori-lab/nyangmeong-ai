# 내부 API·DTO (초안)

Java 백엔드만 부르는 API다. 공통 규칙은 `docs/api/README.md`에 있다. Java 쪽 계약은 백엔드 `global/external`(`OcrClient`·`ReceiptOcrResponse`, `CharacterGenerator`·`CharacterGenerationRequest`·`CharacterSpec`)이고, 이 문서의 필드는 그 record와 같아야 한다. 한쪽을 바꾸면 다른 쪽도 같은 때 바꾼다.

## API 목록

| 메서드 | 경로 | 설명 | 기능 ID | 담당 | 요청 DTO | 응답 DTO |
| --- | --- | --- | --- | --- | --- | --- |
| POST | /internal/v1/ocr/receipt | 영수증 이미지(multipart `file`)에서 항목을 뽑는다. 저장하지 않는다. 추출 0건도 200(값이 모두 null, `sections` 빈 배열). 오류: 분석 시간 초과 504 `OCR_TIMEOUT`, 외부 API 오류 502 `OCR_API_ERROR`. 시간 제한은 Java 제한(15초)보다 짧게 둔다 | AIM-008-06, AIM-010-01 | LJS | ReceiptOcrRequest | ReceiptOcrResponse |
| POST | /internal/v1/character/generate | 사진과 등록 정보로 픽셀 캐릭터 PNG를 만든다. 응답 본문이 `image/png`(512×512, `ApiResponse` 껍데기 없음). 저장하지 않는다. 오류(`ApiResponse`): 외부 API 오류 502 `CHARACTER_API_ERROR`, 규격을 맞추지 못함 502 `CHARACTER_SPEC_MISMATCH` | MYP-010-08·17 | LJS | CharacterGenerationRequest | (PNG) |
| DELETE | /internal/v1/members/{mbrSn}/conversations | 탈퇴 회원의 대화방·메시지를 물리 삭제한다. 대화가 없어도 200 | AIM-011-19 | LJS | - | - |

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

### CharacterGenerationRequest
쓰는 API: POST /internal/v1/character/generate (multipart/form-data)
| 필드 | 타입 | 필수 | 검증·설명 | 근거 |
| --- | --- | --- | --- | --- |
| photo | 파일 | Y | 첨부 사진 | MYP-010-08 |
| petSeCd | String | Y | 반려동물 구분 공통코드(강아지·고양이) | PET.PET_SE_CD |
| vrtyNm | String | N | 품종 | MYP-010-08 |
| colrNm | String | N | 털색 | MYP-010-08 |
| chrcCn | String | N | 특징 | MYP-010-08 |

## mock 모드

`AI_MODE=mock`이면 외부 API를 부르지 않는다. OCR은 Java `FakeOcrClient`와 같은 시나리오를 돌려준다(어떻게 고르는지는 OCR 마일스톤 기획 때 정한다: `fake` 2마리, `fake-single`, `fake-partial`, `fake-empty`, `fake-fail`, `fake-timeout`). 캐릭터는 규격(512×512, 얼굴 영역 128·64·256·256)을 지킨 고정 PNG를 돌려준다.
