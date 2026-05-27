"""
Safety Manager - FastAPI 메인 애플리케이션
한전(KEPCO) 폭염 안전관리 시스템
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.config import settings
from backend.models.database import init_db, async_session
from backend.routers import weather, alerts, workers, push
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

scheduler = AsyncIOScheduler(timezone="Asia/Seoul")


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 생명주기 관리"""
    # Startup
    logger.info("Safety Manager 시작")
    await init_db()
    logger.info("데이터베이스 초기화 완료")

    # 스케줄러 시작 (15분 간격 모니터링)
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

    # Shutdown
    scheduler.shutdown()
    await cleanup()
    logger.info("Safety Manager 종료")


app = FastAPI(
    title="KEPCO 안전관리 시스템",
    description="한전 폭염 안전관리 및 작업중지 알람 시스템",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 설정 (사내망 이관 시 origins 제한)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 운영 시 특정 도메인으로 제한
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 서빙 (프론트엔드)
app.mount("/static", StaticFiles(directory="frontend"), name="static")

# 라우터 등록
app.include_router(weather.router)
app.include_router(alerts.router)
app.include_router(workers.router)
app.include_router(push.router)


@app.get("/")
async def root():
    """메인 대시보드 페이지"""
    return FileResponse("frontend/index.html")


@app.get("/sw.js")
async def service_worker():
    """Service Worker는 루트 경로에서 서빙해야 스코프가 전체 적용됨"""
    return FileResponse("frontend/sw.js", media_type="application/javascript")


@app.get("/install")
async def install_guide():
    """앱 설치 안내 페이지 (QR코드 포함 - 현장 게시/배포용)"""
    return FileResponse("frontend/install-guide.html")


@app.get("/manual")
async def manual():
    """개발/관리자용 매뉴얼"""
    return FileResponse("frontend/manual.html")


@app.get("/guide")
async def user_guide():
    """사용자(안전담당자)용 매뉴얼"""
    return FileResponse("frontend/user-guide.html")


@app.get("/health")
async def health_check():
    """헬스 체크"""
    return {
        "status": "healthy",
        "environment": settings.app_env,
        "monitoring_interval": f"{settings.weather_check_interval_minutes}분",
    }


@app.post("/api/monitor/trigger")
async def trigger_monitoring():
    """수동 모니터링 트리거 (관리자용)"""
    monitor = HeatWaveMonitor(
        weather_provider=get_weather_provider(),
        notification_sender=get_notification_sender(),
        threshold_manager=get_threshold_manager(),
    )
    async with async_session() as session:
        result = await monitor.check_all_sites(session)
    return result
