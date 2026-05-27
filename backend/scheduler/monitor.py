"""
폭염 모니터링 스케줄러
- 설정된 간격(기본 15분)으로 모든 옥외 작업현장의 날씨를 확인
- 폭염 단계 판정 후 해당 현장 작업자에게 알림 발송
- 중복 발송 방지 (같은 단계 알림은 1시간 내 재발송 안 함)
"""

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.models import AlertStage, AlertStatus
from backend.services.interfaces import WeatherProvider, NotificationSender
from backend.services.repository import (
    WorkSiteRepository,
    WorkerRepository,
    WeatherLogRepository,
    AlertLogRepository,
)
from backend.services.weather_service import HeatIndexCalculator, ThresholdManager

logger = logging.getLogger(__name__)


class HeatWaveMonitor:
    """
    폭염 모니터링 핵심 로직
    - WeatherProvider, NotificationSender를 인터페이스로 주입받음
    - DB 세션도 외부에서 주입
    """

    def __init__(
        self,
        weather_provider: WeatherProvider,
        notification_sender: NotificationSender,
        threshold_manager: ThresholdManager,
    ):
        self._weather = weather_provider
        self._notifier = notification_sender
        self._thresholds = threshold_manager

    async def check_all_sites(self, session: AsyncSession, site_ids: list[int] | None = None) -> dict:
        """
        작업현장 날씨 확인 & 알림 발송
        site_ids가 주어지면 해당 현장만, 없으면 전체 활성 현장
        """
        site_repo = WorkSiteRepository(session)
        if site_ids:
            all_sites = await site_repo.get_all_outdoor_active()
            sites = [s for s in all_sites if s.id in site_ids]
        else:
            sites = await site_repo.get_all_outdoor_active()

        result = {
            "checked_at": datetime.now().isoformat(),
            "sites_checked": 0,
            "alerts_sent": 0,
            "alerts_skipped": 0,
            "errors": [],
        }

        for site in sites:
            try:
                await self._check_site(session, site, site_repo, result)
                result["sites_checked"] += 1
            except Exception as e:
                error_msg = f"현장 '{site.name}'(ID:{site.id}) 모니터링 실패: {str(e)}"
                logger.error(error_msg, exc_info=True)
                result["errors"].append(error_msg)

        logger.info(
            f"모니터링 완료: {result['sites_checked']}개 현장, "
            f"{result['alerts_sent']}건 알림 발송, "
            f"{result['alerts_skipped']}건 스킵"
        )
        return result

    async def _check_site(self, session, site, site_repo, result):
        """개별 현장 날씨 확인 및 알림 처리"""

        # 1. 날씨 조회
        weather = await self._weather.get_current_weather(
            site.latitude, site.longitude
        )

        # 2. 체감온도 & WBGT 계산
        apparent_temp = HeatIndexCalculator.calculate_heat_index(
            weather.temperature, weather.humidity
        )
        wbgt = HeatIndexCalculator.estimate_wbgt_outdoor(
            weather.temperature, weather.humidity, weather.wind_speed
        )

        # 3. 단계 판정
        stage_info = self._thresholds.determine_stage(apparent_temp)

        # 4. 날씨 기록 저장
        log_repo = WeatherLogRepository(session)
        await log_repo.create(
            work_site_id=site.id,
            temperature=weather.temperature,
            humidity=weather.humidity,
            wind_speed=weather.wind_speed,
            apparent_temperature=apparent_temp,
            wbgt_estimated=wbgt,
            stage=stage_info["key"] if stage_info else None,
        )

        # 5. 단계가 "주의" 이상이면 알림 발송
        if not stage_info or stage_info["key"] == "stage_1_interest":
            return

        # 6. 현장 작업자들에게 알림
        workers = await site_repo.get_workers(site.id)
        alert_repo = AlertLogRepository(session)

        # 발송 대상 작업자 확인 (중복 방지 체크)
        workers_to_alert = []
        for worker in workers:
            recent = await alert_repo.get_recent_by_worker(worker.id, hours=1)
            already_sent = any(
                a.stage.value == stage_info["key"] for a in recent
            )
            if already_sent:
                result["alerts_skipped"] += 1
            else:
                workers_to_alert.append(worker)

        if not workers_to_alert:
            return

        # 현장 단위로 1회 타겟 푸시 발송 (해당 현장 worker 구독자에게)
        notif_result = await self._notifier.send(
            recipient_phone="site_broadcast",
            recipient_name=f"{site.name} 작업자",
            stage_name=stage_info["name"],
            temperature=apparent_temp,
            work_site_name=site.name,
            actions=stage_info["actions"],
            site_id=site.id,
        )

        # 각 작업자별 알림 이력 기록 (푸시 성공/실패와 무관하게 처리)
        push_ok = notif_result.success
        for worker in workers_to_alert:
            await alert_repo.create(
                worker_id=worker.id,
                work_site_id=site.id,
                stage=stage_info["key"],
                apparent_temperature=apparent_temp,
                wbgt_estimated=wbgt,
                message=f"폭염 {stage_info['name']} 단계 - 체감온도 {apparent_temp}°C",
                channel=notif_result.channel,
                status=AlertStatus.SENT if push_ok else AlertStatus.FAILED,
                error_message=notif_result.error_message,
            )
            result["alerts_sent"] += 1

        # 관리자에게 요약 푸시 1건 발송 (worker 발송 결과와 무관하게 항상)
        from backend.services.push_service import WebPushSender
        if isinstance(self._notifier, WebPushSender):
            await self._notifier.send_admin_summary(
                stage_name=stage_info["name"],
                temperature=apparent_temp,
                work_site_name=site.name,
                sent_count=len(workers_to_alert),
                total_count=len(workers),
                site_id=site.id,
                push_success=push_ok,
            )
