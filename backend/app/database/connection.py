from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    # Two agents write concurrently; give SQLite time to wait for the write lock.
    connect_args={"timeout": 30} if _is_sqlite else {},
    pool_pre_ping=not _is_sqlite,
)

if _is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

async_sessionmaker_db = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_sessionmaker_db() as session:
        yield session


# Columns added after the first release. create_all() never alters existing tables,
# so older databases get them here: (table, column, SQL type and default).
_ADDED_COLUMNS = [
    # Experiments created before the code-only agents existed were LLM experiments.
    ("ms_experiments", "agent_type", "VARCHAR(20) NOT NULL DEFAULT 'llm'"),
    ("ms_experiments", "speed", "VARCHAR(10) NOT NULL DEFAULT 'watch'"),
]


def _add_missing_columns(sync_conn) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    tables = set(inspector.get_table_names())
    for table, column, ddl in _ADDED_COLUMNS:
        if table in tables and column not in {c["name"] for c in inspector.get_columns(table)}:
            sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


async def init_db() -> None:
    from app.database.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
