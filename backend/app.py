"""
Safety Manager - FastAPI 메인 애플리케이션
한전(KEPCO) 폭염 안전관리 시스템
"""

import os
import logging
from datetime import datetime
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


SMS_STAGE_MESSAGES = {
    "stage_1_interest": (
        '[체감온도 31도 이상, 폭염 "관심" 단계]\n'
        "폭염 시작입니다.\n"
        "충분한 수분 섭취와\n"
        "적절한 휴식을 취하세요!"
    ),
    "stage_2_caution": (
        "[체감온도 33도 이상, 폭염주의보]\n"
        "더위가 더욱 강해집니다.\n"
        "작업시간을 조정하시고,\n"
        "매 2시간 이내 20분 이상 휴식을 취하세요!"
    ),
    "stage_3_warning": (
        "[체감온도 35도 이상, 폭염경보]\n"
        "폭염 위험이 높습니다.\n"
        "어지럼, 메스꺼움을 느끼면 즉시 작업을 멈추고 그늘로 가세요!\n"
        "작업중지권 사용을 망설이지 마세요!"
    ),
    "stage_4_danger": (
        "[체감온도 38도 이상, 폭염중대경보]\n"
        "폭염 최고 단계입니다.\n"
        "무리는 곧 사고!\n"
        "재난 및 안전관리 등에 필요한 긴급조치 작업 외에는\n"
        "야외작업을 중지하세요!"
    ),
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 생명주기 관리"""
    # .html 파일 자동 복원 (사내 보안 소프트웨어가 .html 삭제 시 .dat 백업에서 복원)
    import shutil
    restored = 0
    for dat_file in FRONTEND_DIR.glob("*.dat"):
        html_file = dat_file.with_suffix(".html")
        if not html_file.exists():
            shutil.copy2(dat_file, html_file)
            restored += 1
            logger.info(f"HTML 복원: {dat_file.name} -> {html_file.name}")
    if restored:
        logger.info(f"보안 삭제된 HTML 파일 {restored}개 자동 복원 완료")

    logger.info("Safety Manager 시작")
    try:
        await init_db()
        logger.info(f"DB 연결 성공: {settings.database_url[:40]}...")
    except Exception as e:
        logger.error(f"DB 연결 실패: {e}")
        if "asyncpg" in settings.database_url:
            logger.warning("PostgreSQL 실패 → SQLite 폴백")
            from backend.models.database import Base
            from sqlalchemy.ext.asyncio import create_async_engine
            from backend.models import database
            fallback_url = "sqlite+aiosqlite:////tmp/safety_manager.db" if IS_VERCEL else "sqlite+aiosqlite:///./safety_manager.db"
            database.engine = create_async_engine(fallback_url, echo=False)
            database.async_session = async_sessionmaker(database.engine, class_=AsyncSession, expire_on_commit=False)
            async with database.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

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
        scheduler.add_job(
            scheduled_auto_sms,
            "cron",
            hour="10,13",
            id="auto_sms",
            name="자동 SMS (10시/13시)",
        )
        scheduler.start()
        logger.info(
            f"폭염 모니터링 스케줄러 시작 (간격: {settings.weather_check_interval_minutes}분)"
        )
        logger.info("자동 SMS 스케줄 등록: 매일 10:00, 13:00")

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


async def scheduled_auto_sms():
    """오전 10시 / 오후 1시 자동 SMS 발송 (폭염 단계별 메시지)"""
    from backend.services.alert_service import SmsSender
    from backend.services.repository import WorkSiteRepository
    from backend.services.weather_service import HeatIndexCalculator

    sender = SmsSender()
    if not sender._app_key or not sender._secret_key:
        logger.info("[Auto SMS] SMS 미설정 — 자동발송 건너뜀")
        return

    total_sent = 0
    total_failed = 0
    total_skipped = 0

    try:
        weather_provider = get_weather_provider()
        threshold_mgr = get_threshold_manager()

        async with async_session() as session:
            site_repo = WorkSiteRepository(session)
            sites = await site_repo.get_all_outdoor_active()
            logger.info(f"[Auto SMS] {len(sites)}개 현장 대상 자동 발송 시작")

            for site in sites:
                try:
                    weather = await weather_provider.get_current_weather(
                        site.latitude, site.longitude
                    )
                    apparent_temp = HeatIndexCalculator.calculate_heat_index(
                        weather.temperature, weather.humidity
                    )
                    stage_info = threshold_mgr.determine_stage(apparent_temp)
                    if not stage_info:
                        total_skipped += 1
                        continue

                    stage_key = stage_info["key"]
                    message = SMS_STAGE_MESSAGES.get(stage_key)
                    if not message:
                        total_skipped += 1
                        continue

                    workers = await site_repo.get_workers(site.id)
                    workers_dicts = [
                        {"name": w.name, "phone": w.phone, "site": site.name}
                        for w in workers if w.phone
                    ]
                    if not workers_dicts:
                        total_skipped += 1
                        continue

                    phone_list = [w["phone"] for w in workers_dicts]
                    result = await sender.send_bulk(
                        phone_list, message, workers=workers_dicts
                    )
                    total_sent += result.get("sent", 0)
                    total_failed += result.get("failed", 0)
                    logger.info(
                        f"[Auto SMS] {site.name} ({stage_info['name']}, "
                        f"체감 {apparent_temp}°C) → "
                        f"{result.get('sent', 0)}건 성공, "
                        f"{result.get('failed', 0)}건 실패"
                    )
                except Exception as e:
                    logger.error(f"[Auto SMS] {site.name} 처리 실패: {e}")

    except Exception as e:
        logger.error(f"[Auto SMS] 전체 자동 발송 실패: {e}")
    finally:
        await sender.close()

    logger.info(
        f"[Auto SMS] 완료: 성공 {total_sent}, 실패 {total_failed}, "
        f"건너뜀 {total_skipped}"
    )


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


@app.get("/api/branch-offices")
async def get_branch_offices():
    """등록된 사업소 목록 반환"""
    from backend.models.database import async_session as get_session
    from backend.models.models import WorkSite
    from sqlalchemy import select, distinct

    async with get_session() as session:
        result = await session.execute(
            select(distinct(WorkSite.branch_office)).where(
                WorkSite.branch_office.isnot(None),
                WorkSite.branch_office != "",
                WorkSite.is_active == True,
            )
        )
        offices = [row[0] for row in result.all()]
    return {"offices": sorted(offices), "total": len(offices)}


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


class SmsWorker(BaseModel):
    name: str = ""
    phone: str
    site: str = ""


class SmsRequest(BaseModel):
    message: str
    phone_numbers: list[str] = []  # ["010-1234-5678"] (하위 호환)
    workers: list[SmsWorker] = []  # [{name, phone, site}] (상세 결과용)


@app.post("/api/sms/send")
async def send_sms(data: SmsRequest):
    """SMS 일괄 발송 (NHN Cloud SMS API)"""
    from backend.services.alert_service import SmsSender
    sender = SmsSender()
    workers_dicts = [w.model_dump() for w in data.workers] if data.workers else None
    result = await sender.send_bulk(data.phone_numbers, data.message, workers=workers_dicts)
    return result


@app.get("/api/sms/status")
async def sms_status():
    """NHN Cloud SMS 설정 상태 확인"""
    configured = bool(settings.sms_app_key and settings.sms_secret_key and settings.sms_sender_phone)
    return {
        "configured": configured,
        "sender_phone": settings.sms_sender_phone if settings.sms_sender_phone else "",
        "app_key_preview": settings.sms_app_key[:4] + "****" if settings.sms_app_key else "",
        "message": "NHN Cloud SMS 설정 완료" if configured else "SMS_APP_KEY, SMS_SECRET_KEY, SMS_SENDER_PHONE 설정 필요",
    }


class SmsTestRequest(BaseModel):
    phone: str
    message: str = ""


@app.post("/api/sms/test")
async def sms_test(data: SmsTestRequest):
    """SMS 테스트 발송 (1건)"""
    from backend.services.alert_service import SmsSender
    sender = SmsSender()
    test_msg = data.message or "[KEPCO 안전관리] SMS 테스트 발송입니다.\n본 메시지가 수신되면 SMS 연동이 정상입니다."
    try:
        result = await sender.send_bulk(
            [data.phone], test_msg,
            workers=[{"name": "테스트", "phone": data.phone, "site": "테스트"}],
        )
        return result
    finally:
        await sender.close()


@app.get("/api/sms/auto-schedule")
async def sms_auto_schedule():
    """자동 SMS 발송 스케줄 및 단계별 메시지 조회"""
    configured = bool(settings.sms_app_key and settings.sms_secret_key and settings.sms_sender_phone)
    return {
        "enabled": configured,
        "schedule": ["10:00", "13:00"],
        "description": "매일 오전 10시, 오후 1시 폭염 단계별 자동 SMS 발송",
        "messages": {
            "관심 (31°C)": SMS_STAGE_MESSAGES["stage_1_interest"],
            "주의 (33°C)": SMS_STAGE_MESSAGES["stage_2_caution"],
            "경고 (35°C)": SMS_STAGE_MESSAGES["stage_3_warning"],
            "위험 (38°C)": SMS_STAGE_MESSAGES["stage_4_danger"],
        },
    }


