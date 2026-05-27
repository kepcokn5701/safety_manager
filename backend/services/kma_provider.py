"""
기상청 API허브 기반 날씨 데이터 제공자
- 기상청 API허브(apihub.kma.go.kr) 단기예보 API 사용
- 단기예보조회(getVilageFcst): 기온, 습도, 풍속 제공
- 위경도 → 격자좌표(nx, ny) 변환 포함
"""

import logging
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

import httpx

from backend.config import settings
from backend.services.interfaces import WeatherProvider, WeatherResult

logger = logging.getLogger(__name__)


def latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
    """
    위경도 → 기상청 격자좌표(nx, ny) 변환
    기상청 격자 변환 공식 (Lambert Conformal Conic Projection)
    """
    RE = 6371.00877  # 지구 반경 (km)
    GRID = 5.0       # 격자 간격 (km)
    SLAT1 = 30.0     # 투영 위도1 (degree)
    SLAT2 = 60.0     # 투영 위도2 (degree)
    OLON = 126.0     # 기준점 경도 (degree)
    OLAT = 38.0      # 기준점 위도 (degree)
    XO = 43          # 기준점 X좌표 (GRID)
    YO = 136         # 기준점 Y좌표 (GRID)

    DEGRAD = math.pi / 180.0

    re = RE / GRID
    slat1 = SLAT1 * DEGRAD
    slat2 = SLAT2 * DEGRAD
    olon = OLON * DEGRAD
    olat = OLAT * DEGRAD

    sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5)
    sf = (sf ** sn) * math.cos(slat1) / sn
    ro = math.tan(math.pi * 0.25 + olat * 0.5)
    ro = re * sf / (ro ** sn)

    ra = math.tan(math.pi * 0.25 + lat * DEGRAD * 0.5)
    ra = re * sf / (ra ** sn)
    theta = lon * DEGRAD - olon
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn

    nx = int(ra * math.sin(theta) + XO + 0.5)
    ny = int(ro - ra * math.cos(theta) + YO + 0.5)

    return nx, ny


# 단기예보 발표시각: 0200, 0500, 0800, 1100, 1400, 1700, 2000, 2300
_BASE_TIMES = ["0200", "0500", "0800", "1100", "1400", "1700", "2000", "2300"]


def _get_base_datetime() -> tuple[str, str]:
    """
    단기예보 API용 base_date, base_time 계산
    - 발표시각: 02, 05, 08, 11, 14, 17, 20, 23시
    - API 제공은 발표 후 약 10분 뒤
    - 현재 시각 기준 가장 최근 발표 시각을 반환
    """
    now = datetime.now(KST)
    # 발표 후 약 10분 뒤 제공 → 여유있게 15분
    adjusted = now - timedelta(minutes=15)

    current_hhmm = adjusted.strftime("%H%M")

    # 현재 시각 이전의 가장 최근 발표시각 찾기
    base_time = None
    for bt in reversed(_BASE_TIMES):
        if current_hhmm >= bt:
            base_time = bt
            break

    if base_time is None:
        # 자정~02시15분 사이 → 전날 2300 발표
        adjusted = adjusted - timedelta(days=1)
        base_time = "2300"

    base_date = adjusted.strftime("%Y%m%d")
    return base_date, base_time


def _get_nearest_fcst_time() -> str:
    """현재 시각에 가장 가까운 예보시각(정시) 반환"""
    now = datetime.now(KST)
    # 현재 시각의 정시 (예: 11:30 → 1200, 11:10 → 1100)
    if now.minute >= 30:
        target = now + timedelta(hours=1)
    else:
        target = now
    return target.strftime("%H00")


class KmaProvider(WeatherProvider):
    """
    기상청 API허브 단기예보 API 기반 날씨 데이터 제공자
    - 기상청 API허브(apihub.kma.go.kr) 인증키 필요
    - 카테고리: TMP(기온), REH(습도), WSD(풍속)
    """

    BASE_URL = "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst"

    def __init__(self):
        if not settings.kma_api_key:
            raise ValueError(
                "기상청 API 키가 설정되지 않았습니다. "
                ".env 파일에 KMA_API_KEY를 설정하세요. "
                "(기상청 API허브 https://apihub.kma.go.kr 에서 발급)"
            )

        proxy_config = settings.get_proxy_dict()
        self._client = httpx.AsyncClient(
            timeout=15.0,
            proxy=proxy_config.get("https://") or proxy_config.get("http://"),
        )

    async def get_current_weather(
        self, latitude: float, longitude: float
    ) -> WeatherResult:
        nx, ny = latlon_to_grid(latitude, longitude)
        base_date, base_time = _get_base_datetime()

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

        response = await self._client.get(self.BASE_URL, params=params)
        response.raise_for_status()
        data = response.json()

        # 응답 구조 파싱
        header = data.get("response", {}).get("header", {})
        result_code = header.get("resultCode", "")

        if result_code != "00":
            result_msg = header.get("resultMsg", "알 수 없는 오류")
            raise RuntimeError(
                f"기상청 API 오류: [{result_code}] {result_msg} "
                f"(base_date={base_date}, base_time={base_time}, nx={nx}, ny={ny})"
            )

        items = (
            data.get("response", {})
            .get("body", {})
            .get("items", {})
            .get("item", [])
        )

        # 현재 시각에 가장 가까운 예보시각의 데이터 추출
        target_time = _get_nearest_fcst_time()
        today = datetime.now().strftime("%Y%m%d")

        # 해당 예보시각의 카테고리별 값 추출
        weather_data = {}
        for item in items:
            fcst_date = item.get("fcstDate", "")
            fcst_time = item.get("fcstTime", "")
            if fcst_date == today and fcst_time == target_time:
                category = item.get("category")
                value = item.get("fcstValue")
                if category and value is not None:
                    try:
                        weather_data[category] = float(value)
                    except (ValueError, TypeError):
                        pass

        # 정확한 시각 데이터가 없으면 가장 빠른 예보시각 사용
        if not weather_data:
            earliest_times = {}
            for item in items:
                fcst_time = item.get("fcstTime", "")
                category = item.get("category")
                value = item.get("fcstValue")
                if category and value is not None and category not in earliest_times:
                    try:
                        earliest_times[category] = float(value)
                    except (ValueError, TypeError):
                        pass
            weather_data = earliest_times

        temperature = weather_data.get("TMP", 0.0)   # 기온 (°C)
        humidity = weather_data.get("REH", 0.0)       # 습도 (%)
        wind_speed = weather_data.get("WSD", 0.0)     # 풍속 (m/s)

        logger.info(
            f"기상청 날씨 조회: nx={nx}, ny={ny}, "
            f"기온={temperature}°C, 습도={humidity}%, 풍속={wind_speed}m/s"
        )

        # 기상청 API는 체감온도를 직접 제공하지 않으므로
        # HeatIndexCalculator에서 계산 (weather_service.py)
        # 여기서는 기온을 apparent_temperature로 임시 설정
        return WeatherResult(
            temperature=temperature,
            humidity=humidity,
            wind_speed=wind_speed,
            apparent_temperature=temperature,
            provider="kma",
        )

    async def close(self) -> None:
        await self._client.aclose()
