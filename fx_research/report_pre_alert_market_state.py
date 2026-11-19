import math
import os
from collections import defaultdict
from statistics import mean, median

import psycopg


HISTORY_BARS = 302

TREND_FLAT_THRESHOLD_PCT = 0.02
OUTCOME_FLAT_THRESHOLD_PCT = 0.001

VOLATILITY_LOW_MAX = 0.8
VOLATILITY_HIGH_MIN = 1.5

HORIZONS_MINUTES = (5, 15, 30, 60)


def is_valid_price(value):
    """価格が正の有限数か確認する。"""
    try:
        price = float(value)
    except (TypeError, ValueError):
        return False

    return math.isfinite(price) and price > 0


def is_finite_number(value):
    """値が有限数か確認する。"""
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def classify_trend(bars, minutes):
    """アラート直前のトレンドを判定する。"""
    required_bars = minutes // 5 + 1

    if len(bars) < required_bars:
        return "UNKNOWN"

    selected = bars[-required_bars:]

    for previous, current in zip(selected, selected[1:]):
        if (current[0] - previous[0]).total_seconds() != 300:
            return "UNKNOWN"

        if not is_valid_price(previous[1]) or not is_valid_price(current[1]):
            return "UNKNOWN"

    first_close = float(selected[0][1])
    last_close = float(selected[-1][1])

    change_pct = ((last_close - first_close) / first_close) * 100

    if not math.isfinite(change_pct):
        return "UNKNOWN"

    if change_pct > TREND_FLAT_THRESHOLD_PCT:
        return "UP"

    if change_pct < -TREND_FLAT_THRESHOLD_PCT:
        return "DOWN"

    return "FLAT"


def calculate_returns(bars):
    """連続する正常な5分足の変動率を計算する。"""
    returns = []

    for previous, current in zip(bars, bars[1:]):
        previous_time, previous_close = previous
        current_time, current_close = current

        if (current_time - previous_time).total_seconds() != 300:
            continue

        if not is_valid_price(previous_close):
            continue
        if not is_valid_price(current_close):
            continue

        previous_close = float(previous_close)
        current_close = float(current_close)

        change_pct = (
            (current_close - previous_close) / previous_close
        ) * 100

        if math.isfinite(change_pct):
            returns.append(change_pct)
