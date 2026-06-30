"""
Safety Manager - FastAPI 메인 애플리케이션
한전(KEPCO) 폭염 안전관리 시스템
"""

import os
import logging
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from sqlalchemy import select, func, case, and_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from backend.config import settings
from backend.models.database import init_db, async_session
from backend.models.models import SmsLog, SmsType, SmsFixedRecipient
from backend.routers import weather, alerts, workers, push, upload
from backend.dependencies import (
    get_weather_provider,
    get_notification_sender,
    get_threshold_manager,
    cleanup,
)
from backend.scheduler.monitor import HeatWaveMonitor
from backend.utils.masking import mask_phone

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


_tomorrow_forecast_cache = {}
_progress = {"task": "", "current": 0, "total": 0, "detail": ""}

LMS_COST = 30.0  # LMS 건당 비용 (원)


async def _log_sms(sms_type: str, details: list[dict], stage: str = "", message: str = ""):
    """SMS 발송 이력을 DB에 저장"""
    try:
        async with async_session() as session:
            for d in details:
                log = SmsLog(
                    sms_type=sms_type,
                    recipient_phone=d.get("phone", ""),
                    recipient_name=d.get("name", ""),
                    site_name=d.get("site", ""),
                    stage=stage,
                    message_preview=message[:100] if message else "",
                    full_message=message or "",
                    status=d.get("status", "failed"),
                    error_message=d.get("error"),
                    cost=LMS_COST if d.get("status") == "sent" else 0,
                    sent_at=datetime.now(),
                )
                session.add(log)
            await session.commit()
    except Exception as e:
        logger.error(f"[SMS Log] 이력 저장 실패: {e}")


def _mask_sms_result(result: dict) -> dict:
    """SMS 발송 결과의 details 내 전화번호를 마스킹하여 API 응답용으로 변환"""
    if "details" in result:
        for d in result["details"]:
            if "phone" in d:
                d["phone"] = mask_phone(d["phone"])
    return result


WORK_STOP_LINK = "https://www.kepco.co.kr/home/customer/safety/report/stop-work/guide.do"

SMS_STAGE_MESSAGES = {
    "stage_1_interest": (
        "[한국전력공사 경남본부]\n"
        "현재 #{현장주소} 공사현장의 체감온도가 31도 이상으로 "
        '폭염 "관심" 단계입니다.\n'
        "폭염이 시작되니 충분한 수분 섭취와 적절한 휴식을 취하세요!"
    ),
    "stage_2_caution": (
        "[한국전력공사 경남본부]\n"
        "현재 #{현장주소} 공사현장의 체감온도가 33도 이상으로 "
        '폭염 "주의보" 단계입니다.\n'
        "더위가 더욱 강해지니, 작업시간을 조정하시고 "
        "매 2시간 이내 20분 이상 휴식을 취하세요!"
    ),
    "stage_3_warning": (
        "[한국전력공사 경남본부]\n"
        "현재 #{현장주소} 공사현장의 체감온도가 35도 이상으로 "
        '폭염 "경보" 단계입니다.\n'
        "폭염 위험이 높습니다. 어지럼, 메스꺼움을 느끼면 "
        "작업을 멈추고 그늘로 가세요!\n"
        "작업중지권 사용을 망설이지 마세요!"
    ),
    "stage_4_danger": (
        "[한국전력공사 경남본부]\n"
        "현재 #{현장주소} 공사현장의 체감온도가 38도 이상으로 "
        '폭염 "중대경보" 단계입니다.\n'
        "폭염 최고 단계입니다. 무리는 곧 사고로 이어지니, "
        "재난 및 안전관리 등에 필요한 긴급조치 작업 외에는 "
        "야외작업을 중지하세요!"
    ),
}

SMS_FOOTER = f"\n\n☞ 작업중지 요청: {WORK_STOP_LINK}"


def _build_site_sms(stage_key: str, site_address: str, tomorrow_text: str = "") -> str:
    """현장 주소를 치환한 SMS 메시지 생성"""
    template = SMS_STAGE_MESSAGES.get(stage_key, "")
    msg = template.replace("#{현장주소}", site_address or "해당 현장")
    msg += SMS_FOOTER
    if tomorrow_text:
        msg += tomorrow_text
    return msg


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

        # DB 마이그레이션
        try:
            async with async_session() as session:
                from sqlalchemy import text
                # work_site_workers.role
                result = await session.execute(text("PRAGMA table_info(work_site_workers)"))
                columns = [row[1] for row in result.fetchall()]
                if "role" not in columns:
                    await session.execute(text("ALTER TABLE work_site_workers ADD COLUMN role VARCHAR(20) DEFAULT 'worker'"))
                    logger.info("DB 마이그레이션: work_site_workers.role 컬럼 추가")
                # sms_logs.full_message
                result = await session.execute(text("PRAGMA table_info(sms_logs)"))
                columns = [row[1] for row in result.fetchall()]
                if columns and "full_message" not in columns:
                    await session.execute(text("ALTER TABLE sms_logs ADD COLUMN full_message TEXT DEFAULT ''"))
                    logger.info("DB 마이그레이션: sms_logs.full_message 컬럼 추가")
                await session.commit()
        except Exception as e:
            logger.warning(f"DB 마이그레이션 확인/실행 중 오류 (무시): {e}")
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
            scheduled_tomorrow_forecast,
            "cron",
            hour="9",
            id="tomorrow_forecast",
            name="내일 예보 수집 (9시)",
        )
        scheduler.add_job(
            scheduled_auto_sms,
            "cron",
            hour="10",
            minute="0",
            id="auto_sms_morning",
            name="자동 SMS (10시)",
        )
        scheduler.add_job(
            scheduled_auto_sms,
            "cron",
            hour="14",
            minute="20",
            id="auto_sms_afternoon",
            name="자동 SMS (14시20분 — 14시 발표 날씨 반영)",
        )
        scheduler.add_job(
            scheduled_daily_reset,
            "cron",
            hour="17",
            id="daily_reset",
            name="사전신고 데이터 초기화 (17시)",
        )
        scheduler.start()
        logger.info(
            f"폭염 모니터링 스케줄러 시작 (간격: {settings.weather_check_interval_minutes}분)"
        )
        logger.info("스케줄 등록: 09:00 내일예보, 10:00/13:00 SMS, 17:00 데이터 초기화")

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


async def scheduled_tomorrow_forecast():
    """매일 09:00 — 현장별 내일 예보를 수집하여 캐시에 저장"""
    global _tomorrow_forecast_cache
    from backend.services.kma_provider import latlon_to_grid
    from backend.services.repository import WorkSiteRepository

    logger.info("[내일예보] 내일 예보 수집 시작")
    _tomorrow_forecast_cache = {}
    _progress.update(task="tomorrow_forecast", current=0, total=0, detail="현장 목록 조회 중...")

    try:
        weather_provider = get_weather_provider()
        async with async_session() as session:
            site_repo = WorkSiteRepository(session)
            sites = await site_repo.get_all_outdoor_active()
            _progress.update(total=len(sites), detail=f"{len(sites)}개 현장 예보 수집 시작")

            grid_done = {}
            for i, site in enumerate(sites):
                _progress.update(current=i + 1, detail=site.name)
                if site.latitude == 0 and site.longitude == 0:
                    continue
                nx, ny = latlon_to_grid(site.latitude, site.longitude)
                grid_key = f"{nx},{ny}"
                if grid_key in grid_done:
                    _tomorrow_forecast_cache[site.id] = grid_done[grid_key]
                    continue

                try:
                    forecast = await weather_provider.get_tomorrow_forecast(
                        site.latitude, site.longitude
                    )
                    grid_done[grid_key] = forecast
                    _tomorrow_forecast_cache[site.id] = forecast
                except Exception as e:
                    logger.warning(f"[내일예보] {site.name} 예보 실패: {e}")
                    grid_done[grid_key] = None

        success = sum(1 for v in _tomorrow_forecast_cache.values() if v)
        _progress.update(task="", current=0, total=0, detail="")
        logger.info(f"[내일예보] 수집 완료: {success}/{len(_tomorrow_forecast_cache)}건 성공")
    except Exception as e:
        _progress.update(task="", current=0, total=0, detail="")
        logger.error(f"[내일예보] 수집 실패: {e}")


def _build_tomorrow_text(forecast: dict | None) -> str:
    """내일 예보 캐시 → SMS 추가 문구 생성"""
    if not forecast:
        return ""
    date_str = forecast.get("date", "")
    if date_str and len(date_str) == 8:
        date_display = f"{date_str[4:6]}/{date_str[6:8]}"
    else:
        date_display = "내일"

    time_str = forecast.get("max_temp_time", "")
    if time_str and len(time_str) == 4:
        hour = time_str[:2]
        time_display = f"{hour}시경"
    else:
        time_display = ""

    apparent = forecast.get("max_apparent", 0)
    stage_name = forecast.get("stage_name")

    sky = forecast.get("sky", "")
    pty = forecast.get("pty")
    pop = forecast.get("max_pop", 0)

    if pty:
        weather_text = pty
    else:
        weather_text = sky

    if pop and pop >= 30:
        weather_text += f"(강수확률 {int(pop)}%)"

    line = f"\n\n[내일({date_display}) 예보]"
    line += f"\n날씨: {weather_text}"
    if stage_name:
        line += f"\n체감 {apparent}도({stage_name}) {time_display} 예상"
        line += "\n내일 작업 시 각별히 주의 바랍니다."
    else:
        line += f"\n최고 체감 {apparent}도 {time_display} 예상"
    line += "\n※ 예보 기반 참고 정보입니다."
    return line


async def scheduled_auto_sms():
    """오전 10시 / 오후 2시 20분 자동 SMS 발송 (폭염 단계별 메시지 + 내일 예보)
    동일 전화번호는 가장 높은 단계 메시지 1건만 발송 (중복제거)
    14:20 발송 = 기상청 14시 발표 데이터 반영 (발표 후 약 10~15분 소요)"""
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
    stage_order = ["stage_4_danger", "stage_3_warning", "stage_2_caution", "stage_1_interest"]

    # 자동발송 대상 설정 확인
    auto_target = await _get_system_setting("auto_sms_target", "all")
    target_label = "현장책임자만" if auto_target == "manager" else "작업자 전원"
    logger.info(f"[Auto SMS] 발송 대상: {target_label}")

    try:
        weather_provider = get_weather_provider()
        threshold_mgr = get_threshold_manager()

        sent_phones = set()

        async with async_session() as session:
            site_repo = WorkSiteRepository(session)
            sites = await site_repo.get_all_outdoor_active()
            logger.info(f"[Auto SMS] {len(sites)}개 현장 대상 자동 발송 시작")

            # 1단계: 현장별 폭염 단계 판정 + 작업자 수집
            site_stage_data = []
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
                    if stage_key not in SMS_STAGE_MESSAGES:
                        total_skipped += 1
                        continue

                    tomorrow = _tomorrow_forecast_cache.get(site.id)
                    tomorrow_text = _build_tomorrow_text(tomorrow)
                    full_message = _build_site_sms(stage_key, site.address, tomorrow_text)

                    # 대상 설정에 따라 작업자 필터링
                    if auto_target == "manager":
                        wr_list = await site_repo.get_workers_with_role(site.id)
                        workers_dicts = [
                            {"name": wr["worker"].name, "phone": wr["worker"].phone, "site": site.name}
                            for wr in wr_list if wr["worker"].phone and wr["role"] == "manager"
                        ]
                    else:
                        workers = await site_repo.get_workers(site.id)
                        workers_dicts = [
                            {"name": w.name, "phone": w.phone, "site": site.name}
                            for w in workers if w.phone
                        ]
                    if workers_dicts:
                        site_stage_data.append({
                            "site": site, "stage_key": stage_key, "stage_info": stage_info,
                            "message": full_message, "workers": workers_dicts,
                            "apparent_temp": apparent_temp,
                            "kma_base_time": weather.kma_base_time or "",
                        })
                    else:
                        total_skipped += 1
                except Exception as e:
                    logger.error(f"[Auto SMS] {site.name} 처리 실패: {e}")

            # 2단계: 높은 단계 우선으로 정렬
            site_stage_data.sort(key=lambda x: stage_order.index(x["stage_key"]) if x["stage_key"] in stage_order else 99)

            # 고정수신 멤버 로드
            fixed_recipients = (await session.execute(
                select(SmsFixedRecipient).where(SmsFixedRecipient.is_active == True)
            )).scalars().all()

            # 3단계: 현장별 발송 (전화번호 중복제거, 고정수신은 첫 발송에만 추가)
            fixed_added = False
            for sd in site_stage_data:
                sk = sd["stage_key"]
                # 현장별 전화번호 중복제거
                unique_workers = []
                for w in sd["workers"]:
                    phone_key = w["phone"].replace("-", "")
                    if phone_key not in sent_phones:
                        sent_phones.add(phone_key)
                        unique_workers.append(w)
                # 고정수신 멤버는 가장 높은 단계의 첫 현장에 1회만 포함
                if not fixed_added:
                    for fr in fixed_recipients:
                        pk = fr.phone.replace("-", "")
                        if pk not in sent_phones:
                            sent_phones.add(pk)
                            unique_workers.append({"name": fr.name, "phone": fr.phone, "site": f"[확인용] {fr.role}"})
                    fixed_added = True
                if not unique_workers:
                    continue
                phone_list = [w["phone"] for w in unique_workers]
                result = await sender.send_bulk(phone_list, sd["message"], workers=unique_workers)
                total_sent += result.get("sent", 0)
                total_failed += result.get("failed", 0)
                await _log_sms("auto", result.get("details", []), stage=sk, message=sd["message"])
                logger.info(
                    f"[Auto SMS] {sk} 단계 ({sd['site'].name}) → "
                    f"{result.get('sent', 0)}건 성공, "
                    f"{result.get('failed', 0)}건 실패"
                )

    except Exception as e:
        logger.error(f"[Auto SMS] 전체 자동 발송 실패: {e}")
    finally:
        await sender.close()

    logger.info(
        f"[Auto SMS] 완료: 성공 {total_sent}, 실패 {total_failed}, "
        f"건너뜀 {total_skipped}, 중복제거 후 총 {len(sent_phones)}명"
    )


async def scheduled_daily_reset():
    """매일 17시 사전신고 데이터 초기화 (당일 외 작업 데이터에 알림 발송 방지)"""
    from sqlalchemy import text
    try:
        async with async_session() as session:
            r1 = await session.execute(text("SELECT COUNT(*) FROM work_sites"))
            site_count = r1.scalar() or 0
            r2 = await session.execute(text("SELECT COUNT(*) FROM workers"))
            worker_count = r2.scalar() or 0

            if site_count == 0:
                logger.info("[17시 초기화] 데이터 없음 — 건너뜀")
                return

            await session.execute(text("DELETE FROM alert_logs"))
            await session.execute(text("DELETE FROM weather_logs"))
            await session.execute(text("DELETE FROM work_site_workers"))
            await session.execute(text("DELETE FROM workers"))
            await session.execute(text("DELETE FROM work_sites"))
            await session.commit()
            logger.info(f"[17시 초기화] 완료: {site_count}개 현장, {worker_count}명 작업자 삭제")
    except Exception as e:
        logger.error(f"[17시 초기화] 실패: {e}")


async def _get_system_setting(key: str, default: str = "") -> str:
    """시스템 설정값 조회"""
    from backend.models.models import SystemSetting
    try:
        async with async_session() as session:
            result = await session.execute(
                select(SystemSetting).where(SystemSetting.key == key)
            )
            row = result.scalar_one_or_none()
            return row.value if row else default
    except Exception:
        return default


async def _set_system_setting(key: str, value: str):
    """시스템 설정값 저장"""
    from backend.models.models import SystemSetting
    async with async_session() as session:
        result = await session.execute(
            select(SystemSetting).where(SystemSetting.key == key)
        )
        row = result.scalar_one_or_none()
        if row:
            row.value = value
        else:
            session.add(SystemSetting(key=key, value=value))
        await session.commit()


app = FastAPI(
    title="한국전력공사 경남본부 안전관리 시스템",
    description="폭염 안전관리 및 작업중지 알람 시스템",
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
    address: str = ""


class SmsRequest(BaseModel):
    message: str
    phone_numbers: list[str] = []  # ["010-1234-5678"] (하위 호환)
    workers: list[SmsWorker] = []  # [{name, phone, site}] (상세 결과용)
    site_ids: list[int] = []  # 현장 ID 목록 (DB에서 원본 번호 조회)
    target_role: str = "all"  # "all" | "manager"


@app.post("/api/sms/send")
async def send_sms(data: SmsRequest):
    """SMS 일괄 발송 (NHN Cloud SMS API) — 동일 전화번호 자동 중복제거, #{현장주소} 치환 지원"""
    from backend.services.alert_service import SmsSender
    from backend.services.repository import WorkSiteRepository
    sender = SmsSender()

    # site_ids가 전달되면 DB에서 원본 전화번호 조회 (마스킹 우회)
    if data.site_ids:
        workers_dicts = []
        async with async_session() as session:
            site_repo = WorkSiteRepository(session)
            for sid in data.site_ids:
                site = await site_repo.get_by_id(sid)
                if not site:
                    continue
                if data.target_role == "manager":
                    wr_list = await site_repo.get_workers_with_role(sid)
                    for wr in wr_list:
                        w = wr["worker"]
                        if w.phone and wr["role"] == "manager":
                            workers_dicts.append({"name": w.name, "phone": w.phone, "site": site.name, "address": site.address or ""})
                else:
                    ws = await site_repo.get_workers(sid)
                    for w in ws:
                        if w.phone:
                            workers_dicts.append({"name": w.name, "phone": w.phone, "site": site.name, "address": site.address or ""})
    else:
        workers_dicts = [w.model_dump() for w in data.workers] if data.workers else None

    # 전화번호 중복제거 (같은 번호가 여러 현장에 있을 수 있음)
    if workers_dicts:
        seen = set()
        unique_workers = []
        for w in workers_dicts:
            phone_key = w["phone"].replace("-", "")
            if phone_key not in seen:
                seen.add(phone_key)
                unique_workers.append(w)
        deduped_count = len(workers_dicts) - len(unique_workers)
        workers_dicts = unique_workers
        phone_numbers = [w["phone"] for w in unique_workers]
    else:
        seen = set()
        phone_numbers = []
        for p in data.phone_numbers:
            key = p.replace("-", "")
            if key not in seen:
                seen.add(key)
                phone_numbers.append(p)
        deduped_count = len(data.phone_numbers) - len(phone_numbers)

    try:
        # 고정수신 멤버 추가
        async with async_session() as session:
            fixed = (await session.execute(
                select(SmsFixedRecipient).where(SmsFixedRecipient.is_active == True)
            )).scalars().all()
        fixed_added = 0
        for fr in fixed:
            phone_key = fr.phone.replace("-", "")
            if phone_key not in seen:
                seen.add(phone_key)
                phone_numbers.append(fr.phone)
                if workers_dicts is not None:
                    workers_dicts.append({"name": fr.name, "phone": fr.phone, "site": f"[확인용] {fr.role}", "address": ""})
                fixed_added += 1

        # #{현장주소} 치환: 주소별 그룹핑 후 개별 발송
        has_address_var = "#{현장주소}" in data.message
        if has_address_var and workers_dicts:
            address_groups = {}
            for w in workers_dicts:
                addr = w.get("address", "") or ""
                if addr not in address_groups:
                    address_groups[addr] = []
                address_groups[addr].append(w)

            total_result = {"sent": 0, "failed": 0, "details": []}
            for addr, group_workers in address_groups.items():
                substituted_msg = data.message.replace("#{현장주소}", addr or "해당 현장")
                group_phones = [w["phone"] for w in group_workers]
                result = await sender.send_bulk(group_phones, substituted_msg, workers=group_workers)
                total_result["sent"] += result.get("sent", 0)
                total_result["failed"] += result.get("failed", 0)
                total_result["details"].extend(result.get("details", []))
                await _log_sms("real", result.get("details", []), message=substituted_msg)

            if deduped_count > 0:
                total_result["deduped"] = deduped_count
            if fixed_added > 0:
                total_result["fixed_added"] = fixed_added
            return _mask_sms_result(total_result)
        else:
            result = await sender.send_bulk(phone_numbers, data.message, workers=workers_dicts)
            if deduped_count > 0:
                result["deduped"] = deduped_count
            if fixed_added > 0:
                result["fixed_added"] = fixed_added
            await _log_sms("real", result.get("details", []), message=data.message)
            return _mask_sms_result(result)
    finally:
        await sender.close()


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
    is_mock: bool = True


@app.post("/api/sms/test")
async def sms_test(data: SmsTestRequest):
    """SMS 테스트 발송 (1건)"""
    from backend.services.alert_service import SmsSender
    sender = SmsSender()
    test_msg = data.message or "[한국전력공사 경남본부] SMS 테스트 발송입니다.\n본 메시지가 수신되면 SMS 연동이 정상입니다."
    try:
        result = await sender.send_bulk(
            [data.phone], test_msg,
            workers=[{"name": "테스트", "phone": data.phone, "site": "테스트"}],
        )
        sms_type = "mock" if data.is_mock else "real"
        await _log_sms(sms_type, result.get("details", []), message=test_msg)
        return _mask_sms_result(result)
    finally:
        await sender.close()


@app.get("/api/sms/auto-schedule")
async def sms_auto_schedule():
    """자동 SMS 발송 스케줄 및 단계별 메시지 조회"""
    configured = bool(settings.sms_app_key and settings.sms_secret_key and settings.sms_sender_phone)
    auto_target = await _get_system_setting("auto_sms_target", "all")
    return {
        "enabled": configured,
        "auto_target": auto_target,
        "schedule": ["09:00 내일예보 수집", "10:00 SMS 발송", "14:20 SMS 발송 (14시 날씨 반영)", "17:00 데이터 초기화"],
        "description": "매일 9시 내일 예보 수집 → 10시/14시20분 SMS 발송 → 17시 사전신고 데이터 초기화",
        "messages": {
            "관심 (31°C)": SMS_STAGE_MESSAGES["stage_1_interest"],
            "주의 (33°C)": SMS_STAGE_MESSAGES["stage_2_caution"],
            "경고 (35°C)": SMS_STAGE_MESSAGES["stage_3_warning"],
            "위험 (38°C)": SMS_STAGE_MESSAGES["stage_4_danger"],
        },
    }


@app.get("/api/sms/auto-target")
async def get_auto_target():
    """자동발송 대상 설정 조회"""
    target = await _get_system_setting("auto_sms_target", "all")
    return {"target": target}


class AutoTargetRequest(BaseModel):
    target: str  # "all" or "manager"


@app.post("/api/sms/auto-target")
async def set_auto_target(data: AutoTargetRequest):
    """자동발송 대상 설정 변경"""
    if data.target not in ("all", "manager"):
        return {"error": "올바르지 않은 대상입니다. 'all' 또는 'manager'만 가능합니다."}
    await _set_system_setting("auto_sms_target", data.target)
    label = "현장책임자만" if data.target == "manager" else "작업자 전원"
    logger.info(f"[설정 변경] 자동발송 대상: {label}")
    return {"target": data.target, "label": label}


@app.get("/api/sms/stats")
async def sms_stats(date: str = Query(default="", description="YYYY-MM-DD")):
    """SMS 발송 통계 (요약 + 날짜별 상세)"""
    async with async_session() as session:
        # 전체 요약
        summary_q = select(
            SmsLog.sms_type,
            SmsLog.status,
            func.count().label("count"),
            func.sum(SmsLog.cost).label("total_cost"),
        ).group_by(SmsLog.sms_type, SmsLog.status)
        summary_rows = (await session.execute(summary_q)).all()

        summary = {"mock": {"sent": 0, "failed": 0, "cost": 0}, "real": {"sent": 0, "failed": 0, "cost": 0}, "auto": {"sent": 0, "failed": 0, "cost": 0}}
        for sms_type, status, count, cost in summary_rows:
            key = sms_type.value if hasattr(sms_type, "value") else sms_type
            if key in summary:
                summary[key][status] = count
                if status == "sent":
                    summary[key]["cost"] = float(cost or 0)

        total_sent = sum(s["sent"] for s in summary.values())
        total_failed = sum(s["failed"] for s in summary.values())
        total_cost = sum(s["cost"] for s in summary.values())

        # 일별 집계
        daily_q = select(
            func.date(SmsLog.sent_at).label("day"),
            SmsLog.sms_type,
            SmsLog.status,
            func.count().label("count"),
            func.sum(SmsLog.cost).label("cost"),
        ).group_by(func.date(SmsLog.sent_at), SmsLog.sms_type, SmsLog.status).order_by(func.date(SmsLog.sent_at).desc())
        daily_rows = (await session.execute(daily_q)).all()

        daily = {}
        for day, sms_type, status, count, cost in daily_rows:
            d = str(day)
            if d not in daily:
                daily[d] = {"date": d, "mock_sent": 0, "mock_failed": 0, "real_sent": 0, "real_failed": 0, "auto_sent": 0, "auto_failed": 0, "cost": 0}
            key = sms_type.value if hasattr(sms_type, "value") else sms_type
            daily[d][f"{key}_{status}"] = count
            if status == "sent":
                daily[d]["cost"] += float(cost or 0)

        # 특정 날짜 상세 이력
        detail_list = []
        if date:
            detail_q = select(SmsLog).where(
                func.date(SmsLog.sent_at) == date
            ).order_by(SmsLog.sent_at.desc())
            detail_rows = (await session.execute(detail_q)).scalars().all()
            for r in detail_rows:
                detail_list.append({
                    "id": r.id,
                    "type": r.sms_type.value if hasattr(r.sms_type, "value") else r.sms_type,
                    "phone": mask_phone(r.recipient_phone),
                    "name": r.recipient_name,
                    "site": r.site_name,
                    "stage": r.stage,
                    "status": r.status,
                    "error": r.error_message,
                    "cost": r.cost,
                    "sent_at": r.sent_at.strftime("%H:%M:%S") if r.sent_at else "",
                })

        return {
            "summary": summary,
            "total": {"sent": total_sent, "failed": total_failed, "cost": total_cost},
            "daily": list(daily.values()),
            "details": detail_list,
        }


@app.get("/api/sms/today-content")
async def sms_today_content():
    """오늘 발송된 SMS 내용 조회 (고유 메시지만)"""
    today = datetime.now().strftime("%Y-%m-%d")
    async with async_session() as session:
        q = select(
            SmsLog.full_message,
            SmsLog.sms_type,
            SmsLog.stage,
            func.min(SmsLog.sent_at).label("first_sent"),
            func.count().label("count"),
        ).where(
            and_(
                func.date(SmsLog.sent_at) == today,
                SmsLog.status == "sent",
                SmsLog.full_message != "",
            )
        ).group_by(SmsLog.full_message, SmsLog.sms_type, SmsLog.stage).order_by(func.min(SmsLog.sent_at).desc())
        rows = (await session.execute(q)).all()

        messages = []
        for full_message, sms_type, stage, first_sent, count in rows:
            messages.append({
                "message": full_message,
                "type": sms_type.value if hasattr(sms_type, "value") else sms_type,
                "stage": stage,
                "sent_at": first_sent.strftime("%H:%M") if first_sent else "",
                "count": count,
            })

    return {"date": today, "messages": messages}


# ── SMS 고정수신 멤버 ──

class FixedRecipientRequest(BaseModel):
    name: str
    phone: str
    role: str = ""


@app.get("/api/sms/fixed-recipients")
async def get_fixed_recipients():
    """SMS 고정수신 멤버 목록 조회"""
    async with async_session() as session:
        rows = (await session.execute(
            select(SmsFixedRecipient).where(SmsFixedRecipient.is_active == True).order_by(SmsFixedRecipient.id)
        )).scalars().all()
        return [{"id": r.id, "name": r.name, "phone": mask_phone(r.phone), "role": r.role} for r in rows]


@app.post("/api/sms/fixed-recipients")
async def add_fixed_recipient(data: FixedRecipientRequest):
    """SMS 고정수신 멤버 추가"""
    import re
    phone = re.sub(r"[^0-9]", "", data.phone)
    if len(phone) != 11 or not phone.startswith("01"):
        return {"error": "올바른 전화번호 형식이 아닙니다."}
    formatted = f"{phone[:3]}-{phone[3:7]}-{phone[7:]}"

    async with async_session() as session:
        existing = (await session.execute(
            select(SmsFixedRecipient).where(
                and_(SmsFixedRecipient.phone == formatted, SmsFixedRecipient.is_active == True)
            )
        )).scalar_one_or_none()
        if existing:
            return {"error": f"{formatted} 은(는) 이미 등록되어 있습니다."}

        recipient = SmsFixedRecipient(name=data.name, phone=formatted, role=data.role)
        session.add(recipient)
        await session.commit()
        return {"id": recipient.id, "name": recipient.name, "phone": mask_phone(formatted), "role": recipient.role}


@app.delete("/api/sms/fixed-recipients/{recipient_id}")
async def delete_fixed_recipient(recipient_id: int):
    """SMS 고정수신 멤버 삭제"""
    async with async_session() as session:
        r = (await session.execute(
            select(SmsFixedRecipient).where(SmsFixedRecipient.id == recipient_id)
        )).scalar_one_or_none()
        if not r:
            return {"error": "해당 멤버를 찾을 수 없습니다."}
        r.is_active = False
        await session.commit()
        return {"deleted": True}


@app.get("/api/weather/tomorrow")
async def get_tomorrow_forecast_api():
    """내일 예보 캐시 조회 (09:00에 자동 수집된 데이터)"""
    if not _tomorrow_forecast_cache:
        return {"cached": False, "message": "내일 예보가 아직 수집되지 않았습니다. 매일 09:00에 자동 수집됩니다.", "forecasts": {}}

    result = {}
    for site_id, forecast in _tomorrow_forecast_cache.items():
        if forecast:
            result[site_id] = {
                "date": forecast.get("date"),
                "max_apparent": forecast.get("max_apparent"),
                "max_temp": forecast.get("max_temp"),
                "max_temp_time": forecast.get("max_temp_time"),
                "max_pop": forecast.get("max_pop"),
                "sky": forecast.get("sky"),
                "pty": forecast.get("pty"),
                "stage_name": forecast.get("stage_name"),
                "sms_preview": _build_tomorrow_text(forecast),
            }
    return {"cached": True, "count": len(result), "forecasts": result}


@app.post("/api/weather/tomorrow/collect")
async def collect_tomorrow_forecast_now():
    """내일 예보 수동 수집 (테스트용)"""
    await scheduled_tomorrow_forecast()
    count = sum(1 for v in _tomorrow_forecast_cache.values() if v)
    return {"message": f"내일 예보 수집 완료: {count}건", "count": count}


@app.get("/api/progress")
async def get_progress():
    """현재 진행 중인 작업의 진행률 조회"""
    if not _progress["task"]:
        return {"active": False}
    pct = 0
    if _progress["total"] > 0:
        pct = round(_progress["current"] / _progress["total"] * 100)
    return {
        "active": True,
        "task": _progress["task"],
        "current": _progress["current"],
        "total": _progress["total"],
        "percent": pct,
        "detail": _progress["detail"],
    }


