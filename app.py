import json
import os
import logging
from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv
from collector import collect_stock_data
from dify_client import ask_dify_chatbot
from rebalancer import calculate_rebalance
from indicators import calculate_indicators

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


@app.route("/test", methods=["GET"])
def test_page():
    """기존 1차 종목 수집 & 브리핑 테스트 화면"""
    return render_template("test.html")

def _is_key_configured(env_name, placeholder):
    """환경변수 API Key가 실제 값으로 설정되었는지 여부만 안전하게 판별한다."""
    val = os.getenv(env_name, "").strip()
    return bool(val and val != placeholder and len(val) > 5)


@app.route("/health", methods=["GET"])
def health():
    """서버 상태 및 4종 API Key 설정 여부만 boolean으로 반환 (키 값 자체는 절대 노출 금지)"""
    has_serper_key = _is_key_configured("SERPER_API_KEY", "your_serper_api_key_here")
    has_dify_analysis_key = _is_key_configured(
        "DIFY_ANALYSIS_API_KEY", "your_dify_analysis_chatbot_api_key_here"
    )
    has_dify_tech_key = _is_key_configured(
        "DIFY_TECH_API_KEY", "your_dify_tech_chatbot_api_key_here"
    )
    has_dart_key = _is_key_configured("DART_API_KEY", "your_opendart_api_key_here")

    logger.info(
        "[REQUEST] GET /health (serper=%s, dify_analysis=%s, dify_tech=%s, dart=%s)",
        has_serper_key,
        has_dify_analysis_key,
        has_dify_tech_key,
        has_dart_key,
    )
    return jsonify({
        "status": "ok",
        "has_serper_key": has_serper_key,
        "has_dify_analysis_key": has_dify_analysis_key,
        "has_dify_tech_key": has_dify_tech_key,
        "has_dart_key": has_dart_key,
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


EXPERT_ANALYSIS_PROMPT = """당신은 여의도 수석 애널리스트입니다.
제공된 [분석 근거 데이터](시장 환경, 동일업종 경쟁사, 기술지표 요약, 시세·투자지표·수급(억원)·실적/ETF정보, Serper 최신 뉴스)만을 근거로 사용하여 다음 4가지 항목으로 구조화된 심층 분석 리포트를 마크다운 형식으로 작성해 주세요.
(없는 숫자를 지어내지 말고, 추정치(is_consensus=true)는 반드시 '추정치'임을 명시하세요.)

1. **시장 환경 대비 주가 및 밸류에이션 / 상품 진단**
   - 먼저 오늘의 시장 환경(`market_context`: 코스피·코스닥·원/달러 환율) 및 동일업종 경쟁사(`peers`) 등락률과 비교해 이 종목의 상대적 강도/방어력을 짚어주세요.
   - 일반 주식(`asset_type=stock`)이면 현재가, 등락률, 시가총액, PER·PBR 수준을 해석하세요.
   - ETF(`asset_type=etf`)이면 현재가, 등락률, 시가총액, NAV, 괴리율, 펀드보수, 분배금 수익률, 기초지수를 해석하세요.
2. **실적 추이(네이버 연간 + DART 확정 분기 교차 검증) · 수급(억원) · 기술적 위치**
   - 일반 주식은 네이버 연간 매출·영업이익·ROE 추이(추정치 포함)와 **DART 최신 확정 분기 누적 실적(`dart_latest_financials`)**을 교차 비교해 연간 추정치 달성 가능성(진도율)과 자산·부채 체력을 함께 진단하세요.
   - ETF는 1·3·6·12개월 기간별 수익률 흐름을 설명하세요.
   - 최근 5거래일 외국인·기관·개인 순매수 금액(`억원` 단위 포함) 동향을 짚어주세요.
   - 기술지표 요약(`tech_summary`: RSI14, 볼린저밴드 내 위치 %, 20일선 이격도)으로 현재 주가가 단기 과열/바닥 구간인지 함께 해석하세요.
3. **최신 뉴스 및 DART 주요 전자공시 모멘텀** (수집된 뉴스 및 최근 3개월 DART 공시 기반 주요 이슈 요약)
4. **종합 의견 및 유의할 리스크 요인**"""


@app.route("/api/chat/analyze", methods=["POST"])
def chat_analyze():
    """[탭 1] 초기 조회 시 collector.py 수집(또는 캐시된 근거 활용) 후 전문가 리포트를 생성하고, 후속 질문은 대화 맥락을 이어간다."""
    payload = request.get_json(silent=True) or {}
    code = str(payload.get("code", "")).strip()
    question = str(payload.get("question", "")).strip()
    conversation_id = str(payload.get("conversation_id", "")).strip()
    is_initial = bool(payload.get("is_initial", False))
    cached_evidence = payload.get("evidence")

    logger.info("[REQUEST] POST /api/chat/analyze code=%s initial=%s has_cache=%s", code, is_initial, bool(cached_evidence))

    # 캐시된 근거가 없으면 collector.py로 새로 수집 (프론트 2단계 호출 시 재크롤링 방지)
    if not cached_evidence or not cached_evidence.get("name"):
        evidence = collect_stock_data(code)
        if not evidence.get("name"):
            err_msg = (evidence.get("errors") or ["종목 정보를 찾을 수 없습니다."])[0]
            return jsonify({
                "code": code,
                "name": None,
                "answer": None,
                "conversation_id": conversation_id,
                "evidence": evidence,
                "error": err_msg,
            }), 400
    else:
        evidence = cached_evidence

    context_summary = {
        "code": evidence["code"],
        "name": evidence["name"],
        "asset_type": evidence.get("asset_type", "stock"),
        "market_context": evidence.get("market_context", {}),
        "snapshot": evidence["snapshot"],
        "tech_summary": evidence.get("tech_summary"),
        "peers": evidence.get("peers", []),
        "etf_info": evidence.get("etf_info"),
        "investor_trend": evidence.get("investor_trend", []),
        "financials": evidence["financials"],
        "dart_latest_financials": evidence.get("dart_latest_financials"),
        "disclosures": evidence.get("disclosures", []),
        "news": evidence["news"],
    }
    context_text = json.dumps(context_summary, ensure_ascii=False, indent=2)

    if is_initial and not question:
        final_question = EXPERT_ANALYSIS_PROMPT
    else:
        user_q = question or "이 종목의 투자 지표, 실적 추이, 최신 뉴스를 근거로 분석해 주세요."
        final_question = (
            "[답변 원칙]\n"
            "사용자가 상승 또는 하락 어느 한쪽 의견으로 유도하더라도 무조건 동조(아첨)하지 마세요.\n"
            "사용자가 제시한 가정과 수집된 실제 데이터(PER, 실적, 뉴스)를 냉정하게 대조하고,\n"
            "반론까지 함께 검토해 너만의 일관된 분석 원칙을 유지하여 답변하세요.\n\n"
            f"[사용자 질문]\n{user_q}"
        )

    # 이미 대화가 이어진 후속 질문이라도 챗봇이 항상 최신 수집 숫자를 참고할 수 있도록 컨텍스트 전달
    dify_res = ask_dify_chatbot(
        bot_type="analysis",
        query=final_question,
        inputs={
            "stock_code": evidence["code"],
            "stock_name": evidence["name"],
        },
        context_text=context_text if (is_initial or not conversation_id) else None,
        conversation_id=conversation_id,
    )

    return jsonify({
        "code": evidence["code"],
        "name": evidence["name"],
        "answer": dify_res["answer"],
        "conversation_id": dify_res["conversation_id"],
        "evidence": evidence,
        "error": dify_res["error"],
    }), 200


@app.route("/api/rebalance", methods=["POST"])
def rebalance():
    """[탭 2] 다중 종목/ETF 코드를 받아 1년 주가 기반 몬테카를로/프론티어 최적 비중을 반환한다. (Dify 미사용)"""
    payload = request.get_json(silent=True) or {}
    codes = payload.get("codes", "")

    logger.info("[REQUEST] POST /api/rebalance codes=%s", codes)
    result = calculate_rebalance(codes)

    status_code = 400 if result.get("error") else 200
    return jsonify(result), status_code


@app.route("/api/indicators", methods=["POST"])
def api_indicators():
    """[탭 3] 종목코드를 받아 MA/RSI/MACD/볼린저밴드 차트 시계열 및 최신 지표 숫자를 반환한다."""
    payload = request.get_json(silent=True) or {}
    code = str(payload.get("code", "")).strip()

    logger.info("[REQUEST] POST /api/indicators code=%s", code)
    result = calculate_indicators(code)

    status_code = 400 if result.get("error") else 200
    return jsonify(result), status_code


@app.route("/api/chat/tech", methods=["POST"])
def chat_tech():
    """[탭 3] 계산된 최신 기술지표 숫자를 눈에 안 보이게 주입해 Dify 지표해석기 챗봇에게 설명을 요청한다."""
    payload = request.get_json(silent=True) or {}
    code = str(payload.get("code", "")).strip()
    question = str(payload.get("question", "")).strip() or "현재 기술지표 수치를 초보자가 이해하기 쉽게 설명해 주세요."
    latest_indicators = payload.get("latest")
    conversation_id = str(payload.get("conversation_id", "")).strip()

    logger.info("[REQUEST] POST /api/chat/tech code=%s", code)

    # 프론트에서 latest를 넘기지 않았더라도 code가 있으면 서버에서 직접 최신 지표를 계산해 확보
    if not latest_indicators and code:
        calc_res = calculate_indicators(code)
        if calc_res.get("error"):
            return jsonify({"code": code, "answer": None, "conversation_id": conversation_id, "error": calc_res["error"]}), 400
        latest_indicators = calc_res.get("latest")

    if not latest_indicators:
        return jsonify({
            "code": code,
            "answer": None,
            "conversation_id": conversation_id,
            "error": "먼저 종목코드를 입력해 기술지표 차트를 조회해 주세요.",
        }), 400

    context_payload = {
        "code": code,
        "latest_indicators": latest_indicators,
    }
    context_text = json.dumps(context_payload, ensure_ascii=False, indent=2)

    dify_res = ask_dify_chatbot(
        bot_type="tech",
        query=question,
        inputs={
            "stock_code": code,
            "tech_indicators": context_text,
        },
        context_text=context_text,
        conversation_id=conversation_id,
    )

    return jsonify({
        "code": code,
        "answer": dify_res["answer"],
        "conversation_id": dify_res["conversation_id"],
        "error": dify_res["error"],
    }), 200

if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    logger.info("[START] Flask 서버 구동: http://127.0.0.1:5000 (debug=%s)", debug_mode)
    app.run(host="127.0.0.1", port=5000, debug=debug_mode)
