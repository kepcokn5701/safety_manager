"""
웹 푸시 알림 서비스
- VAPID 키 자동 생성/관리
- 구독 ID 기반 (전화번호 입력 불필요)
- 모든 구독자에게 브로드캐스트
"""

import json
import logging
from datetime import datetime

from backend.config import settings
from backend.services.interfaces import NotificationSender, NotificationResult
from backend.services.vapid_manager import get_vapid_keys

logger = logging.getLogger(__name__)

# 인메모리 구독 저장소: endpoint URL → subscription 객체
_subscriptions: dict[str, dict] = {}


class WebPushSender(NotificationSender):
    """
    Web Push API 기반 알림 발송자
    - VAPID 키 자동 관리 (수동 설정 불필요)
    - 모든 구독자에게 발송 (브로드캐스트)
    """

    def __init__(self):
        keys = get_vapid_keys()
        self._vapid_private_key = keys["private_key"]
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
        """모든 구독자에게 웹 푸시 알림 브로드캐스트"""

        if not _subscriptions:
            return NotificationResult(
                success=False,
                channel="web_push",
                recipient="broadcast",
                error_message="등록된 푸시 구독자가 없습니다.",
            )

        payload = {
            "title": f"[폭염 {stage_name}] {work_site_name}",
            "body": (
                f"체감온도 {temperature}°C\n"
                f"{actions[0] if actions else '안전에 유의하세요.'}"
            ),
            "icon": "/static/icons/icon-192.svg",
            "badge": "/static/icons/badge-72.svg",
            "tag": f"heat-{stage_name}",
            "data": {
                "stage": stage_name,
                "temperature": temperature,
                "site": work_site_name,
                "actions": actions,
                "url": "/",
            },
        }

        sent = 0
        failed = 0
        expired_endpoints = []

        for endpoint, subscription in _subscriptions.items():
            try:
                from pywebpush import webpush

                webpush(
                    subscription_info=subscription,
                    data=json.dumps(payload, ensure_ascii=False),
                    vapid_private_key=self._vapid_private_key,
                    vapid_claims={"sub": f"mailto:{self._vapid_email}"},
                )
                sent += 1

            except Exception as e:
                error_msg = str(e)
                if "410" in error_msg or "404" in error_msg:
                    expired_endpoints.append(endpoint)
                failed += 1
                logger.warning(f"푸시 발송 실패 ({endpoint[:40]}...): {error_msg[:100]}")

        # 만료된 구독 정리
        for ep in expired_endpoints:
            _subscriptions.pop(ep, None)
            logger.info(f"만료된 구독 제거: {ep[:40]}...")

        logger.info(f"푸시 브로드캐스트: 성공 {sent}, 실패 {failed}")
        return NotificationResult(
            success=sent > 0,
            channel="web_push",
            recipient=f"broadcast({sent}/{sent + failed})",
            message_id=f"push_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            error_message=f"실패 {failed}건" if failed else None,
        )

    async def close(self) -> None:
        pass


def register_subscription(subscription: dict) -> str:
    """구독 등록. endpoint를 키로 사용."""
    endpoint = subscription.get("endpoint", "")
    if not endpoint:
        raise ValueError("유효하지 않은 구독 정보입니다.")
    _subscriptions[endpoint] = subscription
    logger.info(f"푸시 구독 등록 (총 {len(_subscriptions)}명)")
    return endpoint


def unregister_subscription(endpoint: str):
    """구독 해제"""
    _subscriptions.pop(endpoint, None)
    logger.info(f"푸시 구독 해제 (총 {len(_subscriptions)}명)")


def get_subscription_count() -> int:
    return len(_subscriptions)
