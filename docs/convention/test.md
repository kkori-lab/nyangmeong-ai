# 테스트

테스트를 쓰거나, 검증 명령에서 테스트가 실패했을 때 연다.

- 테스트를 지우거나 끄거나(`skip`·`xfail`) 기대값을 바꿔서 통과시키지 않는다. 가끔 실패하는 테스트도 꺼서 넘기지 않고 원인을 고친다.
- PR은 `sh scripts/check.sh`가 통과해야 병합한다. CI(`.github/workflows/build.yml`)도 같은 검사를 돈다.
- 테스트는 `tests/` 아래에 `app/`과 같은 폴더 구조로 둔다. 테스트 함수 이름은 `test_<대상>_<조건이나 결과>`이고 한글을 써도 된다.
- 외부 AI API를 부르지 않는다. 앱에는 실제 클라이언트만 있으므로 `dependency_overrides`로 가짜 객체를 끼운다(대화창은 `tests/chat/fakes.py`, `tests/chat/conftest.py`의 `client`가 기본으로 끼운다). `tests/conftest.py`가 테스트마다 AI 키를 비워 두므로 가짜를 빠뜨리면 실제 호출 대신 502로 실패한다. 키가 없는 CI에서도 통과해야 한다.
- DB에 붙는 자동 테스트는 만들지 않는다. 팀 공용 DB라 다른 사람의 데이터를 바꾼다. SQL은 `repository`에 모으고, 그 위의 `service`는 가짜 `repository`로 시험한다.
- 명세 규칙(라우팅 최장 일치, 등록 판정, 영수증 파싱, 할인 배분 등)은 입력·기대값 표로 시험한다(`pytest.mark.parametrize`). 기대값에 기능 ID를 주석으로 적는다.
- 각자 PC의 `.env.local`과 관계없이 돌도록, 설정이 필요한 테스트는 `monkeypatch.setenv`로 값을 넣고 `get_settings.cache_clear()`를 부른다(`tests/conftest.py`).
