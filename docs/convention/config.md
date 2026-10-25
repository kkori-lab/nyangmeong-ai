# 설정과 비밀값

설정 파일, 비밀값, 환경변수를 다룰 때와 핸드오프를 쓸 때 연다.

**이 저장소는 공개다. 한 번 커밋된 값은 지워도 이력에 남는다.**

- 설정은 `.env.local` 하나에 둔다. 비밀값(DB 접속 정보, JWT·암호화 키, 내부 호출 키, 외부 AI API 키)이 들어 있어 git에 올리지 않고(`.gitignore`) 디스코드로 공유한다. 서버 주소도 공개 저장소에 적지 않는다.
- 키 목록은 커밋된 `.env.local.example`에 둔다. 값은 비우고(`AI_MODE=mock`만 예외), 비밀값을 쓰지 않는다. 키를 추가·변경하면 이 예시 파일도 같은 PR에서 고치고 디스코드의 파일도 갱신한다.
- 코드는 `.env.local`을 직접 읽지 않고 `app/core/config.py`의 `Settings`로 읽는다. 키를 추가하면 `Settings`에도 필드를 넣는다. 비밀값 필드는 `SecretStr`로 둔다.
- 환경변수가 `.env.local`보다 우선한다. 운영 서버는 환경변수로 넣는다.
- DB는 `APP_PROFILE`로 고른다. `local`(기본)은 `LOCAL_DB_*`, `prod`(공용 DB)는 `PROD_DB_*`를 쓴다. 이름은 백엔드 `spring.profiles`와 같다. 기본값을 `prod`로 바꾸지 않는다. 값을 빠뜨린 PC가 공용 DB에 쓰게 된다.
- 백엔드와 같아야 하는 값: `JWT_SECRET_BASE64` = 백엔드 `app.jwt.secret-base64`. `INTERNAL_API_KEY` = 백엔드가 이 서버를 부를 때 보내는 키.
- Google 서비스 계정 키 같은 파일은 저장소 밖이나 git 제외 경로에 두고 `.env.local`에는 경로만 적는다.
- DMS MCP 서버 주소(`DMS_MCP_URL`)도 `.env.local`에 둔다. setup이 읽어 감지한 AI 도구(Claude Code·Codex)에 등록한다.
- 로그에 비밀번호와 토큰을 남기지 않는다.
- 작업 기록은 `handoff/<이름>.md`에 사람마다 한 파일로 두고 커밋한다. 다른 PC에서도 이어서 작업하기 위해서다. 공개 저장소이므로 비밀값과 개인 PC 경로를 쓰지 않는다.
