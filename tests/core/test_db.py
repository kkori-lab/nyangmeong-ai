from app.core.config import Settings
from app.core.db import database_url


def settings(db_url: str) -> Settings:
    return Settings(db_url=db_url, db_username="nm_ai", db_password="pw")


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
