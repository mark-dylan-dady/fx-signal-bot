
import os
from collections import defaultdict
from statistics import median

import psycopg


HISTORY_BARS = 600
BASELINE_RETURNS = 288
CHANGE_MULTIPLIER = 3.0


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
                grouped[symbol].append((timestamp, float(close)))

    if not grouped:
        print("No price data found.")
        return

    for symbol, bars in sorted(grouped.items()):
        print(f"\n=== {symbol} ===")

        if len(bars) < 3:
            print("Not enough price data.")
            continue

        returns = []

        for previous, current in zip(bars, bars[1:]):
            previous_time, previous_close = previous
            current_time, current_close = current

            # Only compare consecutive 5-minute bars.
            if (current_time - previous_time).total_seconds() != 300:
                continue

            if previous_close == 0:
                continue

            change_pct = abs(
                (current_close - previous_close)
                / previous_close
            ) * 100

            returns.append((current_time, change_pct))

        if not returns:
            print("No consecutive 5-minute bars available.")
            continue

        latest_time, latest_change = returns[-1]

        print(f"Latest timestamp: {latest_time}")
        print(f"Latest absolute change: {latest_change:.5f}%")

        # Exclude the latest return from the historical baseline.
        history = [
            value for _, value in returns[:-1]
        ][-BASELINE_RETURNS:]

        if len(history) < 30:
            print(
                f"Not enough historical returns: {len(history)}"
            )
            continue

        baseline = median(history)

        print(f"Historical median: {baseline:.5f}%")

        if baseline <= 0:
            print("Baseline is zero; detection skipped.")
            continue

        ratio = latest_change / baseline
        print(f"Change ratio: {ratio:.2f}x")

        if ratio >= CHANGE_MULTIPLIER:
            print("ALERT: Unusually large price movement!")
        else:
            print("No unusual movement detected.")


if __name__ == "__main__":
    detect_market_changes()
