"""
웹 푸시 알림 API 라우터
- VAPID 키 자동 제공
- 구독/해제 (DB 저장, 서버리스 호환)
"""

from fastapi import APIRouter
from pydantic import BaseModel

from backend.config import settings
from backend.services.vapid_manager import get_vapid_keys
from backend.services.push_service import (
    register_subscription,
    unregister_subscription,
    get_subscription_count,
)
from backend.dependencies import get_notification_sender

router = APIRouter(prefix="/api/push", tags=["푸시 알림"])


class SubscribeRequest(BaseModel):
    subscription: dict
    subscriber_type: str = "admin"  # "admin" | "worker"
    site_id: int | None = None      # worker인 경우 현장 ID


class UnsubscribeRequest(BaseModel):
    endpoint: str


@router.get("/vapid-key")
async def get_vapid_public_key():
    """VAPID 공개키 반환"""
    keys = get_vapid_keys()
    return {"public_key": keys["public_key"]}


@router.post("/subscribe")
async def subscribe(data: SubscribeRequest):
    """브라우저 푸시 알림 구독"""
    endpoint = await register_subscription(
        data.subscription,
        subscriber_type=data.subscriber_type,
        site_id=data.site_id,
    )
    count = await get_subscription_count()
    return {
        "message": "알림이 활성화되었습니다.",
        "subscriber_type": data.subscriber_type,
        "site_id": data.site_id,
        "total_subscriptions": count,
    }


@router.post("/unsubscribe")
async def unsubscribe(data: UnsubscribeRequest):
    """구독 해제"""
    await unregister_subscription(data.endpoint)
    return {"message": "알림이 해제되었습니다."}


@router.post("/test")
async def test_push():
    """테스트 푸시 알림 발송"""
    sender = get_notification_sender()
    result = await sender.send(
        recipient_phone="broadcast",
        recipient_name="전체",
        stage_name="테스트",
        temperature=35.0,
        work_site_name="테스트 현장",
        actions=["이 메시지는 테스트입니다.", "정상 수신되면 알림 설정이 완료된 것입니다."],
    )
    return {
        "success": result.success,
        "channel": result.channel,
        "recipient": result.recipient,
        "error": result.error_message,
    }


@router.get("/status")
async def push_status():
    """푸시 알림 상태 (구독 상세 포함)"""
    from backend.models.database import async_session
    from backend.models.models import PushSubscription
    from sqlalchemy import select

    keys = get_vapid_keys()
    count = await get_subscription_count()

    # 구독 상세
    subs_detail = []
    async with async_session() as session:
        result = await session.execute(select(PushSubscription))
        for row in result.scalars().all():
            subs_detail.append({
                "id": row.id,
                "type": row.subscriber_type,
                "site_id": row.site_id,
                "endpoint_short": row.endpoint[:60] + "..." if len(row.endpoint) > 60 else row.endpoint,
                "created": row.created_at.isoformat() if row.created_at else None,
            })

    return {
        "channel": settings.notification_channel,
        "vapid_configured": bool(keys.get("public_key")),
        "active_subscriptions": count,
        "subscriptions": subs_detail,
    }
