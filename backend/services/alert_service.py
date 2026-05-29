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
    SMS 발송 - Android SMS Gateway 앱 연동
    안드로이드 폰에 SMS Gateway 앱 설치 → 폰이 SMS 게이트웨이 역할
    - 로컬 모드: 같은 네트워크에서 폰 IP로 직접 호출
    - 클라우드 모드: sms.capcom.me 클라우드 릴레이
    """

    def __init__(self):
        self._gateway_url = settings.sms_gateway_url  # 폰의 IP 또는 클라우드 URL
        self._gateway_login = settings.sms_gateway_login
        self._gateway_password = settings.sms_gateway_password
        proxy_config = settings.get_proxy_dict()
        self._client = httpx.AsyncClient(
            timeout=15.0,
            proxy=proxy_config.get("https://") or proxy_config.get("http://"),
        )

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
            logger.info(f"[SMS 미설정] {recipient_name}({recipient_phone}): {message[:50]}")
            return NotificationResult(
                success=False, channel="sms", recipient=recipient_phone,
                error_message="SMS Gateway URL 미설정 (.env에 SMS_GATEWAY_URL 설정 필요)",
            )

        phone_number = recipient_phone.replace("-", "")
        try:
            # Android SMS Gateway API 호출
            headers = {}
            if self._gateway_login and self._gateway_password:
                import base64
                creds = base64.b64encode(f"{self._gateway_login}:{self._gateway_password}".encode()).decode()
                headers["Authorization"] = f"Basic {creds}"

            response = await self._client.post(
                f"{self._gateway_url.rstrip('/')}/message",
                json={
                    "message": message,
                    "phoneNumbers": [phone_number],
                },
                headers=headers,
            )

            if response.status_code in (200, 201, 202):
                logger.info(f"[SMS] {recipient_name}({recipient_phone}): 발송 성공")
                return NotificationResult(
                    success=True, channel="sms", recipient=recipient_phone,
                    message_id=str(response.json().get("id", "")),
                )
            else:
                error = f"HTTP {response.status_code}: {response.text[:100]}"
                logger.warning(f"[SMS] {recipient_name}({recipient_phone}): 실패 - {error}")
                return NotificationResult(
                    success=False, channel="sms", recipient=recipient_phone,
                    error_message=error,
                )
        except Exception as e:
            logger.error(f"[SMS] 발송 실패: {e}")
            return NotificationResult(
                success=False, channel="sms", recipient=recipient_phone,
                error_message=str(e)[:100],
            )

    async def send_bulk(self, phone_numbers: list[str], message: str) -> dict:
        """여러 번호에 동일 메시지 일괄 발송"""
        if not self._gateway_url:
            return {"sent": 0, "failed": len(phone_numbers), "error": "SMS Gateway 미설정"}

        clean_numbers = [p.replace("-", "") for p in phone_numbers if p]
        if not clean_numbers:
            return {"sent": 0, "failed": 0}

        try:
            headers = {}
            if self._gateway_login and self._gateway_password:
                import base64
                creds = base64.b64encode(f"{self._gateway_login}:{self._gateway_password}".encode()).decode()
                headers["Authorization"] = f"Basic {creds}"

            response = await self._client.post(
                f"{self._gateway_url.rstrip('/')}/message",
                json={"message": message, "phoneNumbers": clean_numbers},
                headers=headers,
            )
            if response.status_code in (200, 201, 202):
                return {"sent": len(clean_numbers), "failed": 0}
            else:
                return {"sent": 0, "failed": len(clean_numbers), "error": response.text[:100]}
        except Exception as e:
            return {"sent": 0, "failed": len(clean_numbers), "error": str(e)[:100]}

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
