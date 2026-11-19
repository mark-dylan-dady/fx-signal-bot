import math
import os
from collections import defaultdict
from statistics import median

import psycopg


HISTORY_BARS = 600
BASELINE_RETURNS = 288
CHANGE_MULTIPLIER = 3.0
RECENT_HOURS = 24


def is_valid_price(value):
    """価格が正の有限数か確認する。"""
    try:
        price = float(value)
    except (TypeError, ValueError):
        return False

    return math.isfinite(price) and price > 0


def save_alerts(alerts):
    """全通貨ペアのアラートをまとめてDBに保存する。"""
    if not alerts:
        return 0

    database_url = os.environ["DATABASE_URL"]

    query = """
        INSERT INTO market_alerts (
            symbol,
            alert_timestamp,
            change_pct,
            baseline_pct,
            ratio,
            direction
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol, alert_timestamp) DO NOTHING
    """

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.executemany(query, alerts)
            saved_count = cur.rowcount

    return saved_count


def detect_market_changes():
    database_url = os.environ["DATABASE_URL"]

    query = """
        SELECT symbol, timestamp, close
        FROM (
            SELECT
                symbol,
                timestamp,
                close,
                ROW_NUMBER() OVER (
                    PARTITION BY symbol
                    ORDER BY timestamp DESC
                ) AS rn
            FROM price_bars
        ) AS recent
        WHERE rn <= %s
        ORDER BY symbol, timestamp
    """

    grouped = defaultdict(list)

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (HISTORY_BARS,))
            for symbol, timestamp, close in cur.fetchall():
                grouped[symbol].append((timestamp, close))

    if not grouped:
        print("No price data found.")
        return

    all_alerts = []

    for symbol, bars in sorted(grouped.items()):
        print(f"\\n=== {symbol} ===")

        returns = []

        for previous, current in zip(bars, bars[1:]):
            previous_time, previous_close = previous
            current_time, current_close = current

            # 欠損区間をまたぐ価格変化は計算しない。
