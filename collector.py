import logging
import os
import re
import requests
from dotenv import load_dotenv

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

    current_price = clean_number(data.get("closePrice"), as_float=False)
    change_rate = clean_number(data.get("fluctuationsRatio"), as_float=True)

    logger.info("[PARSE] 기본 정보 파싱 완료 (name=%s, price=%s)", stock_name, current_price)
    return {
        "name": stock_name,
        "current_price": current_price,
        "change_rate": change_rate,
    }, None


def fetch_integration_info(code):
    """네이버 금융 integration API에서 시가총액, PER, PBR을 가져와 숫자로 정제한다."""
    url = f"https://m.stock.naver.com/api/stock/{code}/integration"
    logger.info("[NAVER] 네이버 금융 투자정보 API 접근 시작 (url=%s)", url)

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

    market_cap = parse_korean_market_cap(info_map.get("시총"))
    per = clean_number(info_map.get("PER"), as_float=True)
    pbr = clean_number(info_map.get("PBR"), as_float=True)

    logger.info("[PARSE] 투자정보 파싱 완료 (market_cap=%s, per=%s, pbr=%s)", market_cap, per, pbr)
    return {
        "market_cap": market_cap,
        "per": per,
        "pbr": pbr,
    }, None


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
    """종목 데이터 수집 통합 함수 (4차: 기본 시세 + 투자정보 + 기업실적분석 + Serper 뉴스)"""
    result = {
        "code": str(code).strip() if code else "",
        "name": None,
        "snapshot": {
            "current_price": None,
            "change_rate": None,
            "market_cap": None,
            "per": None,
            "pbr": None,
        },
        "financials": [],
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

    result["name"] = basic_info["name"]
    result["snapshot"]["current_price"] = basic_info["current_price"]
    result["snapshot"]["change_rate"] = basic_info["change_rate"]

    integ_info, err = fetch_integration_info(valid_code)
    if err:
        result["errors"].append(err)
    elif integ_info:
        result["snapshot"]["market_cap"] = integ_info["market_cap"]
        result["snapshot"]["per"] = integ_info["per"]
        result["snapshot"]["pbr"] = integ_info["pbr"]

    financials, err = fetch_financials(valid_code)
    if err:
        result["errors"].append(err)
    else:
        result["financials"] = financials

    # 네이버에서 파싱한 정식 종목명으로 Serper News API 호출
    if result["name"]:
        news_list, err = fetch_serper_news(result["name"])
        if err:
            result["errors"].append(err)
        else:
            result["news"] = news_list

    logger.info(
        "[RESPONSE] 수집 완료 (code=%s, financials=%d, news=%d, errors=%d)",
        result["code"],
        len(result["financials"]),
        len(result["news"]),
        len(result["errors"]),
    )
    return result
