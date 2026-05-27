"""
날씨 서비스 - Open-Meteo 구현체 + 체감온도/WBGT 계산
"""

import json
import logging
import math
from pathlib import Path

import httpx

from backend.config import settings
from backend.services.interfaces import WeatherProvider, WeatherResult

logger = logging.getLogger(__name__)


class OpenMeteoProvider(WeatherProvider):
    """
    Open-Meteo API 기반 날씨 데이터 제공자
    - 무료, API 키 불필요
    - 프록시 설정 지원
    """

    BASE_URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(self):
        proxy_config = settings.get_proxy_dict()
        self._client = httpx.AsyncClient(
            timeout=10.0,
            proxy=proxy_config.get("https://") or proxy_config.get("http://"),
        )

    async def get_current_weather(
        self, latitude: float, longitude: float
    ) -> WeatherResult:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": [
                "temperature_2m",
                "relative_humidity_2m",
                "apparent_temperature",
                "wind_speed_10m",
            ],
            "timezone": "Asia/Seoul",
        }

        response = await self._client.get(self.BASE_URL, params=params)
        response.raise_for_status()
        data = response.json()

        current = data["current"]

        return WeatherResult(
            temperature=current["temperature_2m"],
            humidity=current["relative_humidity_2m"],
            wind_speed=current["wind_speed_10m"],
            apparent_temperature=current["apparent_temperature"],
            provider="open_meteo",
        )

    async def close(self) -> None:
        await self._client.aclose()


class HeatIndexCalculator:
    """
    체감온도 및 WBGT 계산기
    - 체감온도: 기상청/NWS Heat Index 공식
    - WBGT: 간이 추정 공식 (옥외, 직사일광 기준)
    """

    @staticmethod
    def calculate_heat_index(temperature: float, humidity: float) -> float:
        """
        체감온도 계산 (Rothfusz regression equation)
        기상청에서 사용하는 NWS Heat Index 공식과 동일
        """
        T = temperature
        RH = humidity

        # 26.7°C 미만이면 체감온도 ≈ 기온
        if T < 26.7:
            return T

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

        return round(HI, 1)

    @staticmethod
    def estimate_wbgt_outdoor(
        temperature: float, humidity: float, wind_speed: float
    ) -> float:
        """
        WBGT 간이 추정 (옥외, 직사일광 기준)

        WBGT_outdoor ≈ 0.7 * Tw + 0.2 * Tg + 0.1 * Ta
        - Tw(습구온도): Stull 근사식으로 추정
        - Tg(흑구온도): 기온 + 일사보정 (간이추정)
        - Ta(건구온도): 기온

        참고: 정확한 WBGT는 전용 측정기 필요.
        이 값은 참고용 추정치입니다.
        """
        Ta = temperature
        RH = humidity

        # 습구온도 추정 (Stull 2011 근사식)
        Tw = Ta * math.atan(0.151977 * math.sqrt(RH + 8.313659)) + \
             math.atan(Ta + RH) - \
             math.atan(RH - 1.676331) + \
             0.00391838 * (RH ** 1.5) * math.atan(0.023101 * RH) - \
             4.686035

        # 흑구온도 간이 추정 (맑은 날 기준, 풍속 보정)
        solar_addition = max(0, 7.0 - wind_speed * 0.5)
        Tg = Ta + solar_addition

        # WBGT 계산
        wbgt = 0.7 * Tw + 0.2 * Tg + 0.1 * Ta

        return round(wbgt, 1)


class ThresholdManager:
    """
    기준값 관리자 - JSON 설정 파일에서 폭염 단계/WBGT 기준 로딩
    소스코드 수정 없이 설정 파일만 변경하면 기준값 변경 가능
    """

    def __init__(self, config_path: str = None):
        self._config_path = config_path or settings.thresholds_config_path
        self._config: dict = {}
        self._load()

    def _load(self):
        path = Path(self._config_path)
        if not path.is_absolute():
            # 프로젝트 루트 기준 상대경로 처리
            path = Path(__file__).resolve().parent.parent.parent / path
        with open(path, "r", encoding="utf-8") as f:
            self._config = json.load(f)

    def reload(self):
        """설정 파일 재로딩 (런타임 중 기준값 변경 시)"""
        self._load()

    def determine_stage(self, apparent_temperature: float) -> dict | None:
        """
        체감온도 기반 폭염 단계 판정
        가장 높은 단계부터 역순으로 확인
        """
        stages = self._config["heat_wave_stages"]
        stage_order = [
            "stage_4_danger",
            "stage_3_warning",
            "stage_2_caution",
            "stage_1_interest",
        ]

        for key in stage_order:
            stage = stages[key]
            if apparent_temperature >= stage["apparent_temp_min"]:
                return {"key": key, **stage}

        return None

    def get_wbgt_recommendation(
        self, wbgt: float, work_intensity: str
    ) -> str:
        """
        WBGT 기반 작업강도별 권고사항 반환
        산업안전보건기준에 관한 규칙 제559조 별표14 기준
        """
        standards = self._config["wbgt_standards"]["work_intensity"]
        intensity = standards.get(work_intensity)

        if not intensity:
            return "알 수 없는 작업강도입니다."

        ratio_labels = self._config["wbgt_standards"]["work_rest_ratio"]

        if wbgt >= intensity["continuous"] and wbgt < intensity["work_75"]:
            return f"[{intensity['name']}] {ratio_labels['work_75']} 권고"
        elif wbgt >= intensity["work_75"] and wbgt < intensity["work_50"]:
            return f"[{intensity['name']}] {ratio_labels['work_50']} 권고"
        elif wbgt >= intensity["work_50"] and wbgt < intensity["work_25"]:
            return f"[{intensity['name']}] {ratio_labels['work_25']} 권고"
        elif wbgt >= intensity["work_25"]:
            return f"[{intensity['name']}] ⚠ 해당 강도 작업 중지 권고"
        elif wbgt >= intensity["continuous"]:
            return f"[{intensity['name']}] {ratio_labels['continuous']} 가능 (주의)"
        else:
            return f"[{intensity['name']}] 정상 작업 가능"

    @property
    def config(self) -> dict:
        return self._config
