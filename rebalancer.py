import logging
import re
from datetime import datetime, timedelta
import FinanceDataReader as fdr
import numpy as np
import pandas as pd
from collector import fetch_basic_info

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE = 0.035  # 무위험 수익률 연 3.5% 가정


def parse_and_validate_codes(raw_codes):
    """입력된 종목코드 목록(문자열 또는 리스트)을 정제하고 6자리 숫자 2개 이상인지 검증한다."""
    if isinstance(raw_codes, str):
        items = [c.strip() for c in re.split(r"[,\s]+", raw_codes) if c.strip()]
    elif isinstance(raw_codes, list):
        items = [str(c).strip() for c in raw_codes if str(c).strip()]
    else:
        items = []

    # 순서 유지하며 중복 제거
    unique_codes = list(dict.fromkeys(items))

    if len(unique_codes) < 2:
        return None, "리밸런싱을 계산하려면 서로 다른 종목코드를 2개 이상 입력해 주세요. (예: 005930, 000660, 069500)"

    for code in unique_codes:
        if not re.fullmatch(r"\d{6}", code):
            return None, f"올바른 6자리 종목코드가 아닙니다: '{code}'"

    return unique_codes, None


def fetch_close_prices(codes, days=365):
    """FinanceDataReader로 다중 종목의 최근 1년 종가(Close) 데이터를 수집해 DataFrame으로 반환한다."""
    end_date = datetime.today()
    start_date = end_date - timedelta(days=days)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    price_series_map = {}

    for code in codes:
        logger.info("[FDR] FinanceDataReader 데이터 조회 시작 (code=%s, start=%s)", code, start_str)
        try:
            df = fdr.DataReader(code, start_str, end_str)
        except Exception as e:
            logger.error("[ERROR] FinanceDataReader 조회 실패 (code=%s): %s", code, e, exc_info=True)
            return None, f"종목코드 '{code}'의 주가 데이터를 불러오는 중 오류가 발생했습니다."

        if df is None or df.empty or "Close" not in df.columns:
            return None, f"종목코드 '{code}'의 최근 1년 주가 데이터가 없습니다. 코드를 확인해 주세요."

        close_series = df["Close"].dropna()
        if len(close_series) < 30:
            return None, f"종목코드 '{code}'의 거래일 데이터가 부족하여 분석할 수 없습니다 (조회 일수: {len(close_series)}일)."

        logger.info("[FDR] FinanceDataReader 데이터 조회 완료 (code=%s, rows=%d)", code, len(close_series))
        price_series_map[code] = close_series

    prices_df = pd.concat(price_series_map, axis=1).dropna()
    if len(prices_df) < 30:
        return None, "선택한 종목들의 공통 거래일 데이터가 30일 미만으로 부족합니다."

    return prices_df, None


def compute_return_stats(prices_df):
    """종가 DataFrame으로부터 일간 수익률, 연율화 기대수익률, 연율화 공분산 행렬을 계산한다."""
    daily_returns = prices_df.pct_change().dropna()
    annual_mean_returns = daily_returns.mean() * TRADING_DAYS_PER_YEAR
    annual_cov_matrix = daily_returns.cov() * TRADING_DAYS_PER_YEAR
    return daily_returns, annual_mean_returns, annual_cov_matrix


def calculate_rebalance(raw_codes, num_simulations=3000):
    """[탭 2] 단순화 몬테카를로 시뮬레이션과 효율적 프론티어로 최적 비중을 계산한다. (Dify 미사용)"""
    codes, err = parse_and_validate_codes(raw_codes)
    if err:
        return {"codes": [], "optimal_weights": {}, "metrics": {}, "frontier_points": [], "error": err}

    prices_df, err = fetch_close_prices(codes)
    if err:
        return {"codes": codes, "optimal_weights": {}, "metrics": {}, "frontier_points": [], "error": err}

    _, mean_returns, cov_matrix = compute_return_stats(prices_df)
    mean_vec = mean_returns.values
    cov_mat = cov_matrix.values
    n_assets = len(codes)

    all_weights = np.random.random((num_simulations, n_assets))
    all_weights = all_weights / all_weights.sum(axis=1, keepdims=True)

    port_returns = all_weights @ mean_vec
    # 각 포트폴리오 비중별 연율화 변동성 계산
    port_vols = np.sqrt(np.einsum("ij,jk,ik->i", all_weights, cov_mat, all_weights))
    sharpe_ratios = np.where(port_vols > 0, (port_returns - RISK_FREE_RATE) / port_vols, 0.0)

    best_idx = int(np.argmax(sharpe_ratios))
    best_weights = all_weights[best_idx]

    # 백분율(%) 변환 및 마지막 항목 보정으로 합계 100.0% 일치
    pct_weights = [round(float(w) * 100, 1) for w in best_weights]
    diff = round(100.0 - sum(pct_weights), 1)
    pct_weights[-1] = round(pct_weights[-1] + diff, 1)
    optimal_weights = {code: pct for code, pct in zip(codes, pct_weights)}

    metrics = {
        "expected_return": round(float(port_returns[best_idx]) * 100, 2),
        "volatility": round(float(port_vols[best_idx]) * 100, 2),
        "sharpe_ratio": round(float(sharpe_ratios[best_idx]), 2),
    }

    # 산점도 차트 렌더링 속도를 위해 최대 300개 포인트 샘플링
    step = max(1, num_simulations // 300)
    frontier_points = [
        {
            "risk": round(float(port_vols[i]) * 100, 2),
            "return": round(float(port_returns[i]) * 100, 2),
            "sharpe": round(float(sharpe_ratios[i]), 2),
        }
        for i in range(0, num_simulations, step)
    ]

    # 종목명 매핑 조회 (실패 시 종목코드 그대로 사용)
    names = {}
    for code in codes:
        b_info, _ = fetch_basic_info(code)
        names[code] = b_info["name"] if b_info and b_info.get("name") else code

    logger.info(
        "[CALC] 몬테카를로/프론티어 계산 완료 (codes=%s, sharpe=%s, optimal=%s)",
        codes,
        metrics["sharpe_ratio"],
        optimal_weights,
    )

    return {
        "codes": codes,
        "names": names,
        "optimal_weights": optimal_weights,
        "metrics": metrics,
        "frontier_points": frontier_points,
        "data_days": len(prices_df),
        "error": None,
    }
