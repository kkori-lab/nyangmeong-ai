# 서비스 안내서 검토 메모

`data/guide/*.yaml`(AI 매니저 사용법 안내서)에서 사람만 보는 내용을 옮겼다. AI 프롬프트에는 들어가지 않는다.
안내서 초안 draft-0.1(2026-11-04) 기준, 2026-11-05 프론트 대조 반영.

## 출처

- 프론트 코드(nyangmeong-frontend develop 2026-11-04): 진입 경로·버튼 이름이 정답
- DMS 화면설계서(도메인별 최신): 사용 순서
- IA 구조도 v0.5(2026-11-01): 빠진 화면 대조
- data/routing.yaml v0.9: 화면 목록과 번호

화면설계서: 건강기록_화면설계서_v1.2_20261101, 마이페이지_화면설계서_v0.6_20261025, 커뮤니티_화면설계서_v0.8_20261101, 고객센터_화면설계서_v0.4_20261025, 플레이스_화면설계서_v0.7_20260930, 메인페이지_화면설계서_v0.10_20261103, 공통레이아웃_화면설계서_v0.11_20261101

## 칸 설명

- `entry`: 진입 경로. pc·mobile·other. [대괄호]는 화면의 버튼·메뉴 이름 그대로
- `tasks`: 그 화면에서 할 수 있는 일. steps는 사용자에게 그대로 말해도 되는 순서, faq_keywords는 이 일을 물을 때 쓰는 말
- `status`: 정상 | 일부 준비 중 | 가짜 응답(연결 전). 정상이 아니면 not_ready의 기능은 "곧 제공돼요"로 안내
- `diffs`: 화면설계서와 실제 화면이 다른 곳(안내는 실제 화면 기준). 사용자에게 말하지 않는다
- `todo`: 확인 못 한 것. 사용자에게 말하지 않는다

## 남은 문제

- routing.yaml에 1:1 문의(SCR-CSC-003) 행이 없다. "문의" 키워드는 num 7 공지사항 목록으로 가고, 1:1 문의 사용법은 num 7 tasks에 넣었다
- 프론트 src/features/ai/shared/screenPaths.js가 SCR-MYP-004(num 27 공동양육 관리)를 /mypage/caregivers로 보내는데 그 주소는 라우트에 없다. 실제 화면은 /mypage/pets 카드 아래 가족 영역

## 프론트 대조 (2026-11-05, 프론트 develop de4b256)

안내서 화면 34개와 공통 task(C-1~C-6)의 `path`·진입 경로·[버튼 이름]을 프론트 코드(라우트·메뉴·화면 JSX)와 대조했다. 결과는 맞음 11 · 고침 22 · 프론트 문제 1이고, 안내서 32곳을 고쳤다. 공통 task는 맞음이라 따로 셌다. 청크 id·num·routing.yaml은 바꾸지 않았다.

- 공통으로 고친 것: 폭 1100px 이하에는 헤더 프로필 아이콘이 없다. 모바일 진입은 "프로필 >" 대신 [전체 메뉴] drawer(맨 위 내 이름 → 마이페이지, 고객센터·설정 링크) 기준으로 적었다
- 플레이스 7개 화면 `login_required` true: 프론트가 플레이스를 회원만 열게 바꿨다(프론트 커밋 96707a9). 의도한 정책인지는 확인 필요(아래 G)
- 이미 연결돼 not_ready에서 뺀 것: 반려동물 수정 창 [건강 일지에서 기록하기], 포인트 [건강 일지], 가계부 영수증 인식(실제 `/ai/receipts`), 회원정보 닉네임·휴대폰·프로필 사진 저장

| 파일 | num | 화면 | 결과 | 고친 것·남은 것 |
| --- | --- | --- | --- | --- |
| common.yaml | (C-1~C-6) | 공통 레이아웃(AI 버튼·알림·로그아웃·모바일 메뉴·헤더 메뉴) | 맞음 |  |
| common.yaml | 9 | 설정 | 고침 | 9-1 첫 단계가 PC 전용(모바일은 프로필 아이콘이 없고 drawer의 설정) |
| common.yaml | 10 | 채팅 | 맞음 |  |
| community.yaml | 4 | 펫이야기 목록 | 맞음 |  |
| community.yaml | 22 | 펫이야기 글 상세 | 맞음 |  |
| community.yaml | 23 | 실종센터 | 맞음 |  |
| community.yaml | 24 | 펫뉴스 | 맞음 |  |
| community.yaml | 25 | 우리동네 펫돌봄 | 맞음 |  |
| health.yaml | 1 | 종합 건강기록 | 고침 | 1-3 [케어 캘린더에서 일정 등록하기] 링크는 예방·검진 기록이 하나도 없을 때만 보임 |
| health.yaml | 11 | 케어 캘린더 | 고침 | 11-3 일정 종류 선택지가 [병원][미용·목욕][케어·투약][기타] 4개 |
| health.yaml | 12 | 케어 캘린더 토탈 케어리스트 | 고침 | entry.other "메인 화면의 케어 카드에서 주소"(뜻 불명) → 메인 "데일리 케어미션" 카드의 [토탈 케어리스트] 링크 · 프론트 문제 C |
| health.yaml | 13 | 건강 일지 | 맞음 |  |
| health.yaml | 14 | 건강 일지 검진기록 | 고침 | 14-2의 [촬영하기]는 폭 1100px 이하에서만 보임 |
| health.yaml | 15 | 종합 건강기록 처방 및 투약 이력 | 맞음 |  |
| health.yaml | 16 | 종합 건강기록 검사 결과 | 맞음 |  |
| main.yaml | 8 | 메인 | 프론트 문제 | 8-4 [토탈 케어리스트] 링크 해시가 케어리스트 탭을 못 엶(C) |
| mypage.yaml | 5 | 마이페이지 홈 | 고침 | mobile 진입을 [전체 메뉴] 맨 위 내 이름으로 |
| mypage.yaml | 6 | 픽셀 캐릭터 관리 | 고침 | mobile 진입의 "프로필 >" |
| mypage.yaml | 26 | 반려동물 등록·수정 | 고침 | [건강 일지에서 기록하기]는 이미 `/health/diary`로 이동해 not_ready 삭제, 포인트 화면 [반려동물 등록하기]는 그 화면 위에 등록 창이 열림, mobile 진입의 "프로필 >" |
| mypage.yaml | 27 | 공동양육 관리 | 고침 | mobile 진입의 "프로필 >" · 프론트 문제 A(AI 이동용 `/mypage/caregivers` 라우트 없음) |
| mypage.yaml | 28 | 픽셀 캐릭터 상세 | 맞음 |  |
| mypage.yaml | 29 | 케어미션 · 포인트 | 고침 | [건강 일지] 버튼은 이미 `/health/diary`로 이동해 not_ready 비우고 status 정상, mobile 진입의 "프로필 >" |
| mypage.yaml | 30 | 가계부 | 고침 | 영수증 인식은 실제 API라 not_ready 비우고 status 정상, mobile 진입의 "프로필 >" |
| mypage.yaml | 31 | 가계부 전체 내역 | 고침 | mobile 진입의 "프로필 >" |
| mypage.yaml | 32 | 회원정보 수정 | 고침 | 닉네임·휴대폰·프로필 사진은 이미 실제 저장이라 not_ready에 회원 탈퇴만 남김(status 일부 준비 중), mobile 진입은 761~1100px ▾ 메뉴뿐 · 프론트 문제 D |
| place.yaml | 2 | 플레이스 병원 화면 | 고침 | `login_required` true(프론트 커밋 96707a9) |
| place.yaml | 3 | 플레이스 | 고침 | `login_required` true |
| place.yaml | 17 | 플레이스 미용 화면 | 고침 | `login_required` true |
| place.yaml | 18 | 플레이스 용품 화면 | 고침 | `login_required` true |
| place.yaml | 19 | 플레이스 동반 화면 | 고침 | `login_required` true |
| place.yaml | 20 | 플레이스 호텔 화면 | 고침 | `login_required` true |
| place.yaml | 21 | 동물병원 요약 카드 | 고침 | `login_required` true |
| support.yaml | 7 | 공지사항 목록 | 고침 | mobile 진입(프로필 아이콘 없음, drawer 고객센터) |
| support.yaml | 33 | FAQ 목록 | 고침 | mobile 진입의 "프로필 >" |
| support.yaml | 34 | 공지 상세 | 맞음 |  |

프론트에 알릴 것(안내서는 지금 화면 그대로 적었다)

- A. SCR-MYP-004(num 27 공동양육 관리): `screenPaths.js`가 `/mypage/caregivers`로 보내는데 라우트·캐치올이 없어 빈 화면. 리다이렉트나 `PATHS.MYPAGE_PETS`로
- B. `/mypage/withdraw` 라우트 없음. [회원 탈퇴]는 준비 중 토스트(안내서 not_ready에 있음)
- C. 메인 [토탈 케어리스트]가 `/health/calendar#c-care`로 가는데 탭 해시는 `#hlt003-care`라 캘린더 탭이 열림
- D. 폭 760px 이하에서 회원정보 수정(SCR-MYP-040)으로 가는 메뉴가 없음(하단 탭·drawer 모두)
- E. routing.yaml num 12~16은 탭 해시 없이 이동해 기본 탭이 열림. 프론트가 화면별 해시를 붙일 수 있음(routing.yaml 변경 불필요)
- G. 플레이스 로그인 정책: 비로그인도 열려야 한다면 안내서가 아니라 프론트를 고친다

## 안내서에 넣지 않은 routing.yaml 행

routing.yaml에서 안내서에 넣지 않은 행(라우팅 제외·결번·관리자)

- 35 랜딩페이지 (SCR-MAN-002)
- 36 로그인 · 회원가입 (SCR-ACC-001 / 002)
- 37 기본 레이아웃 · 드롭다운 3종 (SCR-COM-002·004·005·006)
- 38 AI 매니저 새 창 런처 (SCR-COM-007)
- 39 대화창 자신 (SCR-AIM-0xx)
- 40 OCR 촬영 · 결과 확인 · 실패 (SCR-AIM-008 / 009 / 010)
- 41 검진상세 (SCR-HLT-005)
- 42 검사 수치 입력 (SCR-HLT-007)
- 43 결번 (SCR-HLT-000·001·004·006·008·009)
- 44 플레이스 (보류) (SCR-PLC-001 / 002)
- 45 관리자 도메인 전체 (—)

## 화면별 메모(설계서와 다른 곳·확인 못 한 것·근거 파일)

- 1 종합 건강기록 (SCR-HLT-011)
  - 설계서와 다름: 설계서의 반려동물 선택은 칩으로 그려졌지만 코드는 요약 카드 안의 탭(반려동물 이름 탭)이에요
  - 설계서와 다름: 설계서 목업은 네 묶음을 한 번에 그렸지만 코드는 탭 4개 중 선택한 묶음만 보여줘요
  - 코드: `src/pages/health/HealthSummaryPage.jsx`, `src/features/health/summary/`, `src/routes/domains/health/healthRoutes.js`, `src/layouts/subMenus.js`
  - 설계서: 건강기록_화면설계서_v1.2_20261101 SCR-HLT-011
- 2 플레이스 병원 화면 (SCR-HOS-001)
  - 설계서와 다름: 설계서에는 [전체] 탭과 검색 [검색] 버튼이 있지만 코드에는 없음. 종류 버튼은 병원·미용·용품·동반·호텔 5개, 검색은 Enter로만 실행
  - 설계서와 다름: 설계서 정렬 기본값은 추천순이지만 코드 기본값은 거리순(선택지는 거리순·추천순·이름순)
  - 설계서와 다름: 설계서의 병원 카드 영업시간·진료중·24시·응급 배지와 '저장한 즐겨찾기가 없습니다.' 문구는 코드에 없음. 즐겨찾기가 없으면 영역을 숨김
  - 설계서와 다름: 설계서 결과 핀·카드 표시는 A·B 글자, 코드는 1·2·3 숫자
  - 확인 못 함: 비로그인 상태로 열었을 때 동작 미확인. 라우트는 공개지만 즐겨찾기 조회(/place-bookmarks)가 401을 받으면 로그인 화면으로 이동할 수 있음
  - 확인 못 함: 플레이스 화면에서 떠 있는 AI 버튼이 보이지 않는 것이 의도인지 설계서(SCR-COM-007) 확인 필요
  - 코드: `src/pages/place/PlacePage.jsx`, `src/features/place/PlacePanel.jsx`, `src/features/place/PlaceCategoryNav.jsx`, `src/features/place/PlaceSearchForm.jsx`, `src/features/place/PlaceMap.jsx`, `src/features/place/usePlaceSearch.js`, `src/layouts/gnbMenus.js`
  - 설계서: 플레이스_화면설계서_v0.7_20260930 SCR-HOS-001
- 3 플레이스 (SCR-HOS-001)
  - 코드: `src/pages/place/PlacePage.jsx`, `src/features/place/placeData.js`
  - 설계서: 플레이스_화면설계서_v0.7_20260930 SCR-HOS-001
- 4 펫이야기 목록 (SCR-CMU-001-01)
  - 설계서와 다름: 설계서는 비로그인 사용자가 목록을 보다가 [글쓰기]를 누르면 로그인 후 복귀한다고 하지만, 코드는 커뮤니티 화면 전체가 로그인 필요라 로그인하지 않으면 목록부터 볼 수 없다
  - 설계서와 다름: 설계서 검색 버튼 [검색] → 코드는 검색칸 안 검색 아이콘/Enter
  - 코드: `src/pages/community/PostListPage.jsx`, `src/features/community/PostList.jsx`, `src/features/community/PostForm.jsx`, `src/features/community/StoryRail.jsx`, `src/routes/domains/community/communityRoutes.js`
  - 설계서: 커뮤니티_화면설계서_v0.8_20261101 SCR-CMU-001-01 (글쓰기는 SCR-CMU-001-03)
- 5 마이페이지 홈 (SCR-MYP-001)
  - 확인 못 함: 설계서의 대표(REP) 배지 위치와 6마리 표시는 코드에서 개수(6)만 확인했고 배지 모양은 확인 못 함
  - 코드: `src/pages/mypage/MyPageHomePage.jsx`, `src/features/pet/home/MyPetsSection.jsx`, `src/features/point/home/PointSummaryCard.jsx`, `src/features/expense/home/ExpenseSummaryCard.jsx`, `src/features/point/home/MissionSummaryCard.jsx`
  - 설계서: 마이페이지_화면설계서_v0.6_20261025 SCR-MYP-001
- 6 픽셀 캐릭터 관리 (SCR-MYP-010)
  - 설계서와 다름: 설계서의 캐릭터 만들기는 최근 코드에서 AI 서버(POST /ai/characters) 요청으로 연결돼 실제로 생성돼요
  - 코드: `src/pages/mypage/CharacterPage.jsx`, `src/features/pet/character/CharacterCard.jsx`, `src/features/pet/character/CharacterCreateModal.jsx`, `src/features/pet/api.js`
  - 설계서: 마이페이지_화면설계서_v0.6_20261025 SCR-MYP-010
- 7 공지사항 목록 (SCR-CSC-001)
  - 설계서와 다름: 설계서 검색칸 '공지 제목 검색' → 코드 '제목 또는 내용 검색'
  - 설계서와 다름: 설계서는 1:1 문의 목록이 먼저 열린다고 하지만, 코드는 문의를 한 번도 안 남긴 사람이면 목록을 건너뛰고 바로 새 문의 작성 화면을 연다
  - 확인 못 함: routing.yaml에 1:1 문의(SCR-CSC-003) 행 없음. '문의' 키워드가 이 공지사항 목록(num 7)으로 가서, 1:1 문의 목록·작성·상세 경로(/inquiries, /inquiries/new, /inquiries/:otoInqrySn)를 이 행에 함께 적음
  - 확인 못 함: 문의 유형 선택 항목 이름은 서버 공통코드(CSCG02, 7종)에서 받아오며 코드에 고정 문구가 없어 확인 못 함. 설계서는 건강기록 문의·픽셀 캐릭터·플레이스·커뮤니티·포인트·결제·가계부·계정·로그인·기타
  - 확인 못 함: 이미지 첨부 한도를 문의 폼 전용으로 확인하지 않고 공용 이미지 첨부 칸(최대 10장, 10MB)의 값을 적음
  - 코드: `src/pages/notice/NoticeListPage.jsx`, `src/features/notice/NoticeList.jsx`, `src/layouts/CustomerCenterLayout.jsx`, `src/layouts/subMenus.js`, `src/routes/domains/support/supportRoutes.js`, `src/pages/inquiry/InquiryListPage.jsx`, `src/pages/inquiry/InquiryWritePage.jsx`, `src/features/inquiry/InquiryList.jsx`, `src/features/inquiry/InquiryForm.jsx`, `src/features/inquiry/InquiryDetail.jsx`, `src/features/inquiry/api.js`
  - 설계서: 고객센터_화면설계서_v0.4_20261025 SCR-CSC-001 (1:1 문의 부분은 SCR-CSC-003)
- 8 메인 (SCR-MAN-001)
  - 설계서와 다름: 설계서는 질문창이 메인 안에서 대화창으로 확장된다고 하지만 코드는 새 창(/ai-chat)을 열고 질문을 넘김
  - 설계서와 다름: 설계서의 위젯 카드 순서 조정(회원별 저장)은 코드에 없음
  - 설계서와 다름: 설계서의 [건강기록 전체 보기]는 코드에서 [통합대시보드 전체 보기]이고, 선택한 반려동물을 넘기지 않고 종합 건강기록으로만 이동
  - 설계서와 다름: 설계서의 '토탈 케어리스트' 섹션은 코드에서 '데일리 케어미션' 섹션이고 [토탈 케어리스트]는 케어 캘린더로 가는 링크.
  - 설계서와 다름: 설계서 위젯 6종 중 AI 건강분석 리포트가 맨 앞(왼쪽 위)에 있음
  - 확인 못 함: 비로그인 상태의 메인 표시는 설계서에서도 미정이라 확인하지 못함(메인 라우트는 로그인 필요)
  - 확인 못 함: 건강기록 API 연결 후 위젯 실제 값과 기록 없음 문구가 어떻게 바뀌는지 확인 필요
  - 코드: `src/pages/main/MainPage.jsx`, `src/features/dashboard/HeroAsk.jsx`, `src/features/dashboard/dashboardSample.js`, `src/features/dashboard/MissionList.jsx`, `src/layouts/FloatingButtons.jsx`, `src/routes/domains/main/mainRoutes.js`
  - 설계서: 메인페이지_화면설계서_v0.10_20261103 SCR-MAN-001
- 9 설정 (SCR-COM-008)
  - 확인 못 함: 캐릭터 생성 완료 알림을 설계서는 '확정 필요'로 두었으나 코드는 끌 수 없음으로 고정
  - 코드: `src/pages/settings/NotificationSettingsPage.jsx`, `src/features/notification/settings/NotificationSettingsForm.jsx`, `src/features/notification/queries.js`, `src/layouts/ProfileDropdown.jsx`, `src/layouts/NavDrawer.jsx`, `src/layouts/bottomNavMenus.js`
  - 설계서: 공통레이아웃_화면설계서_v0.11_20261101 SCR-COM-008
- 10 채팅 (SCR-COM-009)
  - 설계서와 다름: 설계서의 [새 창] 버튼은 코드에서 [새 창으로 띄우기]
  - 설계서와 다름: 설계서의 읽음 동기화와 안 읽은 수 배지는 코드가 브라우저 저장소 기반 연습용 값으로 흉내 냄
  - 확인 못 함: /chat 새 창 라우트는 로그인 보호(ProtectedRoute) 밖이라 비로그인 시 동작 미확인
  - 확인 못 함: 채팅 API 연결 후 실제 목록·거래 카드 동작 확인 필요
  - 코드: `src/layouts/ChatModal.jsx`, `src/layouts/UserHeader.jsx`, `src/context/ChatModalProvider.jsx`, `src/hooks/useChatWindow.js`, `src/pages/chat/ChatPage.jsx`, `src/features/chat/api.js`, `src/features/chat/room/ChatRoomList.jsx`, `src/features/chat/room/ChatMessageInput.jsx`, `src/layouts/NotificationDropdown.jsx`
  - 설계서: 공통레이아웃_화면설계서_v0.11_20261101 SCR-COM-009
- 11 케어 캘린더 (SCR-HLT-003)
  - 확인 못 함: 일정 모달의 반려동물이 1마리뿐일 때 반려동물 선택칸이 숨는지는 확인하지 못했어요
  - 코드: `src/pages/health/CareCalendarPage.jsx`, `src/features/health/MonthCalendar.jsx`, `src/features/health/ScheduleModal.jsx`, `src/features/health/ScheduleDayDetail.jsx`, `src/features/health/UpcomingSchedules.jsx`, `src/features/health/scheduleTypes.js`
  - 설계서: 건강기록_화면설계서_v1.2_20261101 SCR-HLT-003
- 12 케어 캘린더 토탈 케어리스트 (SCR-HLT-003)
  - 설계서와 다름: 설계서는 메인 표시가 6개를 넘으면 '메인에는 6개까지 보여줄 수 있어요' 안내가 뜬다고 하지만 프론트 코드에는 그 문구가 없어요(저장 요청을 그대로 보내요)
  - 확인 못 함: 메인 표시를 7번째로 눌렀을 때 실제로 어떤 안내가 나오는지는 서버 응답에 달려 있어 확인하지 못했어요
  - 확인 못 함: 좁은 화면에서 케어리스트 탭 진입 경로의 실제 메뉴 이름은 확인하지 못했어요
  - 코드: `src/features/health/CareList.jsx`, `src/features/health/CareTile.jsx`, `src/features/health/CareItemModal.jsx`, `src/features/health/CareItemMenu.jsx`, `src/features/health/CareRecordList.jsx`
  - 설계서: 건강기록_화면설계서_v1.2_20261101 SCR-HLT-003
- 13 건강 일지 (SCR-HLT-002)
  - 확인 못 함: 관찰 항목 저장 버튼의 정확한 이름은 확인하지 못했어요
  - 코드: `src/pages/health/HealthDiaryPage.jsx`, `src/features/health/diary/TodayRecordCard.jsx`, `src/features/health/diary/TodayRecordForm.jsx`, `src/features/health/diary/DailyTrendCard.jsx`, `src/features/health/diary/RecentRecordTable.jsx`, `src/features/health/diary/ObservationCard.jsx`, `src/features/health/diary/ObservationModal.jsx`, `src/features/health/diaryTypes.js`
  - 설계서: 건강기록_화면설계서_v1.2_20261101 SCR-HLT-002
- 14 건강 일지 검진기록 (SCR-HLT-002)
  - 확인 못 함: 검진기록 줄에서 [수정] 버튼은 없고 병원 이름 링크로 검진상세에 가서 고치는 것으로 보여요. 검진상세 기본정보 카드의 수정 버튼 이름은 확인하지 못했어요
  - 확인 못 함: 영수증 인식 결과 화면의 가계부 기록 체크 문구와 반려동물 배정 방식은 일부만 확인했어요
  - 코드: `src/pages/health/HealthDiaryPage.jsx`, `src/features/health/diary/CheckupListCard.jsx`, `src/features/health/diary/CheckupModal.jsx`, `src/features/health/diary/ReceiptResultStep.jsx`, `src/features/health/receiptApi.js`, `src/features/ai/receipt/ReceiptUploadModal.jsx`
  - 설계서: 건강기록_화면설계서_v1.2_20261101 SCR-HLT-002
- 15 종합 건강기록 처방 및 투약 이력 (SCR-HLT-011)
  - 확인 못 함: 처방약 수정 방법(줄을 눌러 고치는지)은 확인하지 못했어요
  - 코드: `src/pages/health/HealthSummaryPage.jsx`, `src/features/health/summary/PrescriptionHistoryCard.jsx`, `src/features/health/checkup/PrescriptionTab.jsx`, `src/features/health/checkup/PrescriptionForm.jsx`
  - 설계서: 건강기록_화면설계서_v1.2_20261101 SCR-HLT-011
- 16 종합 건강기록 검사 결과 (SCR-HLT-011)
  - 확인 못 함: 검진상세에서 [검사 수치 추가]를 누르면 같은 화면 안에서 입력 칸이 열리는지, 검사 수치 입력 화면으로 이동하는지 코드만으로는 완전히 확인하지 못했어요(수정은 이동하는 것으로 보여요)
  - 코드: `src/pages/health/HealthSummaryPage.jsx`, `src/features/health/summary/LabResultCard.jsx`, `src/features/health/summary/LabTrendCard.jsx`, `src/features/health/checkup/BloodResultList.jsx`, `src/features/health/checkup/BloodResultForm.jsx`, `src/features/health/checkup/AttachmentTab.jsx`, `src/features/health/labInput/AnalysisReview.jsx`
  - 설계서: 건강기록_화면설계서_v1.2_20261101 SCR-HLT-011
- 17 플레이스 미용 화면 (SCR-HOS-001)
  - 코드: `src/pages/place/PlacePage.jsx`, `src/features/place/placeData.js`
  - 설계서: 플레이스_화면설계서_v0.7_20260930 SCR-HOS-001
- 18 플레이스 용품 화면 (SCR-HOS-001)
  - 코드: `src/pages/place/PlacePage.jsx`, `src/features/place/placeData.js`
  - 설계서: 플레이스_화면설계서_v0.7_20260930 SCR-HOS-001
- 19 플레이스 동반 화면 (SCR-HOS-001)
  - 코드: `src/pages/place/PlacePage.jsx`, `src/features/place/placeData.js`
  - 설계서: 플레이스_화면설계서_v0.7_20260930 SCR-HOS-001
- 20 플레이스 호텔 화면 (SCR-HOS-001)
  - 코드: `src/pages/place/PlacePage.jsx`, `src/features/place/placeData.js`
  - 설계서: 플레이스_화면설계서_v0.7_20260930 SCR-HOS-001
- 21 동물병원 요약 카드 (SCR-HOS-002)
  - 설계서와 다름: 설계서의 핀 선택 상태에는 [카카오맵 상세보기]만 있고, 코드 요약 카드에는 [상세보기]와 [길찾기] 두 버튼이 있음
  - 설계서와 다름: 설계서의 영업시간·진료중 등 표시는 코드 요약 카드에 없음
  - 확인 못 함: SCR-HOS-002 번호가 붙은 설계서 화면을 추출하지 못해 SCR-HOS-001 핀 선택 상태 기준으로 작성
  - 코드: `src/features/place/PlacePopup.jsx`, `src/features/place/PlacePin.jsx`, `src/features/place/placeFormat.js`
  - 설계서: 플레이스_화면설계서_v0.7_20260930 SCR-HOS-001 (핀 선택 상태). SCR-HOS-002 번호로 된 별도 화면은 설계서에서 찾지 못함
- 22 펫이야기 글 상세 (SCR-CMU-001-02)
  - 설계서와 다름: 신고 사유: 설계서(스팸·욕설/비방·유해콘텐츠·개인정보 노출·허위정보·기타) → 코드(스팸 · 광고성 / 욕설 · 비방 / 음란물 · 유해 콘텐츠 / 개인정보 노출 / 사기 · 허위 정보 / 기타)
  - 설계서와 다름: 설계서 [답글쓰기] · [신고]가 댓글 아래에 나란히 → 코드는 신고가 댓글 오른쪽 점 세 개 메뉴 안의 [신고하기]
  - 설계서와 다름: 설계서 공유하기는 링크 복사 또는 공유 채널 선택 → 코드는 [링크 복사] / [다른 앱으로 공유]
  - 코드: `src/pages/community/PostDetailPage.jsx`, `src/pages/community/PostEditPage.jsx`, `src/features/community/PostDetail.jsx`, `src/features/community/CommentSection.jsx`, `src/components/ReportModal.jsx`, `src/components/SharePanel.jsx`
  - 설계서: 커뮤니티_화면설계서_v0.8_20261101 SCR-CMU-001-02
- 23 실종센터 (SCR-CMU-002)
  - 설계서와 다름: 설계서 목록 필터가 화면에 바로 펼쳐져 있음 → 코드는 [상세 필터] 버튼으로 열고 닫음(내 글만 보기 체크박스 추가)
  - 설계서와 다름: 설계서는 한 줄 3개 카드 → 코드 12개씩, 화면 폭에 따라 3·2·1개 열
  - 확인 못 함: 오른쪽 안내(실종 Check 가이드)의 [자세한 대처 요령 보기]가 공지사항 목록으로 가는지만 확인했고, 어떤 공지 글인지는 확인 못 함
  - 코드: `src/pages/community/MissingListPage.jsx`, `src/pages/community/MissingDetailPage.jsx`, `src/pages/community/MissingWritePage.jsx`, `src/features/community/missing/MissingList.jsx`, `src/features/community/missing/MissingFilters.jsx`, `src/features/community/missing/MissingForm.jsx`, `src/features/community/missing/MissingDetail.jsx`, `src/features/community/missing/MissingSideBox.jsx`, `src/features/community/missing/MissingOwnerModals.jsx`
  - 설계서: 커뮤니티_화면설계서_v0.8_20261101 SCR-CMU-002-01 ~ 002-06
- 24 펫뉴스 (SCR-CMU-003-01)
  - 설계서와 다름: 설계서 검색칸 '뉴스 제목 검색' → 코드 '제목 또는 내용 검색'
  - 설계서와 다름: 설계서 [원문보기 ↗] → 코드 [원문 기사 보기]
  - 확인 못 함: 뉴스 상세는 별도 routing.yaml 행이 없음(펫뉴스 목록 행에 포함해 안내)
  - 코드: `src/pages/news/NewsListPage.jsx`, `src/pages/news/NewsDetailPage.jsx`, `src/features/news/NewsList.jsx`, `src/features/news/NewsDetail.jsx`, `src/features/news/newsCodes.js`
  - 설계서: 커뮤니티_화면설계서_v0.8_20261101 SCR-CMU-003-01, 003-02
- 25 우리동네 펫돌봄 (SCR-CMU-004)
  - 설계서와 다름: 설계서는 [채팅하기]가 사이트 안 채팅 모달을 연다고 하지만, 코드는 돌봄 글의 [채팅하기]·[채팅 목록 보기]가 별도 채팅 창(팝업)을 연다. 헤더 채팅 아이콘은 모달
  - 설계서와 다름: 설계서 상세 [채팅하기] 위치 → 코드는 오른쪽 요약 상자(비용·일정·장소 아래)에 있음
  - 설계서와 다름: 설계서 목록은 [상세 필터]를 접고 펴는 구조를 명시했고 코드도 같음. 설계서에 없는 [내 글만 보기]가 코드엔 있음
  - 확인 못 함: 돌봄 상세 화면의 좋아요·공유·신고 위치는 코드 구조만 확인했고 화면에서 눌러 보지는 않음
  - 코드: `src/pages/community/CareListPage.jsx`, `src/pages/community/CareDetailPage.jsx`, `src/pages/community/CareWritePage.jsx`, `src/features/community/care/CareList.jsx`, `src/features/community/care/CareFilters.jsx`, `src/features/community/care/CareForm.jsx`, `src/features/community/care/CareDetail.jsx`, `src/features/community/care/CareSideBox.jsx`, `src/features/community/careCodes.js`, `src/hooks/useChatWindow.js`
  - 설계서: 커뮤니티_화면설계서_v0.8_20261101 SCR-CMU-004-01 ~ 004-03
- 26 반려동물 등록·수정 (SCR-MYP-002)
  - 설계서와 다름: 설계서의 대표 지정은 카드 안에 없고 코드에서는 픽셀 캐릭터 화면의 [대표 지정] 버튼에서 해요(반려동물 관리 화면에는 대표 지정 버튼이 없음)
  - 확인 못 함: 모바일에서 카드를 밀어서 넘기는지, 화살표가 숨는지는 화면 크기별로 확인 못 함
  - 코드: `src/pages/mypage/PetListPage.jsx`, `src/features/pet/list/PetSlide.jsx`, `src/features/pet/list/PetFormModal.jsx`, `src/features/pet/list/PetDeleteDialog.jsx`, `src/features/pet/list/PetUnlinkDialog.jsx`, `src/features/pet/list/PetEmpty.jsx`
  - 설계서: 마이페이지_화면설계서_v0.6_20261025 SCR-MYP-002
- 27 공동양육 관리 (SCR-MYP-004)
  - 설계서와 다름: AI 화면 경로 표(src/features/ai/shared/screenPaths.js)는 SCR-MYP-004를 /mypage/caregivers로 연결하지만 그 주소는 실제 화면으로 등록돼 있지 않아요. 실제 위치는 /mypage/pets 안의 가족 영역이에요
  - 설계서와 다름: 설계서의 가족 카드는 이름·권한(조회+수정)·연동일을 보여 주지만 코드는 이름과 연동일만 보여 줘요
  - 확인 못 함: 초대 알림을 눌렀을 때 어디로 가는지는 코드에서 확인 못 함
  - 확인 못 함: 받은 초대 수락 화면으로 들어가는 PC/모바일 메뉴 길은 링크로만 확인함
  - 코드: `src/features/pet/list/FamilySection.jsx`, `src/features/pet/list/InviteModal.jsx`, `src/features/pet/list/SentInvitations.jsx`, `src/features/pet/list/PetUnlinkDialog.jsx`, `src/pages/mypage/InvitationPage.jsx`, `src/features/pet/invite/InvitationAccept.jsx`, `src/routes/domains/mypage/mypageRoutes.js`
  - 설계서: 마이페이지_화면설계서_v0.6_20261025 SCR-MYP-004
- 28 픽셀 캐릭터 상세 (SCR-MYP-011)
  - 설계서와 다름: 설계서의 아이템 상점은 별도 화면이지만 코드에서는 꾸미기 화면 위에 뜨는 창이에요(별도 주소 없음)
  - 확인 못 함: 아이템 가격과 포인트 금액은 서버 값이라 안내서에는 적지 않음
  - 코드: `src/pages/mypage/CharacterPage.jsx`, `src/features/pet/character/CharacterDecorate.jsx`, `src/features/pet/character/ItemShopModal.jsx`, `src/features/pet/character/ItemStorage.jsx`, `src/features/pet/character/WearPreview.jsx`
  - 설계서: 마이페이지_화면설계서_v0.6_20261025 SCR-MYP-011
- 29 케어미션 · 포인트 (SCR-MYP-020)
  - 설계서와 다름: 요약 칸의 [캐릭터 꾸미기] 버튼은 모바일(760px 미만)에서 숨겨져요
  - 확인 못 함: 케어미션 8개 규칙과 50% 이하 미지급 같은 정산 세부는 설계서에만 있고 화면 문구로 확인 못 해 안내서에 쓰지 않음
  - 코드: `src/pages/mypage/PointPage.jsx`, `src/features/point/summary/PointSummary.jsx`, `src/features/point/mission/CareMission.jsx`, `src/features/point/history/PointHistory.jsx`, `src/features/point/guide/PointGuide.jsx`
  - 설계서: 마이페이지_화면설계서_v0.6_20261025 SCR-MYP-020
- 30 가계부 (SCR-MYP-030)
  - 설계서와 다름: 설계서는 달력 날짜를 누르면 바로 등록 방법을 고르게 하지만, 코드는 날짜를 누르면 먼저 그날 내역이 펼쳐지고 [지출 추가]를 눌러야 등록 방법을 골라요(내역이 없는 날도 날짜를 누르면 등록할 수 있다고 안내 문구에 적혀 있음)
  - 설계서와 다름: 영수증 인식(recognizeReceipt)은 가짜 응답(파일 이름으로 성공·실패를 흉내냄)이라 설계서의 AI 영수증 인식은 아직 연결 전이에요
  - 확인 못 함: 달력 날짜 클릭 한 번으로 바로 등록 방법 선택 창이 열리는지, 내역 펼침 후 [지출 추가]만 가능한지 화면에서 확인 못 함
  - 확인 못 함: 영수증 파일 허용 형식과 크기 제한 문구는 코드에서 확인 못 함(설계서는 jpg·png·webp, 10MB)
  - 코드: `src/pages/mypage/ExpensePage.jsx`, `src/features/expense/dashboard/ExpenseDashboard.jsx`, `src/features/expense/dashboard/ExpenseAddModal.jsx`, `src/features/expense/dashboard/ExpenseReceiptUpload.jsx`, `src/features/expense/dashboard/ExpenseReceiptReview.jsx`, `src/features/expense/dashboard/ExpenseLimitModal.jsx`, `src/features/expense/api.js`
  - 설계서: 마이페이지_화면설계서_v0.6_20261025 SCR-MYP-030
- 31 가계부 전체 내역 (SCR-MYP-031)
  - 설계서와 다름: 화면 이름은 설계서 '전체 내역(30-2)'이고 코드 제목은 '전체 내역'이에요. 내용은 같아요
  - 코드: `src/pages/mypage/ExpenseAllPage.jsx`, `src/features/expense/history/ExpenseHistory.jsx`, `src/features/expense/history/ExpenseFilterBar.jsx`, `src/features/expense/history/ExpenseRangeSelect.jsx`, `src/features/expense/history/ExpenseBulkDeleteDialog.jsx`
  - 설계서: 마이페이지_화면설계서_v0.6_20261025 SCR-MYP-031
- 32 회원정보 수정 (SCR-MYP-040)
  - 설계서와 다름: 회원 탈퇴 주소(/mypage/withdraw)는 paths.js에 있지만 라우트에 연결돼 있지 않아 [회원 탈퇴] 버튼은 이동하지 않고 준비 중 안내만 띄워요
  - 설계서와 다름: 닉네임·휴대폰·사진은 member/api.js에서 가짜 응답(해당 API 연결 마일스톤에서 교체 예정)이에요. 비밀번호 확인·변경만 실제 서버 호출이에요
  - 확인 못 함: 모바일(760px 미만)에서 회원정보 수정 화면으로 가는 길(하단 탭에는 없음)은 코드에서 확인 못 함
  - 확인 못 함: 휴대폰 번호 입력 형식 규칙은 확인 못 함
  - 코드: `src/pages/mypage/ProfileEditPage.jsx`, `src/features/member/profile/ProfileEditForm.jsx`, `src/features/member/profile/NicknameField.jsx`, `src/features/member/profile/PhoneField.jsx`, `src/features/member/profile/PasswordChangeCard.jsx`, `src/features/member/api.js`
  - 설계서: 마이페이지_화면설계서_v0.6_20261025 SCR-MYP-040
- 33 FAQ 목록 (SCR-CSC-002-01)
  - 설계서와 다름: 설계서 카테고리 '신고/제재' 표기 → 코드 [신고 · 제재]
  - 코드: `src/pages/faq/FaqListPage.jsx`, `src/features/faq/FaqList.jsx`, `src/features/faq/api.js`
  - 설계서: 고객센터_화면설계서_v0.4_20261025 SCR-CSC-002 (SCR-CSC-002-01 번호로는 추출되지 않아 SCR-CSC-002로 읽음)
- 34 공지 상세 (SCR-CSC-001-02)
  - 코드: `src/pages/notice/NoticeDetailPage.jsx`, `src/features/notice/NoticeDetail.jsx`
  - 설계서: 고객센터_화면설계서_v0.4_20261025 SCR-CSC-001 상세보기 (SCR-CSC-001-02 번호로는 추출되지 않아 SCR-CSC-001에서 읽음)
