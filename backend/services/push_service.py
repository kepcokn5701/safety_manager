"""
웹 푸시 알림 서비스
- VAPID 키 자동 생성/관리
- DB 기반 구독 관리 (서버리스 환경 호환)
- 모든 구독자에게 브로드캐스트
"""

import json
import logging
from datetime import datetime

from sqlalchemy import select, delete

from backend.config import settings
from backend.services.interfaces import NotificationSender, NotificationResult
from backend.services.vapid_manager import get_vapid_keys

logger = logging.getLogger(__name__)


class WebPushSender(NotificationSender):
    """Web Push API 기반 알림 발송자 (DB에서 구독 로드)"""

    def __init__(self):
        keys = get_vapid_keys()
        self._vapid_private_key = keys["private_key"]
        self._vapid_email = settings.vapid_email

    async def _get_all_subscriptions(self) -> list[dict]:
        """DB에서 모든 구독 조회"""
        from backend.models.database import async_session
        from backend.models.models import PushSubscription

        async with async_session() as session:
            result = await session.execute(select(PushSubscription))
            rows = result.scalars().all()
            subs = []
            for row in rows:
                try:
                    subs.append({
                        "id": row.id,
                        "endpoint": row.endpoint,
                        "subscription": json.loads(row.subscription_json),
                    })
                except json.JSONDecodeError:
                    pass
            return subs

    async def _remove_subscription(self, endpoint: str):
        """만료된 구독 DB에서 제거"""
        from backend.models.database import async_session
        from backend.models.models import PushSubscription

        async with async_session() as session:
            await session.execute(
                delete(PushSubscription).where(PushSubscription.endpoint == endpoint)
            )
            await session.commit()

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

        subscriptions = await self._get_all_subscriptions()

        if not subscriptions:
            return NotificationResult(
                success=False,
                channel="web_push",
                recipient="broadcast",
                error_message="등록된 푸시 구독자가 없습니다.",
            )

        stage_icon_map = {
            "관심": "/static/icons/alert-interest.svg",
            "주의": "/static/icons/alert-caution.svg",
            "경고": "/static/icons/alert-warning.svg",
            "위험": "/static/icons/alert-danger.svg",
        }

        payload = {
            "title": f"[폭염 {stage_name}] {work_site_name}",
            "body": (
                f"체감온도 {temperature}°C\n"
                f"{actions[0] if actions else '안전에 유의하세요.'}"
            ),
            "icon": stage_icon_map.get(stage_name, "/static/icons/icon-192.svg"),
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

        for sub in subscriptions:
            try:
                from pywebpush import webpush

                webpush(
                    subscription_info=sub["subscription"],
                    data=json.dumps(payload, ensure_ascii=False),
                    vapid_private_key=self._vapid_private_key,
                    vapid_claims={"sub": f"mailto:{self._vapid_email}"},
                )
                sent += 1

            except Exception as e:
                error_msg = str(e)
                if "410" in error_msg or "404" in error_msg:
                    await self._remove_subscription(sub["endpoint"])
                failed += 1
                logger.warning(f"푸시 발송 실패: {error_msg[:100]}")

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


async def register_subscription(subscription: dict) -> str:
    """구독 등록 (DB 저장)"""
    from backend.models.database import async_session
    from backend.models.models import PushSubscription

    endpoint = subscription.get("endpoint", "")
    if not endpoint:
        raise ValueError("유효하지 않은 구독 정보입니다.")

    async with async_session() as session:
        # 기존 구독 업데이트 또는 신규 생성
        result = await session.execute(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint)
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.subscription_json = json.dumps(subscription)
        else:
            session.add(PushSubscription(
                endpoint=endpoint,
                subscription_json=json.dumps(subscription),
            ))
        await session.commit()

    count = await get_subscription_count()
    logger.info(f"푸시 구독 등록 (총 {count}명)")
    return endpoint


async def unregister_subscription(endpoint: str):
    """구독 해제 (DB 삭제)"""
    from backend.models.database import async_session
    from backend.models.models import PushSubscription

    async with async_session() as session:
        await session.execute(
            delete(PushSubscription).where(PushSubscription.endpoint == endpoint)
        )
        await session.commit()

    logger.info("푸시 구독 해제")


async def get_subscription_count() -> int:
    from backend.models.database import async_session
    from backend.models.models import PushSubscription
    from sqlalchemy import func

    async with async_session() as session:
        result = await session.execute(select(func.count(PushSubscription.id)))
        return result.scalar() or 0
