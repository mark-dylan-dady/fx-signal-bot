
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
    """タイムスタンプを日本時間の6時間帯に分類する。"""
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    hour = timestamp.astimezone(JST).hour

    for label, start_hour, end_hour in TIME_BLOCKS:
        if start_hour <= hour < end_hour:
            return label

    return "UNKNOWN"


def analyze():
    connection = get_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    symbol,
                    direction,
                    alert_timestamp
                FROM market_alerts
                ORDER BY alert_timestamp
                """
            )
            rows = cursor.fetchall()

    finally:
        connection.close()

    if not rows:
        print("No market alerts found.")
        return

    # 全アラート数
    total_by_symbol = defaultdict(int)

    # 時間帯・方向別の件数
    counts = defaultdict(int)

    # 時間帯別の合計件数
    block_totals = defaultdict(int)

    # 時間帯別・銘柄別の件数
    symbol_block_totals = defaultdict(int)

    for symbol, direction, timestamp in rows:
        block = get_time_block(timestamp)

        total_by_symbol[symbol] += 1
        counts[(symbol, block, direction)] += 1
        block_totals[block] += 1
        symbol_block_totals[(symbol, block)] += 1

    total_alerts = len(rows)

    print()
    print("=" * 78)
    print("PROJECT ORION: ALERT FREQUENCY ANALYSIS")
    print("Time zone: Asia/Tokyo")
    print("=" * 78)

    print()
    print(f"Total alerts: {total_alerts}")

    print()
    print("-" * 78)
    print("TOTAL ALERTS BY SYMBOL")
    print("-" * 78)

    for symbol in sorted(total_by_symbol):
        count = total_by_symbol[symbol]
        percentage = count / total_alerts * 100

        print(
            f"{symbol:10} | "
            f"{count:5} alerts | "
            f"{percentage:5.1f}%"
        )

    print()
    print("-" * 78)
    print("ALERT FREQUENCY BY TIME BLOCK")
    print("-" * 78)

    for block, _, _ in TIME_BLOCKS:
        count = block_totals[block]
        percentage = count / total_alerts * 100

        print()
        print(
            f"{block} JST | "
            f"{count} alerts | "
            f"{percentage:.1f}% of all alerts"
        )

        for symbol in sorted(total_by_symbol):
            symbol_count = symbol_block_totals[(symbol, block)]

            up = counts[(symbol, block, "UP")]
            down = counts[(symbol, block, "DOWN")]
            unknown = sum(
                value
                for (s, b, d), value in counts.items()
                if s == symbol and b == block
                and d not in ("UP", "DOWN")
            )

            print(
                f"  {symbol:10} | "
                f"UP: {up:4} | "
                f"DOWN: {down:4} | "
                f"UNKNOWN: {unknown:4} | "
                f"TOTAL: {symbol_count:4}"
            )

    print()
    print("-" * 78)
    print("DIRECTION DISTRIBUTION BY SYMBOL")
    print("-" * 78)

    for symbol in sorted(total_by_symbol):
        up = sum(
            count
            for (s, block, direction), count in counts.items()
            if s == symbol and direction == "UP"
        )
        down = sum(
            count
            for (s, block, direction), count in counts.items()
            if s == symbol and direction == "DOWN"
        )
        unknown = total_by_symbol[symbol] - up - down

        print()
        print(f"{symbol}")
        print(f"  UP      : {up}")
        print(f"  DOWN    : {down}")
        print(f"  UNKNOWN : {unknown}")

    print()
    print("=" * 78)
    print("ALERT FREQUENCY ANALYSIS COMPLETED")
    print("=" * 78)


if __name__ == "__main__":
    analyze()
