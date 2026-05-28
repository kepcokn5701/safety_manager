"""
환경 설정 모듈
- .env 파일 기반 설정
- 사내망 이관 시 환경변수만 변경하면 동작
- 프록시 설정 지원
"""

import os
from pathlib import Path

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional

# Vercel 환경에서는 /tmp/ 에만 쓰기 가능
_is_vercel = bool(os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"))


def _resolve_database_url() -> str:
    """데이터베이스 URL 결정 (POSTGRES_URL > DATABASE_URL > SQLite)"""
    pg_url = (os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL") or "").strip()

    if pg_url and pg_url.startswith(("postgres://", "postgresql://")):
        from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
        parsed = urlparse(pg_url)
        # asyncpg 호환 파라미터만 유지
        clean_q = {}
        for k, v in parse_qs(parsed.query).items():
            if k == "sslmode":
                clean_q["ssl"] = v
            elif k in ("ssl", "timeout", "command_timeout", "statement_cache_size"):
                clean_q[k] = v
            # supa, sslcert 등 asyncpg 미지원 파라미터 제거
        if "ssl" not in clean_q:
            clean_q["ssl"] = ["require"]
        query = urlencode({k: v[0] for k, v in clean_q.items()})
        return urlunparse(parsed._replace(scheme="postgresql+asyncpg", query=query))

    if _is_vercel:
        return "sqlite+aiosqlite:////tmp/safety_manager.db"
    return "sqlite+aiosqlite:///./safety_manager.db"


_default_db = _resolve_database_url()


class Settings(BaseSettings):
    # 서버
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_env: str = "development"

    # 데이터베이스 (SQLite ↔ PostgreSQL 교체 가능)
    database_url: str = _default_db

    # 카카오 API
    kakao_rest_api_key: str = ""
    kakao_java_script_key: str = ""
    kakao_sender_key: str = ""
    kakao_template_code_caution: str = "heat_caution"
    kakao_template_code_warning: str = "heat_warning"
    kakao_template_code_danger: str = "heat_danger"

    # 기상청 API (공공데이터포털 서비스키)
    kma_api_key: str = ""

    # 프록시 설정 (사내망 프록시 대비)
    http_proxy: Optional[str] = None
    https_proxy: Optional[str] = None
    no_proxy: Optional[str] = None

    # 기상 모니터링
    weather_check_interval_minutes: int = 15
    default_latitude: float = 37.5665
    default_longitude: float = 126.9780

    # 웹 푸시 알림 (VAPID 키 - 비어있으면 서버가 자동 생성)
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_email: str = "safety@kepco.co.kr"

    # 알림 채널 선택: "web_push" | "kakao" | "console"
    notification_channel: str = "web_push"

    # SMS 설정 (추후 연동)
    sms_api_key: str = ""
    sms_sender_phone: str = ""       # 발신번호
    sms_provider: str = ""           # "nhn_cloud" | "coolsms" | ""

    # 기준값 설정 파일 경로
    thresholds_config_path: str = "config/thresholds.json"

    # 로깅
    log_level: str = "INFO"

    model_config = {
        "env_file": ".env" if not _is_vercel else None,
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }

    def get_proxy_dict(self) -> dict[str, str]:
        """httpx용 프록시 설정 반환"""
        proxies = {}
        if self.http_proxy:
            proxies["http://"] = self.http_proxy
        if self.https_proxy:
            proxies["https://"] = self.https_proxy
        return proxies if proxies else {}


settings = Settings()
