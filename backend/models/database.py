"""
데이터베이스 설정 모듈
- SQLAlchemy async 기반
- SQLite / PostgreSQL 교체 가능 (DATABASE_URL 환경변수만 변경)
"""

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from backend.config import settings


_engine_kwargs = {}
if "asyncpg" in settings.database_url:
    _engine_kwargs.update(
        poolclass=NullPool,
        connect_args={
            "statement_cache_size": 0,
            "command_timeout": 8,
        },
    )

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    **_engine_kwargs,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    """DB 테이블 생성 + 컬럼 마이그레이션 (앱 시작 시 호출)"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # 기존 테이블에 새 컬럼 추가 (없으면 추가, 있으면 무시)
        _migrations = [
            ("weather_logs", "kma_base_time", "VARCHAR(20)"),
            ("alert_logs", "weather_base_time", "VARCHAR(20)"),
        ]
        for table, col, col_type in _migrations:
            try:
                await conn.execute(
                    __import__("sqlalchemy").text(
                        f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"
                    )
                )
            except Exception:
                pass


async def get_db() -> AsyncSession:
    """FastAPI Dependency Injection용 세션 제공"""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
