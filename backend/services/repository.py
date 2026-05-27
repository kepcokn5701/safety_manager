"""
Repository 패턴 - DB 접근 추상화
- DB 종류(SQLite/PostgreSQL/MySQL 등)가 바뀌어도 비즈니스 로직 코드 변경 없음
- SQLAlchemy ORM 기반이므로 DATABASE_URL만 변경하면 DB 교체 가능
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.models import (
    Worker, WorkSite, WorkSiteWorker, WeatherLog, AlertLog,
    AlertStage, AlertStatus, WorkIntensity,
)


class WorkerRepository:
    """작업자 CRUD"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, **kwargs) -> Worker:
        worker = Worker(**kwargs)
        self._session.add(worker)
        await self._session.commit()
        await self._session.refresh(worker)
        return worker

    async def get_by_id(self, worker_id: int) -> Optional[Worker]:
        return await self._session.get(Worker, worker_id)

    async def get_by_phone(self, phone: str) -> Optional[Worker]:
        result = await self._session.execute(
            select(Worker).where(Worker.phone == phone)
        )
        return result.scalar_one_or_none()

    async def get_all_active(self) -> list[Worker]:
        result = await self._session.execute(
            select(Worker).where(Worker.is_active == True)
        )
        return list(result.scalars().all())

    async def update(self, worker_id: int, **kwargs) -> Optional[Worker]:
        worker = await self.get_by_id(worker_id)
        if not worker:
            return None
        for key, value in kwargs.items():
            setattr(worker, key, value)
        await self._session.commit()
        await self._session.refresh(worker)
        return worker

    async def deactivate(self, worker_id: int) -> bool:
        worker = await self.get_by_id(worker_id)
        if not worker:
            return False
        worker.is_active = False
        await self._session.commit()
        return True


class WorkSiteRepository:
    """작업현장 CRUD"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, **kwargs) -> WorkSite:
        site = WorkSite(**kwargs)
        self._session.add(site)
        await self._session.commit()
        await self._session.refresh(site)
        return site

    async def get_by_id(self, site_id: int) -> Optional[WorkSite]:
        return await self._session.get(WorkSite, site_id)

    async def get_all_active(self) -> list[WorkSite]:
        result = await self._session.execute(
            select(WorkSite).where(WorkSite.is_active == True)
        )
        return list(result.scalars().all())

    async def get_all_outdoor_active(self) -> list[WorkSite]:
        """활성 옥외 작업현장 조회 (폭염 모니터링 대상)"""
        result = await self._session.execute(
            select(WorkSite).where(
                and_(WorkSite.is_active == True, WorkSite.is_outdoor == True)
            )
        )
        return list(result.scalars().all())

    async def assign_worker(self, site_id: int, worker_id: int) -> WorkSiteWorker:
        mapping = WorkSiteWorker(work_site_id=site_id, worker_id=worker_id)
        self._session.add(mapping)
        await self._session.commit()
        await self._session.refresh(mapping)
        return mapping

    async def get_workers(self, site_id: int) -> list[Worker]:
        result = await self._session.execute(
            select(Worker)
            .join(WorkSiteWorker, WorkSiteWorker.worker_id == Worker.id)
            .where(
                and_(
                    WorkSiteWorker.work_site_id == site_id,
                    Worker.is_active == True,
                )
            )
        )
        return list(result.scalars().all())

    async def remove_worker(self, site_id: int, worker_id: int) -> bool:
        result = await self._session.execute(
            select(WorkSiteWorker).where(
                and_(
                    WorkSiteWorker.work_site_id == site_id,
                    WorkSiteWorker.worker_id == worker_id,
                )
            )
        )
        mapping = result.scalar_one_or_none()
        if not mapping:
            return False
        await self._session.delete(mapping)
        await self._session.commit()
        return True


class WeatherLogRepository:
    """날씨 기록"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, **kwargs) -> WeatherLog:
        log = WeatherLog(**kwargs)
        self._session.add(log)
        await self._session.commit()
        await self._session.refresh(log)
        return log

    async def get_latest_by_site(self, site_id: int) -> Optional[WeatherLog]:
        result = await self._session.execute(
            select(WeatherLog)
            .where(WeatherLog.work_site_id == site_id)
            .order_by(WeatherLog.recorded_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_history(
        self, site_id: int, hours: int = 24
    ) -> list[WeatherLog]:
        since = datetime.utcnow() - timedelta(hours=hours)
        result = await self._session.execute(
            select(WeatherLog)
            .where(
                and_(
                    WeatherLog.work_site_id == site_id,
                    WeatherLog.recorded_at >= since,
                )
            )
            .order_by(WeatherLog.recorded_at.desc())
        )
        return list(result.scalars().all())


class AlertLogRepository:
    """알림 이력"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, **kwargs) -> AlertLog:
        log = AlertLog(**kwargs)
        self._session.add(log)
        await self._session.commit()
        await self._session.refresh(log)
        return log

    async def get_recent_by_worker(
        self, worker_id: int, hours: int = 1
    ) -> list[AlertLog]:
        """최근 N시간 내 발송된 알림 조회 (중복 발송 방지용)"""
        since = datetime.utcnow() - timedelta(hours=hours)
        result = await self._session.execute(
            select(AlertLog).where(
                and_(
                    AlertLog.worker_id == worker_id,
                    AlertLog.sent_at >= since,
                    AlertLog.status == AlertStatus.SENT,
                )
            )
        )
        return list(result.scalars().all())

    async def get_latest_by_site_workers(
        self, site_id: int, worker_ids: list[int]
    ) -> dict[int, AlertLog]:
        """현장의 작업자별 가장 최근 알림 조회"""
        if not worker_ids:
            return {}
        result = await self._session.execute(
            select(AlertLog).where(
                and_(
                    AlertLog.work_site_id == site_id,
                    AlertLog.worker_id.in_(worker_ids),
                )
            ).order_by(AlertLog.sent_at.desc())
        )
        logs = list(result.scalars().all())
        latest = {}
        for log in logs:
            if log.worker_id not in latest:
                latest[log.worker_id] = log
        return latest

    async def get_history(
        self,
        site_id: Optional[int] = None,
        limit: int = 100,
    ) -> list[AlertLog]:
        query = select(AlertLog).order_by(AlertLog.sent_at.desc()).limit(limit)
        if site_id:
            query = query.where(AlertLog.work_site_id == site_id)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_stats(self, days: int = 7) -> dict:
        """알림 통계 (최근 N일)"""
        since = datetime.utcnow() - timedelta(days=days)
        result = await self._session.execute(
            select(AlertLog).where(AlertLog.sent_at >= since)
        )
        logs = list(result.scalars().all())

        stats = {
            "total": len(logs),
            "sent": sum(1 for l in logs if l.status == AlertStatus.SENT),
            "failed": sum(1 for l in logs if l.status == AlertStatus.FAILED),
            "by_stage": {},
        }
        for log in logs:
            stage = log.stage.value if log.stage else "unknown"
            stats["by_stage"][stage] = stats["by_stage"].get(stage, 0) + 1

        return stats
