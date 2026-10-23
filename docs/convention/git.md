# 냥멍케어 AI 컨벤션: Git 규칙 (제안, 팀 합의 전)

`AGENTS.md`에서 이어지는 문서다.

## 브랜치

| 브랜치 | 용도 |
| --- | --- |
| `main` | 배포본. `develop`과 `hotfix/`에서만 PR |
| `develop` | 통합. 개인 브랜치와 `hotfix/`에서 PR |
| 개인 브랜치 | 한 사람이 하나를 계속 쓴다. 이름은 자기 이니셜(예: `LJS`) |
| `hotfix/{내용}` | 배포본 긴급 수정. `main`에서 분기해 `main`과 `develop` 양쪽에 병합하고 지운다 |

- 기능마다 브랜치를 새로 만들지 않고 자기 브랜치에서 작업해 `develop`으로 PR을 올린다.
- PR 하나에는 기능 하나만 담는다. 열려 있는 PR이 있는 동안 같은 브랜치에 올린 커밋은 그 PR에 함께 들어가므로, 앞 PR이 병합된 뒤에 다음 기능을 시작한다.
- 작업을 마치면 `develop`의 최신 내용을 자기 브랜치에 합친 뒤 푸시하고 PR을 올린다. 건너뛰면 그 사이 병합된 다른 사람의 변경과 PR에서 충돌한다. 작업한 내용은 먼저 커밋한다.

  ```
  git checkout develop
  git pull origin develop      # 로컬 develop을 원격 기준으로 최신화
  git checkout LJS             # 자기 브랜치
  git merge develop            # 로컬 develop을 자기 브랜치에 병합
  git push origin LJS
  ```

- 로컬 `develop`에는 직접 커밋하지 않는다. 최신화하는 데만 쓴다.
- rebase는 쓰지 않는다. 개인 브랜치는 이미 푸시되어 있어서 rebase하면 커밋이 새로 만들어지고 강제 푸시가 필요해진다.
- merge 중 충돌이 나도 `git merge --abort`로 되돌리지 않는다. 충돌 파일을 고쳐 그 파일만 `git add`하고 `git commit`으로 merge를 끝낸다. abort해도 충돌은 그대로 남아 다음 merge나 PR에서 다시 나온다. 혼자 풀기 어려우면 충돌 상태로 두고 그 코드를 쓴 사람에게 묻는다.
- 병합은 merge 커밋으로 한다. squash는 쓰지 않는다. 개인 브랜치는 병합 뒤에도 계속 쓰는데, squash로 합치면 이력이 갈라져 이미 병합된 변경이 다음 PR에 다시 나타난다.
- `main`과 `develop`에는 직접 푸시하지 않는다.
- `hotfix/`는 배포본에 문제가 생겨 `develop`의 다음 배포를 기다릴 수 없을 때만 쓴다. `main`으로 PR을 올려 병합한 뒤 같은 내용을 `develop`에도 병합한다. 한쪽만 병합하면 다음 배포에서 수정이 사라진다.

## 커밋

```
[<이니셜>] <종류>: <무엇을 했는지>

[LJS] feat: 반려동물 등록 API 추가
[LJS] fix: 체중 기록 삭제 시 프로필 체중이 갱신되지 않는 문제 수정
```

종류는 `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `style`, `chore`, `ci`, `revert`다. Conventional Commits의 범위 표기(`feat(pet):`)와 `!`는 쓰지 않는다. 이니셜은 자기 브랜치 이름과 같게 쓴다. 관련 기능명세서 ID가 있으면 본문에 적는다(예: `FN-MYP-003-01`).

커밋 메시지에 `Co-Authored-By:` 줄을 넣지 않는다. AI 도구가 자동으로 붙인 줄은 setup이 등록하는 커밋 훅(`.githooks/commit-msg`)이 지운다. GitHub은 이 줄에 적힌 계정을 그 커밋의 공동 작성자로 표시한다.

## PR

- 대상은 `develop`이다(`hotfix/`만 `main`과 `develop` 양쪽). 승인 없이 누구나 병합할 수 있다. CI 통과 후 merge 커밋으로 병합한다.
- 제목은 커밋 형식과 같게 쓴다.
- PR을 열면(초안은 리뷰 가능으로 바꿀 때) `.github/workflows/pr-notify.yml`이 디스코드 채널로 알린다. 병합·닫힘은 알리지 않는다. 웹훅 주소는 저장소 시크릿 `DISCORD_WEBHOOK_URL`에만 둔다(공개 저장소라 파일에 적지 않는다). 프론트·백엔드·AI 저장소의 채널은 각 저장소 시크릿이 정한다.
- 본문은 `.github/pull_request_template.md`를 채운다. 프론트·백엔드 저장소와 같은 규칙이다(프론트는 `Features` 자리에 `Screenshots`).
  - 섹션 제목은 영어, 내용은 한국어로 쓴다. 순서를 바꾸지 않는다.
  - 해당 없는 섹션은 지우지 않고 `없음`이라고 쓴다. 더 적을 것이 있으면 섹션을 추가해도 된다.
  - 리뷰어 섹션은 두지 않는다(리뷰어 없이 병합한다).

| 섹션 | 쓰는 것 |
| --- | --- |
| `## Summary` | 화면 ID·기능 ID와 이 PR이 하는 일 1~3줄 |
| `## Changes` | 파일·모듈 단위 변경 목록 |
| `## Features` | 구현한 기능 표 `\| 기능 ID \| 내용 \|` (아래 규칙) |
| `## Test Plan` | 체크박스(`sh scripts/check.sh`의 ruff·pytest, Postman으로 호출한 API)와 `Result:`(검증 판정) |
| `## Design Decisions` | `Decision`·`Why`·`Alternatives Considered` (아래 규칙) |
| `## Breaking Changes` | 프론트·백엔드에 영향 가는 변경: `/ai/**` 응답 필드·형식, 내부 API 계약, DB·ERD, `.env.local` 키 |

- `Features` 표: 공통 기반 코드는 기능 ID 칸에 `(기반)`이라고 쓴다. 여러 ID는 `FN-COM-004-03·04·05·12`처럼 묶는다. 다른 담당에게 넘긴 것은 내용에 `연결 남음: … (담당)`이라고 쓴다.
  - 예: `| FN-COM-004-06·11 | POST /api/notifications/{inappNotiSn}/read, 남의·없는 알림은 404 NOTIFICATION_NOT_FOUND |`
- `Design Decisions`에는 기획과 달라진 것과 다른 담당·프론트에 영향 가는 선택만 쓴다. 사소한 구현 선택은 쓰지 않는다. `Alternatives Considered`는 실제로 비교한 대안이 있을 때만 쓴다.

## 작업 상태 공유

- 기능의 현재 상태는 GitHub 이슈로 관리한다. 기능 하나에 이슈 하나, 제목에 FN ID나 화면 ID를 쓴다.
- 다른 사람의 코드에 영향을 주는 결정은 개인 기록에 두지 않는다. 이 문서를 고치는 PR로 알린다.
