"""
Vercel 서버리스 함수 엔트리포인트
Vercel의 Python Runtime이 이 파일을 ASGI 앱으로 인식합니다.
"""

import sys
import os

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import app
