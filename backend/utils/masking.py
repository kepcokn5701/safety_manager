"""
개인정보 마스킹 유틸리티
- API 응답에서 전화번호 등 개인정보를 마스킹하여 반환
- DB 저장이나 SMS 발송 로직에는 적용하지 않음
"""


def mask_phone(phone: str) -> str:
    """전화번호 마스킹: 010-1234-5678 -> 010-****-5678, 01012345678 -> 010****5678"""
    if not phone:
        return phone
    digits = phone.replace("-", "")
    if len(digits) >= 8:
        if "-" in phone:
            parts = phone.split("-")
            if len(parts) == 3:
                return f"{parts[0]}-****-{parts[2]}"
        return digits[:3] + "****" + digits[-4:]
    return "****"
