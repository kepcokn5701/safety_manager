"""
데이터베이스 설정 모듈
- SQLAlchemy async 기반
- SQLite / PostgreSQL 교체 가능 (DATABASE_URL 환경변수만 변경)
"""

from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from backend.config import settings


_engine_kwargs = {}
_is_pg = "psycopg" in settings.database_url or "asyncpg" in settings.database_url
if _is_pg:
    _engine_kwargs.update(poolclass=NullPool)

engine = create_async_engine(
    settings.database_url,
    echo=False,
    **_engine_kwargs,
)

# Supabase pgbouncer: prepared statement 완전 비활성화
if "psycopg" in settings.database_url:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_prepare_threshold(dbapi_conn, connection_record):
        dbapi_conn.prepare_threshold = 0

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    """DB 테이블 생성 (앱 시작 시 호출)"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    """FastAPI Dependency Injection용 세션 제공"""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
