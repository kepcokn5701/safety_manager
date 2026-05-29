"""
알림 서비스 - 카카오 알림톡 구현체 + 콘솔 출력(개발용)
"""

import logging
from datetime import datetime

import httpx

from backend.config import settings
from backend.services.interfaces import NotificationSender, NotificationResult

logger = logging.getLogger(__name__)


class KakaoAlimTalkSender(NotificationSender):
    """
    카카오 알림톡 발송 구현체

    사전 준비:
    1. 카카오 비즈니스 채널 개설
    2. 알림톡 발신 프로필 등록
    3. 메시지 템플릿 등록 (폭염 단계별)
    4. .env에 API 키 설정
    """

    SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    BIZ_SEND_URL = "https://kapi.kakao.com/v1/api/talk/friends/message/default/send"

    def __init__(self):
        proxy_config = settings.get_proxy_dict()
        self._client = httpx.AsyncClient(
            timeout=10.0,
            proxy=proxy_config.get("https://") or proxy_config.get("http://"),
        )
        self._api_key = settings.kakao_rest_api_key
        self._sender_key = settings.kakao_sender_key

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
        """카카오 알림톡으로 폭염 경보 발송"""

        message_text = self._build_message(
            recipient_name, stage_name, temperature, work_site_name, actions
        )

        # 알림톡 비즈 메시지 API 호출
        template_code = self._get_template_code(stage_name)

        payload = {
            "senderkey": self._sender_key,
            "template_code": template_code,
            "receiver_num": recipient_phone.replace("-", ""),
            "message": message_text,
        }

        headers = {
            "Authorization": f"KakaoAK {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = await self._client.post(
                self.BIZ_SEND_URL,
                json=payload,
                headers=headers,
            )

            if response.status_code == 200:
                result_data = response.json()
                return NotificationResult(
                    success=True,
                    channel="kakao_alimtalk",
                    recipient=recipient_phone,
                    message_id=str(result_data.get("result_code", "")),
                )
            else:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                logger.error(f"카카오 알림톡 발송 실패: {error_msg}")
                return NotificationResult(
                    success=False,
                    channel="kakao_alimtalk",
                    recipient=recipient_phone,
                    error_message=error_msg,
                )

        except httpx.RequestError as e:
            error_msg = f"네트워크 오류: {str(e)}"
            logger.error(f"카카오 알림톡 발송 실패: {error_msg}")
            return NotificationResult(
                success=False,
                channel="kakao_alimtalk",
                recipient=recipient_phone,
                error_message=error_msg,
            )

    def _build_message(
        self,
        name: str,
        stage_name: str,
        temperature: float,
        work_site_name: str,
        actions: list[str],
    ) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        actions_text = "\n".join(f"  - {a}" for a in actions[:4])

        return (
            f"[KEPCO 안전관리] 폭염 {stage_name} 단계\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"■ 대상자: {name}님\n"
            f"■ 현장: {work_site_name}\n"
            f"■ 체감온도: {temperature}°C\n"
            f"■ 발령시각: {now}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"[조치사항]\n{actions_text}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"안전이 최우선입니다. 건강에 유의하세요."
        )

    def _get_template_code(self, stage_name: str) -> str:
        mapping = {
            "주의": settings.kakao_template_code_caution,
            "경고": settings.kakao_template_code_warning,
            "위험": settings.kakao_template_code_danger,
        }
        return mapping.get(stage_name, settings.kakao_template_code_caution)

    async def close(self) -> None:
        await self._client.aclose()


class SmsSender(NotificationSender):
    """
    SMS 발송 - Traccar SMS Gateway 앱 연동
    Play Store: "Traccar SMS Gateway" (anton tananaev)
    폰에서 HTTP API를 노출 → 서버가 호출 → 폰이 문자 발송

    API: POST http://폰IP:8082/
         Header: Authorization: API키
         Body: {"to": "+821012345678", "message": "내용"}
    """

    def __init__(self):
        self._gateway_url = settings.sms_gateway_url
        self._api_key = settings.sms_gateway_api_key
        self._client = httpx.AsyncClient(timeout=10.0)

    def _format_phone(self, phone: str) -> str:
        """010-1234-5678 → +821012345678"""
        digits = phone.replace("-", "").replace(" ", "")
        if digits.startswith("0"):
            return "+82" + digits[1:]
        return digits if digits.startswith("+") else "+" + digits

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
        message = (
            f"[KEPCO 안전관리] 폭염 {stage_name}\n"
            f"현장: {work_site_name}\n"
            f"체감온도: {temperature}°C\n"
            f"{actions[0] if actions else '안전에 유의하세요.'}"
        )

        if not self._gateway_url:
            return NotificationResult(
                success=False, channel="sms", recipient=recipient_phone,
                error_message="SMS Gateway 미설정",
            )

        try:
            response = await self._client.post(
                self._gateway_url.rstrip("/") + "/",
                json={"to": self._format_phone(recipient_phone), "message": message},
                headers={"Authorization": self._api_key} if self._api_key else {},
            )
            ok = response.status_code in (200, 201, 202, 204)
            if ok:
                logger.info(f"[SMS] {recipient_name}({recipient_phone}): 발송 성공")
            else:
                logger.warning(f"[SMS] {recipient_name}({recipient_phone}): HTTP {response.status_code}")
            return NotificationResult(
                success=ok, channel="sms", recipient=recipient_phone,
                error_message=None if ok else f"HTTP {response.status_code}",
            )
        except Exception as e:
            logger.error(f"[SMS] 발송 실패: {e}")
            return NotificationResult(
                success=False, channel="sms", recipient=recipient_phone,
                error_message=str(e)[:100],
            )

    async def send_bulk(self, phone_numbers: list[str], message: str) -> dict:
        """여러 번호에 순차 발송 (Traccar는 1건씩)"""
        if not self._gateway_url:
            return {"sent": 0, "failed": len(phone_numbers), "error": "SMS Gateway 미설정"}

        sent = 0
        failed = 0
        for phone in phone_numbers:
            if not phone:
                continue
            try:
                response = await self._client.post(
                    self._gateway_url.rstrip("/") + "/",
                    json={"to": self._format_phone(phone), "message": message},
                    headers={"Authorization": self._api_key} if self._api_key else {},
                )
                if response.status_code in (200, 201, 202, 204):
                    sent += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
        return {"sent": sent, "failed": failed}

    async def close(self) -> None:
        await self._client.aclose()


class ConsoleSender(NotificationSender):
    """
    콘솔 출력용 알림 발송자 (개발/테스트용)
    실제 API 호출 없이 콘솔에 메시지 출력
    """

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
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        actions_text = "\n".join(f"    - {a}" for a in actions)

        print(
            f"\n{'='*50}\n"
            f"  [콘솔 알림] 폭염 {stage_name} 단계\n"
            f"  대상: {recipient_name} ({recipient_phone})\n"
            f"  현장: {work_site_name}\n"
            f"  체감온도: {temperature}°C\n"
            f"  시각: {now}\n"
            f"  조치사항:\n{actions_text}\n"
            f"{'='*50}\n"
        )

        return NotificationResult(
            success=True,
            channel="console",
            recipient=recipient_phone,
            message_id=f"console_{now}",
        )

    async def close(self) -> None:
        pass
