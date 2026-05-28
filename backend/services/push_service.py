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
            return self._parse_subscriptions(result.scalars().all())

    async def _get_worker_subscriptions(self, site_id: int) -> list[dict]:
        """특정 현장의 worker 구독만 조회"""
        from backend.models.database import async_session
        from backend.models.models import PushSubscription
        from sqlalchemy import and_

        async with async_session() as session:
            result = await session.execute(
                select(PushSubscription).where(
                    and_(
                        PushSubscription.subscriber_type == "worker",
                        PushSubscription.site_id == site_id,
                    )
                )
            )
            return self._parse_subscriptions(result.scalars().all())

    async def _get_admin_subscriptions(self) -> list[dict]:
        """관리자 구독만 조회"""
        from backend.models.database import async_session
        from backend.models.models import PushSubscription

        async with async_session() as session:
            result = await session.execute(
                select(PushSubscription).where(
                    PushSubscription.subscriber_type == "admin"
                )
            )
            return self._parse_subscriptions(result.scalars().all())

    @staticmethod
    def _parse_subscriptions(rows) -> list[dict]:
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

    async def _send_to_subscriptions(self, subscriptions: list[dict], payload: dict) -> tuple[int, int]:
        """구독 목록에 푸시 발송, (성공, 실패) 반환"""
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
                failed += 1
                error_msg = str(e)
                logger.warning(f"푸시 발송 실패 (endpoint={sub['endpoint'][:50]}): {error_msg[:200]}")
                # 구독 자동 삭제 안 함 - 일시적 오류일 수 있음
                # 사용자가 직접 구독 해제할 때만 삭제
        return sent, failed

    async def send(
        self,
        recipient_phone: str,
        recipient_name: str,
        stage_name: str,
        temperature: float,
        work_site_name: str,
        actions: list[str],
        site_id: int | None = None,
    ) -> NotificationResult:
        """현장 작업자에게 타겟 푸시 발송 (site_id 기반)"""

        stage_icon_map = {
            "관심": "/static/icons/alert-interest.svg",
            "주의": "/static/icons/alert-caution.svg",
            "경고": "/static/icons/alert-warning.svg",
            "위험": "/static/icons/alert-danger.svg",
        }

        # site_id가 있으면 해당 현장 worker만, 없으면 전체 브로드캐스트
        if site_id:
            subscriptions = await self._get_worker_subscriptions(site_id)
        else:
            subscriptions = await self._get_all_subscriptions()

        if not subscriptions:
            return NotificationResult(
                success=False,
                channel="web_push",
                recipient=f"site_{site_id}" if site_id else "broadcast",
                error_message="등록된 푸시 구독자가 없습니다.",
            )

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
                "type": "worker_alert",
                "stage": stage_name,
                "temperature": temperature,
                "site": work_site_name,
                "site_id": site_id,
                "actions": actions,
                "url": f"/worker/{site_id}" if site_id else "/",
            },
        }

        sent, failed = await self._send_to_subscriptions(subscriptions, payload)
        logger.info(f"푸시 발송 (site={site_id}): 성공 {sent}, 실패 {failed}")

        return NotificationResult(
            success=sent > 0,
            channel="web_push",
            recipient=f"site_{site_id}({sent}/{sent + failed})" if site_id else f"broadcast({sent}/{sent + failed})",
            message_id=f"push_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            error_message=f"실패 {failed}건" if failed else None,
        )

    async def send_admin_summary(
        self,
        stage_name: str,
        temperature: float,
        work_site_name: str,
        sent_count: int,
        total_count: int,
        site_id: int | None = None,
        push_success: bool = True,
    ) -> None:
        """관리자에게 발송 결과 요약 푸시 1건"""
        subscriptions = await self._get_admin_subscriptions()
        if not subscriptions:
            return

        stage_icon_map = {
            "관심": "/static/icons/alert-interest.svg",
            "주의": "/static/icons/alert-caution.svg",
            "경고": "/static/icons/alert-warning.svg",
            "위험": "/static/icons/alert-danger.svg",
        }

        push_status = "푸시 발송 완료" if push_success else "푸시 구독자 없음 (작업자 QR 등록 필요)"
        payload = {
            "title": f"[폭염 {stage_name}] {work_site_name}",
            "body": f"체감 {temperature}°C - 대상 {sent_count}/{total_count}명\n{push_status}",
            "icon": stage_icon_map.get(stage_name, "/static/icons/icon-192.svg"),
            "badge": "/static/icons/badge-72.svg",
            "tag": f"admin-summary-{site_id}",
            "data": {
                "type": "admin_summary",
                "stage": stage_name,
                "temperature": temperature,
                "site": work_site_name,
                "sent_count": sent_count,
                "total_count": total_count,
                "url": "/",
            },
        }

        sent, failed = await self._send_to_subscriptions(subscriptions, payload)
        logger.info(f"관리자 요약 푸시: 성공 {sent}, 실패 {failed}")

    async def close(self) -> None:
        pass


async def register_subscription(
    subscription: dict,
    subscriber_type: str = "admin",
    site_id: int | None = None,
) -> str:
    """구독 등록 (DB 저장)"""
    from backend.models.database import async_session
    from backend.models.models import PushSubscription

    endpoint = subscription.get("endpoint", "")
    if not endpoint:
        raise ValueError("유효하지 않은 구독 정보입니다.")

    async with async_session() as session:
        result = await session.execute(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint)
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.subscription_json = json.dumps(subscription)
            existing.subscriber_type = subscriber_type
            existing.site_id = site_id
        else:
            session.add(PushSubscription(
                endpoint=endpoint,
                subscription_json=json.dumps(subscription),
                subscriber_type=subscriber_type,
                site_id=site_id,
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
