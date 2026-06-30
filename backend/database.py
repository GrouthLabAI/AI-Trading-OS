# AI Trading OS - Database initialization
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from backend.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    """Create all tables + add any missing columns on startup.

    SQLite does not support ALTER TABLE ADD COLUMN IF NOT EXISTS,
    so we attempt to add known columns gracefully, ignoring errors
    when the column already exists.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Auto-migrate: add columns that exist in models but not yet in SQLite
    import sqlite3
    from backend.config import settings as s

    # Extract the SQLite file path from the connection URL
    db_path = s.database_url.replace("sqlite+aiosqlite:///", "")
    sync_conn = sqlite3.connect(db_path)
    try:
        cursor = sync_conn.execute("PRAGMA table_info(stock_pick)")
        existing_cols = {row[1] for row in cursor.fetchall()}

        # Columns we've added to StockPick after initial table creation
        # (model_attr, sql_type, default_val)
        extra_cols = [
            ("first_limit_time", "TEXT", "''"),
            ("open_count", "INTEGER", "0"),
            ("lu_turnover", "REAL", "0.0"),
            ("amplitude", "REAL", "0.0"),
            ("volume_ratio", "REAL", "0.0"),
            ("total_market_cap", "REAL", "0.0"),
            ("sector", "TEXT", "''"),
            ("board_pattern", "TEXT", "''"),
        ]

        for col_name, col_type, col_default in extra_cols:
            if col_name not in existing_cols:
                sync_conn.execute(
                    f"ALTER TABLE stock_pick ADD COLUMN {col_name} {col_type} DEFAULT {col_default}"
                )
                print(f"  ✓ Migrated: stock_pick.{col_name}")

        sync_conn.commit()
    finally:
        sync_conn.close()


async def get_db() -> AsyncSession:
    """Dependency: yield an async database session."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
