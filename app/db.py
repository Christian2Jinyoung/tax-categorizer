import sqlite3

from sqlmodel import SQLModel, Session, create_engine

from app.config import settings

settings.database_path_abs.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{settings.database_path_abs}")

# Columns added to LineItem after the table already existed in some dev DBs.
# SQLModel.metadata.create_all() only creates missing tables, not missing columns
# on existing ones, so new nullable columns need an explicit ALTER TABLE here.
_LINEITEM_COLUMN_MIGRATIONS = {
    "quantity": "ALTER TABLE lineitem ADD COLUMN quantity INTEGER",
    "item_uid": "ALTER TABLE lineitem ADD COLUMN item_uid TEXT",
    "abbreviated_description": "ALTER TABLE lineitem ADD COLUMN abbreviated_description TEXT",
}


def _migrate_lineitem_columns() -> None:
    conn = sqlite3.connect(settings.database_path_abs)
    try:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(lineitem)")}
        if not existing:
            return  # table doesn't exist yet - create_all() will make it with all columns
        for column, ddl in _LINEITEM_COLUMN_MIGRATIONS.items():
            if column not in existing:
                conn.execute(ddl)
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _migrate_lineitem_columns()


def get_session() -> Session:
    return Session(engine)
