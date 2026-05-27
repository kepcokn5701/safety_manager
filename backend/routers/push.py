"""
웹 푸시 알림 API 라우터
- 구독 등록/해제
- VAPID 공개키 제공
- 테스트 발송
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.database import get_db
from backend.services.push_service import (
    register_subscription,
    unregister_subscription,
    get_subscription_count,
)
from backend.dependencies import get_notification_sender

router = APIRouter(prefix="/api/push", tags=["푸시 알림"])


class SubscriptionRequest(BaseModel):
    phone: str
    subscription: dict  # PushSubscription 객체


class TestPushRequest(BaseModel):
    phone: str
    name: str = "테스트 사용자"


@router.get("/vapid-key")
async def get_vapid_public_key():
    """VAPID 공개키 반환 (프론트엔드에서 구독 시 필요)"""
    return {"public_key": settings.vapid_public_key}


@router.post("/subscribe")
async def subscribe(data: SubscriptionRequest):
    """브라우저 푸시 알림 구독 등록"""
    register_subscription(data.phone, data.subscription)
    return {
        "message": "푸시 알림 구독이 등록되었습니다.",
        "phone": data.phone,
        "total_subscriptions": get_subscription_count(),
    }


@router.post("/unsubscribe")
async def unsubscribe(data: SubscriptionRequest):
    """브라우저 푸시 알림 구독 해제"""
    unregister_subscription(data.phone)
    return {"message": "푸시 알림 구독이 해제되었습니다."}


@router.post("/test")
async def test_push(data: TestPushRequest):
    """테스트 푸시 알림 발송"""
    sender = get_notification_sender()
    result = await sender.send(
        recipient_phone=data.phone,
        recipient_name=data.name,
        stage_name="주의",
        temperature=35.5,
        work_site_name="테스트 현장",
        actions=["이 메시지는 테스트 알림입니다.", "정상 수신되면 알림 설정이 완료된 것입니다."],
    )
    return {
        "success": result.success,
        "channel": result.channel,
        "error": result.error_message,
    }


@router.get("/status")
async def push_status():
    """푸시 알림 상태 확인"""
    return {
        "channel": settings.notification_channel,
        "vapid_configured": bool(settings.vapid_public_key),
        "active_subscriptions": get_subscription_count(),
    }
