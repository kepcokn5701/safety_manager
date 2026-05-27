"""
기상청 API 기반 날씨 데이터 제공자
- 공공데이터포털(data.go.kr) 기상청 단기예보 API 사용
- 초단기실황조회(getUltraSrtNcst): 현재 기온, 습도, 풍속 제공
- 위경도 → 격자좌표(nx, ny) 변환 포함
"""

import logging
import math
from datetime import datetime, timedelta

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


def _get_base_datetime() -> tuple[str, str]:
    """
    초단기실황 API용 base_date, base_time 계산
    - 매시 정각에 발표, API 제공은 약 10분 뒤
    - 현재 시각 기준 가장 최근 발표 시각을 반환
    """
    now = datetime.now()

    # API 데이터는 매시 40분경에 확정 → 여유 있게 처리
    if now.minute < 15:
        now = now - timedelta(hours=1)

    base_date = now.strftime("%Y%m%d")
    base_time = now.strftime("%H00")

    return base_date, base_time


class KmaProvider(WeatherProvider):
    """
    기상청 초단기실황 API 기반 날씨 데이터 제공자
    - 공공데이터포털(data.go.kr) 서비스키 필요
    - 카테고리: T1H(기온), REH(습도), WSD(풍속)
    """

    BASE_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"

    def __init__(self):
        if not settings.kma_api_key:
            raise ValueError(
                "기상청 API 키가 설정되지 않았습니다. "
                ".env 파일에 KMA_API_KEY를 설정하세요. "
                "(공공데이터포털 https://www.data.go.kr 에서 발급)"
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
            "serviceKey": settings.kma_api_key,
            "numOfRows": "10",
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

        # 카테고리별 값 추출
        weather_data = {}
        for item in items:
            category = item.get("category")
            value = item.get("obsrValue")
            if category and value is not None:
                weather_data[category] = float(value)

        temperature = weather_data.get("T1H", 0.0)   # 기온 (°C)
        humidity = weather_data.get("REH", 0.0)       # 습도 (%)
        wind_speed = weather_data.get("WSD", 0.0)     # 풍속 (m/s)

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
