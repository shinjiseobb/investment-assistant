import os
import logging
from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv
from collector import collect_stock_data

# .env 환경변수 로드
load_dotenv()

# 표준 logging 모듈 설정 (print 사용 금지 규칙 준수)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/health", methods=["GET"])
def health():
    """서버 상태 및 Serper API Key 설정 여부만 반환 (키 값 자체는 절대 노출 금지)"""
    serper_key = os.getenv("SERPER_API_KEY", "").strip()
    has_serper_key = bool(serper_key and serper_key != "your_serper_api_key_here" and len(serper_key) > 5)
    
    logger.info("[REQUEST] GET /health (has_serper_key=%s)", has_serper_key)
    return jsonify({
        "status": "ok",
        "has_serper_key": has_serper_key
    }), 200


@app.route("/fetch", methods=["POST"])
def fetch():
    """종목코드를 받아 네이버 금융 수집 + Serper 뉴스 검색을 통합 실행하고 JSON을 반환한다."""
    payload = request.get_json(silent=True) or {}
    code = payload.get("code", "")

    logger.info("[REQUEST] POST /fetch code=%s", code)
    result = collect_stock_data(code)

    # 종목명조차 찾지 못한 완전 실패(유효성/404 등)는 400, 부분 성공 이상은 200 반환
    status_code = 400 if (not result.get("name") and result.get("errors")) else 200
    return jsonify(result), status_code

if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    logger.info("[START] Flask 서버 구동: http://127.0.0.1:5000 (debug=%s)", debug_mode)
    app.run(host="127.0.0.1", port=5000, debug=debug_mode)
