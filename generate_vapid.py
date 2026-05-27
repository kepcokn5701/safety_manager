"""
VAPID 키 생성 스크립트
웹 푸시 알림에 필요한 공개키/비밀키를 생성합니다.

사용법:
    python generate_vapid.py

생성된 키를 .env 파일의 VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY에 붙여넣으세요.
"""

import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization


def generate_vapid_keys():
    # ECDSA P-256 키 생성
    private_key = ec.generate_private_key(ec.SECP256R1())

    # 비밀키 → URL-safe base64
    private_numbers = private_key.private_numbers()
    private_bytes = private_numbers.private_value.to_bytes(32, byteorder="big")
    private_b64 = base64.urlsafe_b64encode(private_bytes).decode("utf-8").rstrip("=")

    # 공개키 → URL-safe base64 (비압축 형식 65바이트)
    public_key = private_key.public_key()
    public_bytes = public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    public_b64 = base64.urlsafe_b64encode(public_bytes).decode("utf-8").rstrip("=")

    return private_b64, public_b64


if __name__ == "__main__":
    priv, pub = generate_vapid_keys()

    print()
    print("=" * 60)
    print("  VAPID 키 생성 완료!")
    print("=" * 60)
    print()
    print("아래 값을 .env 파일에 붙여넣으세요:")
    print()
    print(f"VAPID_PRIVATE_KEY={priv}")
    print(f"VAPID_PUBLIC_KEY={pub}")
    print()
    print("=" * 60)
