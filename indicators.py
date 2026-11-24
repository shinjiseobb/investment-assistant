import logging
import re
from datetime import datetime, timedelta
import FinanceDataReader as fdr
import pandas as pd

logger = logging.getLogger(__name__)


def _to_clean_list(series, decimals=2):
    """Pandas Series의 NaN을 JSON 호환 None으로 변환하고 반올림된 리스트를 반환한다."""
    result = []
    for val in series:
        if pd.isna(val):
            result.append(None)
        else:
            result.append(int(round(val)) if decimals == 0 else round(float(val), decimals))
    return result


def calculate_indicators(code, days=365, display_days=120):
    """[탭 3] FinanceDataReader로 최근 주가를 수집해 MA, RSI, MACD, 볼린저밴드를 계산한다."""
    code_str = str(code).strip() if code else ""
    if not re.fullmatch(r"\d{6}", code_str):
        return {"code": code_str, "error": f"올바른 6자리 종목코드가 아닙니다: '{code_str}'"}

    end_date = datetime.today()
    start_date = end_date - timedelta(days=days)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    logger.info("[FDR] 기술지표용 주가 조회 시작 (code=%s, start=%s)", code_str, start_str)

    try:
        df = fdr.DataReader(code_str, start_str, end_str)
    except Exception as e:
        logger.error("[ERROR] FinanceDataReader 조회 실패 (code=%s): %s", code_str, e, exc_info=True)
        return {"code": code_str, "error": f"종목코드 '{code_str}'의 주가 데이터를 불러오지 못했습니다."}

    if df is None or df.empty or "Close" not in df.columns:
        return {"code": code_str, "error": f"종목코드 '{code_str}'의 주가 데이터가 없습니다."}

    df = df[["Close"]].dropna().copy()
    if len(df) < 30:
        return {"code": code_str, "error": f"기술지표 계산을 위한 거래일 데이터가 부족합니다 ({len(df)}일)."}

    logger.info("[FDR] 기술지표용 주가 조회 완료 (code=%s, rows=%d)", code_str, len(df))

    close = df["Close"]

    # 1. 이동평균선 (MA 5 / 20 / 60)
    df["ma5"] = close.rolling(window=5).mean()
    df["ma20"] = close.rolling(window=20).mean()
    df["ma60"] = close.rolling(window=60).mean()

    # 2. 볼린저밴드 (20일, 표준편차 2배)
    std20 = close.rolling(window=20).std()
    df["bb_upper"] = df["ma20"] + (std20 * 2)
    df["bb_lower"] = df["ma20"] - (std20 * 2)

    # 3. RSI (14일, Wilder EMA 방식)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    df["rsi14"] = 100 - (100 / (1 + rs))
    # 손실이 0인 구간은 RSI 100으로 보정
    df.loc[avg_loss == 0, "rsi14"] = 100.0

    # 4. MACD (12, 26, 9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()

    # 차트 가독성을 위해 최근 N거래일만 추출
    view_df = df.tail(display_days)
    dates = [idx.strftime("%Y-%m-%d") for idx in view_df.index]

    close_list = _to_clean_list(view_df["Close"], decimals=0)
    ma5_list = _to_clean_list(view_df["ma5"], decimals=0)
    ma20_list = _to_clean_list(view_df["ma20"], decimals=0)
    ma60_list = _to_clean_list(view_df["ma60"], decimals=0)
    bb_upper_list = _to_clean_list(view_df["bb_upper"], decimals=0)
    bb_lower_list = _to_clean_list(view_df["bb_lower"], decimals=0)
    rsi14_list = _to_clean_list(view_df["rsi14"], decimals=2)
    macd_list = _to_clean_list(view_df["macd"], decimals=2)
    macd_signal_list = _to_clean_list(view_df["macd_signal"], decimals=2)

    latest = {
        "date": dates[-1],
        "close": close_list[-1],
        "ma5": ma5_list[-1],
        "ma20": ma20_list[-1],
        "ma60": ma60_list[-1],
        "rsi14": rsi14_list[-1],
        "macd": macd_list[-1],
        "macd_signal": macd_signal_list[-1],
        "bb_upper": bb_upper_list[-1],
        "bb_lower": bb_lower_list[-1],
    }

    logger.info("[CALC] 기술지표 계산 완료 (code=%s, latest_rsi14=%s, latest_close=%s)", code_str, latest["rsi14"], latest["close"])

    return {
        "code": code_str,
        "dates": dates,
        "close": close_list,
        "ma5": ma5_list,
        "ma20": ma20_list,
        "ma60": ma60_list,
        "bb_upper": bb_upper_list,
        "bb_lower": bb_lower_list,
        "rsi14": rsi14_list,
        "macd": macd_list,
        "macd_signal": macd_signal_list,
        "latest": latest,
        "error": None,
    }
