from app.core.config import AppProfile, Settings
from app.core.db import database_url


def settings(db_url: str) -> Settings:
    return Settings(
        _env_file=None, local_db_url=db_url, local_db_username="nm_ai", local_db_password="pw"
    )


def profile_settings(profile: AppProfile) -> Settings:
    return Settings(
        _env_file=None,
        app_profile=profile,
        local_db_url="mysql://localhost:3306/nyangmeong_local",
        local_db_username="root",
        local_db_password="local-pw",
        prod_db_url="mysql://db.example:3306/pawever",
        prod_db_username="nm_ai",
        prod_db_password="prod-pw",
    )


def test_database_url_백엔드_JDBC_주소를_받는다() -> None:
    url = database_url(
        settings(
            "jdbc:mysql://db.example:3306/pawever?serverTimezone=Asia/Seoul&characterEncoding=UTF-8"
        )
    )

    assert url.drivername == "mysql+asyncmy"
    assert (url.host, url.port, url.database) == ("db.example", 3306, "pawever")
    assert (url.username, url.password) == ("nm_ai", "pw")
    assert dict(url.query) == {"charset": "utf8mb4"}


def test_database_url_mysql_주소를_받는다() -> None:
    url = database_url(settings("mysql://db.example:3306/pawever"))

    assert (url.drivername, url.host, url.database) == ("mysql+asyncmy", "db.example", "pawever")


def test_database_url_local_프로필이면_로컬_DB를_쓴다() -> None:
    url = database_url(profile_settings(AppProfile.LOCAL))

    assert (url.host, url.database) == ("localhost", "nyangmeong_local")
    assert (url.username, url.password) == ("root", "local-pw")


def test_database_url_prod_프로필이면_공용_DB를_쓴다() -> None:
    url = database_url(profile_settings(AppProfile.PROD))

    assert (url.host, url.database) == ("db.example", "pawever")
    assert (url.username, url.password) == ("nm_ai", "prod-pw")


def test_app_profile_기본값은_local이다() -> None:
    assert Settings(_env_file=None).app_profile is AppProfile.LOCAL
