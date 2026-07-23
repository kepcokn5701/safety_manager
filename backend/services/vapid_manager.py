"""
VAPID 키 관리
- 우선순위: .env 설정 > DB 저장값 > 자동 생성 후 DB 저장
- Vercel 서버리스에서도 키가 유지됨 (DB 기반)
"""

import base64
import json
import logging

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

logger = logging.getLogger(__name__)

_cached_keys: dict | None = None


def _generate_keys() -> dict:
    """ECDSA P-256 VAPID 키 쌍 생성"""
    private_key = ec.generate_private_key(ec.SECP256R1())

    private_numbers = private_key.private_numbers()
    private_bytes = private_numbers.private_value.to_bytes(32, byteorder="big")
    private_b64 = base64.urlsafe_b64encode(private_bytes).decode().rstrip("=")

    public_key = private_key.public_key()
    public_bytes = public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    public_b64 = base64.urlsafe_b64encode(public_bytes).decode().rstrip("=")

    return {"public_key": public_b64, "private_key": private_b64}


def get_vapid_keys() -> dict:
    """
    VAPID 키 반환. 우선순위:
    1. 메모리 캐시
    2. .env에 설정된 값
    3. (DB 로드는 async이므로 별도 초기화 필요)
    4. 자동 생성 (init_vapid_keys_from_db에서 DB 저장)
    """
    global _cached_keys

    if _cached_keys:
        return _cached_keys

    # .env에서 설정된 값 확인
    from backend.config import settings
    if settings.vapid_public_key and settings.vapid_private_key:
        _cached_keys = {
            "public_key": settings.vapid_public_key,
            "private_key": settings.vapid_private_key,
        }
        logger.info("VAPID 키: .env 설정값 사용")
        return _cached_keys

    # DB에서 아직 로드 안 된 경우 → 임시 생성 (앱 시작 시 init_vapid_keys_from_db가 덮어씀)
    _cached_keys = _generate_keys()
    logger.warning("VAPID 키: 임시 생성 (앱 시작 시 DB에서 로드됨)")
    return _cached_keys


async def init_vapid_keys_from_db():
    """
    앱 시작 시 호출 - DB에서 VAPID 키를 로드하거나, 없으면 생성 후 DB에 저장.
    이렇게 하면 Vercel 서버리스에서도 키가 영구 유지됨.
    """
    global _cached_keys

    # .env에 이미 설정되어 있으면 스킵
    from backend.config import settings
    if settings.vapid_public_key and settings.vapid_private_key:
        _cached_keys = {
            "public_key": settings.vapid_public_key,
            "private_key": settings.vapid_private_key,
        }
        logger.info("VAPID 키: .env 설정값 사용")
        return

    from backend.models.database import async_session
    from backend.models.models import SystemSetting
    from sqlalchemy import select

    try:
        async with async_session() as session:
            result = await session.execute(
                select(SystemSetting).where(SystemSetting.key == "vapid_keys")
            )
            setting = result.scalar_one_or_none()

            if setting:
                keys = json.loads(setting.value)
                _cached_keys = keys
                logger.info("VAPID 키: DB에서 로드 완료")
            else:
                # DB에 없으면 생성 후 저장
                keys = _generate_keys()
                session.add(SystemSetting(
                    key="vapid_keys",
                    value=json.dumps(keys),
                ))
                await session.commit()
                _cached_keys = keys
                logger.info("VAPID 키: 자동 생성 후 DB에 저장 완료")
    except Exception as e:
        logger.error(f"VAPID 키 DB 초기화 실패: {e}")
        if not _cached_keys:
            _cached_keys = _generate_keys()
            logger.warning("VAPID 키: 메모리에만 임시 생성")
