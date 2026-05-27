"""
FastAPI 의존성 주입(DI) 컨테이너
- 인터페이스 구현체를 한 곳에서 관리
- 사내망 이관 시 이 파일만 수정하면 구현체 교체 가능
"""

from backend.config import settings
from backend.services.interfaces import WeatherProvider, NotificationSender
from backend.services.weather_service import OpenMeteoProvider, ThresholdManager
from backend.services.alert_service import KakaoAlimTalkSender, ConsoleSender
from backend.services.push_service import WebPushSender


# ── 싱글톤 인스턴스 ──
_weather_provider: WeatherProvider | None = None
_notification_sender: NotificationSender | None = None
_threshold_manager: ThresholdManager | None = None


def get_weather_provider() -> WeatherProvider:
    """
    날씨 데이터 제공자 반환
    사내망 이관 시 여기서 KmaProvider()로 교체
    """
    global _weather_provider
    if _weather_provider is None:
        _weather_provider = OpenMeteoProvider()
    return _weather_provider


def get_notification_sender() -> NotificationSender:
    """
    알림 발송자 반환 (notification_channel 설정에 따라 자동 선택)
    - "web_push": 브라우저 웹 푸시 (프로토타입 기본값)
    - "kakao": 카카오 알림톡 (운영환경)
    - "console": 콘솔 출력 (개발/테스트용)
    """
    global _notification_sender
    if _notification_sender is None:
        channel = settings.notification_channel

        if channel == "kakao" and settings.kakao_rest_api_key:
            _notification_sender = KakaoAlimTalkSender()
        elif channel == "web_push":
            _notification_sender = WebPushSender()
        else:
            _notification_sender = ConsoleSender()
    return _notification_sender


def get_threshold_manager() -> ThresholdManager:
    """기준값 관리자 반환"""
    global _threshold_manager
    if _threshold_manager is None:
        _threshold_manager = ThresholdManager()
    return _threshold_manager


async def cleanup():
    """앱 종료 시 리소스 정리"""
    global _weather_provider, _notification_sender
    if _weather_provider:
        await _weather_provider.close()
        _weather_provider = None
    if _notification_sender:
        await _notification_sender.close()
        _notification_sender = None
