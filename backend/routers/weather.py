"""
날씨 & 폭염 단계 API 라우터
"""

from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.database import get_db
from backend.models.models import WorkIntensity
from backend.models.schemas import WeatherStatusResponse, WeatherData, HeatStageInfo
from backend.services.repository import WorkSiteRepository, WeatherLogRepository, AlertLogRepository
from backend.services.weather_service import (
    HeatIndexCalculator,
    ThresholdManager,
)
from backend.dependencies import get_weather_provider

router = APIRouter(prefix="/api/weather", tags=["날씨"])

threshold_mgr = ThresholdManager()


@router.get("/status/{site_id}", response_model=WeatherStatusResponse)
async def get_weather_status(
    site_id: int,
    db: AsyncSession = Depends(get_db),
    weather_provider=Depends(get_weather_provider),
):
    """특정 작업현장의 현재 날씨 및 폭염 단계 조회"""
    site_repo = WorkSiteRepository(db)
    site = await site_repo.get_by_id(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="작업현장을 찾을 수 없습니다.")

    weather = await weather_provider.get_current_weather(site.latitude, site.longitude)

    apparent_temp = HeatIndexCalculator.calculate_heat_index(
        weather.temperature, weather.humidity
    )
    wbgt = HeatIndexCalculator.estimate_wbgt_outdoor(
        weather.temperature, weather.humidity, weather.wind_speed
    )

    stage_info = threshold_mgr.determine_stage(apparent_temp)

    # 날씨 기록 저장
    log_repo = WeatherLogRepository(db)
    await log_repo.create(
        work_site_id=site.id,
        temperature=weather.temperature,
        humidity=weather.humidity,
        wind_speed=weather.wind_speed,
        apparent_temperature=apparent_temp,
        wbgt_estimated=wbgt,
        stage=stage_info["key"] if stage_info else None,
    )

    # WBGT 기반 권고사항
    wbgt_rec = threshold_mgr.get_wbgt_recommendation(
        wbgt, site.work_intensity.value if isinstance(site.work_intensity, WorkIntensity) else site.work_intensity
    )

    stage_response = None
    if stage_info:
        stage_response = HeatStageInfo(
            stage_key=stage_info["key"],
            stage_name=stage_info["name"],
            color=stage_info["color"],
            actions=stage_info["actions"],
            rest_guideline=stage_info["rest_guideline"],
            work_restriction=stage_info["work_restriction"],
        )

    return WeatherStatusResponse(
        work_site_id=site.id,
        work_site_name=site.name,
        weather=WeatherData(
            temperature=weather.temperature,
            humidity=weather.humidity,
            wind_speed=weather.wind_speed,
            apparent_temperature=apparent_temp,
            wbgt_estimated=wbgt,
        ),
        stage=stage_response,
        wbgt_work_recommendation=wbgt_rec,
        checked_at=datetime.now(KST),
    )


@router.get("/status-all")
async def get_all_weather_status(
    db: AsyncSession = Depends(get_db),
    weather_provider=Depends(get_weather_provider),
):
    """모든 활성 옥외 작업현장의 날씨를 한 번에 조회"""
    site_repo = WorkSiteRepository(db)
    sites = await site_repo.get_all_outdoor_active()

    results = []
    for site in sites:
        try:
            weather = await weather_provider.get_current_weather(
                site.latitude, site.longitude
            )
            apparent_temp = HeatIndexCalculator.calculate_heat_index(
                weather.temperature, weather.humidity
            )
            wbgt = HeatIndexCalculator.estimate_wbgt_outdoor(
                weather.temperature, weather.humidity, weather.wind_speed
            )
            stage_info = threshold_mgr.determine_stage(apparent_temp)
            intensity = (
                site.work_intensity.value
                if isinstance(site.work_intensity, WorkIntensity)
                else site.work_intensity
            )
            wbgt_rec = threshold_mgr.get_wbgt_recommendation(wbgt, intensity)

            # 현장에 배정된 작업자 조회
            workers = await site_repo.get_workers(site.id)
            worker_ids = [w.id for w in workers]

            # 작업자별 최근 알림 발송 상태 조회
            alert_repo = AlertLogRepository(db)
            latest_alerts = await alert_repo.get_latest_by_site_workers(site.id, worker_ids)

            worker_list = []
            for w in workers:
                wdata = {"id": w.id, "name": w.name, "phone": w.phone, "is_vulnerable": w.is_vulnerable}
                alert = latest_alerts.get(w.id)
                if alert:
                    wdata["last_alert"] = {
                        "stage": alert.stage.value if alert.stage else None,
                        "status": alert.status.value if alert.status else None,
                        "channel": alert.channel,
                        "sent_at": alert.sent_at.isoformat(),
                        "temperature": alert.apparent_temperature,
                    }
                else:
                    wdata["last_alert"] = None
                worker_list.append(wdata)

            results.append({
                "site_id": site.id,
                "site_name": site.name,
                "address": site.address or "",
                "latitude": site.latitude,
                "longitude": site.longitude,
                "work_intensity": intensity,
                "workers": worker_list,
                "worker_count": len(worker_list),
                "weather": {
                    "temperature": weather.temperature,
                    "humidity": weather.humidity,
                    "wind_speed": weather.wind_speed,
                    "apparent_temperature": apparent_temp,
                    "wbgt_estimated": wbgt,
                },
                "stage": {
                    "key": stage_info["key"],
                    "name": stage_info["name"],
                    "color": stage_info["color"],
                    "actions": stage_info["actions"],
                    "rest_guideline": stage_info["rest_guideline"],
                    "work_restriction": stage_info["work_restriction"],
                } if stage_info else None,
                "wbgt_recommendation": wbgt_rec,
                "checked_at": datetime.now(KST).isoformat(),
            })
        except Exception as e:
            results.append({
                "site_id": site.id,
                "site_name": site.name,
                "address": site.address or "",
                "error": str(e),
            })

    # 위험도 높은 순으로 정렬
    stage_order = {
        "stage_4_danger": 0, "stage_3_warning": 1,
        "stage_2_caution": 2, "stage_1_interest": 3,
    }
    results.sort(key=lambda r: stage_order.get(
        (r.get("stage") or {}).get("key", ""), 99
    ))

    return {"sites": results, "total": len(results)}


@router.get("/cached/{site_id}")
async def get_cached_weather(
    site_id: int,
    db: AsyncSession = Depends(get_db),
):
    """DB에 저장된 최근 날씨 반환 (외부 API 호출 없음, 작업자 앱용)"""
    site_repo = WorkSiteRepository(db)
    site = await site_repo.get_by_id(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="작업현장을 찾을 수 없습니다.")

    log_repo = WeatherLogRepository(db)
    latest = await log_repo.get_latest_by_site(site_id)

    if not latest:
        # 캐시 없으면 한 번만 조회
        weather_provider = get_weather_provider()
        weather = await weather_provider.get_current_weather(site.latitude, site.longitude)
        apparent_temp = HeatIndexCalculator.calculate_heat_index(weather.temperature, weather.humidity)
        wbgt = HeatIndexCalculator.estimate_wbgt_outdoor(weather.temperature, weather.humidity, weather.wind_speed)
        stage_info = threshold_mgr.determine_stage(apparent_temp)
        await log_repo.create(
            work_site_id=site.id,
            temperature=weather.temperature, humidity=weather.humidity,
            wind_speed=weather.wind_speed, apparent_temperature=apparent_temp,
            wbgt_estimated=wbgt, stage=stage_info["key"] if stage_info else None,
        )
        latest = await log_repo.get_latest_by_site(site_id)

    apparent_temp = latest.apparent_temperature
    stage_info = threshold_mgr.determine_stage(apparent_temp)
    intensity = site.work_intensity.value if isinstance(site.work_intensity, WorkIntensity) else site.work_intensity
    wbgt_rec = threshold_mgr.get_wbgt_recommendation(latest.wbgt_estimated, intensity)

    stage_response = None
    if stage_info:
        stage_response = HeatStageInfo(
            stage_key=stage_info["key"], stage_name=stage_info["name"],
            color=stage_info["color"], actions=stage_info["actions"],
            rest_guideline=stage_info["rest_guideline"],
            work_restriction=stage_info["work_restriction"],
        )

    return WeatherStatusResponse(
        work_site_id=site.id, work_site_name=site.name,
        weather=WeatherData(
            temperature=latest.temperature, humidity=latest.humidity,
            wind_speed=latest.wind_speed, apparent_temperature=apparent_temp,
            wbgt_estimated=latest.wbgt_estimated,
        ),
        stage=stage_response,
        wbgt_work_recommendation=wbgt_rec,
        checked_at=latest.recorded_at,
    )


@router.get("/history/{site_id}")
async def get_weather_history(
    site_id: int,
    hours: int = 24,
    db: AsyncSession = Depends(get_db),
):
    """작업현장의 날씨 이력 조회"""
    log_repo = WeatherLogRepository(db)
    logs = await log_repo.get_history(site_id, hours)
    return [
        {
            "temperature": l.temperature,
            "humidity": l.humidity,
            "apparent_temperature": l.apparent_temperature,
            "wbgt_estimated": l.wbgt_estimated,
            "stage": l.stage.value if l.stage else None,
            "recorded_at": l.recorded_at.isoformat(),
        }
        for l in logs
    ]


@router.post("/thresholds/reload")
async def reload_thresholds():
    """기준값 설정 파일 재로딩 (런타임 중 변경 반영)"""
    threshold_mgr.reload()
    return {"message": "기준값이 재로딩되었습니다.", "config": threshold_mgr.config}
