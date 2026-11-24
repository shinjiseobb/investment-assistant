import logging
import os
import re
from datetime import datetime, timedelta
import requests
import FinanceDataReader as fdr
from dotenv import load_dotenv
from dart_client import fetch_dart_disclosures

load_dotenv()

logger = logging.getLogger(__name__)

# 네이버 서버 차단을 방지하기 위한 매너 명찰 (User-Agent)
NAVER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://stock.naver.com/",
}

REQUEST_TIMEOUT = 10


def clean_number(value, as_float=False):
    """콤마, 단위(원, 배, % 등), 공백을 제거하고 순수 숫자로 변환한다. 결측치('-')는 None 반환."""
    if value is None:
        return None

    text = str(value).strip()
    if not text or text in ("-", "N/A", "null", "None"):
        return None

    # 콤마, 공백 및 대표 단위 문자열 제거
    cleaned = text.replace(",", "").replace(" ", "")
    cleaned = re.sub(r"(원|배|%|주)$", "", cleaned)

    try:
        num = float(cleaned)
        return round(num, 2) if as_float else int(num)
    except ValueError:
        return None


def parse_korean_market_cap(value):
    """'895조 5,836억' 또는 '5,836억' 형태의 시가총액 문자열을 원(KRW) 단위 순수 정수로 변환한다."""
    if value is None:
        return None

    text = str(value).strip().replace(",", "").replace(" ", "")
    if not text or text in ("-", "N/A", "null", "None"):
        return None

    total = 0
    matched = False

    jo_match = re.search(r"(\d+)조", text)
    if jo_match:
        total += int(jo_match.group(1)) * 1_000_000_000_000
        matched = True

    eok_match = re.search(r"(\d+)억", text)
    if eok_match:
        total += int(eok_match.group(1)) * 100_000_000
        matched = True

    if matched:
        return total

    return clean_number(text, as_float=False)


def validate_code(code):
    """종목코드가 비어있지 않고 6자리 숫자인지 검증한다."""
    if not code or not str(code).strip():
        return None, "종목코드가 입력되지 않았습니다. 6자리 숫자 코드를 입력해 주세요."

    code_str = str(code).strip()
    if not re.fullmatch(r"\d{6}", code_str):
        return None, f"올바른 종목코드 형식이 아닙니다 ('{code_str}'). 6자리 숫자로 입력해 주세요. (예: 000660)"

    return code_str, None


def fetch_basic_info(code):
    """네이버 금융 basic API에서 정식 종목명, 현재가, 등락률을 가져온다."""
    url = f"https://m.stock.naver.com/api/stock/{code}/basic"
    logger.info("[NAVER] 네이버 금융 API 접근 시작 (User-Agent 적용, url=%s)", url)

    try:
        resp = requests.get(url, headers=NAVER_HEADERS, timeout=REQUEST_TIMEOUT)
    except requests.Timeout:
        logger.error("[ERROR] 네이버 금융 basic API 네트워크 타임아웃 (code=%s)", code, exc_info=True)
        return None, "네트워크 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요."
    except requests.RequestException as e:
        logger.error("[ERROR] 네이버 금융 basic API 요청 실패: %s", e, exc_info=True)
        return None, "네이버 금융 서버에 연결하지 못했습니다."

    if resp.status_code in (404, 409):
        return None, f"종목코드 '{code}'에 해당하는 종목을 네이버 금융에서 찾을 수 없습니다."
    if resp.status_code == 403:
        return None, "네이버 금융 페이지 접근이 차단되었습니다 (403)."
    if resp.status_code != 200:
        return None, f"네이버 금융 페이지 접근에 실패했습니다 (상태 코드: {resp.status_code})."

    try:
        data = resp.json()
    except ValueError:
        logger.error("[ERROR] 네이버 금융 basic 응답 JSON 변환 실패 (code=%s)", code, exc_info=True)
        return None, "네이버 금융 응답 데이터를 JSON으로 변환하는 데 실패했습니다."

    stock_name = data.get("stockName")
    if not stock_name:
        return None, "종목명을 파싱하는 데 실패했습니다. 네이버 데이터 구조가 변경되었거나 지원하지 않는 종목입니다."

    asset_type = data.get("stockEndType", "stock")  # 'stock' 또는 'etf'
    current_price = clean_number(data.get("closePrice"), as_float=False)
    change_rate = clean_number(data.get("fluctuationsRatio"), as_float=True)

    logger.info("[PARSE] 기본 정보 파싱 완료 (name=%s, type=%s, price=%s)", stock_name, asset_type, current_price)
    return {
        "name": stock_name,
        "asset_type": asset_type,
        "current_price": current_price,
        "change_rate": change_rate,
    }, None


def fetch_integration_info(code, asset_type="stock"):
    """네이버 금융 integration API에서 투자정보(주식/ETF)와 최근 5일 투자자별 수급을 가져온다."""
    url = f"https://m.stock.naver.com/api/stock/{code}/integration"
    logger.info("[NAVER] 네이버 금융 투자정보 API 접근 시작 (url=%s, type=%s)", url, asset_type)

    try:
        resp = requests.get(url, headers=NAVER_HEADERS, timeout=REQUEST_TIMEOUT)
    except requests.Timeout:
        logger.error("[ERROR] 네이버 금융 integration API 타임아웃 (code=%s)", code, exc_info=True)
        return None, "투자정보 조회 중 네트워크 응답 시간이 초과되었습니다."
    except requests.RequestException as e:
        logger.error("[ERROR] 네이버 금융 integration API 요청 실패: %s", e, exc_info=True)
        return None, "네이버 금융 투자정보 서버에 연결하지 못했습니다."

    if resp.status_code != 200:
        return None, f"투자정보를 가져오지 못했습니다 (상태 코드: {resp.status_code})."

    try:
        data = resp.json()
    except ValueError:
        logger.error("[ERROR] 네이버 금융 integration 응답 JSON 변환 실패 (code=%s)", code, exc_info=True)
        return None, "투자정보 응답 데이터를 JSON으로 변환하는 데 실패했습니다."

    total_infos = data.get("totalInfos", [])
    info_map = {item.get("key"): item.get("value") for item in total_infos if item.get("key")}

    # 공통: 최근 5일 투자자별 매매동향 (외국인/기관/개인 순매수량 + 억원 환산)
    investor_trend = []
    for item in (data.get("dealTrendInfos") or [])[:5]:
        bizdate = str(item.get("bizdate") or "")
        formatted_date = f"{bizdate[:4]}-{bizdate[4:6]}-{bizdate[6:]}" if len(bizdate) == 8 else bizdate
        close_p = clean_number(item.get("closePrice"), as_float=False)
        f_net = clean_number(item.get("foreignerPureBuyQuant"), as_float=False)
        o_net = clean_number(item.get("organPureBuyQuant"), as_float=False)
        i_net = clean_number(item.get("individualPureBuyQuant"), as_float=False)

        def _to_eok(qty):
            if qty is None or close_p is None:
                return None
            return round((qty * close_p) / 100_000_000, 1)

        investor_trend.append({
            "date": formatted_date,
            "close_price": close_p,
            "foreigner_net": f_net,
            "foreigner_eok": _to_eok(f_net),
            "organ_net": o_net,
            "organ_eok": _to_eok(o_net),
            "individual_net": i_net,
            "individual_eok": _to_eok(i_net),
            "foreigner_ratio": clean_number(item.get("foreignerHoldRatio"), as_float=True),
        })

    # 동일업종 경쟁사 비교 (상위 5개)
    peers = []
    for p in (data.get("industryCompareInfo") or [])[:5]:
        p_code = p.get("itemCode")
        p_name = p.get("stockName")
        if p_code and p_name:
            p_ratio = clean_number(p.get("fluctuationsRatio"), as_float=True)
            comp_name = (p.get("compareToPreviousPrice") or {}).get("name", "")
            if p_ratio is not None and comp_name == "FALLING" and p_ratio > 0:
                p_ratio = -p_ratio
            peers.append({
                "code": p_code,
                "name": p_name,
                "price": clean_number(p.get("closePrice"), as_float=False),
                "change_rate": p_ratio,
            })

    if asset_type == "etf":
        etf_ind = data.get("etfKeyIndicator") or {}
        dev_sign = etf_ind.get("deviationSign") or ""
        dev_rate = etf_ind.get("deviationRate")
        if dev_rate is not None and dev_sign == "-":
            dev_rate = -abs(float(dev_rate))

        etf_info = {
            "issuer": etf_ind.get("issuerName") or info_map.get("운용사"),
            "base_index": info_map.get("기초지수"),
            "nav": clean_number(etf_ind.get("nav") or info_map.get("NAV"), as_float=True),
            "total_nav": parse_korean_market_cap(etf_ind.get("totalNav")),
            "deviation_rate": round(float(dev_rate), 2) if dev_rate is not None else None,
            "total_fee": etf_ind.get("totalFee") if etf_ind.get("totalFee") is not None else clean_number(info_map.get("펀드보수"), as_float=True),
            "dividend_yield": etf_ind.get("dividendYieldTtm"),
            "return_1m": etf_ind.get("returnRate1m") if etf_ind.get("returnRate1m") is not None else clean_number(info_map.get("최근 1개월 수익률"), as_float=True),
            "return_3m": etf_ind.get("returnRate3m") if etf_ind.get("returnRate3m") is not None else clean_number(info_map.get("최근 3개월 수익률"), as_float=True),
            "return_6m": clean_number(info_map.get("최근 6개월 수익률"), as_float=True),
            "return_1y": etf_ind.get("returnRate1y") if etf_ind.get("returnRate1y") is not None else clean_number(info_map.get("최근 1년 수익률"), as_float=True),
            "description": data.get("description") or "",
        }
        market_cap = parse_korean_market_cap(etf_ind.get("marketValue") or info_map.get("시총"))
        per = None
        pbr = None
        logger.info("[PARSE] ETF 정보 파싱 완료 (nav=%s, fee=%s, trend=%d)", etf_info["nav"], etf_info["total_fee"], len(investor_trend))
    else:
        etf_info = None
        market_cap = parse_korean_market_cap(info_map.get("시총"))
        per = clean_number(info_map.get("PER"), as_float=True)
        pbr = clean_number(info_map.get("PBR"), as_float=True)
        logger.info("[PARSE] 투자정보 파싱 완료 (market_cap=%s, per=%s, pbr=%s, trend=%d)", market_cap, per, pbr, len(investor_trend))

    return {
        "market_cap": market_cap,
        "per": per,
        "pbr": pbr,
        "etf_info": etf_info,
        "investor_trend": investor_trend,
        "peers": peers,
    }, None


def fetch_market_context():
    """FinanceDataReader로 오늘의 코스피(KS11), 코스닥(KQ11), 원/달러 환율(USD/KRW)을 조회한다."""
    start_str = (datetime.today() - timedelta(days=14)).strftime("%Y-%m-%d")
    symbols = {
        "kospi": ("KS11", "코스피"),
        "kosdaq": ("KQ11", "코스닥"),
        "usd_krw": ("USD/KRW", "원/달러"),
    }
    context = {}
    for key, (sym, label) in symbols.items():
        try:
            df = fdr.DataReader(sym, start_str)
            if df is not None and len(df) >= 2 and "Close" in df.columns:
                closes = df["Close"].dropna()
                curr = float(closes.iloc[-1])
                prev = float(closes.iloc[-2])
                chg = round(((curr - prev) / prev) * 100, 2) if prev else 0.0
                context[key] = {
                    "label": label,
                    "value": round(curr, 2),
                    "change_rate": chg,
                }
        except Exception as e:
            logger.warning("[FDR] 시장 지표 조회 실패 (%s): %s", sym, e)
    return context


def build_tech_summary(code):
    """indicators.py를 재사용해 RSI(14), 볼린저밴드 위치(%), 20일선 이격도(%) 요약을 생성한다."""
    try:
        from indicators import calculate_indicators
        ind = calculate_indicators(code, days=180, display_days=5)
        if ind.get("error") or not ind.get("latest"):
            return None
        latest = ind["latest"]
        close = latest.get("close")
        bb_up = latest.get("bb_upper")
        bb_low = latest.get("bb_lower")
        ma20 = latest.get("ma20")

        bb_pos = None
        if close is not None and bb_up is not None and bb_low is not None and (bb_up - bb_low) > 0:
            bb_pos = round(((close - bb_low) / (bb_up - bb_low)) * 100, 1)

        ma20_gap = None
        if close is not None and ma20 is not None and ma20 > 0:
            ma20_gap = round(((close - ma20) / ma20) * 100, 2)

        return {
            "rsi14": latest.get("rsi14"),
            "bb_position_pct": bb_pos,
            "ma20": ma20,
            "ma20_gap_pct": ma20_gap,
            "macd": latest.get("macd"),
        }
    except Exception as e:
        logger.warning("[CALC] 기술지표 요약 생성 실패 (code=%s): %s", code, e)
        return None


def fetch_financials(code):
    """네이버 금융 finance/annual API에서 연간 매출액, 영업이익, ROE와 추정치 여부(is_consensus)를 수집한다."""
    url = f"https://m.stock.naver.com/api/stock/{code}/finance/annual"
    logger.info("[NAVER] 네이버 금융 기업실적분석 API 접근 시작 (url=%s)", url)

    try:
        resp = requests.get(url, headers=NAVER_HEADERS, timeout=REQUEST_TIMEOUT)
    except requests.Timeout:
        logger.error("[ERROR] 네이버 금융 finance API 타임아웃 (code=%s)", code, exc_info=True)
        return [], "기업실적분석 조회 중 네트워크 응답 시간이 초과되었습니다."
    except requests.RequestException as e:
        logger.error("[ERROR] 네이버 금융 finance API 요청 실패: %s", e, exc_info=True)
        return [], "네이버 금융 기업실적분석 서버에 연결하지 못했습니다."

    if resp.status_code != 200:
        return [], f"기업실적분석 데이터를 가져오지 못했습니다 (상태 코드: {resp.status_code})."

    try:
        data = resp.json()
    except ValueError:
        logger.error("[ERROR] 네이버 금융 finance 응답 JSON 변환 실패 (code=%s)", code, exc_info=True)
        return [], "기업실적분석 응답 데이터를 JSON으로 변환하는 데 실패했습니다."

    finance_info = data.get("financeInfo") or {}
    tr_titles = finance_info.get("trTitleList", [])
    row_list = finance_info.get("rowList", [])

    if not tr_titles or not row_list:
        return [], "기업실적분석 데이터가 비어 있거나 구조가 변경되었습니다."

    # 필요한 행(매출액, 영업이익, ROE)만 빠르게 조회할 수 있도록 딕셔너리로 정리
    row_map = {row.get("title"): row.get("columns", {}) for row in row_list if row.get("title")}

    financials = []
    for col in tr_titles:
        col_key = col.get("key")
        if not col_key:
            continue

        period_title = (col.get("title") or col_key).strip().rstrip(".")
        is_consensus = col.get("isConsensus") == "Y"

        rev_raw = (row_map.get("매출액", {}).get(col_key) or {}).get("value")
        op_raw = (row_map.get("영업이익", {}).get(col_key) or {}).get("value")
        roe_raw = (row_map.get("ROE", {}).get(col_key) or {}).get("value")

        # 네이버 기업실적분석의 매출액/영업이익은 '억 원' 단위이므로 원(KRW) 단위로 통일
        rev_eok = clean_number(rev_raw, as_float=False)
        op_eok = clean_number(op_raw, as_float=False)

        financials.append({
            "period": period_title,
            "period_type": "annual",
            "is_consensus": is_consensus,
            "revenue": rev_eok * 100_000_000 if rev_eok is not None else None,
            "operating_income": op_eok * 100_000_000 if op_eok is not None else None,
            "roe": clean_number(roe_raw, as_float=True),
        })

    logger.info("[PARSE] 기업실적분석 파싱 완료 (기간 수=%d)", len(financials))
    return financials, None


def fetch_serper_news(stock_name, num=5):
    """파싱된 정식 종목명으로 Serper News API를 호출하여 최신 뉴스 최대 5개를 가져온다."""
    api_key = os.getenv("SERPER_API_KEY", "").strip()
    if not api_key or api_key == "your_serper_api_key_here":
        logger.warning("[SERPER] Serper API Key 미설정으로 뉴스 검색을 건너뜁니다.")
        return [], "Serper API Key가 설정되지 않아 뉴스를 수집할 수 없습니다. (.env 파일을 확인해 주세요)"

    url = "https://google.serper.dev/news"
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "q": stock_name,
        "gl": "kr",
        "hl": "ko",
        "num": num,
    }

    logger.info("[SERPER] Serper News API 호출 시작 (query=%s)", stock_name)

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
    except requests.Timeout:
        logger.error("[ERROR] Serper News API 타임아웃 (query=%s)", stock_name, exc_info=True)
        return [], "뉴스 검색 중 네트워크 응답 시간이 초과되었습니다."
    except requests.RequestException as e:
        logger.error("[ERROR] Serper News API 요청 실패: %s", e, exc_info=True)
        return [], "Serper 뉴스 서버에 연결하지 못했습니다."

    if resp.status_code in (401, 403):
        return [], "Serper API 인증에 실패했습니다. API Key를 확인해 주세요."
    if resp.status_code != 200:
        return [], f"Serper 뉴스 API 호출에 실패했습니다 (상태 코드: {resp.status_code})."

    try:
        data = resp.json()
    except ValueError:
        logger.error("[ERROR] Serper News 응답 JSON 변환 실패", exc_info=True)
        return [], "뉴스 검색 응답을 JSON으로 변환하는 데 실패했습니다."

    raw_news = data.get("news", [])[:num]
    news_list = []
    for item in raw_news:
        news_list.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "description": item.get("snippet", ""),
            "published": item.get("date", ""),
        })

    logger.info("[SERPER] 뉴스 수집 완료 (수집 건수=%d)", len(news_list))
    return news_list, None


def collect_stock_data(code):
    """종목 데이터 수집 통합 함수 (주식/ETF 자동 분기 + 최근 5일 수급 + Serper 뉴스)"""
    result = {
        "code": str(code).strip() if code else "",
        "name": None,
        "asset_type": "stock",
        "snapshot": {
            "current_price": None,
            "change_rate": None,
            "market_cap": None,
            "per": None,
            "pbr": None,
        },
        "etf_info": None,
        "investor_trend": [],
        "peers": [],
        "market_context": {},
        "tech_summary": None,
        "financials": [],
        "disclosures": [],
        "news": [],
        "errors": [],
    }

    valid_code, err = validate_code(code)
    if err:
        result["errors"].append(err)
        return result

    result["code"] = valid_code

    basic_info, err = fetch_basic_info(valid_code)
    if err:
        result["errors"].append(err)
        return result

    asset_type = basic_info.get("asset_type", "stock")
    result["name"] = basic_info["name"]
    result["asset_type"] = asset_type
    result["snapshot"]["current_price"] = basic_info["current_price"]
    result["snapshot"]["change_rate"] = basic_info["change_rate"]

    integ_info, err = fetch_integration_info(valid_code, asset_type=asset_type)
    if err:
        result["errors"].append(err)
    elif integ_info:
        result["snapshot"]["market_cap"] = integ_info["market_cap"]
        result["snapshot"]["per"] = integ_info["per"]
        result["snapshot"]["pbr"] = integ_info["pbr"]
        result["etf_info"] = integ_info.get("etf_info")
        result["investor_trend"] = integ_info.get("investor_trend", [])
        result["peers"] = integ_info.get("peers", [])

    # 거시 시장 환경 (코스피/코스닥/원달러) 및 기술지표 핵심 요약
    result["market_context"] = fetch_market_context()
    result["tech_summary"] = build_tech_summary(valid_code)

    # ETF는 기업 재무제표 및 DART 기업 공시가 없으므로 일반 주식일 때만 조회
    if asset_type != "etf":
        financials, err = fetch_financials(valid_code)
        if err:
            result["errors"].append(err)
        else:
            result["financials"] = financials

        disclosures, err = fetch_dart_disclosures(valid_code)
        if err:
            result["errors"].append(err)
        else:
            result["disclosures"] = disclosures

    # 네이버에서 파싱한 정식 종목명으로 Serper News API 호출
    if result["name"]:
        news_list, err = fetch_serper_news(result["name"])
        if err:
            result["errors"].append(err)
        else:
            result["news"] = news_list

    logger.info(
        "[RESPONSE] 수집 완료 (code=%s, type=%s, financials=%d, disclosures=%d, trend=%d, news=%d, errors=%d)",
        result["code"],
        result["asset_type"],
        len(result["financials"]),
        len(result["disclosures"]),
        len(result["investor_trend"]),
        len(result["news"]),
        len(result["errors"]),
    )
    return result
