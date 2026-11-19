import os
from collections import defaultdict
from statistics import mean, median

import psycopg

from fx_research.report_pre_alert_market_state import (
    OUTCOME_FLAT_THRESHOLD_PCT,
    analyze_market_state,
    load_alerts,
    load_pre_alert_bars,
)


MIN_SAMPLE_NOTICE = 10


def calculate_statistics(changes, direction):
    """値動きの統計とアラート方向に対する継続・反転を計算する。"""
    if not changes:
        return {
            "count": 0,
            "average": None,
            "median": None,
            "continuation": 0,
            "reversal": 0,
            "flat": 0,
            "continuation_rate": None,
            "reversal_rate": None,
            "flat_rate": None,
        }

    count = len(changes)
    average_change = mean(changes)
    median_change = median(changes)

    continuation = 0
    reversal = 0
    flat = 0

    if direction in ("UP", "DOWN"):
        for change in changes:
            aligned_change = change if direction == "UP" else -change

            if aligned_change > OUTCOME_FLAT_THRESHOLD_PCT:
                continuation += 1
            elif aligned_change < -OUTCOME_FLAT_THRESHOLD_PCT:
                reversal += 1
            else:
                flat += 1

        continuation_rate = continuation / count * 100
        reversal_rate = reversal / count * 100
        flat_rate = flat / count * 100
    else:
        continuation_rate = None
        reversal_rate = None
        flat_rate = None

    return {
        "count": count,
        "average": average_change,
        "median": median_change,
        "continuation": continuation,
        "reversal": reversal,
        "flat": flat,
        "continuation_rate": continuation_rate,
        "reversal_rate": reversal_rate,
        "flat_rate": flat_rate,
    }


def create_report():
    """市場状態ごとの値動きを比較する。"""
    database_url = os.environ["DATABASE_URL"]

    grouped = defaultdict(list)

    total_alerts = 0
    analyzed_alerts = 0
    unknown_state_alerts = 0
    total_evaluations = 0
    invalid_evaluations = 0

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            alerts = load_alerts(cur)
            total_alerts = len(alerts)

            for alert_id, alert in alerts.items():
                symbol = alert["symbol"]
                alert_time = alert["alert_time"]
                direction = alert["direction"].upper()

                invalid_evaluations += alert.get(
                    "invalid_evaluations", 0
