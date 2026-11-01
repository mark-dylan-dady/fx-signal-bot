
from collections import defaultdict
from datetime import timezone
from zoneinfo import ZoneInfo

from fx_research.db import get_connection


JST = ZoneInfo("Asia/Tokyo")

TIME_BLOCKS = [
    ("00:00-05:59", 0, 6),
    ("06:00-11:59", 6, 12),
    ("12:00-17:59", 12, 18),
    ("18:00-23:59", 18, 24),
]


def get_time_block(timestamp):
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    hour = timestamp.astimezone(JST).hour

    for label, start, end in TIME_BLOCKS:
        if start <= hour < end:
            return label

    return None


def analyze_alert_rate():
    print("=" * 78)
    print("PROJECT ORION: ALERT RATE ANALYSIS")
    print("Time zone: Asia/Tokyo")
    print("Rate: alerts per 1,000 price bars")
    print("=" * 78)

    with get_connection() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT symbol, timestamp
                FROM price_bars
                ORDER BY timestamp
            """)
            price_rows = cur.fetchall()

            cur.execute("""
                SELECT symbol, alert_timestamp
                FROM market_alerts
            """)
            alert_rows = cur.fetchall()

    bar_counts = defaultdict(int)
    alert_counts = defaultdict(int)

    for symbol, timestamp in price_rows:
        block = get_time_block(timestamp)
        if block:
            bar_counts[(symbol, block)] += 1

    for symbol, timestamp in alert_rows:
        block = get_time_block(timestamp)
        if block:
            alert_counts[(symbol, block)] += 1

    symbols = sorted({
        symbol for symbol, _ in bar_counts
    })

    print(f"\nTotal price bars: {len(price_rows)}")
    print(f"Total alerts: {len(alert_rows)}")

    print("\n" + "-" * 78)
    print("ALERT RATE BY SYMBOL AND TIME BLOCK")
    print("-" * 78)

    for symbol in symbols:
        print(f"\n{symbol}")

        for label, _, _ in TIME_BLOCKS:
            bars = bar_counts[(symbol, label)]
            alerts = alert_counts[(symbol, label)]

            if bars == 0:
                print(
                    f"  {label} | No price data available"
                )
                continue

            rate = alerts / bars * 1000

            print(
                f"  {label} | "
                f"Bars: {bars:5d} | "
                f"Alerts: {alerts:4d} | "
                f"Rate: {rate:7.2f} per 1,000 bars"
            )

    print("\n" + "-" * 78)
    print("COMBINED ALERT RATE BY TIME BLOCK")
    print("-" * 78)

    for label, _, _ in TIME_BLOCKS:
        bars = sum(
            bar_counts[(symbol, label)]
            for symbol in symbols
        )
        alerts = sum(
            alert_counts[(symbol, label)]
            for symbol in symbols
        )

        if bars == 0:
            print(f"{label} | No price data available")
            continue

        rate = alerts / bars * 1000

        print(
            f"{label} | "
            f"Bars: {bars:5d} | "
            f"Alerts: {alerts:4d} | "
            f"Rate: {rate:7.2f} per 1,000 bars"
        )

    print("\n" + "=" * 78)
    print("ALERT RATE ANALYSIS COMPLETED")
    print("=" * 78)


if __name__ == "__main__":
    analyze_alert_rate()
