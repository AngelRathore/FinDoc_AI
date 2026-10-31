from sqlalchemy import text

from db.session import get_engine


def database_is_ready() -> bool:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
    return True
