"""
Safety Manager - FastAPI 메인 애플리케이션
한전(KEPCO) 폭염 안전관리 시스템
"""

import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from backend.config import settings
from backend.models.database import init_db, async_session
from backend.routers import weather, alerts, workers, push, upload
from backend.dependencies import (
    get_weather_provider,
    get_notification_sender,
    get_threshold_manager,
    cleanup,
)
from backend.scheduler.monitor import HeatWaveMonitor

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 프로젝트 루트 경로 (Vercel / 로컬 모두 대응)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"

# Vercel 환경 감지
IS_VERCEL = bool(os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 생명주기 관리"""
    logger.info("Safety Manager 시작")
    try:
        await init_db()
        logger.info(f"데이터베이스 초기화 완료 (URL: {settings.database_url[:30]}...)")
    except Exception as e:
        logger.error(f"DB 연결 실패: {e}")
        # PostgreSQL 실패 시 SQLite 폴백
        if "asyncpg" in settings.database_url:
            logger.warning("PostgreSQL 연결 실패 → SQLite 폴백")
            from backend.models.database import engine, Base
            import sqlalchemy
            fallback_url = "sqlite+aiosqlite:////tmp/safety_manager.db" if IS_VERCEL else "sqlite+aiosqlite:///./safety_manager.db"
            from sqlalchemy.ext.asyncio import create_async_engine
            from backend.models import database
            database.engine = create_async_engine(fallback_url, echo=False)
            database.async_session = async_sessionmaker(database.engine, class_=AsyncSession, expire_on_commit=False)
            async with database.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("SQLite 폴백 완료")

    try:
        from backend.services.vapid_manager import init_vapid_keys_from_db
        await init_vapid_keys_from_db()
    except Exception as e:
        logger.error(f"VAPID 키 초기화 실패: {e}")

    # 스케줄러는 Vercel(서버리스)에서는 실행하지 않음
    scheduler = None
    if not IS_VERCEL:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
        scheduler.add_job(
            scheduled_monitoring,
            "interval",
            minutes=settings.weather_check_interval_minutes,
            id="heat_wave_monitor",
            name="폭염 모니터링",
        )
        scheduler.start()
        logger.info(
            f"폭염 모니터링 스케줄러 시작 (간격: {settings.weather_check_interval_minutes}분)"
        )

    yield

    if scheduler:
        scheduler.shutdown()
    await cleanup()
    logger.info("Safety Manager 종료")


async def scheduled_monitoring():
    """스케줄러에서 호출되는 모니터링 작업"""
    monitor = HeatWaveMonitor(
        weather_provider=get_weather_provider(),
        notification_sender=get_notification_sender(),
        threshold_manager=get_threshold_manager(),
    )
    async with async_session() as session:
        result = await monitor.check_all_sites(session)
        logger.info(f"정기 모니터링 결과: {result}")


app = FastAPI(
    title="KEPCO 안전관리 시스템",
    description="한전 폭염 안전관리 및 작업중지 알람 시스템",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 서빙
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# 라우터 등록
app.include_router(weather.router)
app.include_router(alerts.router)
app.include_router(workers.router)
app.include_router(push.router)
app.include_router(upload.router)


def _file(name: str):
    return FileResponse(str(FRONTEND_DIR / name))


@app.get("/")
async def root():
    return _file("index.html")


@app.get("/worker")
async def worker_index():
    """작업자 앱 - site_id 없이 접속 시 안내 페이지"""
    return _file("worker.html")


@app.get("/worker/{site_id}")
async def worker_page(site_id: int):
    return _file("worker.html")


@app.get("/sw.js")
async def service_worker():
    return FileResponse(str(FRONTEND_DIR / "sw.js"), media_type="application/javascript")


@app.get("/install")
async def install_guide():
    return _file("install-guide.html")


@app.get("/manual")
async def manual():
    return _file("manual.html")


@app.get("/guide")
async def user_guide():
    return _file("user-guide.html")


@app.get("/debug/db")
async def debug_db():
    """DB 연결 디버깅"""
    import os
    pg_url = os.environ.get("POSTGRES_URL", "(not set)")
    resolved = settings.database_url
    # 비밀번호 마스킹
    import re
    pg_masked = re.sub(r':([^@]+)@', ':***@', pg_url)
    resolved_masked = re.sub(r':([^@]+)@', ':***@', resolved)

    # 실제 연결 테스트
    from backend.models import database
    try:
        async with database.engine.begin() as conn:
            from sqlalchemy import text
            result = await conn.execute(text("SELECT 1"))
            db_ok = True
    except Exception as e:
        db_ok = str(e)[:200]

    return {
        "env_POSTGRES_URL": pg_masked[:80],
        "resolved_url": resolved_masked[:80],
        "connection_test": db_ok,
    }


@app.get("/health")
async def health_check():
    from backend.models import database
    actual_url = str(database.engine.url)
    db_type = "postgresql" if "asyncpg" in actual_url else "sqlite"
    return {
        "status": "healthy",
        "environment": settings.app_env,
        "is_vercel": IS_VERCEL,
        "db_type": db_type,
        "db_persistent": "tmp" not in actual_url,
        "db_url_prefix": actual_url[:50],
    }


@app.post("/api/reset")
async def reset_all_data():
    """모든 데이터 초기화 (작업현장, 작업자, 날씨기록, 알림이력)"""
    from sqlalchemy import text
    async with async_session() as session:
        # 외래키 순서에 맞게 삭제
        await session.execute(text("DELETE FROM alert_logs"))
        await session.execute(text("DELETE FROM weather_logs"))
        await session.execute(text("DELETE FROM work_site_workers"))
        await session.execute(text("DELETE FROM workers"))
        await session.execute(text("DELETE FROM work_sites"))
        await session.commit()
    return {"message": "모든 데이터가 초기화되었습니다."}


@app.post("/api/monitor/trigger")
async def trigger_monitoring(site_ids: list[int] | None = None):
    """수동 알림 발송 - 이미 조회된 날씨 기준 (날씨 재조회 안 함)"""
    monitor = HeatWaveMonitor(
        weather_provider=get_weather_provider(),
        notification_sender=get_notification_sender(),
        threshold_manager=get_threshold_manager(),
    )
    async with async_session() as session:
        result = await monitor.check_all_sites(
            session, site_ids=site_ids, use_cached_weather=True
        )
    return result


@app.post("/api/monitor/simulate")
async def simulate_heat_wave(
    temperature: float = 36.0,
    humidity: float = 70.0,
):
    """
    혹서기 시뮬레이션 - 가상 온도로 폭염 알림 테스트.
    체감온도 기준: 33° 관심, 35° 주의, 38° 경고, 41° 위험
    예시: /api/monitor/simulate?temperature=39&humidity=75
    """
    from backend.services.interfaces import WeatherResult, WeatherProvider

    class SimulatedWeather(WeatherProvider):
        def __init__(self, temp, hum):
            self.temp = temp
            self.hum = hum

        async def get_current_weather(self, lat, lon):
            return WeatherResult(
                temperature=self.temp,
                humidity=self.hum,
                wind_speed=1.5,
                apparent_temperature=self.temp,
                provider="simulation",
            )

        async def close(self):
            pass

    monitor = HeatWaveMonitor(
        weather_provider=SimulatedWeather(temperature, humidity),
        notification_sender=get_notification_sender(),
        threshold_manager=get_threshold_manager(),
    )
    async with async_session() as session:
        result = await monitor.check_all_sites(session)

    return {
        "simulation": True,
        "simulated_temperature": temperature,
        "simulated_humidity": humidity,
        **result,
    }


class NoticeRequest(BaseModel):
    title: str
    message: str
    site_ids: list[int] | None = None  # None이면 전체 현장


@app.post("/api/notice/send")
async def send_notice(data: NoticeRequest):
    """관리자 → 작업자 공지사항 푸시 발송"""
    from backend.services.push_service import WebPushSender
    sender = get_notification_sender()
    if not isinstance(sender, WebPushSender):
        return {"success": False, "error": "웹 푸시 채널만 지원"}

    total_sent = 0
    total_failed = 0
    sites_targeted = 0

    if data.site_ids:
        # 선택 현장만
        for sid in data.site_ids:
            subs = await sender._get_worker_subscriptions(sid)
            if subs:
                sites_targeted += 1
                payload = {
                    "title": data.title,
                    "body": data.message,
                    "icon": "/static/icons/icon-192.svg",
                    "badge": "/static/icons/badge-72.svg",
                    "tag": "notice",
                    "data": {
                        "type": "notice",
                        "url": f"/worker/{sid}",
                    },
                }
                s, f = await sender._send_to_subscriptions(subs, payload)
                total_sent += s
                total_failed += f
    else:
        # 전체 worker 구독자
        from backend.models.database import async_session as get_session
        from backend.models.models import PushSubscription
        from sqlalchemy import select

        async with get_session() as session:
            result = await session.execute(
                select(PushSubscription).where(PushSubscription.subscriber_type == "worker")
            )
            all_subs = sender._parse_subscriptions(result.scalars().all())

        if all_subs:
            sites_targeted = -1  # 전체
            payload = {
                "title": data.title,
                "body": data.message,
                "icon": "/static/icons/icon-192.svg",
                "badge": "/static/icons/badge-72.svg",
                "tag": "notice",
                "data": {
                    "type": "notice",
                    "url": "/",
                },
            }
            s, f = await sender._send_to_subscriptions(all_subs, payload)
            total_sent = s
            total_failed = f

    return {
        "success": total_sent > 0,
        "sent": total_sent,
        "failed": total_failed,
        "sites_targeted": sites_targeted,
    }
