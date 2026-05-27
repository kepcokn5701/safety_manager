"""
Vercel 서버리스 함수 엔트리포인트
"""

import sys
import os
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Vercel 환경 표시
os.environ.setdefault("VERCEL", "1")

from backend.app import app
