
import os
from collections import defaultdict
from statistics import median

import psycopg


HISTORY_BARS = 600
BASELINE_RETURNS = 288
CHANGE_MULTIPLIER = 3.0
RECENT_HOURS = 24


def save_alerts(alerts):
    """検出したアラートをDBに保存する。"""
    database_url = os.environ["DATABASE_URL"]

    query = """
        INSERT INTO market_alerts (
            symbol,
            alert_timestamp,
            change_pct,
            baseline_pct,
            ratio
        )
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (symbol, alert_timestamp) DO NOTHING
    """

    if not alerts:
        return 0

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
                grouped[symbol].append(
                    (timestamp, float(close))
                )

    if not grouped:
        print("No price data found.")
        return

    total_saved = 0

    for symbol, bars in sorted(grouped.items()):
        print(f"\n=== {symbol} ===")

        returns = []

        for previous, current in zip(bars, bars[1:]):
            previous_time, previous_close = previous
            current_time, current_close = current

            # Skip gaps: only compare consecutive 5-minute bars.
            if (
                current_time - previous_time
            ).total_seconds() != 300:
                continue

            if previous_close <= 0:
                continue

            change_pct = abs(
                (current_close - previous_close)
                / previous_close
            ) * 100

            returns.append((current_time, change_pct))

        if len(returns) < BASELINE_RETURNS + 1:
            print(
                f"Not enough valid returns: {len(returns)}"
            )
            continue

        latest_time = returns[-1][0]
        cutoff_time = (
            latest_time.timestamp() - RECENT_HOURS * 3600
        )

        alerts = []

        for i, (timestamp, change_pct) in enumerate(returns):
            if timestamp.timestamp() < cutoff_time:
                continue

            # Use only earlier returns for the baseline.
            history = [
                value
                for _, value in returns[:i]
            ][-BASELINE_RETURNS:]

            if len(history) < 30:
                continue

            baseline = median(history)

            if baseline <= 0:
                continue

            ratio = change_pct / baseline

            if ratio >= CHANGE_MULTIPLIER:
                alerts.append(
                    (
                        symbol,
                        timestamp,
                        change_pct,
                        baseline,
                        ratio,
                    )
                )

        print(f"Latest data: {latest_time}")
        print(f"Valid 5-minute returns: {len(returns)}")
        print(
            f"Alerts in last {RECENT_HOURS} hours: {len(alerts)}"
        )

        if not alerts:
            print("No unusual movements detected.")
            continue

        saved_count = save_alerts(alerts)
        total_saved += saved_count

        print(f"New alerts saved: {saved_count}")

        for _, timestamp, change_pct, baseline, ratio in alerts:
            print(
                f"ALERT | {timestamp} | "
                f"change={change_pct:.5f}% | "
                f"median={baseline:.5f}% | "
                f"ratio={ratio:.2f}x"
            )

    print(f"\nTotal new alerts saved: {total_saved}")


if __name__ == "__main__":
    detect_market_changes()
