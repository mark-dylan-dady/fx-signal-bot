
from collections import defaultdict
from datetime import timezone
from statistics import mean, median
from zoneinfo import ZoneInfo

from fx_research.db import get_connection


JST = ZoneInfo("Asia/Tokyo")

TIME_BLOCKS = [
    ("00:00-05:59", 0, 6),
    ("06:00-11:59", 6, 12),
    ("12:00-17:59", 12, 18),
    ("18:00-23:59", 18, 24),
]

HORIZONS = [5, 15, 60]


def get_time_block(timestamp):
    """UTC timestampを日本時間に変換して6時間帯に分類する。"""
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
                    a.symbol,
                    a.direction,
                    a.alert_timestamp,
                    a.change_pct,
                    e.horizon_minutes,
                    e.price_change_pct
                FROM market_alerts AS a
                INNER JOIN alert_evaluations AS e
                    ON a.id = e.alert_id
                WHERE
                    a.direction IN ('UP', 'DOWN')
                    AND e.horizon_minutes IN (5, 15, 60)
                    AND e.price_change_pct IS NOT NULL
                ORDER BY
                    a.symbol,
                    a.alert_timestamp,
                    e.horizon_minutes
                """
            )
            rows = cursor.fetchall()

    finally:
        connection.close()

    groups = defaultdict(list)

    for row in rows:
        (
            symbol,
            direction,
            alert_timestamp,
            alert_change,
            horizon,
            future_change,
        ) = row

        time_block = get_time_block(alert_timestamp)

        if direction == "UP":
            if future_change > 0:
                result = "CONTINUATION"
            elif future_change < 0:
                result = "REVERSAL"
            else:
                result = "UNCHANGED"

        elif direction == "DOWN":
            if future_change < 0:
                result = "CONTINUATION"
            elif future_change > 0:
                result = "REVERSAL"
            else:
                result = "UNCHANGED"

        else:
            continue

        key = (symbol, time_block, direction, horizon)

        groups[key].append(
            {
                "alert_change": float(alert_change),
                "future_change": float(future_change),
                "result": result,
            }
        )

    print()
    print("=" * 78)
    print("PROJECT ORION: TIME-OF-DAY ALERT ANALYSIS")
    print("Time zone: Asia/Tokyo")
    print("=" * 78)

    print(f"Total directional evaluation records: {len(rows)}")
    print(f"Analysis groups: {len(groups)}")

    if not groups:
        print()
        print("No valid directional evaluation records found.")
        return

    for symbol in sorted({key[0] for key in groups}):
        print()
        print("-" * 78)
        print(f"SYMBOL: {symbol}")
        print("-" * 78)

        for time_block, _, _ in TIME_BLOCKS:
            for direction in ("UP", "DOWN"):
                for horizon in HORIZONS:
                    key = (symbol, time_block, direction, horizon)
                    records = groups.get(key)

                    if not records:
                        continue

                    total = len(records)
                    continuation = sum(
                        r["result"] == "CONTINUATION" for r in records
                    )
                    reversal = sum(
                        r["result"] == "REVERSAL" for r in records
                    )
                    unchanged = sum(
                        r["result"] == "UNCHANGED" for r in records
                    )

                    continuation_pct = continuation / total * 100
                    reversal_pct = reversal / total * 100

                    avg_alert = mean(
                        r["alert_change"] for r in records
                    )
                    avg_future = mean(
                        r["future_change"] for r in records
                    )
                    median_future = median(
                        r["future_change"] for r in records
                    )

                    print()
                    print(
                        f"{time_block} JST | {direction} | "
                        f"{horizon}m | n={total}"
                    )
                    print(
                        f"  Average alert magnitude : {avg_alert:+.5f}%"
                    )
                    print(
                        f"  Average future change  : {avg_future:+.5f}%"
                    )
                    print(
                        f"  Median future change   : {median_future:+.5f}%"
                    )
                    print(
                        f"  Continuation           : "
                        f"{continuation} ({continuation_pct:.1f}%)"
                    )
                    print(
                        f"  Reversal               : "
                        f"{reversal} ({reversal_pct:.1f}%)"
                    )
                    print(
                        f"  Unchanged              : {unchanged}"
                    )

    print()
    print("=" * 78)
    print("TIME-OF-DAY ANALYSIS COMPLETED")
    print("=" * 78)


if __name__ == "__main__":
    analyze()
