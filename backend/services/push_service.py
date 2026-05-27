"""
웹 푸시 알림 서비스 구현체
- 브라우저 Web Push API 사용
- 카카오 알림톡 승인 전 프로토타입용
- pywebpush 라이브러리 사용
"""

import json
import logging
from datetime import datetime

from backend.config import settings
from backend.services.interfaces import NotificationSender, NotificationResult

logger = logging.getLogger(__name__)

# 인메모리 구독 저장소 (프로토타입용)
# 운영 시 DB 테이블로 이관
_subscriptions: dict[str, dict] = {}


class WebPushSender(NotificationSender):
    """
    Web Push API 기반 알림 발송자

    동작 방식:
    1. 사용자가 브라우저에서 알림 허용 → 구독 정보가 서버에 저장됨
    2. 폭염 단계 감지 시 → 구독 정보를 이용해 브라우저 푸시 알림 발송
    3. 브라우저가 꺼져 있어도 Service Worker가 알림을 수신

    사전 준비:
    - .env에 VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY 설정
    - 프론트엔드에서 Service Worker 등록 및 구독
    """

    def __init__(self):
        self._vapid_public_key = settings.vapid_public_key
        self._vapid_private_key = settings.vapid_private_key
        self._vapid_email = settings.vapid_email

    async def send(
        self,
        recipient_phone: str,
        recipient_name: str,
        stage_name: str,
        temperature: float,
        work_site_name: str,
        actions: list[str],
    ) -> NotificationResult:
        """웹 푸시 알림 발송"""

        subscription = _subscriptions.get(recipient_phone)
        if not subscription:
            logger.warning(f"푸시 구독 정보 없음: {recipient_name}({recipient_phone})")
            return NotificationResult(
                success=False,
                channel="web_push",
                recipient=recipient_phone,
                error_message="푸시 구독 정보가 없습니다. 대시보드에서 알림을 허용해주세요.",
            )

        payload = {
            "title": f"[폭염 {stage_name}] {work_site_name}",
            "body": (
                f"체감온도 {temperature}°C\n"
                f"{actions[0] if actions else '안전에 유의하세요.'}"
            ),
            "icon": "/static/icon-192.png",
            "badge": "/static/badge-72.png",
            "tag": f"heat-{stage_name}",
            "data": {
                "stage": stage_name,
                "temperature": temperature,
                "site": work_site_name,
                "actions": actions,
                "url": "/",
            },
        }

        try:
            from pywebpush import webpush, WebPushException

            webpush(
                subscription_info=subscription,
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=self._vapid_private_key,
                vapid_claims={
                    "sub": f"mailto:{self._vapid_email}",
                },
            )

            logger.info(f"웹 푸시 발송 성공: {recipient_name}({recipient_phone})")
            return NotificationResult(
                success=True,
                channel="web_push",
                recipient=recipient_phone,
                message_id=f"push_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            )

        except Exception as e:
            error_msg = str(e)
            logger.error(f"웹 푸시 발송 실패: {recipient_name} - {error_msg}")

            # 구독 만료/취소된 경우 구독 정보 제거
            if "410" in error_msg or "404" in error_msg:
                _subscriptions.pop(recipient_phone, None)
                error_msg = "구독이 만료되었습니다. 대시보드에서 다시 알림을 허용해주세요."

            return NotificationResult(
                success=False,
                channel="web_push",
                recipient=recipient_phone,
                error_message=error_msg,
            )

    async def close(self) -> None:
        pass


def register_subscription(phone: str, subscription: dict):
    """브라우저 푸시 구독 등록"""
    _subscriptions[phone] = subscription
    logger.info(f"푸시 구독 등록: {phone}")


def unregister_subscription(phone: str):
    """브라우저 푸시 구독 해제"""
    _subscriptions.pop(phone, None)
    logger.info(f"푸시 구독 해제: {phone}")


def get_subscription_count() -> int:
    """등록된 구독 수"""
    return len(_subscriptions)
