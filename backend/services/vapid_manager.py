"""
VAPID 키 자동 관리
- 키가 없으면 서버 시작 시 자동 생성
- 생성된 키를 파일에 저장하여 재시작해도 유지
"""

import base64
import json
import logging
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

logger = logging.getLogger(__name__)

# 키 저장 경로 (Vercel: /tmp/, 로컬: 프로젝트 루트)
_is_vercel = bool(os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"))
_KEY_FILE = Path("/tmp/vapid_keys.json") if _is_vercel else Path(__file__).resolve().parent.parent.parent / "vapid_keys.json"

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
    3. 파일에 저장된 값
    4. 자동 생성 후 파일에 저장
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

    # 파일에서 로드
    if _KEY_FILE.exists():
        try:
            with open(_KEY_FILE, "r") as f:
                _cached_keys = json.load(f)
            logger.info(f"VAPID 키: 파일에서 로드 ({_KEY_FILE})")
            return _cached_keys
        except Exception:
            pass

    # 자동 생성
    _cached_keys = _generate_keys()
    try:
        with open(_KEY_FILE, "w") as f:
            json.dump(_cached_keys, f)
        logger.info(f"VAPID 키: 자동 생성 후 저장 ({_KEY_FILE})")
    except Exception as e:
        logger.warning(f"VAPID 키 파일 저장 실패 (메모리에만 유지): {e}")

    return _cached_keys
