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
    """모든 활성 옥외 작업현장의 날씨를 한 번에 조회 (격자 캐시로 최적화)"""
    import asyncio
    from backend.services.kma_provider import latlon_to_grid

    site_repo = WorkSiteRepository(db)
    sites = await site_repo.get_all_outdoor_active()

    # 1단계: 격자별로 현장 묶기 (같은 격자 = 같은 날씨)
    grid_sites = {}
    for site in sites:
        nx, ny = latlon_to_grid(site.latitude, site.longitude)
        grid_key = f"{nx},{ny}"
        if grid_key not in grid_sites:
            grid_sites[grid_key] = {"lat": site.latitude, "lon": site.longitude, "sites": []}
        grid_sites[grid_key]["sites"].append(site)

    # 2단계: 격자별로 병렬 날씨 조회
    async def fetch_grid_weather(grid_key, grid_info):
        try:
            weather = await weather_provider.get_current_weather(grid_info["lat"], grid_info["lon"])
            return grid_key, weather, None
        except Exception as e:
            return grid_key, None, str(e)

    grid_results = await asyncio.gather(
        *[fetch_grid_weather(k, v) for k, v in grid_sites.items()]
    )
    weather_cache = {}
    for grid_key, weather, error in grid_results:
        if weather:
            weather_cache[grid_key] = weather

    # 3단계: 현장별 결과 조합
    alert_repo = AlertLogRepository(db)
    results = []
    for site in sites:
        try:
            nx, ny = latlon_to_grid(site.latitude, site.longitude)
            grid_key = f"{nx},{ny}"
            weather = weather_cache.get(grid_key)
            if not weather:
                results.append({"site_id": site.id, "site_name": site.name, "address": site.address or "", "error": "날씨 조회 실패"})
                continue

            apparent_temp = HeatIndexCalculator.calculate_heat_index(weather.temperature, weather.humidity)
            wbgt = HeatIndexCalculator.estimate_wbgt_outdoor(weather.temperature, weather.humidity, weather.wind_speed)
            stage_info = threshold_mgr.determine_stage(apparent_temp)
            intensity = site.work_intensity.value if isinstance(site.work_intensity, WorkIntensity) else site.work_intensity
            wbgt_rec = threshold_mgr.get_wbgt_recommendation(wbgt, intensity)

            # 날씨 로그 저장
            log_repo = WeatherLogRepository(db)
            await log_repo.create(
                work_site_id=site.id, temperature=weather.temperature,
                humidity=weather.humidity, wind_speed=weather.wind_speed,
                apparent_temperature=apparent_temp, wbgt_estimated=wbgt,
                stage=stage_info["key"] if stage_info else None,
            )

            # 작업자 + 알림 상태
            workers = await site_repo.get_workers(site.id)
            worker_ids = [w.id for w in workers]
            latest_alerts = await alert_repo.get_latest_by_site_workers(site.id, worker_ids) if worker_ids else {}

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
                "branch_office": site.branch_office or "",
                "latitude": site.latitude,
                "longitude": site.longitude,
                "work_intensity": intensity,
                "workers": worker_list,
                "worker_count": len(worker_list),
                "ack_count": 0,
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

    success_count = sum(1 for r in results if "weather" in r)
    error_count = sum(1 for r in results if "error" in r)
    return {
        "sites": results, "total": len(results),
        "weather_success": success_count, "weather_error": error_count,
        "grids_queried": len(grid_sites),
    }


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


@router.get("/verify/{site_id}")
async def verify_weather(
    site_id: int,
    db: AsyncSession = Depends(get_db),
):
    """날씨 데이터 검증 — KMA API 원시 데이터부터 계산 과정까지 상세 표시"""
    import math
    import httpx
    from backend.config import settings
    from backend.services.kma_provider import latlon_to_grid, _get_base_datetime, _get_nearest_fcst_time

    site_repo = WorkSiteRepository(db)
    site = await site_repo.get_by_id(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="작업현장을 찾을 수 없습니다.")

    lat, lon = site.latitude, site.longitude
    nx, ny = latlon_to_grid(lat, lon)
    base_date, base_time = _get_base_datetime()
    target_fcst_time = _get_nearest_fcst_time()
    now = datetime.now(KST)

    verification = {
        "site": {
            "id": site.id,
            "name": site.name,
            "address": site.address or "",
            "latitude": lat,
            "longitude": lon,
        },
        "grid": {
            "nx": nx,
            "ny": ny,
            "description": f"기상청 5km 격자 좌표 (위경도 {lat:.6f}, {lon:.6f} → 격자 {nx}, {ny})",
        },
        "api_request": {
            "url": "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst",
            "base_date": base_date,
            "base_time": base_time,
            "target_fcst_time": target_fcst_time,
            "description": f"발표시각 {base_date} {base_time} 기준, 예보시각 {target_fcst_time} 데이터 추출",
        },
        "timestamp": now.isoformat(),
    }

    # 실제 KMA API 호출
    try:
        proxy_config = settings.get_proxy_dict()
        async with httpx.AsyncClient(
            timeout=15.0,
            proxy=proxy_config.get("https://") or proxy_config.get("http://"),
            verify=False,
        ) as client:
            params = {
                "authKey": settings.kma_api_key,
                "numOfRows": "300",
                "pageNo": "1",
                "dataType": "JSON",
                "base_date": base_date,
                "base_time": base_time,
                "nx": nx,
                "ny": ny,
            }
            response = await client.get(
                "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst",
                params=params,
            )
            response.raise_for_status()
            raw_data = response.json()

        header = raw_data.get("response", {}).get("header", {})
        result_code = header.get("resultCode", "")
        result_msg = header.get("resultMsg", "")

        verification["api_response"] = {
            "result_code": result_code,
            "result_message": result_msg,
            "success": result_code == "00",
        }

        if result_code != "00":
            verification["error"] = f"기상청 API 오류: [{result_code}] {result_msg}"
            return verification

        items = (
            raw_data.get("response", {})
            .get("body", {})
            .get("items", {})
            .get("item", [])
        )

        # 예보시각별 데이터 수집
        today = now.strftime("%Y%m%d")
        all_forecast_times = {}
        for item in items:
            fcst_date = item.get("fcstDate", "")
            fcst_time = item.get("fcstTime", "")
            category = item.get("category", "")
            value = item.get("fcstValue", "")
            if fcst_date == today and category in ("TMP", "REH", "WSD", "SKY", "PTY", "POP", "PCP", "VEC"):
                if fcst_time not in all_forecast_times:
                    all_forecast_times[fcst_time] = {}
                try:
                    all_forecast_times[fcst_time][category] = float(value)
                except (ValueError, TypeError):
                    all_forecast_times[fcst_time][category] = value

        # 타겟 시각 데이터
        target_data = all_forecast_times.get(target_fcst_time, {})

        # 폴백 — 가장 빠른 예보시각
        used_fcst_time = target_fcst_time
        if not target_data and all_forecast_times:
            used_fcst_time = sorted(all_forecast_times.keys())[0]
            target_data = all_forecast_times[used_fcst_time]

        temperature = target_data.get("TMP", 0.0)
        humidity = target_data.get("REH", 0.0)
        wind_speed = target_data.get("WSD", 0.0)

        # 카테고리명 매핑
        category_names = {
            "TMP": "기온(°C)", "REH": "습도(%)", "WSD": "풍속(m/s)",
            "SKY": "하늘상태(1맑음/3구름많음/4흐림)", "PTY": "강수형태(0없음/1비/2비눈/3눈)",
            "POP": "강수확률(%)", "PCP": "1시간강수량(mm)", "VEC": "풍향(°)",
        }

        verification["raw_kma_data"] = {
            "used_forecast_time": used_fcst_time,
            "is_fallback": used_fcst_time != target_fcst_time,
            "categories": {
                k: {"value": v, "label": category_names.get(k, k)}
                for k, v in target_data.items()
            },
        }

        # 오늘 전체 시간대 기온 데이터 (추이 확인용)
        hourly_temps = []
        for ft in sorted(all_forecast_times.keys()):
            d = all_forecast_times[ft]
            if "TMP" in d:
                hourly_temps.append({
                    "time": f"{ft[:2]}:{ft[2:]}",
                    "temperature": d.get("TMP"),
                    "humidity": d.get("REH"),
                    "wind_speed": d.get("WSD"),
                })
        verification["hourly_forecast"] = hourly_temps

        # 체감온도 계산 검증
        T = temperature
        RH = humidity
        if T < 26.7:
            apparent_temp = T
            heat_index_detail = {
                "formula": "T < 26.7°C 이므로 체감온도 = 기온 (Heat Index 계산 불필요)",
                "input_temperature": T,
                "input_humidity": RH,
                "result": T,
                "note": "기온이 26.7°C 미만이면 체감온도와 기온이 동일합니다.",
            }
        else:
            HI = (
                -8.78469475556
                + 1.61139411 * T
                + 2.33854883889 * RH
                - 0.14611605 * T * RH
                - 0.012308094 * T * T
                - 0.0164248277778 * RH * RH
                + 0.002211732 * T * T * RH
                + 0.00072546 * T * RH * RH
                - 0.000003582 * T * T * RH * RH
            )
            apparent_temp = round(HI, 1)
            heat_index_detail = {
                "formula": "Rothfusz Regression (NWS Heat Index)",
                "input_temperature": T,
                "input_humidity": RH,
                "coefficients": {
                    "c1": -8.78469475556,
                    "c2_T": round(1.61139411 * T, 4),
                    "c3_RH": round(2.33854883889 * RH, 4),
                    "c4_T*RH": round(-0.14611605 * T * RH, 4),
                    "c5_T²": round(-0.012308094 * T * T, 4),
                    "c6_RH²": round(-0.0164248277778 * RH * RH, 4),
                    "c7_T²*RH": round(0.002211732 * T * T * RH, 4),
                    "c8_T*RH²": round(0.00072546 * T * RH * RH, 4),
                    "c9_T²*RH²": round(-0.000003582 * T * T * RH * RH, 4),
                },
                "raw_result": round(HI, 4),
                "result": apparent_temp,
            }

        verification["heat_index_calculation"] = heat_index_detail

        # WBGT 계산 검증
        Ta = T
        Tw = Ta * math.atan(0.151977 * math.sqrt(RH + 8.313659)) + \
             math.atan(Ta + RH) - \
             math.atan(RH - 1.676331) + \
             0.00391838 * (RH ** 1.5) * math.atan(0.023101 * RH) - \
             4.686035
        solar_addition = max(0, 7.0 - wind_speed * 0.5)
        Tg = Ta + solar_addition
        wbgt = round(0.7 * Tw + 0.2 * Tg + 0.1 * Ta, 1)

        verification["wbgt_calculation"] = {
            "formula": "WBGT = 0.7×Tw + 0.2×Tg + 0.1×Ta",
            "Ta_dry_bulb": round(Ta, 2),
            "Tw_wet_bulb": round(Tw, 2),
            "Tw_formula": "Stull 2011 근사식",
            "Tg_globe": round(Tg, 2),
            "Tg_solar_addition": round(solar_addition, 2),
            "Tg_note": f"기온({Ta}°C) + 일사보정({round(solar_addition, 1)}°C) = {round(Tg, 1)}°C (풍속 {wind_speed}m/s 반영)",
            "result": wbgt,
            "breakdown": f"0.7×{round(Tw, 1)} + 0.2×{round(Tg, 1)} + 0.1×{round(Ta, 1)} = {wbgt}",
        }

        # 폭염 단계 판정
        stage_info = threshold_mgr.determine_stage(apparent_temp)
        thresholds = threshold_mgr.config.get("stages", [])
        verification["stage_determination"] = {
            "apparent_temperature": apparent_temp,
            "determined_stage": stage_info["name"] if stage_info else "정상 (해당 단계 없음)",
            "thresholds": [
                {"name": s["name"], "min_temp": s["min_apparent_temp"],
                 "matched": apparent_temp >= s["min_apparent_temp"]}
                for s in thresholds
            ],
        }

        # 최종 요약
        verification["summary"] = {
            "temperature": temperature,
            "humidity": humidity,
            "wind_speed": wind_speed,
            "apparent_temperature": apparent_temp,
            "wbgt": wbgt,
            "stage": stage_info["name"] if stage_info else "정상",
        }

        # 외부 비교 링크
        verification["external_links"] = {
            "kma_weather": f"https://www.weather.go.kr/w/obs-climate/land/city-obs.do",
            "naver_weather": f"https://search.naver.com/search.naver?query={site.address or site.name}+날씨",
            "kma_api_test": f"https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst?authKey=YOUR_KEY&numOfRows=50&pageNo=1&dataType=JSON&base_date={base_date}&base_time={base_time}&nx={nx}&ny={ny}",
        }

    except httpx.ConnectError as e:
        verification["error"] = f"기상청 API 연결 실패: {str(e)[:100]}"
    except Exception as e:
        verification["error"] = f"검증 중 오류: {type(e).__name__} - {str(e)[:150]}"

    return verification


@router.get("/verify-all")
async def verify_all_weather(
    db: AsyncSession = Depends(get_db),
):
    """전체 현장 날씨 데이터 일괄 검증 — 시스템 값 vs KMA API 원시 데이터 비교"""
    import math
    import httpx
    from backend.config import settings
    from backend.services.kma_provider import latlon_to_grid, _get_base_datetime, _get_nearest_fcst_time

    site_repo = WorkSiteRepository(db)
    sites = await site_repo.get_all_outdoor_active()

    if not sites:
        return {"error": "등록된 현장이 없습니다.", "results": []}

    base_date, base_time = _get_base_datetime()
    target_fcst_time = _get_nearest_fcst_time()
    now = datetime.now(KST)

    # 격자별로 묶어서 API 호출 최소화
    grid_map = {}
    for site in sites:
        nx, ny = latlon_to_grid(site.latitude, site.longitude)
        key = (nx, ny)
        if key not in grid_map:
            grid_map[key] = {"nx": nx, "ny": ny, "sites": []}
        grid_map[key]["sites"].append(site)

    proxy_config = settings.get_proxy_dict()
    grid_weather = {}

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            proxy=proxy_config.get("https://") or proxy_config.get("http://"),
            verify=False,
        ) as client:
            for (nx, ny), info in grid_map.items():
                params = {
                    "authKey": settings.kma_api_key,
                    "numOfRows": "300", "pageNo": "1", "dataType": "JSON",
                    "base_date": base_date, "base_time": base_time,
                    "nx": nx, "ny": ny,
                }
                try:
                    resp = await client.get(
                        "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst",
                        params=params,
                    )
                    resp.raise_for_status()
                    raw = resp.json()

                    header = raw.get("response", {}).get("header", {})
                    if header.get("resultCode") != "00":
                        grid_weather[(nx, ny)] = {"error": header.get("resultMsg", "API 오류")}
                        continue

                    items = raw.get("response", {}).get("body", {}).get("items", {}).get("item", [])
                    today = now.strftime("%Y%m%d")

                    weather_data = {}
                    for item in items:
                        if item.get("fcstDate") == today and item.get("fcstTime") == target_fcst_time:
                            cat = item.get("category")
                            val = item.get("fcstValue")
                            if cat and val is not None:
                                try:
                                    weather_data[cat] = float(val)
                                except (ValueError, TypeError):
                                    pass

                    if not weather_data:
                        for item in items:
                            cat = item.get("category")
                            val = item.get("fcstValue")
                            if cat and val is not None and cat not in weather_data:
                                try:
                                    weather_data[cat] = float(val)
                                except (ValueError, TypeError):
                                    pass

                    grid_weather[(nx, ny)] = weather_data
                except Exception as e:
                    grid_weather[(nx, ny)] = {"error": str(e)[:100]}
    except Exception as e:
        return {"error": f"API 연결 실패: {str(e)[:100]}", "results": []}

    # 각 현장별 시스템 값과 비교
    results = []
    # 시스템 캐시된 날씨 가져오기
    from backend.models.models import WeatherLog
    from sqlalchemy import select, desc

    for site in sites:
        nx, ny = latlon_to_grid(site.latitude, site.longitude)
        raw_data = grid_weather.get((nx, ny), {})

        if "error" in raw_data:
            results.append({
                "site_id": site.id, "site_name": site.name, "address": site.address or "",
                "grid": f"({nx},{ny})", "error": raw_data["error"],
            })
            continue

        kma_temp = raw_data.get("TMP", 0.0)
        kma_humidity = raw_data.get("REH", 0.0)
        kma_wind = raw_data.get("WSD", 0.0)

        # 체감온도 계산
        if kma_temp < 26.7:
            kma_apparent = kma_temp
        else:
            T, RH = kma_temp, kma_humidity
            kma_apparent = round(
                -8.78469475556 + 1.61139411*T + 2.33854883889*RH
                - 0.14611605*T*RH - 0.012308094*T*T - 0.0164248277778*RH*RH
                + 0.002211732*T*T*RH + 0.00072546*T*RH*RH - 0.000003582*T*T*RH*RH, 1)

        # WBGT
        Ta, RHv = kma_temp, kma_humidity
        Tw = Ta * math.atan(0.151977 * math.sqrt(RHv + 8.313659)) + \
             math.atan(Ta + RHv) - math.atan(RHv - 1.676331) + \
             0.00391838 * (RHv ** 1.5) * math.atan(0.023101 * RHv) - 4.686035
        solar_add = max(0, 7.0 - kma_wind * 0.5)
        Tg = Ta + solar_add
        kma_wbgt = round(0.7 * Tw + 0.2 * Tg + 0.1 * Ta, 1)

        stage_info = threshold_mgr.determine_stage(kma_apparent)

        # 시스템 캐시 날씨 조회
        sys_temp = sys_humidity = sys_apparent = sys_wbgt = None
        log_result = await db.execute(
            select(WeatherLog)
            .where(WeatherLog.work_site_id == site.id)
            .order_by(desc(WeatherLog.recorded_at))
            .limit(1)
        )
        log = log_result.scalar_one_or_none()
        if log:
            sys_temp = log.temperature
            sys_humidity = log.humidity
            sys_apparent = log.apparent_temperature
            sys_wbgt = log.wbgt_estimated

        # 비교
        temp_match = sys_temp == kma_temp if sys_temp is not None else None
        humidity_match = sys_humidity == kma_humidity if sys_humidity is not None else None
        apparent_match = sys_apparent == kma_apparent if sys_apparent is not None else None

        results.append({
            "site_id": site.id,
            "site_name": site.name,
            "address": site.address or "",
            "grid": f"({nx},{ny})",
            "kma_raw": {
                "temperature": kma_temp,
                "humidity": kma_humidity,
                "wind_speed": kma_wind,
                "apparent_temperature": kma_apparent,
                "wbgt": kma_wbgt,
                "stage": stage_info["name"] if stage_info else "정상",
            },
            "system_cached": {
                "temperature": sys_temp,
                "humidity": sys_humidity,
                "apparent_temperature": sys_apparent,
                "wbgt": sys_wbgt,
            } if sys_temp is not None else None,
            "comparison": {
                "temperature_match": temp_match,
                "humidity_match": humidity_match,
                "apparent_match": apparent_match,
                "temp_diff": round(abs(sys_temp - kma_temp), 1) if sys_temp is not None else None,
                "apparent_diff": round(abs(sys_apparent - kma_apparent), 1) if sys_apparent is not None else None,
            } if sys_temp is not None else None,
        })

    all_match = all(
        r.get("comparison", {}).get("temperature_match") is True
        and r.get("comparison", {}).get("humidity_match") is True
        for r in results if r.get("comparison")
    )

    return {
        "timestamp": now.isoformat(),
        "base_date": base_date,
        "base_time": base_time,
        "target_fcst_time": target_fcst_time,
        "total_sites": len(sites),
        "grids_queried": len(grid_map),
        "all_match": all_match,
        "results": results,
    }


@router.post("/thresholds/reload")
async def reload_thresholds():
    """기준값 설정 파일 재로딩 (런타임 중 변경 반영)"""
    threshold_mgr.reload()
    return {"message": "기준값이 재로딩되었습니다.", "config": threshold_mgr.config}


@router.get("/status-all/mock")
async def get_all_weather_mock():
    """테스트용: 가상 현장/작업자에 가상 날씨 데이터를 부여하여 전 단계 필터 테스트.
    모의테스트는 항상 가상 데이터만 사용하여 실제 현장과 혼동 방지."""

    # 단계별 가상 온도 (체감온도 기준)
    mock_profiles = [
        {"temp": 36, "humidity": 75, "wind": 1.0, "apparent": 40},  # 위험 (38°+)
        {"temp": 33, "humidity": 70, "wind": 1.5, "apparent": 36},  # 경고 (35°+)
        {"temp": 30, "humidity": 65, "wind": 2.0, "apparent": 34},  # 주의 (33°+)
        {"temp": 28, "humidity": 60, "wind": 2.5, "apparent": 32},  # 관심 (31°+)
        {"temp": 25, "humidity": 55, "wind": 3.0, "apparent": 28},  # 정상
    ]

    # ── 가상 현장 데이터 (모의테스트는 항상 가상 데이터 사용) ──
    # 이름/전화번호/공사명 모두 확실히 가상임을 알 수 있도록 구성
    mock_sites = [
        {"name": "[가상] 창원 배전선로 교체 작업(가상)", "addr": "경남 창원시 의창구 00번지 (가상주소)", "branch": "창원지사(가상)",
         "intensity": "heavy",
         "workers": [
             {"name": "홍길동(가상)", "phone": "000-0000-0001", "vulnerable": False},
             {"name": "김철수(가상)", "phone": "000-0000-0002", "vulnerable": True},
             {"name": "이영희(가상)", "phone": "000-0000-0003", "vulnerable": False},
         ]},
        {"name": "[가상] 진주 변전소 종합점검 작업(가상)", "addr": "경남 진주시 상평동 00번지 (가상주소)", "branch": "진주지사(가상)",
         "intensity": "moderate",
         "workers": [
             {"name": "박민수(가상)", "phone": "000-0000-0004", "vulnerable": False},
             {"name": "최유나(가상)", "phone": "000-0000-0005", "vulnerable": True},
         ]},
        {"name": "[가상] 밀양 지중선로 신설 작업(가상)", "addr": "경남 밀양시 내이동 00번지 (가상주소)", "branch": "밀양지사(가상)",
         "intensity": "heavy",
         "workers": [
             {"name": "정대한(가상)", "phone": "000-0000-0006", "vulnerable": False},
             {"name": "한미래(가상)", "phone": "000-0000-0007", "vulnerable": False},
         ]},
        {"name": "[가상] 통영 배전설비 정비 작업(가상)", "addr": "경남 통영시 광도면 00번지 (가상주소)", "branch": "통영지사(가상)",
         "intensity": "light",
         "workers": [
             {"name": "강하늘(가상)", "phone": "000-0000-0008", "vulnerable": False},
         ]},
        {"name": "[가상] 거제 송전철탑 정기점검 작업(가상)", "addr": "경남 거제시 장목면 00번지 (가상주소)", "branch": "거제지사(가상)",
         "intensity": "heavy",
         "workers": [
             {"name": "오세종(가상)", "phone": "000-0000-0009", "vulnerable": True},
             {"name": "임꺽정(가상)", "phone": "000-0000-0010", "vulnerable": False},
             {"name": "장보고(가상)", "phone": "000-0000-0011", "vulnerable": False},
         ]},
        {"name": "[가상] 함양 농어촌 배전설비 보강 작업(가상)", "addr": "경남 함양군 안의면 00번지 (가상주소)", "branch": "함양지사(가상)",
         "intensity": "moderate",
         "workers": [
             {"name": "성춘향(가상)", "phone": "000-0000-0012", "vulnerable": False},
             {"name": "이몽룡(가상)", "phone": "000-0000-0013", "vulnerable": False},
         ]},
        {"name": "[가상] 김해 스마트그리드 구축 작업(가상)", "addr": "경남 김해시 장유면 00번지 (가상주소)", "branch": "김해지사(가상)",
         "intensity": "moderate",
         "workers": [
             {"name": "심청이(가상)", "phone": "000-0000-0014", "vulnerable": True},
             {"name": "변학도(가상)", "phone": "000-0000-0015", "vulnerable": False},
         ]},
        {"name": "[가상] 사천 태양광발전소 점검 작업(가상)", "addr": "경남 사천시 남일로 00번지 (가상주소)", "branch": "사천지사(가상)",
         "intensity": "light",
         "workers": [
             {"name": "춘향모(가상)", "phone": "000-0000-0016", "vulnerable": False},
         ]},
        {"name": "[가상] 양산 전력구 케이블 포설 작업(가상)", "addr": "경남 양산시 물금읍 00번지 (가상주소)", "branch": "양산지사(가상)",
         "intensity": "heavy",
         "workers": [
             {"name": "월매(가상)", "phone": "000-0000-0017", "vulnerable": True},
             {"name": "방자(가상)", "phone": "000-0000-0018", "vulnerable": False},
         ]},
        {"name": "[가상] 합천 송전철탑 도장 작업(가상)", "addr": "경남 합천군 가야면 00번지 (가상주소)", "branch": "합천지사(가상)",
         "intensity": "moderate",
         "workers": [
             {"name": "향단이(가상)", "phone": "000-0000-0019", "vulnerable": False},
             {"name": "김삿갓(가상)", "phone": "000-0000-0020", "vulnerable": False},
         ]},
    ]

    results = []

    # 모의테스트는 항상 가상 데이터만 사용 (실제 현장과 혼동 방지)
    for i, ms in enumerate(mock_sites):
        profile = mock_profiles[i % len(mock_profiles)]
        apparent_temp = profile["apparent"]
        wbgt = HeatIndexCalculator.estimate_wbgt_outdoor(profile["temp"], profile["humidity"], profile["wind"])
        stage_info = threshold_mgr.determine_stage(apparent_temp)
        intensity = ms.get("intensity", "moderate")
        wbgt_rec = threshold_mgr.get_wbgt_recommendation(wbgt, intensity)

        worker_list = [
            {
                "id": 9000 + i * 10 + j,
                "name": w["name"],
                "phone": w["phone"],
                "is_vulnerable": w.get("vulnerable", False),
                "last_alert": None,
            }
            for j, w in enumerate(ms["workers"])
        ]

        results.append({
            "site_id": 9000 + i,
            "site_name": ms["name"],
            "address": ms["addr"],
            "branch_office": ms["branch"],
            "latitude": 0, "longitude": 0,
            "work_intensity": intensity,
            "workers": worker_list,
            "worker_count": len(worker_list),
            "ack_count": 0,
            "weather": {
                "temperature": profile["temp"],
                "humidity": profile["humidity"],
                "wind_speed": profile["wind"],
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
            "is_mock": True,
        })

    stage_order = {
        "stage_4_danger": 0, "stage_3_warning": 1,
        "stage_2_caution": 2, "stage_1_interest": 3,
    }
    results.sort(key=lambda r: stage_order.get(
        (r.get("stage") or {}).get("key", ""), 99
    ))

    return {
        "sites": results, "total": len(results),
        "weather_success": len(results), "weather_error": 0,
        "grids_queried": 0, "mock": True,
    }
