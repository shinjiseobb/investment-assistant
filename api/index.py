import os
import sys

# 루트 디렉토리의 app.py 및 모듈들을 찾을 수 있도록 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
