"""
알림 관리 API 라우터
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.database import get_db
from backend.services.repository import AlertLogRepository

router = APIRouter(prefix="/api/alerts", tags=["알림"])


@router.get("/history")
async def get_alert_history(
    site_id: int = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    """알림 발송 이력 조회"""
    repo = AlertLogRepository(db)
    logs = await repo.get_history(site_id=site_id, limit=limit)
    return [
        {
            "id": l.id,
            "worker_id": l.worker_id,
            "work_site_id": l.work_site_id,
            "stage": l.stage.value if l.stage else None,
            "apparent_temperature": l.apparent_temperature,
            "wbgt_estimated": l.wbgt_estimated,
            "message": l.message,
            "channel": l.channel,
            "status": l.status.value if l.status else None,
            "sent_at": l.sent_at.isoformat(),
        }
        for l in logs
    ]


@router.get("/stats")
async def get_alert_stats(
    days: int = 7,
    db: AsyncSession = Depends(get_db),
):
    """알림 통계 조회"""
    repo = AlertLogRepository(db)
    return await repo.get_stats(days=days)
