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
            verify=False,
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
    SMS 발송 - NHN Cloud SMS API v3.0
    https://docs.nhncloud.com/ko/Notification/SMS/ko/api-guide/

    API: POST https://sms.api.nhncloudservice.com/sms/v3.0/appKeys/{appKey}/sender/sms
    Header: X-Secret-Key
    Body: {"body":"메시지","sendNo":"발신번호","recipientList":[{"recipientNo":"수신번호"}]}
    """

    BASE_URL = "https://sms.api.nhncloudservice.com/sms/v3.0/appKeys"

    def __init__(self):
        self._app_key = settings.sms_app_key
        self._secret_key = settings.sms_secret_key
        self._sender = settings.sms_sender_phone
        self._client = httpx.AsyncClient(timeout=10.0, verify=False)

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

        if not self._app_key or not self._secret_key:
            return NotificationResult(
                success=False, channel="sms", recipient=recipient_phone,
                error_message="NHN Cloud SMS 미설정",
            )

        phone = recipient_phone.replace("-", "")
        try:
            response = await self._client.post(
                f"{self.BASE_URL}/{self._app_key}/sender/sms",
                headers={
                    "Content-Type": "application/json;charset=UTF-8",
                    "X-Secret-Key": self._secret_key,
                },
                json={
                    "body": message,
                    "sendNo": self._sender.replace("-", ""),
                    "recipientList": [{"recipientNo": phone}],
                },
            )
            data = response.json()
            ok = data.get("header", {}).get("isSuccessful", False)
            if ok:
                logger.info(f"[SMS] {recipient_name}({phone}): 성공")
            else:
                logger.warning(f"[SMS] {recipient_name}({phone}): {data.get('header',{}).get('resultMessage','')}")
            return NotificationResult(
                success=ok, channel="sms", recipient=recipient_phone,
                message_id=str(data.get("body", {}).get("data", {}).get("requestId", "")),
                error_message=None if ok else data.get("header", {}).get("resultMessage", "발송 실패"),
            )
        except Exception as e:
            logger.error(f"[SMS] 발송 실패: {e}")
            return NotificationResult(
                success=False, channel="sms", recipient=recipient_phone,
                error_message=str(e)[:100],
            )

    async def send_bulk(self, phone_numbers: list[str], message: str,
                        workers: list[dict] | None = None) -> dict:
        """여러 번호에 일괄 발송 (최대 1000명)

        workers: [{"name": "홍길동", "phone": "010-1234-5678", "site": "현장A"}, ...]
        workers가 주어지면 phone_numbers 대신 workers 기준으로 발송
        """
        # workers 목록이 있으면 그걸 기준으로 사용
        if workers:
            phone_list = [w.get("phone", "") for w in workers if w.get("phone")]
        else:
            phone_list = [p for p in phone_numbers if p]

        # 이름/현장 매핑 (상세 결과용)
        phone_to_info = {}
        if workers:
            for w in workers:
                phone = w.get("phone", "").replace("-", "")
                phone_to_info[phone] = {
                    "name": w.get("name", ""),
                    "site": w.get("site", ""),
                }

        if not self._app_key or not self._secret_key:
            sender_phone = self._sender or "(미설정)"
            details = []
            for p in phone_list:
                pn = p.replace("-", "")
                info = phone_to_info.get(pn, {})
                details.append({
                    "phone": p,
                    "name": info.get("name", ""),
                    "site": info.get("site", ""),
                    "status": "failed",
                    "error": "SMS API 미설정",
                })
            return {
                "sent": 0,
                "failed": len(phone_list),
                "error": "NHN Cloud SMS 미설정 — .env 파일에서 SMS_APP_KEY, SMS_SECRET_KEY, SMS_SENDER_PHONE 값을 확인하세요.",
                "error_code": "CONFIG_MISSING",
                "details": details,
            }

        recipients = [{"recipientNo": p.replace("-", "")} for p in phone_list]
        if not recipients:
            return {"sent": 0, "failed": 0, "details": []}

        try:
            response = await self._client.post(
                f"{self.BASE_URL}/{self._app_key}/sender/sms",
                headers={
                    "Content-Type": "application/json;charset=UTF-8",
                    "X-Secret-Key": self._secret_key,
                },
                json={
                    "body": message,
                    "sendNo": self._sender.replace("-", ""),
                    "recipientList": recipients,
                },
            )
            data = response.json()
            header = data.get("header", {})
            ok = header.get("isSuccessful", False)
            result_code = header.get("resultCode", -1)
            result_message = header.get("resultMessage", "알 수 없는 오류")

            details = []

            if ok:
                # 성공 시 sendResultList에서 개별 수신자 결과 파싱
                send_result_list = data.get("body", {}).get("data", {}).get("sendResultList", [])
                sent_count = 0
                fail_count = 0
                for i, r in enumerate(send_result_list):
                    recipient_no = r.get("recipientNo", "")
                    recipient_seq = r.get("resultCode", 0)
                    recipient_msg = r.get("resultMessage", "")
                    info = phone_to_info.get(recipient_no, {})

                    # NHN Cloud: resultCode 0 = 성공
                    if recipient_seq == 0:
                        sent_count += 1
                        details.append({
                            "phone": recipient_no,
                            "name": info.get("name", ""),
                            "site": info.get("site", ""),
                            "status": "sent",
                        })
                    else:
                        fail_count += 1
                        details.append({
                            "phone": recipient_no,
                            "name": info.get("name", ""),
                            "site": info.get("site", ""),
                            "status": "failed",
                            "error": recipient_msg or f"오류코드: {recipient_seq}",
                        })

                # sendResultList가 비어있으면 전체 성공으로 간주
                if not send_result_list:
                    sent_count = len(recipients)
                    for rec in recipients:
                        pn = rec["recipientNo"]
                        info = phone_to_info.get(pn, {})
                        details.append({
                            "phone": pn,
                            "name": info.get("name", ""),
                            "site": info.get("site", ""),
                            "status": "sent",
                        })

                result = {"sent": sent_count, "failed": fail_count, "details": details}
                if fail_count > 0:
                    result["error"] = f"{fail_count}건 발송 실패 (상세 내역 확인)"
                return result
            else:
                # API 자체 실패 — 전체 실패
                # 주요 에러코드 한글 매핑
                error_reasons = {
                    -1000: "필수 파라미터 누락 (appKey, body, sendNo 등)",
                    -1001: "유효하지 않은 파라미터 값",
                    -2000: "인증 실패 — SMS_SECRET_KEY가 올바른지 확인하세요",
                    -2001: "권한 없음 — NHN Cloud 콘솔에서 SMS 서비스가 활성화되었는지 확인하세요",
                    -3000: "등록되지 않은 발신번호 — SMS_SENDER_PHONE이 NHN Cloud에 등록되어 있는지 확인하세요",
                    -3001: "비활성화된 발신번호",
                    -4000: "발송 잔여 건수 초과 — NHN Cloud 콘솔에서 발송 한도를 확인하세요",
                    -5000: "내부 서버 오류 — 잠시 후 재시도해 주세요",
                }
                friendly_msg = error_reasons.get(result_code, result_message)
                error_detail = f"[코드: {result_code}] {friendly_msg}"

                for rec in recipients:
                    pn = rec["recipientNo"]
                    info = phone_to_info.get(pn, {})
                    details.append({
                        "phone": pn,
                        "name": info.get("name", ""),
                        "site": info.get("site", ""),
                        "status": "failed",
                        "error": friendly_msg,
                    })

                logger.error(f"[SMS] 일괄 발송 실패: {error_detail}")
                return {
                    "sent": 0,
                    "failed": len(recipients),
                    "error": error_detail,
                    "error_code": str(result_code),
                    "details": details,
                }
        except httpx.ConnectError as e:
            error_msg = f"네트워크 연결 실패 — 인터넷 연결 또는 프록시 설정을 확인하세요. ({str(e)[:80]})"
            logger.error(f"[SMS] {error_msg}")
            details = []
            for rec in recipients:
                pn = rec["recipientNo"]
                info = phone_to_info.get(pn, {})
                details.append({
                    "phone": pn, "name": info.get("name", ""),
                    "site": info.get("site", ""),
                    "status": "failed", "error": "네트워크 연결 실패",
                })
            return {"sent": 0, "failed": len(recipients), "error": error_msg,
                    "error_code": "NETWORK_ERROR", "details": details}
        except httpx.TimeoutException:
            error_msg = "API 응답 시간 초과 (10초) — NHN Cloud 서버가 응답하지 않습니다. 잠시 후 재시도해 주세요."
            logger.error(f"[SMS] {error_msg}")
            details = []
            for rec in recipients:
                pn = rec["recipientNo"]
                info = phone_to_info.get(pn, {})
                details.append({
                    "phone": pn, "name": info.get("name", ""),
                    "site": info.get("site", ""),
                    "status": "failed", "error": "응답 시간 초과",
                })
            return {"sent": 0, "failed": len(recipients), "error": error_msg,
                    "error_code": "TIMEOUT", "details": details}
        except Exception as e:
            error_msg = f"예기치 않은 오류: {type(e).__name__} — {str(e)[:120]}"
            logger.error(f"[SMS] {error_msg}")
            details = []
            for rec in recipients:
                pn = rec["recipientNo"]
                info = phone_to_info.get(pn, {})
                details.append({
                    "phone": pn, "name": info.get("name", ""),
                    "site": info.get("site", ""),
                    "status": "failed", "error": str(e)[:60],
                })
            return {"sent": 0, "failed": len(recipients), "error": error_msg,
                    "error_code": "UNKNOWN", "details": details}

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
