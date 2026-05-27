"""
서비스 인터페이스 (ABC)
- 날씨 데이터 제공자, 알림 발송자를 인터페이스로 분리
- 구현체만 교체하면 다른 API/서비스로 전환 가능
- 사내망 이관 시 기상청 API나 내부 SMS 게이트웨이로 교체 용이
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class WeatherResult:
    """날씨 조회 결과 DTO"""
    temperature: float        # 기온 (°C)
    humidity: float           # 상대습도 (%)
    wind_speed: float         # 풍속 (m/s)
    apparent_temperature: float  # 체감온도 (°C)
    provider: str             # 데이터 제공자 (예: "open_meteo", "kma")


@dataclass
class NotificationResult:
    """알림 발송 결과 DTO"""
    success: bool
    channel: str              # 발송 채널 (예: "kakao_alimtalk", "sms")
    recipient: str            # 수신자 (전화번호)
    message_id: Optional[str] = None
    error_message: Optional[str] = None


class WeatherProvider(ABC):
    """
    날씨 데이터 제공자 인터페이스

    구현 예시:
    - OpenMeteoProvider: Open-Meteo 무료 API (기본)
    - KmaProvider: 기상청 API (사내망 이관 시)
    - MockWeatherProvider: 테스트용
    """

    @abstractmethod
    async def get_current_weather(
        self, latitude: float, longitude: float
    ) -> WeatherResult:
        """현재 날씨 데이터 조회"""
        ...

    @abstractmethod
    async def close(self) -> None:
        """리소스 정리 (HTTP 클라이언트 등)"""
        ...


class NotificationSender(ABC):
    """
    알림 발송자 인터페이스

    구현 예시:
    - KakaoAlimTalkSender: 카카오 알림톡 (기본)
    - SmsSender: SMS 게이트웨이 (사내망)
    - ConsoleSender: 콘솔 출력 (개발/테스트용)
    """

    @abstractmethod
    async def send(
        self,
        recipient_phone: str,
        recipient_name: str,
        stage_name: str,
        temperature: float,
        work_site_name: str,
        actions: list[str],
    ) -> NotificationResult:
        """알림 발송"""
        ...

    @abstractmethod
    async def close(self) -> None:
        """리소스 정리"""
        ...
