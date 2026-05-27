"""
Safety Manager 실행 스크립트
사용법: python run.py
"""

import uvicorn
from backend.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "backend.app:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=(settings.app_env == "development"),
    )
