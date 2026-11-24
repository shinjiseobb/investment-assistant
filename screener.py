import logging
import time
import FinanceDataReader as fdr

logger = logging.getLogger(__name__)

# 서버 메모리에 5분(300초)간 캐시하여 필터 변경 시 0.01초 응답 보장
_SCREENER_CACHE = {}
CACHE_TTL_SECONDS = 300


def _get_krx_listing():
    now = time.time()
    cached = _SCREENER_CACHE.get("KRX")
    if cached and (now - cached["ts"] < CACHE_TTL_SECONDS):
        return cached["data"]

    logger.info("[FDR] KRX 전종목 스크리너 목록 조회 시작")
    df = fdr.StockListing("KRX")
    rows = []
    for _, r in df.iterrows():
        code = str(r.get("Code") or "").strip()
        name = str(r.get("Name") or "").strip()
        market = str(r.get("Market") or "").strip()
        if not code or not name or market not in ("KOSPI", "KOSDAQ"):
            continue
        try:
            close = int(float(r.get("Close") or 0))
            chg = round(float(r.get("ChagesRatio") or 0.0), 2)
            marcap = int(float(r.get("Marcap") or 0))
        except (TypeError, ValueError):
            continue
        if close <= 0 or marcap <= 0:
            continue

        rows.append({
            "code": code,
            "name": name,
            "sub": market,
            "price": close,
            "change_rate": chg,
            "market_cap": marcap,
        })

    _SCREENER_CACHE["KRX"] = {"ts": now, "data": rows}
    logger.info("[FDR] KRX 스크리너 캐시 완료 (%d종목)", len(rows))
    return rows


def _get_sp500_listing():
    now = time.time()
    cached = _SCREENER_CACHE.get("SP500")
    if cached and (now - cached["ts"] < CACHE_TTL_SECONDS):
        return cached["data"]

    logger.info("[FDR] S&P500 스크리너 목록 조회 시작")
    df = fdr.StockListing("S&P500")
    rows = []
    for _, r in df.iterrows():
        code = str(r.get("Symbol") or "").strip()
        name = str(r.get("Name") or "").strip()
        sector = str(r.get("Sector") or "").strip()
        industry = str(r.get("Industry") or "").strip()
        if not code or not name:
            continue
        rows.append({
            "code": code,
            "name": name,
            "sub": sector,
            "industry": industry,
            "price": None,
            "change_rate": None,
            "market_cap": None,
        })

    _SCREENER_CACHE["SP500"] = {"ts": now, "data": rows}
    logger.info("[FDR] S&P500 스크리너 캐시 완료 (%d종목)", len(rows))
    return rows


def run_screener(
    market="KR",
    min_cap_trillion=0,
    max_price=0,
    min_change=None,
    max_change=None,
    sector="",
    keyword="",
    sort_by="market_cap",
    sort_dir="desc",
    limit=50,
):
    """[탭 4] 한국(KRX) 또는 미국(S&P500) 종목을 조건에 따라 필터링 및 정렬해 반환한다."""
    try:
        if market == "US":
            items = list(_get_sp500_listing())
        else:
            items = list(_get_krx_listing())
    except Exception as e:
        logger.error("[ERROR] 스크리너 데이터 조회 실패 (%s): %s", market, e, exc_info=True)
        return {"market": market, "total": 0, "items": [], "sectors": [], "error": "종목 목록을 불러오는 중 오류가 발생했습니다."}

    sectors = sorted({it["sub"] for it in items if it.get("sub")})

    # 필터링 적용
    filtered = []
    kw = str(keyword or "").strip().lower()
    sec = str(sector or "").strip()

    for it in items:
        if sec and it.get("sub") != sec:
            continue
        if kw and (kw not in it["name"].lower() and kw not in it["code"].lower()):
            continue

        if market == "KR":
            if min_cap_trillion and it["market_cap"] < float(min_cap_trillion) * 1_000_000_000_000:
                continue
            if max_price and it["price"] > float(max_price):
                continue
            if min_change is not None and min_change != "" and it["change_rate"] < float(min_change):
                continue
            if max_change is not None and max_change != "" and it["change_rate"] > float(max_change):
                continue

        filtered.append(it)

    # 정렬 (KR은 숫자 정렬, US는 코드/이름 정렬)
    reverse = sort_dir != "asc"
    if market == "KR" and sort_by in ("market_cap", "price", "change_rate"):
        filtered.sort(key=lambda x: x.get(sort_by) or 0, reverse=reverse)
    elif sort_by in ("code", "name", "sub"):
        filtered.sort(key=lambda x: str(x.get(sort_by) or ""), reverse=reverse)

    return {
        "market": market,
        "total": len(filtered),
        "items": filtered[:limit],
        "sectors": sectors,
        "error": None,
    }
